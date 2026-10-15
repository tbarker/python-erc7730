"""Explicit container format tags create fields through the production overlay."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.main import app
from erc7730.model.input.v2.display import InputFieldGroup

SOURCE = Path(__file__).parent / "data/container-fields.artifact.json"
ADDRESS = "0x1111111111111111111111111111111111111111"


def test_compiler_container_fields_cli_library_lint(tmp_path: Path) -> None:
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=SOURCE.read_text())
    fields = descriptor.display.formats["send(address recipient)"].fields
    assert [str(field.path) for field in fields] == ["@.value", "#.recipient"]
    assert fields[0].model_dump(mode="json", exclude_none=True) == {
        "path": "@.value",
        "label": "Amount",
        "format": "amount",
    }
    assert str(descriptor.display.formats["deposit()"].fields[0].path) == "@.value"
    result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(SOURCE)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(descriptor.to_json_string())
    path = tmp_path / "calldata-container.json"
    path.write_text(result.stdout)
    lint = CliRunner().invoke(app, ["lint", str(path), "--skip-abi-validation"])
    assert lint.exit_code == 0, lint.output


def test_container_parameters_groups_and_scoped_updates() -> None:
    docs = json.loads(SOURCE.read_text())
    docs["devdoc"]["custom:clearsig-format"] = "@.value=raw @.chainId=raw @.from=addressName @.to=addressName"
    method = docs["devdoc"]["methods"]["send(address)"]
    method.update(
        {
            "custom:clearsig-format": "@.value=tokenAmount recipient=addressName @.value=tokenAmount",
            "custom:clearsig-token-path": "@.value=@.to",
            "custom:clearsig-group": 'payment="Payment" fields=(@.value,recipient)',
        }
    )
    result = generate_natspec_descriptor(
        1,
        ADDRESS,
        natspec=docs,
        project_defaults={"custom:clearsig-format": "@.value=amount"},
    )
    group, chain, sender, target = result.display.formats["send(address recipient)"].fields
    assert isinstance(group, InputFieldGroup)
    assert [str(field.path) for field in group.fields] == ["@.value", "#.recipient"]
    assert group.fields[0].model_dump(mode="json", exclude_none=True)["params"] == {"tokenPath": "@.to"}
    assert [str(field.path) for field in (chain, sender, target)] == ["@.chainId", "@.from", "@.to"]
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(result, out)
    assert resolved is not None, out.outputs
    ValidateSchemaLinter().lint(result, resolved, out)
    ValidateIntentLinter().lint(result, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("tag", ["@.gas=raw", "@.value=addressName", "@.from=amount", "@.value=unknown"])
def test_invalid_container_format_does_not_create_field(tag: str) -> None:
    warnings: list[str] = []
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi='[{"type":"function","name":"f","inputs":[]}]',
        devdoc={"methods": {"f()": {"custom:clearsig-format": tag}}},
        warnings=warnings,
    )
    assert descriptor.display.formats["f()"].fields == []
    assert any("ignoring container format" in warning for warning in warnings)


def test_labels_and_notice_do_not_create_container_fields() -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi='[{"type":"function","name":"f","inputs":[]}]',
        userdoc={"methods": {"f()": {"notice": "Deposit `@.value`"}}},
        devdoc={
            "methods": {
                "f()": {
                    "custom:clearsig-intent": "Deposit",
                    "custom:clearsig-label": "@.value=Amount",
                }
            }
        },
    )
    assert descriptor.display.formats["f()"].fields == []


def test_data_and_container_names_do_not_alias() -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi='[{"type":"function","name":"f","inputs":[{"name":"value","type":"uint256"}]}]',
        devdoc={
            "methods": {
                "f(uint256)": {
                    "custom:clearsig-format": "@.value=amount value=raw",
                    "custom:clearsig-label": "value=Argument @.value=Transaction",
                }
            }
        },
    )
    fields = descriptor.display.formats["f(uint256 value)"].fields
    assert [(str(field.path), field.label) for field in fields] == [("@.value", "Transaction"), ("#.value", "Argument")]


def test_eip712_container_fields() -> None:
    warnings: list[str] = []
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        eip712_schema=json.dumps([{"primaryType": "Message", "types": {"Message": []}}]),
        devdoc={
            "methods": {
                "Message": {
                    "custom:clearsig-intent": "Sign",
                    "custom:clearsig-format": "@.from=addressName @.to=addressName @.chainId=raw @.value=amount",
                }
            }
        },
        warnings=warnings,
    )
    assert [str(field.path) for field in descriptor.display.formats["Message()"].fields] == [
        "@.from",
        "@.to",
        "@.chainId",
        "@.value",
    ]
    assert any("EIP-712 transfers no native currency" in warning for warning in warnings)
