"""Calldata amount bindings infer display semantics without overriding authored choices."""

import json
from typing import Any

import pytest

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.display import InputFieldDescription, InputUnitParameters
from erc7730.model.resolved.v2.display import ResolvedFieldDescription, ResolvedFieldGroup

ADDRESS = "0x1111111111111111111111111111111111111111"
PARTS = [{"name": "target", "type": "address"}, {"name": "value", "type": "uint256"}, {"name": "data", "type": "bytes"}]
BASE = {
    "custom:clearsig-format": "data=calldata",
    "custom:clearsig-callee-path": "data=#.target",
    "custom:clearsig-amount-path": "data=#.value",
}


def generate(tags: dict[str, str] | None = None, **kwargs: Any) -> InputERC7730Descriptor:
    return generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps([{"type": "function", "name": "execute", "inputs": PARTS}]),
        devdoc={"methods": {"execute(address,uint256,bytes)": BASE | (tags or {})}},
        **kwargs,
    )


def value_field(d: InputERC7730Descriptor) -> InputFieldDescription:
    return next(
        f
        for f in next(iter(d.display.formats.values())).fields
        if isinstance(f, InputFieldDescription) and str(f.path) == "#.value"
    )


def test_binding_infers_amount_and_preserves_display_order() -> None:
    d = generate()
    assert value_field(d).format == "amount"
    assert value_field(d).params is None
    assert [str(f.path) for f in next(iter(d.display.formats.values())).fields] == ["#.data", "#.target", "#.value"]
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs
    assert not out.has_errors


@pytest.mark.parametrize("scope", ["project", "contract", "method"])
def test_explicit_raw_wins(scope: str) -> None:
    override = {"custom:clearsig-format": "value=raw"}
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps([{"type": "function", "name": "execute", "inputs": PARTS}]),
        project_defaults=override if scope == "project" else None,
        devdoc={
            **(override if scope == "contract" else {}),
            "methods": {
                "execute(address,uint256,bytes)": BASE
                | ({"custom:clearsig-format": "data=calldata value=raw"} if scope == "method" else {})
            },
        },
    )
    assert value_field(d).format == "raw"


def test_explicit_unit_keeps_parameters() -> None:
    d = generate({"custom:clearsig-format": "data=calldata value=unit", "custom:clearsig-base": 'value="wei"'})
    assert value_field(d).format == "unit"
    params = value_field(d).params
    assert isinstance(params, InputUnitParameters)
    assert params.base == "wei"


@pytest.mark.parametrize(
    "tags",
    [
        {"custom:clearsig-amount-path": ""},
        {"custom:clearsig-amount-path": "data=#.missing"},
        {"custom:clearsig-amount-path": "data=#.missing.value"},
        {"custom:clearsig-format": "data=raw"},
        {"custom:clearsig-callee-path": ""},
    ],
)
def test_unusable_binding_does_not_infer(tags: dict[str, str]) -> None:
    assert value_field(generate(tags)).format == "raw"


def test_final_constant_binding_replaces_inherited_path() -> None:
    d = generate(
        {"custom:clearsig-amount-path": "", "custom:clearsig-amount": "data=0"},
        project_defaults=BASE,
    )
    assert value_field(d).format == "raw"


def test_exclusion_is_preserved() -> None:
    field = value_field(generate({"custom:clearsig-exclude": "value"}))
    assert field.visible == "never"


@pytest.mark.parametrize("binding", ["value", "#.calls.[].value"])
def test_array_of_structs_relative_and_absolute_paths(binding: str) -> None:
    abi = [{"type": "function", "name": "batch", "inputs": [{"name": "calls", "type": "tuple[]", "components": PARTS}]}]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        devdoc={
            "methods": {
                "batch((address,uint256,bytes)[])": {
                    "custom:clearsig-format": "calls.data=calldata",
                    "custom:clearsig-callee-path": "calls.data=target",
                    "custom:clearsig-amount-path": f"calls.data={binding}",
                }
            }
        },
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    group = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(group, ResolvedFieldGroup)
    fields = group.fields
    value = next(f for f in fields if str(f.path) == "#.calls.[].value")
    assert isinstance(value, ResolvedFieldDescription)
    assert value.format == "amount"


def test_parallel_arrays() -> None:
    abi = [{"type": "function", "name": "batch", "inputs": [dict(p, type=p["type"] + "[]") for p in PARTS]}]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        devdoc={
            "methods": {
                "batch(address[],uint256[],bytes[])": {
                    "custom:clearsig-format": "data=calldata",
                    "custom:clearsig-callee-path": "data=target.[]",
                    "custom:clearsig-amount-path": "data=value.[]",
                }
            }
        },
    )
    fields = next(iter(d.display.formats.values())).fields
    value = next(f for f in fields if str(f.path) == "#.value.[]")
    assert isinstance(value, InputFieldDescription)
    assert value.format == "amount"


def test_non_numeric_target_is_not_reformatted() -> None:
    d = generate({"custom:clearsig-amount-path": "data=#.target"})
    target = next(f for f in next(iter(d.display.formats.values())).fields if str(f.path) == "#.target")
    assert isinstance(target, InputFieldDescription)
    assert target.format == "addressName"
    assert value_field(d).format == "raw"


def test_container_binding_does_not_create_a_display_field() -> None:
    d = generate({"custom:clearsig-amount-path": "data=@.value"})
    assert value_field(d).format == "raw"
    assert all(str(f.path) != "@.value" for f in next(iter(d.display.formats.values())).fields)


def test_typed_data_amount_binding() -> None:
    d = generate({"custom:clearsig-typed-data": "Execute"})
    assert value_field(d).format == "amount"
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs
