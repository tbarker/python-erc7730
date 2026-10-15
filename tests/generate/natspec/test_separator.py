"""Array headings are authored through compiler docs, not fixture edits."""

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.main import app
from tests.generate.natspec.upstream_examples import DATA

ADDRESS = "0x1111111111111111111111111111111111111111"


def artifact() -> dict[str, Any]:
    return json.loads((DATA / "example-array-iteration.artifact.json").read_text())


def arrayiter_field_descriptions(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        leaf
        for field in fields
        for leaf in (arrayiter_field_descriptions(field["fields"]) if "fields" in field else [field])
        if ".[]" in str(leaf.get("path", ""))
    ]


def test_compiler_separators_library_and_cli() -> None:
    source = DATA / "example-array-iteration.artifact.json"
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=source.read_text())
    expected = {"distribute": "Recipient {index}", "batchExecute": "Transaction {index}"}
    for key, value in descriptor.display.formats.items():
        fields = arrayiter_field_descriptions(value.model_dump(mode="json")["fields"])
        assert [field["separator"] for field in fields if field.get("separator")] == [expected[key.split("(")[0]]]
    result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(source)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(descriptor.to_json_string())


def test_separator_scope_and_quoted_pairs() -> None:
    docs = artifact()
    docs["devdoc"]["custom:clearsig-separator"] = 'recipients="Contract {index}"'
    method = docs["devdoc"]["methods"]["distribute(address[],uint256[])"]
    method["custom:clearsig-separator"] = 'recipients="Recipient, id={index}" percentages="Fee {index}"'
    result = generate_natspec_descriptor(
        1,
        ADDRESS,
        natspec=docs,
        project_defaults={"custom:clearsig-separator": 'recipients="Project {index}" datas="Call {index}"'},
    )
    fields = arrayiter_field_descriptions(
        result.display.formats["distribute(address[] recipients,uint256[] percentages)"].model_dump()["fields"]
    )
    assert [field["separator"] for field in fields] == ["Recipient, id={index}", "Fee {index}"]
    del method["custom:clearsig-separator"]
    result = generate_natspec_descriptor(1, ADDRESS, natspec=docs)
    fields = arrayiter_field_descriptions(
        result.display.formats["distribute(address[] recipients,uint256[] percentages)"].model_dump()["fields"]
    )
    assert fields[0]["separator"] == "Contract {index}"


@pytest.mark.parametrize("value", ['"Recipient {missing}"', '"Recipient {index"', '"unterminated'])
def test_invalid_separator_warns(value: str) -> None:
    docs = artifact()
    docs["devdoc"]["methods"]["distribute(address[],uint256[])"]["custom:clearsig-separator"] = "recipients=" + value
    warnings: list[str] = []
    result = generate_natspec_descriptor(1, ADDRESS, natspec=docs, warnings=warnings)
    fields = arrayiter_field_descriptions(
        result.display.formats["distribute(address[] recipients,uint256[] percentages)"].model_dump()["fields"]
    )
    assert fields[0]["separator"] is None
    assert any("ignoring separator" in warning for warning in warnings)


def test_scalar_and_unknown_separator_warn() -> None:
    warnings: list[str] = []
    result = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi='[{"type":"function","name":"send","inputs":[{"name":"amount","type":"uint256"}],"outputs":[]}]',
        devdoc={"methods": {"send(uint256)": {"custom:clearsig-separator": 'amount="Item {index}" missing=Item'}}},
        warnings=warnings,
    )
    assert result.display.formats["send(uint256 amount)"].model_dump()["fields"][0]["separator"] is None
    assert any("requires an array field" in warning for warning in warnings)
    assert any("missing parameter" in warning for warning in warnings)
