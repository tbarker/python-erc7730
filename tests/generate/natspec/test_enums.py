"""Inline enum annotations produce reusable, resolvable descriptor metadata."""

import json
from typing import Any

import pytest

from erc7730.common.output import ListOutputAdder
from erc7730.convert.calldata.convert_erc7730_v2_input_to_calldata import erc7730_v2_descriptor_to_calldata_descriptors
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.input.v2.metadata import InputMapDefinition, InputMetadata

ADDRESS = "0x1111111111111111111111111111111111111111"
ABI = [{"type": "function", "name": "borrow", "inputs": [{"name": "mode", "type": "uint8"}]}]


def generate(declaration: str, tags: dict[str, str] | None = None, **kwargs: Any) -> Any:
    return generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(ABI),
        devdoc={"methods": {"borrow(uint8)": {"custom:clearsig-enum": declaration, **(tags or {})}}},
        **kwargs,
    )


def test_inline_enum_resolves_and_exports_without_format_or_reference() -> None:
    d = generate('mode[0]="Stable",mode[1]="Variable rate",')
    field = d.display.formats["borrow(uint8 mode)"].fields[0]
    assert field.format == "enum"
    enum_id = str(field.params.ref).rsplit(".", 1)[1]
    assert d.metadata.enums == {enum_id: {"0": "Stable", "1": "Variable rate"}}
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(d, resolved, out)
    assert not out.has_errors, out.outputs
    assert erc7730_v2_descriptor_to_calldata_descriptors(d)
    assert generate('mode[0]="Stable",mode[1]="Variable rate",').metadata == d.metadata


def test_inline_enum_overrides_inherited_formatter_and_preserves_metadata() -> None:
    original = InputMetadata(
        enums={"shared": {"0": "Existing"}},
        maps={"tokens": InputMapDefinition.model_validate({"$keyType": "uint256", "values": {"0": ADDRESS}})},
    )
    d = generate(
        'mode[0]="Stable"',
        metadata=original,
        project_defaults={"custom:clearsig-format": "mode=unit", "custom:clearsig-base": 'mode="%"'},
    )
    field = d.display.formats["borrow(uint8 mode)"].fields[0]
    assert field.format == "enum"
    assert set(field.params.model_dump(by_alias=True)) == {"$ref"}
    assert d.metadata.enums["shared"] == {"0": "Existing"}
    assert original.enums == {"shared": {"0": "Existing"}}
    assert d.metadata.maps == original.maps


def test_labels_with_punctuation_and_quotes_and_exclusions() -> None:
    label = 'Fixed, mode=stable "quoted"'
    d = generate(f"mode[0]={json.dumps(label)}", {"custom:clearsig-exclude": "mode"})
    assert next(iter(d.metadata.enums.values())) == {"0": label}
    assert d.display.formats["borrow(uint8 mode)"].fields[0].visible == "never"


def test_generated_metadata_collision_is_rejected() -> None:
    enum_id = next(iter(generate('mode[0]="Stable"').metadata.enums))
    with pytest.raises(ValueError, match="conflicts with metadata"):
        generate('mode[0]="Stable"', metadata=InputMetadata(enums={enum_id: {"0": "Different"}}))


@pytest.mark.parametrize(
    "declaration",
    [
        'mode[-1]="Bad"',
        'mode[0]=""',
        "mode[0]=42",
        "mode[0]=Unquoted",
        'mode[0]="A", mode[00]="B"',
        'missing[0]="A"',
        'garbage mode[0]="A"',
        'mode[0]="A"garbage',
        f'mode[{2**256}]="Overflow"',
        ",".join(f'mode[{i}]="Label"' for i in range(33)),
    ],
)
def test_invalid_definitions_fail_generation(declaration: str) -> None:
    with pytest.raises(ValueError, match="clearsig-enum"):
        generate(declaration)


@pytest.mark.parametrize(
    "tags", [{"custom:clearsig-format": "mode=raw"}, {"custom:clearsig-enum-ref": "mode=$.metadata.enums.shared"}]
)
def test_conflicting_method_annotations_fail(tags: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="conflicts"):
        generate('mode[0]="Stable"', tags)


def test_explicit_enum_format_and_identical_duplicate_are_allowed() -> None:
    assert generate('mode[0]="Stable", mode[00]="Stable"', {"custom:clearsig-format": "mode=enum"}).metadata.enums


def test_shared_reference_still_works() -> None:
    d = generate(
        "",
        {"custom:clearsig-format": "mode=enum", "custom:clearsig-enum-ref": "mode=$.metadata.enums.shared"},
        metadata=InputMetadata(enums={"shared": {"0": "Stable"}}),
    )
    assert str(d.display.formats["borrow(uint8 mode)"].fields[0].params.ref) == "$.metadata.enums.shared"


def test_overloads_and_nested_array_fields_have_separate_definitions() -> None:
    abi = [*ABI, {"type": "function", "name": "borrow", "inputs": [{"name": "mode", "type": "uint256"}]}]
    abi += [
        {
            "type": "function",
            "name": "batch",
            "inputs": [{"name": "orders", "type": "tuple[]", "components": [{"name": "mode", "type": "uint8"}]}],
        }
    ]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        devdoc={
            "methods": {
                "borrow(uint8)": {"custom:clearsig-enum": 'mode[0]="Stable"'},
                "borrow(uint256)": {"custom:clearsig-enum": 'mode[0]="Variable"'},
                "batch((uint8)[])": {"custom:clearsig-enum": 'orders.mode[0]="Batch"'},
            }
        },
    )
    assert d.metadata.enums is not None
    assert len(d.metadata.enums) == 3
    assert {entries["0"] for entries in d.metadata.enums.values()} == {"Stable", "Variable", "Batch"}
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs


def test_contract_scope_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be declared on a method"):
        generate_natspec_descriptor(
            1, ADDRESS, abi=json.dumps(ABI), devdoc={"custom:clearsig-enum": 'mode[0]="Stable"'}
        )


@pytest.mark.parametrize(
    "inputs,target",
    [
        ([{"name": "mode", "type": "address"}], "mode"),
        ([{"name": "order", "type": "tuple", "components": [{"name": "mode", "type": "uint8"}]}], "order"),
        (
            [{"name": name, "type": "tuple", "components": [{"name": "mode", "type": "uint8"}]} for name in ("a", "b")],
            "mode",
        ),
    ],
)
def test_invalid_field_targets_fail(inputs: list[dict[str, Any]], target: str) -> None:
    from erc7730.common.abi import reduce_signature

    # Use the generated declaration to avoid duplicating tuple signature parsing here.
    abi = json.dumps([{"type": "function", "name": "f", "inputs": inputs}])
    base = generate_natspec_descriptor(1, ADDRESS, abi=abi)
    signature = reduce_signature(next(iter(base.display.formats)))
    with pytest.raises(ValueError, match="clearsig-enum"):
        generate_natspec_descriptor(
            1, ADDRESS, abi=abi, devdoc={"methods": {signature: {"custom:clearsig-enum": f'{target}[0]="A"'}}}
        )
