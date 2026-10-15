"""V2 regressions for arrays, coverage, includes and schema-compatible constants."""

from typing import Any

import pytest
from pydantic import ValidationError

from erc7730.common.output import ListOutputAdder
from erc7730.common.schema_types import validate_function_declaration
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.lint.v2.lint_validate_display_fields import ValidateDisplayFieldsLinter
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.resolved.v2.display import ResolvedFieldDescription, ResolvedTokenAmountParameters
from tests.v2.convert.resolved.test_spec_fixes import ADDRESS, descriptor


@pytest.mark.parametrize("eip712", [False, True])
@pytest.mark.parametrize(
    "amounts,tokens,valid",
    [
        ("uint256[]", "address[]", True),
        ("uint256[2]", "address[2]", True),
        ("uint256[2]", "address[3]", False),
        ("uint256[]", "string[]", False),
        ("uint256", "address[]", False),
        ("uint256[]", "address", True),
        ("uint256[2][]", "address[2][]", True),
        ("uint256[2][]", "address[3][]", False),
    ],
)
def test_parallel_parameter_arrays(eip712: bool, amounts: str, tokens: str, valid: bool) -> None:
    key = f"{'Message' if eip712 else 'f'}({amounts} amounts,{tokens} tokens)"
    d = descriptor(
        key,
        [{"path": "amounts", "label": "Amounts", "format": "tokenAmount", "params": {"tokenPath": "tokens"}}],
        {"eip712": {"domain": {"name": "Test"}}} if eip712 else None,
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(d, resolved, out)
    assert out.has_errors is not valid, out.outputs


@pytest.mark.parametrize("format", ["tokenAmount", "tokenTicker"])
@pytest.mark.parametrize("value,valid", [(None, False), ("wrong", False), (True, False), (1, True)])
def test_chain_constant_is_not_silently_dropped(format: str, value: Any, valid: bool) -> None:
    d = descriptor(
        f"f({'address' if format == 'tokenTicker' else 'uint256'} value)",
        [{"path": "value", "label": "Value", "format": format, "params": {"chainId": "$.metadata.constants.chain"}}],
    )
    d = d.model_copy(update={"metadata": d.metadata.model_copy(update={"constants": {"chain": value}})})
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert (resolved is not None) is valid, out.outputs
    assert out.has_errors is not valid, out.outputs


@pytest.mark.parametrize("threshold", ["1000", "0x03e8"])
def test_schema_string_threshold(threshold: str) -> None:
    d = descriptor(
        "f(uint256 amount)",
        [{"path": "amount", "label": "Amount", "format": "tokenAmount", "params": {"threshold": threshold}}],
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    assert (
        next(iter(resolved.display.formats.values())).model_dump(mode="json")["fields"][0]["params"]["threshold"]
        == "0x03e8"
    )


def test_integer_threshold_supported_but_calldata_chain_override_rejected() -> None:
    descriptor(
        "f(uint256 amount)",
        [{"path": "amount", "label": "Amount", "format": "tokenAmount", "params": {"threshold": 1000}}],
    )
    with pytest.raises(ValidationError):
        descriptor(
            "f(bytes data)",
            [{"path": "data", "label": "Call", "format": "calldata", "params": {"callee": ADDRESS, "chainId": 10}}],
        )


@pytest.mark.parametrize(
    "schema",
    ["https://example.com/erc7730-v99.schema.json", "https://eips.ethereum.org/assets/eip-7730/erc7730-v1.schema.json"],
)
def test_schema_uri_remains_informational(schema: str) -> None:
    data = descriptor("f()", []).model_dump(by_alias=True)
    data["$schema"] = schema
    assert InputERC7730Descriptor.model_validate(data).schema_ == schema


@pytest.mark.parametrize("key", ["f(address to,address to)", "f((address to,address to) order)"])
def test_duplicate_parameter_names(key: str) -> None:
    with pytest.raises(ValueError, match="Duplicate parameter names"):
        validate_function_declaration(key)


@pytest.mark.parametrize("eip712", [False, True])
@pytest.mark.parametrize("hidden", [False, True])
def test_parameter_reference_does_not_require_a_separate_display_field(
    eip712: bool, hidden: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    def offline(*args: Any) -> Any:
        raise ConnectionError("offline")

    monkeypatch.setattr("erc7730.common.client.get_contract_abis", offline)
    fields: list[dict[str, Any]] = [
        {"path": "amount", "label": "Amount", "format": "tokenAmount", "params": {"tokenPath": "token"}}
    ]
    if hidden:
        fields.append({"path": "token", "visible": "never"})
    d = descriptor(
        f"{'Message' if eip712 else 'f'}(uint256 amount,address token)",
        fields,
        {"eip712": {"domain": {"name": "Test"}}} if eip712 else None,
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateDisplayFieldsLinter().lint(d, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("path,valid", [("tokens.[0:2]", True), ("tokens.[0:3]", False)])
def test_parallel_array_slices_in_groups(path: str, valid: bool) -> None:
    d = descriptor(
        "f((uint256[4] amounts,address[4] tokens) order)",
        [
            {
                "path": "order",
                "fields": [
                    {
                        "path": "amounts.[0:2]",
                        "label": "Amounts",
                        "format": "tokenAmount",
                        "params": {"tokenPath": path},
                    }
                ],
            }
        ],
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(d, resolved, out)
    assert out.has_errors is not valid, out.outputs


def test_numeric_metadata_threshold_supported() -> None:
    d = descriptor(
        "f(uint256 amount)",
        [
            {
                "path": "amount",
                "label": "Amount",
                "format": "tokenAmount",
                "params": {"threshold": "$.metadata.constants.limit"},
            }
        ],
    )
    d = d.model_copy(update={"metadata": d.metadata.model_copy(update={"constants": {"limit": 1000}})})
    out = ListOutputAdder()
    result = ERC7730InputToResolved().convert(d, out)
    assert result is not None and not out.has_errors
    field = next(iter(result.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    assert isinstance(field.params, ResolvedTokenAmountParameters)
    assert field.params.threshold == "0x03e8"


def test_map_only_dependencies_are_collected() -> None:
    from erc7730.lint.v2.path_schemas import compute_format_schema_paths

    source = InputERC7730Descriptor.model_validate(
        {
            "context": {"contract": {"deployments": [{"chainId": 1, "address": "0x" + "11" * 20}]}},
            "metadata": {"owner": "Example", "maps": {"tokens": {"values": {"1": "0x" + "22" * 20}}}},
            "display": {
                "formats": {
                    "f(uint256 amount,uint256 id)": {
                        "intent": "Send",
                        "fields": [
                            {
                                "path": "amount",
                                "label": "Amount",
                                "format": "tokenAmount",
                                "params": {"token": {"map": "$.metadata.maps.tokens", "keyPath": "id"}},
                            }
                        ],
                    }
                }
            },
        },
        strict=False,
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(source, out)
    assert resolved is not None and not out.has_errors, out.outputs
    paths = compute_format_schema_paths(next(iter(resolved.display.formats.values())))
    assert {str(path) for path in paths.data_paths} == {"#.amount", "#.id"}
