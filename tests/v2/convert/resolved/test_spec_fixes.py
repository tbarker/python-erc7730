"""Regressions for v2 parameter, declaration, group and binding conformance."""

from typing import Any

import pytest
from pydantic import ValidationError

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.resolved.v2.display import ResolvedFieldDescription, ResolvedFieldGroup

ADDRESS = "0x1111111111111111111111111111111111111111"


def descriptor(key: str, fields: list[dict[str, Any]], context: dict[str, Any] | None = None) -> InputERC7730Descriptor:
    return InputERC7730Descriptor.model_validate(
        {
            "context": context or {"contract": {"deployments": [{"chainId": 1, "address": ADDRESS}]}},
            "metadata": {"owner": "Example", "maps": {"tokens": {"values": {"1": ADDRESS}}}},
            "display": {"formats": {key: {"intent": "Send", "fields": fields}}},
        },
        strict=False,
    )


@pytest.mark.parametrize(
    "format,type_",
    [
        ("addressName", "address"),
        ("interoperableAddressName", "bytes"),
        ("tokenAmount", "uint256"),
        ("tokenTicker", "address"),
    ],
)
@pytest.mark.parametrize("params", [None, {}])
def test_optional_parameters(format: str, type_: str, params: dict[str, Any] | None) -> None:
    d = descriptor(f"f({type_} value)", [{"path": "value", "label": "Value", "format": format, "params": params}])
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    assert not out.has_errors, out.outputs
    assert type(d).model_validate_json(d.to_json_string()) == d


