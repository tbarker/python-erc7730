"""Automatic mutations validate renderer results and respect input constraints."""

import json
from typing import Any

import pytest

from erc7730.generate.natspec.examples import ExampleFixture, run_natspec_examples
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

ADDRESS = "0x1111111111111111111111111111111111111111"
ABI = [{"type": "function", "name": "send", "inputs": [{"name": "amount", "type": "uint256"}]}]
DOCS = {
    "methods": {
        "send(uint256)": {
            "custom:clearsig-intent": "Send",
            "custom:clearsig-format": "amount=tokenAmount",
            "custom:clearsig-token-path": "amount=@.to",
        }
    }
}


@pytest.mark.parametrize("decimals", [6, 18])
def test_automatic_cases_detect_consistently_wrong_renderer(decimals: int) -> None:
    descriptor = generate_natspec_descriptor(1, ADDRESS, abi=json.dumps(ABI), devdoc=DOCS)

    def wrong(descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        return {
            "cases": [
                {
                    "description": case.description,
                    "status": "pass",
                    "rendered": {"intent": "Send", "fields": [{"label": "Amount", "value": "1 TEST"}]},
                }
                for case in fixture.tests
            ]
        }

    with pytest.raises(ValueError, match="expected"):
        run_natspec_examples(
            descriptor,
            renderer=wrong,
            config={"dataProvider": {"tokens": {ADDRESS: {"symbol": "TEST", "decimals": decimals, "name": "Test"}}}},
        )


def test_incomplete_renderer_results_cannot_pass() -> None:
    d = generate_natspec_descriptor(1, ADDRESS, abi=json.dumps(ABI), devdoc=DOCS)
    with pytest.raises(ValueError, match="incomplete"):
        run_natspec_examples(d, renderer=lambda d, f: {"cases": []})


def test_ambiguous_typed_domain_is_reported_without_a_false_pass() -> None:
    schema = [{"primaryType": "Message", "types": {"Message": [{"name": "amount", "type": "uint256"}]}}]
    d = generate_natspec_descriptor(1, ADDRESS, eip712_schema=json.dumps(schema))

    def unused(d: InputERC7730Descriptor, f: ExampleFixture) -> dict[str, Any]:
        raise AssertionError("No supported automatic typed-data cases should be sent")

    from erc7730.model.input.v2.context import InputEIP712Context

    assert isinstance(d.context, InputEIP712Context)
    d = d.model_copy(
        update={
            "context": d.context.model_copy(
                update={"eip712": d.context.eip712.model_copy(update={"domainSeparator": "0x" + "00" * 32})}
            )
        }
    )
    report = run_natspec_examples(d, renderer=unused)
    assert report.tests == []
    assert any("EIP-712" in message for message in report.sanity_unavailable)


@pytest.mark.parametrize("type_,low,high", [("int8", -128, 127), ("uint16", 0, 65535)])
def test_integer_mutations_respect_abi_width(type_: str, low: int, high: int) -> None:
    from erc7730.generate.natspec.examples.sanity import _mutations

    values = [value for _, value in _mutations({"name": "value", "type": type_}, 1, [low - 1, high + 1, True])]
    assert low in values and high in values
    assert all(type(value) is int and low <= value <= high for value in values)


def test_nested_tuple_array_values_preserve_dimensions_and_names() -> None:
    from erc7730.generate.natspec.examples.sanity import _baseline, _mutations
    from erc7730.generate.natspec.examples.typed_data import _wire
    from erc7730.generate.natspec.examples.values import named_value

    part = {
        "name": "rows",
        "type": "tuple[2][]",
        "components": [{"name": "amount", "type": "int8"}, {"name": "id", "type": "bytes2"}],
    }
    values = _baseline(part, length=1)
    assert values == [[[1, b"\x00\x01"], [1, b"\x00\x01"]]]
    assert named_value(part, values) == [[{"amount": 1, "id": b"\x00\x01"}] * 2]
    assert _wire(part, values) == [[{"amount": "1", "id": "0x0001"}] * 2]
    changed = dict(_mutations(part, values, []))["first.first.amount.-128"]
    assert changed == [[[-128, b"\x00\x01"], [1, b"\x00\x01"]]]
    assert _baseline(part, length=0) == []
