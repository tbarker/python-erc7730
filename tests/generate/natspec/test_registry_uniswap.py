"""Official registry bundles recreated solely from compiler NatSpec and bindings."""

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from erc7730.common import client
from erc7730.common.output import ListOutputAdder
from erc7730.lint.v2.json_schema import validate_json_schema
from erc7730.lint.v2.lint import lint_all
from erc7730.model.abi import ABI
from tests.generate.natspec.registry_uniswap import DATA, MANIFEST, NAMES, assemble, comparison, expected

pytestmark = pytest.mark.usefixtures("local_explorer")


@pytest.mark.parametrize("name", NAMES)
def test_official_uniswap_roundtrip(name: str) -> None:
    actual = assemble(name)
    out = ListOutputAdder()
    assert validate_json_schema(json.loads(actual.to_json_string()), out), out.outputs
    assert type(actual).model_validate_json(actual.to_json_string()) == actual
    assert comparison(actual) == comparison(expected(name))


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("target", ["generated", "expected"])
def test_uniswap_full_lint(name: str, target: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact = json.loads((DATA / f"{name}.artifact.json").read_text())
    abi = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    # Synthetic source stubs do not have separately deployed contracts. This only
    # avoids explorer I/O; schema, path, intent and parameter lint are real.
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abi)
    descriptor = assemble(name) if target == "generated" else expected(name)
    path = tmp_path / f"{name}.json"
    path.write_text(descriptor.to_json_string())
    out = ListOutputAdder()
    assert lint_all([path], out) == 1
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("name", NAMES)
def test_uniswap_provenance(name: str) -> None:
    entry = MANIFEST["examples"][name]
    artifact = json.loads((DATA / f"{name}.artifact.json").read_text())
    assert artifact["compilerVersion"].startswith("0.8.30+")
    assert artifact["sourceSha256"] == hashlib.sha256((DATA / entry["source"]).read_bytes()).hexdigest()
    source = DATA / "upstream" / f"{name}.json"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["upstream_sha256"]


def test_uniswap_inventory_and_shared_include() -> None:
    assert {p.stem for p in (DATA / "upstream").glob("*.json")} == {*NAMES, "common-eip712-uniswap"}
    assert (
        MANIFEST["include_sha256"]
        == hashlib.sha256((DATA / "upstream/common-eip712-uniswap.json").read_bytes()).hexdigest()
    )


@pytest.mark.parametrize("mutation", ["order", "label", "tokenPath", "hidden", "group"])
def test_uniswap_comparison_detects_display_changes(mutation: str) -> None:
    original = expected("eip712-UniswapX-DutchOrder")
    value = json.loads(original.to_json_string())
    fields = next(iter(value["display"]["formats"].values()))["fields"]
    if mutation == "order":
        fields[0], fields[1] = fields[1], fields[0]
    elif mutation == "label":
        fields[0]["label"] = "Wrong recipient"
    elif mutation == "tokenPath":
        fields[1]["params"]["tokenPath"] = "witness.inputToken"
    elif mutation == "hidden":
        fields[5]["visible"] = "always"
        fields[5]["label"] = "Nonce"
    else:
        fields[3]["label"] = "Named group"
    changed = type(original).model_validate_json(json.dumps(value))
    assert comparison(changed) != comparison(original)


def test_sequential_and_bundled_permit_batches_are_distinct() -> None:
    descriptor = assemble("eip712-uniswap-permit2")
    value = json.loads(descriptor.to_json_string())
    batch = next(fmt for key, fmt in value["display"]["formats"].items() if key.startswith("PermitBatch("))
    group = next(field for field in batch["fields"] if field.get("iteration") == "sequential")
    assert "label" not in group and "path" not in group
    group["iteration"] = "bundled"
    changed = type(descriptor).model_validate_json(json.dumps(value))
    assert comparison(changed) != comparison(descriptor)