@pytest.mark.parametrize(
    "format,params",
    [
        ("date", {"token": ADDRESS}),
        ("raw", {"encoding": "timestamp"}),
        ("tokenTicker", {"token": ADDRESS}),
        ("tokenAmount", {"sources": ["ens"]}),
        ("addressName", {"chainId": 1}),
        ("duration", {"encoding": "timestamp"}),
    ],
)
def test_wrong_parameter_objects_rejected(format: str, params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        descriptor("f(uint256 value)", [{"path": "value", "label": "Value", "format": format, "params": params}])


@pytest.mark.parametrize(
    "key",
    [
        "f(uint value)",
        "f(Foo value)",
        "f(int value)",
        "f(bytes1)",
        "0x12345678",
        "f((uint amount) order)",
    ],
)
def test_semantically_invalid_declarations_fail_local_validation(key: str) -> None:
    from erc7730.common.schema_types import validate_function_declaration

    with pytest.raises(ValueError):
        validate_function_declaration(key)


def test_nested_chain_id_and_slice_groups() -> None:
    d = descriptor(
        "f((uint256 amount,uint256 chainId)[] orders)",
        [
            {
                "path": "orders.[0:2]",
                "label": "Orders",
                "iteration": "sequential",
                "fields": [
                    {
                        "path": "amount",
                        "label": "Amount",
                        "format": "tokenAmount",
                        "params": {"token": ADDRESS, "chainIdPath": "chainId"},
                    },
                    {"path": "chainId", "label": "Chain", "format": "raw"},
                ],
            }
        ],
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    group = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(group, ResolvedFieldGroup)
    assert group.label == "Orders"
    amount = group.fields[0]
    assert isinstance(amount, ResolvedFieldDescription)
    assert amount.params is not None
    assert amount.params.model_dump(mode="json")["chainIdPath"] == "#.orders.[0:2].chainId"
    ValidateSchemaLinter().lint(d, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize(
    "format,name,extra",
    [
        ("tokenAmount", "token", {"chainId": 1}),
        ("tokenAmount", "chainId", {"token": ADDRESS}),
        ("addressName", "senderAddress", {"sources": ["ens"]}),
        ("calldata", "callee", {}),
        ("calldata", "amount", {"callee": ADDRESS}),
        ("nftName", "collection", {}),
        ("tokenTicker", "chainId", {}),
    ],
)
def test_maps_preserve_parameters(format: str, name: str, extra: dict[str, Any]) -> None:
    params = extra | {name: {"map": "$.metadata.maps.tokens", "keyPath": "id"}}
    d = descriptor(
        "f(uint256 value,uint256 id)", [{"path": "value", "label": "Value", "format": format, "params": params}]
    )
    out = ListOutputAdder()
    from erc7730.model.input.v2.metadata import InputMapDefinition
    from erc7730.model.resolved.v2.display import ResolvedValueMap

    values: dict[str, Any] = {"1": 1, "2": 2} if name in ("chainId", "amount") else {"1": ADDRESS}
    d = d.model_copy(
        update={"metadata": d.metadata.model_copy(update={"maps": {"tokens": InputMapDefinition(values=values)}})}
    )
    result = ERC7730InputToResolved().convert(d, out)
    assert result is not None, out.outputs
    field = next(iter(result.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    assert isinstance(getattr(field.params, name), ResolvedValueMap)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("eip712", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "type_,token_path,valid",
    [
        ("string", "token", False),
        ("uint256", "token", False),
        ("bool", "token", False),
        ("bytes20", "token", False),
        ("address", "token", True),
        ("address[]", "token.[0]", True),
        ("string[]", "token.[0]", False),
        ("bytes32", "token.[12:32]", True),
        ("bytes32", "token.[13:32]", False),
        ("address", "@.to", True),
        ("address", "@.from", True),
        ("address", "@.value", False),
        ("address", "@.chainId", False),
    ],
)
def test_token_path_target_type(
    eip712: bool, nested: bool, type_: str, token_path: str, valid: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    from erc7730.common import client
    from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter

    def offline(*args: Any) -> Any:
        raise ConnectionError("offline")

    monkeypatch.setattr(client, "get_contract_abis", offline)
    members = f"uint256 amount,{type_} token"
    key = f"Message({members})" if eip712 else f"f({members})"
    fields: list[dict[str, Any]] = [
        {"path": "amount", "label": "Amount", "format": "tokenAmount", "params": {"tokenPath": token_path}},
        {"path": "token", "label": "Token", "format": "raw"},
    ]
    if nested:
        key = f"Message(Order order)Order({members})" if eip712 else f"f(({members}) order)"
        fields = [{"path": "order", "fields": fields}]
    context = {"eip712": {"domain": {"chainId": 1}}} if eip712 else None
    d = descriptor(key, fields, context)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(d, resolved, out)
    errors = [item for item in out.outputs if item.title == "Invalid token path type"]
    if valid:
        assert not out.has_errors, out.outputs
    else:
        assert len(errors) == 1, out.outputs
        assert "tokenPath" in errors[0].message
        assert "expected an address" in errors[0].message


@pytest.mark.parametrize("eip712", [False, True])
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize(
    "format,parameter,valid_type",
    [
        ("calldata", "calleePath", "address"),
        ("calldata", "spenderPath", "address"),
        ("calldata", "selectorPath", "bytes4"),
        ("calldata", "amountPath", "uint256"),
        ("nftName", "collectionPath", "address"),
        ("tokenAmount", "chainIdPath", "uint256"),
        ("tokenTicker", "chainIdPath", "uint256"),
    ],
)
@pytest.mark.parametrize("valid", [False, True])
def test_formatter_parameter_target_types(
    eip712: bool, nested: bool, format: str, parameter: str, valid_type: str, valid: bool
) -> None:
    value_type = {"calldata": "bytes", "tokenTicker": "address"}.get(format, "uint256")
    target_type = valid_type if valid else "string"
    members = f"{value_type} value,{target_type} target"
    key = f"Message({members})" if eip712 else f"f({members})"
    params = {parameter: "target"}
    if format == "calldata" and parameter != "calleePath":
        params["callee"] = ADDRESS
    fields: list[dict[str, Any]] = [{"path": "value", "label": "Value", "format": format, "params": params}]
    if nested:
        key = f"Message(Item item)Item({members})" if eip712 else f"f(({members}) item)"
        fields = [{"path": "item", "fields": fields}]
    d = descriptor(key, fields, {"eip712": {"domain": {"chainId": 1}}} if eip712 else None)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(d, resolved, out)
    assert out.has_errors is not valid, out.outputs
    if not valid:
        assert any(parameter in item.message and "string" in item.message for item in out.outputs)


@pytest.mark.parametrize(
    "parameter,target_type,path,valid",
    [
        ("calleePath", "address[]", "target", False),
        ("calleePath", "address[]", "target.[0]", True),
        ("calleePath", "bytes32", "target.[12:]", True),
        ("calleePath", "bytes32", "target.[13:]", False),
        ("selectorPath", "bytes32", "target.[:4]", True),
        ("selectorPath", "bytes32", "target.[:5]", False),
        ("selectorPath", "uint32", "target", False),
        ("selectorPath", "bytes4[]", "target", False),
        ("amountPath", "int256", "target", False),
        ("amountPath", "uint256[]", "target", False),
        ("amountPath", "bytes32", "target.[:16]", True),
        ("amountPath", "bytes", "target.[:33]", False),
        ("calleePath", "address", "@.value", False),
        ("amountPath", "address", "@.to", False),
        ("selectorPath", "address", "@.chainId", False),
        ("amountPath", "address", "@.value", True),
    ],
)
def test_parameter_reference_widths_and_containers(parameter: str, target_type: str, path: str, valid: bool) -> None:
    params = {parameter: path}
    if parameter != "calleePath":
        params["callee"] = ADDRESS
    d = descriptor(
        f"f(bytes data,{target_type} target)",
        [{"path": "data", "label": "Call", "format": "calldata", "params": params}],
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(d, resolved, out)
    assert out.has_errors is not valid, out.outputs


@pytest.mark.parametrize(
    "parameter,value,valid",
    [
        ("callee", "0x1234", False),
        ("callee", ADDRESS, True),
        ("spender", "0x1234", False),
        ("selector", "0x12345678", True),
        ("selector", "0x123456", False),
        ("selector", "oops", False),
        ("amount", "0x" + "ff" * 33, False),
        ("amount", "0x" + "ff" * 32, True),
    ],
)
def test_formatter_parameter_constant_types(parameter: str, value: str, valid: bool) -> None:
    params = {"callee": ADDRESS, parameter: "$.metadata.constants.test"}
    d = descriptor("f(bytes data)", [{"path": "data", "label": "Call", "format": "calldata", "params": params}])
    d = d.model_copy(update={"metadata": d.metadata.model_copy(update={"constants": {"test": value}})})
    out = ListOutputAdder()
    if (resolved := ERC7730InputToResolved().convert(d, out)) is not None:
        ValidateSchemaLinter().lint(d, resolved, out)
    assert out.has_errors is not valid, out.outputs
