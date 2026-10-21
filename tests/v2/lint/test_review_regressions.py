"""Regression checks for schema boundaries, array coverage and safe V2 export."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from erc7730.common.output import ListOutputAdder
from erc7730.convert.ledger.eip712.convert_erc7730_v2_to_eip712 import ERC7730V2toEIP712Converter
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.lint.v2.json_schema import _validator
from erc7730.lint.v2.lint import lint_all
from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.display import InputEncryptionParameters
from erc7730.model.resolved.v2.display import ResolvedEncryptionParameters, ResolvedFieldDescription, ResolvedFieldGroup

pytestmark = pytest.mark.usefixtures("local_explorer")

ADDRESS = "0x1111111111111111111111111111111111111111"


def raw(key: str, fields: list[dict[str, Any]], template: str | None = None) -> dict[str, Any]:
    fmt: dict[str, Any] = {"intent": "Inspect", "fields": fields}
    if template is not None:
        fmt["interpolatedIntent"] = template
    return {
        "context": {"eip712": {"domain": {"name": "Example"}, "deployments": [{"chainId": 1, "address": ADDRESS}]}},
        "metadata": {"owner": "Example"},
        "display": {"formats": {key: fmt}},
    }


def leaf(path: str, **overrides: Any) -> dict[str, Any]:
    return {"path": path, "label": "Value", "format": "raw", **overrides}


def check(value: dict[str, Any]) -> ListOutputAdder:
    source = InputERC7730Descriptor.model_validate(value, strict=False)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(source, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(source, resolved, out)
    ValidateIntentLinter().lint(source, resolved, out)
    return out


@pytest.mark.parametrize("extension", [{"legalName": "Legacy"}, {"lastUpdate": "2020-01-01T00:00:00Z"}])
def test_v1_metadata_preserved_but_reported_by_strict_lint(extension: dict[str, Any], tmp_path: Path) -> None:
    value = raw("Message(uint256 value)", [leaf("value")])
    value["metadata"]["info"] = {"url": "https://example.com", **extension}
    source = InputERC7730Descriptor.model_validate(value, strict=False)
    assert source.metadata.info is not None
    assert extension.keys() <= source.metadata.info.model_dump(exclude_none=True).keys()
    path = tmp_path / "eip712-invalid.json"
    path.write_text(json.dumps(value))
    out = ListOutputAdder()
    assert lint_all([path], out, strict=True) == 1
    assert any(item.title == "Invalid V2 JSON schema" for item in out.outputs)


def test_schema_checked_before_pydantic_coercion(tmp_path: Path) -> None:
    value = raw("Message(uint256 value)", [leaf("value")])
    value["context"]["eip712"]["deployments"][0]["chainId"] = "1"
    # The normal loader can coerce this, but published-schema validation cannot.
    InputERC7730Descriptor.model_validate(value, strict=False)
    path = tmp_path / "eip712-invalid.json"
    path.write_text(json.dumps(value))
    out = ListOutputAdder()
    lint_all([path], out, strict=True)
    assert any(item.title == "Invalid V2 JSON schema" for item in out.outputs)


@pytest.mark.parametrize("version", ["2.0.0", "2.1.0"])
def test_packaged_schema_matches_published_copy(version: str) -> None:
    name = f"erc7730-v{version}.schema.json"
    source = Path(__file__).parents[2] / "registries/clear-signing-erc7730-registry/specs" / name
    assert _validator(name).schema == json.loads(source.read_text())


@pytest.mark.parametrize("path,type_", [("order", "Order"), ("order.[0]", "Order[1]")])
@pytest.mark.parametrize("iteration", [None, "bundled"])
def test_named_scalar_groups_preserved(path: str, type_: str, iteration: str | None) -> None:
    group = {"path": path, "label": "Order details", "fields": [leaf("value.[]")]}
    if iteration:
        group["iteration"] = iteration
    source = InputERC7730Descriptor.model_validate(
        raw(f"Message({type_} order)Order(uint256[2] value)", [group]), strict=False
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(source, out)
    assert resolved is not None, out.outputs
    result = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(result, ResolvedFieldGroup)
    assert result.label == "Order details"
    assert result.iteration == iteration
    assert str(result.fields[0].path) == f"#.{path}.value.[]"


@pytest.mark.parametrize(
    "type_,paths",
    [
        ("uint256[3]", ["values.[0]"]),
        ("uint256[3]", ["values.[0]", "values.[1:]"]),
        ("uint256[3]", ["values.[:2]", "values.[-1]"]),
        ("uint256[3]", ["values.[:1]", "values.[2:]"]),
        ("uint256[1000000000]", ["values.[:-1]", "values.[-1]"]),
        ("uint256[]", ["values.[0]"]),
        ("uint256[]", ["values.[:1]", "values.[1:]"]),
        ("uint256[]", ["values.[:-1]", "values.[-1:]"]),
        ("uint256[]", ["values.[:2]", "values.[3:]"]),
        ("uint256[]", ["values.length"]),
        ("uint256[]", ["values"]),
        ("uint256[2][2]", ["values.[0].[0]", "values.[1].[1]"]),
        ("uint256[2][2]", ["values.[0].[]", "values.[1].[]"]),
        ("uint256[][]", ["values.[:1].[]", "values.[1:].[]"]),
    ],
)
def test_partial_array_display_is_valid(type_: str, paths: list[str]) -> None:
    fields = [leaf(path, visible="never" if index else "always") for index, path in enumerate(paths)]
    out = check(raw(f"Message({type_} values)", fields))
    assert not out.has_errors, out.outputs
    assert not any(item.title == "Missing display field" for item in out.outputs), out.outputs


@pytest.mark.parametrize(
    "a,b,paths,valid",
    [
        ("uint256[2]", "uint256[3]", ["a.[]", "b.[]"], False),
        ("uint256[2]", "uint256[3]", ["a", "b"], False),
        ("uint256[2]", "uint256[3]", ["a.[]", "b.[:2]"], True),
        ("uint256[2]", "uint256[3]", ["a.[:1]", "b.[:2]"], False),
        ("uint256[]", "uint256[]", ["a.[]", "b.[]"], True),
        ("uint256[]", "uint256[]", ["a.[0:2]", "b.[0:3]"], False),
        ("uint256[2]", "uint256[2]", ["a.[]", "b.[]"], True),
    ],
)
def test_bundled_array_lengths(a: str, b: str, paths: list[str], valid: bool) -> None:
    out = check(
        raw(f"Message({a} a,{b} b)", [{"label": "Pair", "iteration": "bundled", "fields": [leaf(p) for p in paths]}])
    )
    assert (not any(item.title == "Bundled array size mismatch" for item in out.outputs)) == valid, out.outputs


@pytest.mark.parametrize("path", ["values", "values.[]"])
@pytest.mark.parametrize("reference", ["values", "values.[0]", "values.[0:2]"])
def test_array_root_interpolation(path: str, reference: str) -> None:
    out = check(raw("Message(uint256[] values)", [leaf(path)], f"Inspect {{{reference}}}"))
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("fields", [[leaf("values", visible="never")], [leaf("values"), leaf("values.[0]")]])
def test_interpolation_still_requires_one_always_visible_formatter(fields: list[dict[str, Any]]) -> None:
    out = check(raw("Message(uint256[] values)", fields, "Inspect {values.[0]}"))
    assert any(item.title == "Invalid interpolated intent" for item in out.outputs)


@pytest.mark.parametrize("model", [InputEncryptionParameters, ResolvedEncryptionParameters])
@pytest.mark.parametrize("type_", ["uint999", "uint7", "bytes33", "uint", "", "uint256[0]", "Unknown"])
def test_invalid_plaintext_types(
    model: type[InputEncryptionParameters | ResolvedEncryptionParameters], type_: str
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate({"scheme": "fhevm", "plaintextType": type_})


@pytest.mark.parametrize("type_", [None, "uint64", "int256", "bytes32", "address", "bool", "uint64[][2]"])
def test_valid_plaintext_types(type_: str | None) -> None:
    InputEncryptionParameters(scheme="fhevm", plaintextType=type_)


@pytest.mark.parametrize(
    "restriction",
    [
        {"encryption": {"scheme": "fhevm", "plaintextType": "uint64"}},
        {"visible": {"mustMatch": [1]}},
    ],
)
def test_legacy_export_rejects_restrictions(restriction: dict[str, Any]) -> None:
    source = InputERC7730Descriptor.model_validate(
        raw("Message(uint256 value)", [leaf("value", **restriction)]), strict=False
    )
    out = ListOutputAdder()
    assert ERC7730V2toEIP712Converter().convert(source, out) is None
    assert out.has_errors


@pytest.mark.parametrize("sources", [["ens"], ["local"], ["unrepresentable-source"]])
def test_legacy_export_never_broadens_sources(sources: list[str]) -> None:
    source = InputERC7730Descriptor.model_validate(
        raw(
            "Message(address value)",
            [leaf("value", format="addressName", params={"types": ["wallet"], "sources": sources})],
        ),
        strict=False,
    )
    out = ListOutputAdder()
    exported = ERC7730V2toEIP712Converter().convert(source, out)
    if sources == ["unrepresentable-source"]:
        assert exported is None and out.has_errors
    else:
        assert exported is not None, out.outputs
        encoded = json.dumps(
            {key: value.model_dump(mode="json", by_alias=True, exclude_none=True) for key, value in exported.items()}
        )
        assert '"unstoppable_domain"' not in encoded and '"freename"' not in encoded
        assert '"nameSources": ' + json.dumps(["local_address_book"] if sources == ["local"] else sources) in encoded


@pytest.mark.parametrize("equal", [True, False])
def test_bundled_lengths_inside_array_group(equal: bool) -> None:
    width = 2 if equal else 3
    group = {"path": "orders.[]", "label": "Orders", "iteration": "bundled", "fields": [leaf("a.[]"), leaf("b.[]")]}
    out = check(raw(f"Message(Order[4] orders)Order(uint256[2] a,uint256[{width}] b)", [group]))
    assert (not any(item.title == "Bundled array size mismatch" for item in out.outputs)) == equal, out.outputs


@pytest.mark.parametrize("reference", ["values", "values.[0]", "values.[0].[1]"])
def test_nested_array_root_interpolation(reference: str) -> None:
    out = check(raw("Message(uint256[][] values)", [leaf("values")], f"Inspect {{{reference}}}"))
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("calldata", [False, True])
@pytest.mark.parametrize("template", [None, "Inspect {value}"])
def test_omission_allowed_but_interpolation_requires_formatter(
    calldata: bool, template: str | None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from erc7730.common import client
    from erc7730.common.abi import parse_signature

    key = "f(uint256 value)" if calldata else "Message(uint256 value)"
    value = raw(key, [], template)
    if calldata:
        value["context"] = {"contract": {"deployments": [{"chainId": 1, "address": ADDRESS}]}}
    # Include an entirely unformatted function in the reference ABI too.
    monkeypatch.setattr(
        client, "get_contract_abis", lambda *args: [parse_signature("f(uint256 value)"), parse_signature("other()")]
    )
    path = tmp_path / ("calldata-partial.json" if calldata else "eip712-partial.json")
    path.write_text(json.dumps(value))
    out = ListOutputAdder()
    assert lint_all([path], out, strict=True) == 1
    assert out.has_errors == (template is not None), out.outputs
    assert any(item.title == "Missing display format" for item in out.outputs) is calldata
    if template:
        assert any(item.title == "Invalid interpolated intent" for item in out.outputs), out.outputs


@pytest.mark.parametrize("visibility", ["optional", {"ifNotIn": [0]}])
def test_legacy_export_preserves_visibility_compatibility(visibility: Any) -> None:
    source = InputERC7730Descriptor.model_validate(
        raw("Message(uint256 value)", [leaf("value", visible=visibility)]), strict=False
    )
    out = ListOutputAdder()
    assert ERC7730V2toEIP712Converter().convert(source, out) is not None
    assert not out.has_errors
    assert any(item.title == "Conditional visibility omitted" for item in out.outputs) == isinstance(visibility, dict)


@pytest.mark.parametrize("version,valid", [("2.0.0", False), ("2.1.0", False), ("2", False)])
def test_supported_schemas_require_intent(version: str, valid: bool) -> None:
    from erc7730.lint.v2.json_schema import validate_json_schema

    value = raw("Message(uint256 value)", [leaf("value")])
    value["$schema"] = f"https://example.invalid/erc7730-v{version}.schema.json"
    del value["display"]["formats"]["Message(uint256 value)"]["intent"]
    out = ListOutputAdder()
    assert validate_json_schema(value, out) == valid


@pytest.mark.parametrize("reference", ["erc7730-v3.schema.json", "https://example.invalid/schema.json", 12])
def test_unknown_schema_rejected(reference: Any) -> None:
    from erc7730.lint.v2.json_schema import validate_json_schema

    value = raw("Message(uint256 value)", [leaf("value")])
    value["$schema"] = reference
    out = ListOutputAdder()
    assert not validate_json_schema(value, out)
    assert out.outputs[0].title == "Unsupported V2 JSON schema"


def test_native_amount_parameters_resolve_and_cannot_be_lost_in_legacy_export() -> None:
    from erc7730.lint.v2.json_schema import validate_json_schema
    from erc7730.model.resolved.v2.display import ResolvedAmountParameters

    value = raw(
        "Message(uint256 value)", [leaf("value", format="amount", params={"threshold": "1000", "message": "All"})]
    )
    out = ListOutputAdder()
    assert validate_json_schema(value, out), out.outputs
    source = InputERC7730Descriptor.model_validate(value, strict=False)
    assert InputERC7730Descriptor.model_validate_json(source.to_json_string()) == source
    resolved = ERC7730InputToResolved().convert(source, out)
    assert resolved is not None, out.outputs
    field = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    assert isinstance(field.params, ResolvedAmountParameters)
    assert field.params.threshold is not None
    assert int(str(field.params.threshold), 16) == 1000
    assert field.params.message == "All"
    assert ERC7730V2toEIP712Converter().convert(source, out) is None
    assert any(item.title == "Unsupported native amount parameters" for item in out.outputs)
