"""Regression tests for schema preservation and local intent validation."""

import json
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from erc7730.common import client
from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.abi import ABI
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

pytestmark = pytest.mark.usefixtures("local_explorer")

ADDRESS = "0x1111111111111111111111111111111111111111"


def check(
    format: dict[str, Any],
    *,
    key: str = "f(uint256 amount)",
    eip712: bool = False,
    metadata: dict[str, Any] | None = None,
) -> ListOutputAdder:
    binding = {"deployments": [{"chainId": 1, "address": ADDRESS}]}
    out = ListOutputAdder()
    try:
        descriptor = InputERC7730Descriptor.model_validate(
            {
                "context": {"eip712" if eip712 else "contract": binding},
                "metadata": metadata or {},
                "display": {"formats": {key: format}},
            },
            strict=False,
        )
    except ValidationError as exc:
        out.error(title="Invalid descriptor", message=str(exc))
        return out
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateIntentLinter().lint(descriptor, resolved, out)
    return out


def test_unnamed_inputs_preserve_every_position(monkeypatch: pytest.MonkeyPatch) -> None:
    abi: list[dict[str, Any]] = [
        {
            "type": "function",
            "name": "f",
            "inputs": [
                {"type": "address", "name": ""},
                {"type": "uint256", "name": "_arg0"},
                {
                    "type": "tuple[]",
                    "name": "",
                    "components": [
                        {"type": "uint256", "name": ""},
                        {"type": "address", "name": ""},
                    ],
                },
            ],
        }
    ]
    descriptor = generate_natspec_descriptor(1, ADDRESS, abi=json.dumps(abi))
    key = "f(address __arg0,uint256 _arg0,(uint256 _arg0,address _arg1)[] _arg2)"
    fields = descriptor.display.formats[key].model_dump(mode="json")["fields"]
    assert [field["path"] for field in fields] == ["#.__arg0", "#._arg0", "#._arg2.[]"]
    assert [field["path"] for field in fields[2]["fields"]] == ["_arg0", "_arg1"]
    assert abi[0]["inputs"][0]["name"] == ""  # caller input is not mutated
    reference = TypeAdapter(list[ABI]).validate_python(abi, strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: reference)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(descriptor, resolved, out)
    assert not out.has_errors, out.outputs
    assert not out.has_warnings, out.outputs


def test_same_primary_type_preserves_both_schemas_and_overlays() -> None:
    schemas = [
        {"primaryType": "Message", "types": {"Message": [{"name": name, "type": type_}]}}
        for name, type_ in [("amount", "uint256"), ("recipient", "address")]
    ]
    descriptor = generate_natspec_descriptor(
        1, ADDRESS, eip712_schema=json.dumps(schemas), userdoc={"methods": {"Message": {"notice": "Send"}}}
    )
    assert set(descriptor.display.formats) == {"Message(uint256 amount)", "Message(address recipient)"}
    assert all(format.intent == "Send" for format in descriptor.display.formats.values())
    assert {str(format.fields[0].path) for format in descriptor.display.formats.values()} == {"#.amount", "#.recipient"}


@pytest.mark.parametrize("intent", [None, "", "  ", {}, {"Action": ""}, {"": "Send"}])
@pytest.mark.parametrize("template", [None, "Send {amount}"])
def test_missing_or_empty_intents_are_errors(intent: Any, template: str | None) -> None:
    out = check(
        {
            "intent": intent,
            "interpolatedIntent": template,
            "fields": [{"path": "amount", "label": "Amount", "format": "raw"}],
        }
    )
    assert out.has_errors


@pytest.mark.parametrize(
    "template", ["Send {missing}", "Send {amount", "Send amount}", "Send {}", "Send {{amount}", " "]
)
def test_invalid_placeholders_are_lint_errors(template: str) -> None:
    out = check(
        {
            "intent": "Send",
            "interpolatedIntent": template,
            "fields": [{"path": "amount", "label": "Amount", "format": "raw"}],
        }
    )
    assert any(output.title == "Invalid interpolated intent" for output in out.outputs)


