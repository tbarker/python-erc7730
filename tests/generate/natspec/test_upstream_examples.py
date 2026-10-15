"""Solidity compiler docs -> generator -> authored bundle -> upstream semantics."""

import hashlib
import json
from typing import Any

import jsonschema
import pytest

from tests.generate.natspec.upstream_examples import DATA, MANIFEST, assemble, expected_document, semantic


@pytest.mark.parametrize("name", sorted(MANIFEST["examples"]))
def test_upstream_bundle_roundtrip(name: str) -> None:
    entry = MANIFEST["examples"][name]
    artifact = json.loads((DATA / f"{name}.artifact.json").read_text())
    assert artifact["compilerVersion"].startswith("0.8.30+")
    assert artifact["sourceSha256"] == hashlib.sha256((DATA / entry["source"]).read_bytes()).hexdigest()
    # Corrected targets have a separate checksum; retain the published digest for provenance.
    assert (
        entry.get("fixture_sha256", entry["upstream_sha256"])
        == hashlib.sha256((DATA / "upstream" / f"{name}.json").read_bytes()).hexdigest()
    )
    actual = assemble(name)
    schema = json.loads((DATA.parents[4] / "specs" / "erc7730-v2.schema.json").read_text())
    jsonschema.validate(json.loads(actual.to_json_string()), schema)
    assert type(actual).model_validate_json(actual.to_json_string()) == actual
    expected = semantic(expected_document(name), fragment=entry["fragment"])

    def expect_generated_sources(value: Any) -> None:
        # Published examples omit sources; generation now explicitly supplies this
        # policy. Adapt only the expected side, retaining strict checks on actual output.
        if isinstance(value, dict):
            if value.get("format") == "addressName":
                params = value.setdefault("params", {})
                if params.get("sources") is None:
                    params["sources"] = ["local", "ens"]
            for child in value.values():
                expect_generated_sources(child)
        elif isinstance(value, list):
            for child in value:
                expect_generated_sources(child)

    expect_generated_sources(expected)
    assert semantic(actual, fragment=entry["fragment"]) == expected


@pytest.mark.parametrize("name", sorted(MANIFEST["examples"]))
@pytest.mark.parametrize("target", ["generated", "expected"])
def test_upstream_lint(name: str, target: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import TypeAdapter

    from erc7730.common import client
    from erc7730.common.output import ListOutputAdder
    from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
    from erc7730.lint.v2.lint_validate_display_fields import ValidateDisplayFieldsLinter
    from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter
    from erc7730.model.abi import ABI

    artifact = json.loads((DATA / f"{name}.artifact.json").read_text())
    abis = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    d = assemble(name) if target == "generated" else expected_document(name)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateDisplayFieldsLinter().lint(d, resolved, out)
    ValidateIntentLinter().lint(d, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize(
    "name,pointer,value",
    [
        ("example-main", ["display", "formats", "transfer(address to,uint256 value)", "intent"], "Burn"),
        (
            "example-main",
            ["display", "formats", "transfer(address to,uint256 value)", "fields", 0, "params", "sources"],
            ["local"],
        ),
        (
            "example-main",
            ["display", "formats", "transfer(address to,uint256 value)", "fields", 0, "label"],
            "Wrong recipient",
        ),
        (
            "example-main",
            ["display", "formats", "transfer(address to,uint256 value)", "fields", 1, "params", "tokenPath"],
            "@.from",
        ),
        ("example-main", ["context", "contract", "deployments", 0, "chainId"], 10),
        (
            "example-include",
            ["display", "formats", "approve(address spender,uint256 value)", "fields", 1, "params", "threshold"],
            "100",
        ),
        (
            "example-array-iteration",
            ["display", "formats", "distribute(address[] recipients,uint256[] percentages)", "fields", 1, "iteration"],
            "sequential",
        ),
        (
            "example-visibility-rules",
            [
                "display",
                "formats",
                "transfer(address to,uint256 value,address referrer,address rfu,uint256 legacy,uint256 fee)",
                "fields",
                4,
                "visible",
                "mustMatch",
            ],
            [1],
        ),
        (
            "example-maps",
            ["metadata", "maps", "underlyingToken", "values", "1"],
            "0x1111111111111111111111111111111111111111",
        ),
    ],
)
def test_semantic_comparison_detects_changes(name: str, pointer: list[str | int], value: object) -> None:
    original = assemble(name)
    document = json.loads(original.to_json_string())
    target = document
    for key in pointer[:-1]:
        target = target[key]
    target[pointer[-1]] = value
    changed = type(original).model_validate(document, strict=False)
    assert semantic(changed) != semantic(original)


def test_semantic_comparison_retains_field_order() -> None:
    d = assemble("example-main")
    document = json.loads(d.to_json_string())
    document["display"]["formats"]["transfer(address to,uint256 value)"]["fields"].reverse()
    assert semantic(type(d).model_validate(document, strict=False)) != semantic(d)


def test_fixtures_cover_every_pinned_example() -> None:
    assert {path.stem for path in (DATA / "upstream").glob("example-*.json")} == set(MANIFEST["examples"])
