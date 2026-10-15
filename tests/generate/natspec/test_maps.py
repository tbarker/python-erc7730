"""V2 map resolution, NatSpec authoring, and runtime lookup regressions."""

import json
from typing import Any

import pytest

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.examples.maps import lookup_map
from erc7730.generate.natspec.examples.models import ExampleFixture
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.resolved.v2.descriptor import ResolvedERC7730Descriptor
from erc7730.model.resolved.v2.display import ResolvedFieldDescription, ResolvedTokenAmountParameters, ResolvedValueMap
from tests.v2.convert.resolved.test_spec_fixes import ADDRESS, descriptor

TOKEN = "0x2222222222222222222222222222222222222222"


def mapped(values: dict[str, Any] | None = None, key: str = "id", parameter: str = "token") -> InputERC7730Descriptor:
    d = descriptor(
        "f(uint256 amount,uint256 id)",
        [
            {
                "path": "amount",
                "label": "Amount",
                "format": "tokenAmount",
                "params": {parameter: {"map": "$.metadata.maps.tokens", "keyPath": key}},
            },
            {"path": "id", "label": "ID", "format": "raw"},
        ],
    )
    from erc7730.model.input.v2.metadata import InputMapDefinition

    return d.model_copy(
        update={
            "metadata": d.metadata.model_copy(
                update={"maps": {"tokens": InputMapDefinition(values=values or {"1": ADDRESS, "2": TOKEN})}}
            )
        }
    )