@pytest.mark.parametrize("visible", ["never", "optional", {"ifNotIn": [0]}, {"mustMatch": [0]}])
def test_placeholders_require_always_visible_formatters(visible: Any) -> None:
    out = check(
        {
            "intent": "Send",
            "interpolatedIntent": "Send {amount}",
            "fields": [{"path": "amount", "label": "Amount", "format": "raw", "visible": visible}],
        }
    )
    assert out.has_errors


def test_matching_formatter_does_not_make_a_missing_schema_field_valid() -> None:
    out = check(
        {
            "intent": "Send",
            "interpolatedIntent": "Send {missing}",
            "fields": [{"path": "missing", "label": "Amount", "format": "raw"}],
        }
    )
    assert out.has_errors


@pytest.mark.parametrize(
    "fields",
    [
        [],
        [
            {"path": "amount", "label": "First", "format": "raw"},
            {"path": "amount", "label": "Second", "format": "raw"},
        ],
    ],
)
def test_placeholder_needs_unambiguous_formatter(fields: list[dict[str, Any]]) -> None:
    assert check({"intent": "Send", "interpolatedIntent": "Send {amount}", "fields": fields}).has_errors


@pytest.mark.parametrize(
    "eip712,key", [(False, "f((uint256 amount) order)"), (True, "Message(Order order)Order(uint256 amount)")]
)
def test_nested_paths_and_escaped_braces(eip712: bool, key: str) -> None:
    format = {
        "intent": {"Action": "Send"},
        "interpolatedIntent": "Send {order.amount} {{tokens}}",
        "fields": [{"path": "order", "fields": [{"path": "amount", "label": "Amount", "format": "raw"}]}],
    }
    assert not check(format, key=key, eip712=eip712).has_errors
    format["interpolatedIntent"] = "Send {order.missing}"
    assert check(format, key=key, eip712=eip712).has_errors


@pytest.mark.parametrize("path", ["values.[0]", "values.[]", "values"])
def test_array_wildcard_formatter_covers_elements(path: str) -> None:
    assert not check(
        {
            "intent": "Send",
            "interpolatedIntent": "Send {" + path + "}",
            "fields": [{"path": "values.[]", "label": "Amount", "format": "raw"}],
        },
        key="f(uint256[] values)",
    ).has_errors


def test_fixed_array_bounds() -> None:
    assert check(
        {
            "intent": "Send",
            "interpolatedIntent": "Send {values.[2]}",
            "fields": [{"path": "values.[]", "label": "Amount", "format": "raw"}],
        },
        key="f(uint256[2] values)",
    ).has_errors


def test_container_and_metadata_placeholders() -> None:
    format = {
        "intent": "Wrap",
        "interpolatedIntent": "Wrap {@.value} {$.metadata.constants.ticker}",
        "fields": [
            {"path": "@.value", "label": "Amount", "format": "raw"},
            {"value": "$.metadata.constants.ticker", "label": "Token", "format": "raw"},
        ],
    }
    assert not check(format, key="wrap()", metadata={"constants": {"ticker": "ETH"}}).has_errors


