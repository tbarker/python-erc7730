"""NatSpec is additive to the upstream generation and descriptor interfaces."""

import inspect
import json
from pathlib import Path

import pytest
from pydantic_string_url import HttpUrl
from typer.testing import CliRunner

from erc7730.common.json import read_json_with_includes
from erc7730.common.output import ListOutputAdder
from erc7730.common.schema_types import validate_function_declaration
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.generate import generate_descriptor
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint import lint_all
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.main import app, command_lint
from erc7730.model.input.descriptor import InputERC7730Descriptor as V1Descriptor
from erc7730.model.input.display import InputFieldDescription
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor as V2Descriptor

ADDRESS = "0x" + "11" * 20
ABI = json.dumps([{"type": "function", "name": "send", "inputs": [{"name": "amount", "type": "uint256"}]}])


def test_existing_generator_positional_interface_and_v1_result() -> None:
    assert list(inspect.signature(generate_descriptor).parameters) == [
        "chain_id",
        "contract_address",
        "abi",
        "eip712_schema",
        "owner",
        "legal_name",
        "url",
    ]
    url = HttpUrl("https://example.com")
    positional = generate_descriptor(1, ADDRESS, ABI, None, "Owner", "Legal Name", url)
    keyword = generate_descriptor(1, ADDRESS, abi=ABI, owner="Owner", legal_name="Legal Name", url=url)
    assert isinstance(positional, V1Descriptor)
    assert positional == keyword
    field = positional.display.formats["send(uint256)"].fields[0]
    assert isinstance(field, InputFieldDescription)
    assert field.format == "amount"
    assert isinstance(generate_natspec_descriptor(1, ADDRESS, abi=ABI), V2Descriptor)


def test_cli_keeps_generate_and_adds_natspec(tmp_path: Path) -> None:
    path = tmp_path / "abi.json"
    path.write_text(ABI)
    args = ["--chain-id", "1", "--address", ADDRESS, "--abi", str(path)]
    runner = CliRunner()
    legacy = runner.invoke(
        app, ["generate", *args, "--owner", "Owner", "--legal-name", "Legal", "--url", "https://example.com"]
    )
    authored = runner.invoke(app, ["natspec", *args])
    assert legacy.exit_code == 0, legacy.output
    assert authored.exit_code == 0, authored.output
    assert "send(uint256)" in json.loads(legacy.stdout)["display"]["formats"]
    assert "send(uint256 amount)" in json.loads(authored.stdout)["display"]["formats"]
    assert list(inspect.signature(command_lint).parameters)[:4] == ["paths", "gha", "skip_abi_validation", "v2"]


@pytest.mark.parametrize(
    "declaration",
    [
        "send(uint256 amount)",
        " send( uint256  amount ) ",
        "send(\n\tuint256 amount\n)",
    ],
)
def test_whitespace_preserves_resolution_and_strict_validation(declaration: str) -> None:
    descriptor = generate_natspec_descriptor(1, ADDRESS, abi=ABI)
    descriptor = descriptor.model_copy(
        update={
            "display": descriptor.display.model_copy(
                update={"formats": {declaration: next(iter(descriptor.display.formats.values()))}}
            )
        }
    )
    validate_function_declaration(declaration)
    out = ListOutputAdder()
    result = ERC7730InputToResolved().convert(descriptor, out)
    assert result is not None, out.outputs
    ValidateSchemaLinter().lint(descriptor, result, out)
    assert not out.has_errors, out.outputs
    assert list(result.display.formats) == ["0xa52c101e"]


def test_plain_lint_preserves_legacy_extensions_and_does_not_load_project_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "eip712-legacy.json"
    path.write_text(
        json.dumps(
            {
                "$schema": "erc7730-v2.schema.json",
                "context": {"eip712": {"domainSeparator": "0x" + "11" * 32}},
                "metadata": {
                    "owner": "Owner",
                    "info": {"url": "https://example.com", "legalName": "Legal", "lastUpdate": "2020-01-01T00:00:00Z"},
                },
                "display": {
                    "formats": {
                        "Message(uint256 amount)": {
                            "intent": "Send",
                            "fields": [
                                {
                                    "path": "amount",
                                    "label": "Amount",
                                    "format": "tokenAmount",
                                    "params": {"threshold": 1000},
                                }
                            ],
                        }
                    }
                },
            }
        )
    )
    descriptor = V2Descriptor.load(path)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None and resolved.metadata.info is not None
    assert resolved.metadata.info.legalName == "Legal"
    assert lint_all([path], out) == 1
    assert not out.has_errors, out.outputs
    strict_out = ListOutputAdder()
    lint_all([path], strict_out, strict=True)
    assert strict_out.has_errors
    (tmp_path / "erc7730.toml").write_text("invalid TOML [")
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["lint", str(path)])
    assert result.exit_code == 0, result.output


def test_generic_json_null_override_keeps_upstream_semantics(tmp_path: Path) -> None:
    (tmp_path / "base.json").write_text('{"label":"Inherited"}')
    path = tmp_path / "child.json"
    path.write_text('{"includes":"base.json","label":null}')
    assert read_json_with_includes(path) == {"label": "Inherited"}