def test_runtime_maps_preserve_all_values_and_roundtrip() -> None:
    d = mapped()
    assert type(d).model_validate_json(d.to_json_string()) == d
    out = ListOutputAdder()
    result = ERC7730InputToResolved().convert(d, out)
    assert result is not None, out.outputs
    ValidateSchemaLinter().lint(d, result, out)
    assert not out.has_errors, out.outputs
    field = next(iter(result.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    assert isinstance(field.params, ResolvedTokenAmountParameters)
    ref = field.params.token
    assert isinstance(ref, ResolvedValueMap)
    assert str(ref.keyPath) == "#.id"
    assert lookup_map(ref.values, 1).value == ADDRESS
    assert lookup_map(ref.values, 2).value == TOKEN
    with pytest.raises(ValueError, match="invalid for this transaction"):
        lookup_map(ref.values, 3)
    assert ResolvedERC7730Descriptor.model_validate_json(result.to_json_string()) == result


@pytest.mark.parametrize(
    "values,param",
    [({"1": ADDRESS, "2": "bad"}, "token"), ({"1": 1, "2": True}, "chainId"), ({"1": 1, "2": "2"}, "chainId")],
)
def test_every_map_entry_is_validated(values: dict[str, Any], param: str) -> None:
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(mapped(values, parameter=param), out) is None
    assert out.has_errors


@pytest.mark.parametrize("key", ["missing", "amount.[99]"])
def test_invalid_key_path_is_linted(key: str) -> None:
    d = mapped(key=key)
    out = ListOutputAdder()
    result = ERC7730InputToResolved().convert(d, out)
    assert result is not None
    ValidateSchemaLinter().lint(d, result, out)
    assert out.has_errors


def test_project_and_contract_maps_and_method_reference() -> None:
    abi = [{"name": "f", "type": "function", "inputs": [{"name": "amount", "type": "uint256"}]}]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        project_defaults={"maps": {"tokens": {"values": {"1": ADDRESS, "2": ADDRESS}}}},
        devdoc={
            "custom:clearsig-map": "tokens[2]=" + TOKEN,
            "methods": {
                "f(uint256)": {
                    "custom:clearsig-intent": "Send",
                    "custom:clearsig-format": "amount=tokenAmount",
                    "custom:clearsig-token": "amount=map(tokens,@.chainId)",
                }
            },
        },
    )
    assert d.metadata.maps is not None
    assert d.metadata.maps["tokens"].values == {"1": ADDRESS, "2": TOKEN}
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs


def map_renderer(d: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
    """Small test double with independent calldata decoding and decimal arithmetic."""
    from decimal import Decimal, localcontext

    from eth_abi.abi import decode
    from eth_utils.abi import function_signature_to_4byte_selector

    selector = function_signature_to_4byte_selector("f(uint256,uint256)")
    cases = []
    for case in fixture.tests:
        assert case.raw_tx is not None
        raw = bytes.fromhex(case.raw_tx[2:])
        start = raw.index(selector) + 4
        amount, id_ = decode(["uint256", "uint256"], raw[start : start + 64])
        decimals, symbol = {1: (6, "TEST"), 2: (18, "ALT")}[id_]
        with localcontext() as context:
            context.prec = 100
            text = format(Decimal(amount) / Decimal(10**decimals), "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        cases.append(
            {
                "description": case.description,
                "status": "pass",
                "rendered": {
                    "intent": "Send",
                    "fields": [{"label": "Amount", "value": text + " " + symbol}, {"label": "ID", "value": str(id_)}],
                },
            }
        )
    return {"cases": cases}


def test_automatic_and_authored_map_cases_share_runner() -> None:
    from erc7730.generate.natspec.examples import run_natspec_examples

    docs = {
        "methods": {
            "f(uint256,uint256)": {
                "custom:clearsig-example": 'params=(1500000,2) intent="Send" fields={"Amount":"0.0000000000015 ALT"}'
            }
        }
    }
    report = run_natspec_examples(
        mapped(),
        devdoc=docs,
        renderer=map_renderer,
        config={
            "dataProvider": {
                "tokens": {
                    ADDRESS: {"name": "Test", "symbol": "TEST", "decimals": 6},
                    TOKEN: {"name": "Alt", "symbol": "ALT", "decimals": 18},
                }
            }
        },
    )
    displays = [case.expected.fields[0].value for case in report.tests]
    assert "0.0000000000015 ALT" in displays
    assert "0.000001 TEST" in displays
    assert "0.000000000000000001 ALT" in displays
    assert any("rejection" in reason for reason in report.sanity_unavailable)


def test_authored_unknown_map_key_fails_before_rendering() -> None:
    from erc7730.generate.natspec.examples import run_natspec_examples

    with pytest.raises(ValueError, match="No map entry"):
        run_natspec_examples(
            mapped(),
            devdoc={"methods": {"f(uint256,uint256)": {"custom:clearsig-example": 'params=(1,999) intent="Send"'}}},
            renderer=map_renderer,
        )


def test_mapref_tag_uses_existing_parameter_models() -> None:
    abi = [{"name": "f", "type": "function", "inputs": [{"name": "amount", "type": "uint256"}]}]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        project_defaults={
            "maps": {"tokens": {"values": {"1": ADDRESS}}},
            "custom:clearsig-format": "amount=tokenAmount",
            "custom:clearsig-map-ref": "amount=token:tokens(@.chainId)",
        },
    )
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs
    assert "keyPath" in d.to_json_string()


def test_static_map_key_resolves_only_selected_entry() -> None:
    d = mapped({"1": ADDRESS, "2": "bad"}, key="$.metadata.constants.key")
    d = d.model_copy(update={"metadata": d.metadata.model_copy(update={"constants": {"key": 1}})})
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None
    assert not out.has_errors


def test_scalar_map_key_in_eip712() -> None:
    d = mapped()
    data = json.loads(d.to_json_string())
    data["context"] = {"eip712": {"domain": {"name": "Example"}}}
    data["display"]["formats"]["Message(uint256 amount,uint256 id)"] = data["display"]["formats"].pop(
        "f(uint256 amount,uint256 id)"
    )
    d = type(d).model_validate(data, strict=False)
    out = ListOutputAdder()
    result = ERC7730InputToResolved().convert(d, out)
    assert result is not None, out.outputs
    ValidateSchemaLinter().lint(d, result, out)
    assert not out.has_errors, out.outputs