def test_backticks_are_literal_in_a_descriptor_template() -> None:
    out = check(
        {
            "intent": "Send",
            "interpolatedIntent": "Send `{amount}` tokens",
            "fields": [{"path": "amount", "label": "Amount", "format": "raw"}],
        }
    )
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("eip712", [False, True])
@pytest.mark.parametrize("path", ["missing", "data.[99]", "data.[-5]", "data.[:5]", "data.[3:-2]"])
def test_local_field_paths_are_checked_offline(eip712: bool, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def offline(*args: Any) -> Any:
        raise ConnectionError("offline")

    monkeypatch.setattr(client, "get_contract_abis", offline)
    key = "Message(bytes4 data)" if eip712 else "f(bytes4 data)"
    descriptor = InputERC7730Descriptor.model_validate(
        {
            "context": {"eip712" if eip712 else "contract": {"deployments": [{"chainId": 1, "address": ADDRESS}]}},
            "metadata": {},
            "display": {
                "formats": {key: {"intent": "Inspect", "fields": [{"path": path, "label": "Data", "format": "raw"}]}}
            },
        },
        strict=False,
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(descriptor, resolved, out)
    assert any(output.title == "Invalid display field" for output in out.outputs), out.outputs


@pytest.mark.parametrize(
    "type_,selector,valid",
    [
        ("bytes4", "[3]", True),
        ("bytes4", "[-4]", True),
        ("bytes4", "[4]", False),
        ("bytes4", "[:4]", True),
        ("bytes4", "[:5]", False),
        ("uint16", "[1]", True),
        ("uint16", "[2]", False),
        ("bytes", "[99]", True),
        ("uint256[2]", "[:3]", False),
    ],
)
def test_interpolation_primitive_bounds(type_: str, selector: str, valid: bool) -> None:
    path = f"data.{selector}"
    out = check(
        {
            "intent": "Inspect",
            "interpolatedIntent": "Inspect {" + path + "}",
            "fields": [{"path": path, "label": "Data", "format": "raw"}],
        },
        key=f"f({type_} data)",
    )
    assert out.has_errors is not valid, out.outputs


@pytest.mark.parametrize(
    "type_,format,valid",
    [
        ("string", "date", False),
        ("address", "nftName", False),
        ("uint256", "addressName", False),
        ("bytes", "amount", False),
        ("bool", "tokenAmount", False),
        ("bytes32", "calldata", True),
        ("address", "tokenTicker", True),
        ("uint256[]", "tokenAmount", True),
        ("uint64", "duration", True),
    ],
)
def test_format_applicability_in_generation_and_lint(type_: str, format: str, valid: bool) -> None:
    from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
    from erc7730.model.input.v2.display import (
        InputAddressNameParameters,
        InputCallDataParameters,
        InputDateParameters,
        InputFieldDescription,
        InputNftNameParameters,
    )
    from erc7730.model.input.v2.format import DateEncoding, FieldFormat

    warnings: list[str] = []
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(
            [
                {
                    "type": "function",
                    "name": "f",
                    "inputs": [{"name": "data", "type": type_}],
                }
            ]
        ),
        devdoc={"methods": {f"f({type_})": {"custom:clearsig-format": f"data={format}"}}},
        warnings=warnings,
    )
    field = next(iter(descriptor.display.formats.values())).fields[0]
    assert isinstance(field, InputFieldDescription)
    assert (field.format == format) is valid
    assert any("not applicable" in warning for warning in warnings) is not valid
    # Handwritten descriptors must be rejected, not silently corrected.
    params = {
        "date": InputDateParameters(encoding=DateEncoding.TIMESTAMP),
        "addressName": InputAddressNameParameters(sources=["ens"]),
        "nftName": InputNftNameParameters(collection=ADDRESS),
        "calldata": InputCallDataParameters(callee=ADDRESS),
    }.get(format)
    next(iter(descriptor.display.formats.values())).fields[0] = field.model_copy(
        update={"format": FieldFormat(format), "params": params}
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(descriptor, resolved, out)
    assert any(output.title == "Inapplicable field format" for output in out.outputs) is not valid


@pytest.mark.parametrize("name", ["amount", "value", "price", "amountIn", "salePrice"])
def test_currency_is_never_inferred_from_amount_names(name: str) -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(
            [
                {
                    "type": "function",
                    "name": "f",
                    "inputs": [{"name": name, "type": "uint256"}],
                }
            ]
        ),
    )
    assert next(iter(descriptor.display.formats.values())).model_dump(mode="json")["fields"][0]["format"] == "raw"


@pytest.mark.parametrize("indirect", [False, True])
def test_recursive_eip712_generation_is_actionable(indirect: bool) -> None:
    types = {"Node": [{"name": "children", "type": "Branch[]" if indirect else "Node[]"}]}
    if indirect:
        types["Branch"] = [{"name": "parent", "type": "Node"}]
    with pytest.raises(ValueError, match=r"Recursive EIP-712.*finite display tree"):
        generate_natspec_descriptor(1, ADDRESS, eip712_schema=json.dumps([{"primaryType": "Node", "types": types}]))


def test_reusing_eip712_structs_is_not_recursion() -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        eip712_schema=json.dumps(
            [
                {
                    "primaryType": "Pair",
                    "types": {
                        "Pair": [{"name": "left", "type": "Item"}, {"name": "right", "type": "Item"}],
                        "Item": [{"name": "value", "type": "uint256"}],
                    },
                }
            ]
        ),
    )
    assert len(next(iter(descriptor.display.formats.values())).fields) == 2


def test_local_checks_include_parameter_references_and_encryption() -> None:
    from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter

    def validate(token_path: str, plaintext: str) -> ListOutputAdder:
        descriptor = InputERC7730Descriptor.model_validate(
            {
                "context": {"contract": {"deployments": [{"chainId": 1, "address": ADDRESS}]}},
                "metadata": {},
                "display": {
                    "formats": {
                        "f(bytes32 handle,address token)": {
                            "intent": "Send",
                            "fields": [
                                {
                                    "path": "handle",
                                    "label": "Amount",
                                    "format": "tokenAmount",
                                    "params": {"tokenPath": token_path},
                                    "encryption": {"scheme": "test", "plaintextType": plaintext},
                                }
                            ],
                        }
                    }
                },
            },
            strict=False,
        )
        out = ListOutputAdder()
        resolved = ERC7730InputToResolved().convert(descriptor, out)
        assert resolved is not None, out.outputs
        ValidateSchemaLinter().lint(descriptor, resolved, out)
        return out

    assert not validate("token", "uint256").has_errors
    assert validate("missing", "uint256").has_errors
    assert validate("token", "string").has_errors


def test_recursive_eip712_declaration_accepts_a_finite_lint_path() -> None:
    from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter

    key = "Node(uint256 value,Node[] children)"
    descriptor = InputERC7730Descriptor.model_validate(
        {
            "context": {"eip712": {"deployments": [{"chainId": 1, "address": ADDRESS}]}},
            "metadata": {},
            "display": {
                "formats": {
                    key: {
                        "intent": "Inspect",
                        "fields": [{"path": "children.[0].children.[0].value", "label": "Value", "format": "raw"}],
                    }
                }
            },
        },
        strict=False,
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(descriptor, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize(
    "type_,path,format,valid",
    [
        ("uint256", "data.[-20:]", "addressName", True),
        ("bytes", "data.[0:20]", "addressName", True),
        ("bytes", "data.[-20:]", "addressName", True),
        ("bytes32", "data.[12:32]", "tokenTicker", True),
        ("bytes32", "data.[13:32]", "addressName", False),
        ("bytes32", "data.[0:4]", "amount", True),
        ("uint256[]", "data.[-1]", "addressName", False),
        ("uint256[]", "data.[-1].[-20:]", "addressName", True),
        ("address[]", "data.[-1]", "addressName", True),
    ],
)
def test_formatting_packed_byte_slices(type_: str, path: str, format: str, valid: bool) -> None:
    from erc7730.common.schema_types import format_accepts_path
    from erc7730.model.input.v2.format import FieldFormat
    from erc7730.model.paths import DataPath
    from erc7730.model.paths.path_parser import to_path

    parsed = to_path(path)
    assert isinstance(parsed, DataPath)
    assert format_accepts_path(FieldFormat(format), f"f({type_} data)", False, parsed) is valid


def test_selector_only_key_cannot_bypass_local_validation() -> None:
    descriptor = InputERC7730Descriptor.model_validate(
        {
            "context": {"contract": {"deployments": [{"chainId": 1, "address": ADDRESS}]}},
            "metadata": {},
            "display": {
                "formats": {
                    "0x12345678": {
                        "intent": "Inspect",
                        "fields": [{"path": "missing", "label": "Data", "format": "raw"}],
                    }
                }
            },
        },
        strict=False,
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None
    ValidateSchemaLinter().lint(descriptor, resolved, out)
    assert any(output.title == "Invalid display field" for output in out.outputs), out.outputs
