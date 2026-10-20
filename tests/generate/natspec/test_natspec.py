"""Compiler JSON fixtures represent ITestToken, without compiling Solidity in CI.

/// @title Test Token
/// @notice Simple ERC-20
interface ITestToken {
    /// @notice Send tokens
    /// @param to Recipient
    /// @param amount Amount to send
    /// @custom:clearsig-intent Send
    /// @custom:clearsig-format amount=tokenAmount
    /// @custom:clearsig-token-path amount=@.to
    function transfer(address to, uint256 amount) external returns (bool);
    /// @notice Approve a spender
    /// @param spender Spender
    /// @param amount Allowance
    /// @custom:clearsig-intent Approve
    /// @custom:clearsig-exclude amount
    function approve(address spender, uint256 amount) external returns (bool);
}
"""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter
from typer.testing import CliRunner

from erc7730.common import client
from erc7730.generate.natspec import parse_natspec
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.main import app
from erc7730.model.abi import ABI
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.display import (
    InputField,
    InputFieldDescription,
    InputFieldGroup,
    InputTokenAmountParameters,
)
from erc7730.model.input.v2.format import FieldFormat, VisibilityRule

DATA = Path(__file__).parent / "data"
ADDRESS = "0x0000000000000000000000000000000000000001"
TRANSFER = "transfer(address,uint256)"
APPROVE = "approve(address,uint256)"


@pytest.fixture
def artifact() -> dict[str, Any]:
    return json.loads((DATA / "natspec_artifact.json").read_text())


def generate(artifact: dict[str, Any], **kwargs: Any) -> InputERC7730Descriptor:
    descriptor = generate_natspec_descriptor(1, ADDRESS, abi=json.dumps(artifact["abi"]), **kwargs)
    assert InputERC7730Descriptor.model_validate_json(descriptor.to_json_string()) == descriptor
    return descriptor


def leaf(field: InputField) -> InputFieldDescription:
    assert isinstance(field, InputFieldDescription)
    return field


def test_no_natspec(artifact: dict[str, Any]) -> None:
    descriptor = generate(artifact)
    assert descriptor.to_json_string() == generate(artifact, natspec=None).to_json_string()
    assert descriptor.display.model_dump(mode="json", exclude_none=True) == {
        "formats": {
            "transfer(address to,uint256 amount)": {
                "fields": [
                    {
                        "path": "#.to",
                        "label": "To",
                        "format": "addressName",
                        "params": {"types": ["eoa", "wallet"], "sources": ["local", "ens"]},
                    },
                    {"path": "#.amount", "label": "Amount", "format": "raw"},
                ]
            },
            "approve(address spender,uint256 amount)": {
                "fields": [
                    {
                        "path": "#.spender",
                        "label": "Spender",
                        "format": "addressName",
                        "params": {"types": ["contract"], "sources": ["local", "ens"]},
                    },
                    {"path": "#.amount", "label": "Amount", "format": "raw"},
                ]
            },
        }
    }


def test_notice_params(artifact: dict[str, Any]) -> None:
    dev = {"methods": {TRANSFER: {"params": {"to": "Recipient", "amount": "Amount to send"}}}}
    warnings: list[str] = []
    result = generate(artifact, userdoc=artifact["userdoc"], devdoc=dev, warnings=warnings)
    format = result.display.formats["transfer(address to,uint256 amount)"]
    assert format.intent == "Send tokens"
    assert [leaf(f).label for f in format.fields] == ["Recipient", "Amount to send"]
    assert leaf(format.fields[1]).format == FieldFormat.RAW
    assert all(leaf(f).visible is None for f in format.fields)
    assert any("notice used as intent" in w for w in warnings)
    assert result.metadata.owner is None


def test_custom_artifact(artifact: dict[str, Any]) -> None:
    result = generate_natspec_descriptor(1, ADDRESS, natspec=json.dumps(artifact).encode())
    assert InputERC7730Descriptor.model_validate_json(result.to_json_string()) == result
    assert result.metadata.owner == "Test Token"
    transfer = result.display.formats["transfer(address to,uint256 amount)"]
    assert transfer.intent == "Send"
    assert leaf(transfer.fields[0]).format == FieldFormat.TOKEN_AMOUNT
    params = leaf(transfer.fields[0]).params
    assert isinstance(params, InputTokenAmountParameters)
    assert str(params.tokenPath) == "@.to"
    approve = result.display.formats["approve(address spender,uint256 amount)"]
    assert leaf(approve.fields[1]).visible == VisibilityRule.NEVER
    assert str(approve.fields[1].path) == "#.amount"
    assert len(approve.fields) == 2
    assert leaf(approve.fields[0]).format == FieldFormat.ADDRESS_NAME


def test_split_and_embedded_metadata(artifact: dict[str, Any]) -> None:
    expected = generate(artifact, natspec=artifact)
    assert (
        generate(
            artifact,
            userdoc=(DATA / "natspec_userdoc.json").read_bytes(),
            devdoc=(DATA / "natspec_devdoc.json").read_text(),
        )
        == expected
    )
    assert generate_natspec_descriptor(1, ADDRESS, natspec={"metadata": json.dumps({"output": artifact})}) == expected
    assert generate(artifact, natspec=artifact["userdoc"], devdoc=artifact["devdoc"]) == expected
    with pytest.raises(ValueError, match="Cannot combine"):
        generate(artifact, natspec=artifact, userdoc=artifact["userdoc"])


def test_unmatched_and_unknown(artifact: dict[str, Any]) -> None:
    warnings: list[str] = []
    docs = {"methods": {TRANSFER: {"custom:clearsig-format": "missing=raw amount=bogus"}}}
    result = generate(artifact, devdoc=docs, warnings=warnings)
    assert result == generate(artifact)
    assert len(warnings) == 2


@pytest.mark.parametrize(
    "bad",
    [
        "{",
        "[]",
        b"\xff",
        {"methods": []},
        {"methods": {TRANSFER: None}},
        {"methods": {1: {}}},
        {"methods": {"broken(": {}}},
    ],
)
def test_invalid_docs(artifact: dict[str, Any], bad: Any) -> None:
    warnings: list[str] = []
    assert generate(artifact, devdoc=bad, warnings=warnings) == generate(artifact)
    assert warnings


def test_aliases_and_priorities(artifact: dict[str, Any]) -> None:
    artifact["abi"][0]["inputs"][0]["name"] = "_to"
    docs = {
        "methods": {
            "transfer(address _to,uint256 _amount)": {
                "params": {"to": "Recipient", "AMOUNT": "Quantity"},
                "custom": {
                    "clearsig-label": "to=Final recipient, amount=Final amount",
                    "clearsig-format": "to=ADDRESS_NAME amount=TOKEN_AMOUNT",
                    "clearsig-token-path": "amount=@.to",
                },
            }
        }
    }
    format = generate(artifact, devdoc=docs).display.formats["transfer(address _to,uint256 amount)"]
    assert [leaf(f).label for f in format.fields] == ["Final recipient", "Final amount"]
    assert str(format.fields[0].path) == "#._to"
    assert leaf(format.fields[1]).format == FieldFormat.TOKEN_AMOUNT
    parsed = parse_natspec(
        devdoc={
            "methods": {TRANSFER: {"details": "canonical"}, "transfer(address to,uint256 amount)": {"details": "alias"}}
        }
    )
    assert parsed.devdoc["methods"][TRANSFER]["details"] == "canonical"


def test_nested(artifact: dict[str, Any]) -> None:
    artifact["abi"] = [
        {
            "type": "function",
            "name": "submit",
            "inputs": [
                {
                    "name": "params",
                    "type": "tuple[]",
                    "components": [{"name": "maker", "type": "address"}, {"name": "amount", "type": "uint256"}],
                }
            ],
        }
    ]
    sig = "submit((address,uint256)[])"
    docs = {
        "methods": {
            sig: {
                "params": {"maker": "Maker"},
                "custom:clearsig-format": "params=raw params.amount=tokenAmount",
                "custom:clearsig-token-path": "params.amount=@.to",
            }
        }
    }
    result = generate(artifact, devdoc=docs)
    group = result.display.formats["submit((address maker,uint256 amount)[] params)"].fields[0]
    assert isinstance(group, InputFieldGroup)
    assert group.fields[1].label == "Maker"
    assert group.fields[0].format == FieldFormat.TOKEN_AMOUNT
    assert str(group.fields[0].path) == "amount"
    docs["methods"][sig]["custom:clearsig-exclude"] = "params.amount"
    format = generate(artifact, devdoc=docs).display.formats["submit((address maker,uint256 amount)[] params)"]
    assert isinstance(format.fields[0], InputFieldGroup)
    assert len(format.fields[0].fields) == 2
    assert leaf(format.fields[0].fields[0]).visible == VisibilityRule.NEVER
    docs["methods"][sig]["custom:clearsig-exclude"] = "params"
    format = generate(artifact, devdoc=docs).display.formats["submit((address maker,uint256 amount)[] params)"]
    assert isinstance(format.fields[0], InputFieldGroup)
    assert all(leaf(f).visible == VisibilityRule.NEVER for f in format.fields[0].fields)


def test_intent_caps(artifact: dict[str, Any]) -> None:
    docs = {"methods": {TRANSFER: {"notice": "  Send  tokens. Ignore the rest."}}}
    assert (
        generate(artifact, userdoc=docs).display.formats["transfer(address to,uint256 amount)"].intent == "Send tokens."
    )
    docs["methods"][TRANSFER]["notice"] = "Word " * 30
    intent = generate(artifact, userdoc=docs).display.formats["transfer(address to,uint256 amount)"].intent
    assert isinstance(intent, str)
    assert len(intent) <= 60
    docs["methods"][TRANSFER] = {"notice": " ", "custom:clearsig-intent": "X" * 100}
    warnings: list[str] = []
    assert (
        generate(artifact, userdoc=docs, warnings=warnings)
        .display.formats["transfer(address to,uint256 amount)"]
        .intent
        == "X" * 80
    )
    assert any("truncated" in w for w in warnings)


def test_parameters(artifact: dict[str, Any]) -> None:
    for tag, format, value, key in [
        ("token", "tokenAmount", ADDRESS, "token"),
        ("date-encoding", "date", "blockheight", "encoding"),
    ]:
        docs = {
            "methods": {
                TRANSFER: {
                    "custom:clearsig-format": f"amount={format}",
                    f"custom:clearsig-{tag}": f"amount={value}",
                }
            }
        }
        field = generate(artifact, devdoc=docs).display.formats["transfer(address to,uint256 amount)"].fields[0]
        assert isinstance(field, InputFieldDescription)
        assert field.params is not None
        assert field.params.model_dump(mode="json", exclude_none=True) == {key: value}


def test_eip712(artifact: dict[str, Any]) -> None:
    schema = json.dumps([{"primaryType": "Mail", "types": {"Mail": [{"name": "amount", "type": "uint256"}]}}])
    result = generate_natspec_descriptor(1, ADDRESS, eip712_schema=schema, natspec=artifact)
    assert result.metadata.owner == "Test Token"
    assert result.display.formats["Mail(uint256 amount)"].intent is None
    docs = {"methods": {"Mail": {"params": {"amount": "Quantity"}, "custom:clearsig-intent": "Send mail"}}}
    result = generate_natspec_descriptor(1, ADDRESS, eip712_schema=schema, devdoc=docs)
    assert result.display.formats["Mail(uint256 amount)"].intent == "Send mail"
    assert leaf(result.display.formats["Mail(uint256 amount)"].fields[0]).label == "Quantity"


def test_cli_and_lint(tmp_path: Path, artifact: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    abis = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    runner = CliRunner()
    args = [
        "natspec",
        "--chain-id",
        "1",
        "--address",
        ADDRESS,
        "--natspec",
        str(DATA / "natspec_artifact.json"),
        "--owner",
        "Explicit",
        "--url",
        "https://example.com",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    descriptor = json.loads(result.stdout)
    assert descriptor["metadata"]["owner"] == "Explicit"
    assert "legalName" not in descriptor["metadata"]["info"]
    assert descriptor["metadata"]["info"]["url"] == "https://example.com"
    path = tmp_path / "calldata-test.json"
    path.write_text(result.stdout)
    lint = runner.invoke(app, ["lint", "--strict", str(path), "--skip-abi-validation"])
    assert lint.exit_code == 0, lint.output
    conflict = runner.invoke(app, [*args, "--userdoc", str(DATA / "natspec_userdoc.json")])
    assert conflict.exit_code == 1
    assert "Cannot combine" in conflict.stderr
    assert conflict.stdout == ""


def test_cli_warnings(tmp_path: Path, artifact: dict[str, Any]) -> None:
    artifact["devdoc"]["methods"][TRANSFER]["custom:clearsig-format"] = "absent=raw"
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact))
    result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(path)])
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)
    assert "missing parameter" in result.stderr


@pytest.mark.parametrize(
    "tag,format,value",
    [
        ("token", "tokenAmount", "not-an-address"),
        ("token-path", "tokenAmount", "@.invalid"),
        ("date-encoding", "date", "invalid"),
        ("token-path", "raw", "@.to"),
    ],
)
def test_invalid_parameters(artifact: dict[str, Any], tag: str, format: str, value: str) -> None:
    warnings: list[str] = []
    docs = {
        "methods": {
            TRANSFER: {
                "custom:clearsig-format": f"amount={format}",
                f"custom:clearsig-{tag}": f"amount={value}",
            }
        }
    }
    result = generate(artifact, devdoc=docs, warnings=warnings)
    assert len(result.display.formats["transfer(address to,uint256 amount)"].fields) == 2
    assert warnings


def test_metadata_precedence(artifact: dict[str, Any]) -> None:
    docs = {"title": "Title", "author": "Author"}
    assert generate(artifact, devdoc=docs).metadata.owner == "Author"
    assert generate(artifact, devdoc=docs, owner="Explicit").metadata.owner == "Explicit"
    assert generate(artifact, devdoc={"title": "Title", "author": " "}).metadata.owner == "Title"
    assert generate(artifact, owner="Explicit").metadata.owner == "Explicit"
    assert generate(artifact, devdoc=docs).metadata.contractName == "Title"


def test_empty_pair_conflict() -> None:
    with pytest.raises(ValueError, match="Cannot combine"):
        parse_natspec({"userdoc": {}, "devdoc": {}}, userdoc={})


def test_project_and_contract_defaults(artifact: dict[str, Any]) -> None:
    project = {"custom:clearsig-format": "amount=tokenAmount", "custom:clearsig-token": f"amount={ADDRESS}"}
    docs = {
        "custom:clearsig-token-path": "amount=@.to",
        "methods": {TRANSFER: {"custom:clearsig-format": "amount=raw"}},
    }
    result = generate(artifact, devdoc=docs, project_defaults=project)
    transfer = leaf(result.display.formats["transfer(address to,uint256 amount)"].fields[0])
    approve = leaf(result.display.formats["approve(address spender,uint256 amount)"].fields[0])
    assert transfer.format == FieldFormat.RAW
    assert transfer.params is None
    assert approve.format == FieldFormat.TOKEN_AMOUNT
    assert isinstance(approve.params, InputTokenAmountParameters)
    assert str(approve.params.tokenPath) == "@.to"
    assert approve.params.token is None


def test_project_defaults_without_natspec(artifact: dict[str, Any]) -> None:
    result = generate(
        artifact,
        project_defaults={"custom:clearsig-format": "amount=TOKEN_AMOUNT", "custom:clearsig-token-path": "amount=@.to"},
    )
    for format in result.display.formats.values():
        amount = leaf(format.fields[0])
        assert amount.format == FieldFormat.TOKEN_AMOUNT
        assert isinstance(amount.params, InputTokenAmountParameters)
        assert str(amount.params.tokenPath) == "@.to"


def test_contract_defaults_merge_per_parameter(artifact: dict[str, Any]) -> None:
    artifact["abi"][0]["inputs"][1]["name"] = "_amount"
    docs = {
        "custom": {"clearsig-format": "to=raw amount=tokenAmount", "clearsig-token-path": "amount=@.to"},
        "methods": {
            TRANSFER: {"custom:clearsig-format": "to=ADDRESS_NAME", "custom:clearsig-token": f"_amount={ADDRESS}"}
        },
    }
    warnings: list[str] = []
    result = generate(artifact, devdoc=docs, warnings=warnings)
    transfer = result.display.formats["transfer(address to,uint256 _amount)"]
    assert leaf(transfer.fields[0]).format == FieldFormat.ADDRESS_NAME
    amount = leaf(transfer.fields[1])
    assert amount.format == FieldFormat.TOKEN_AMOUNT
    assert isinstance(amount.params, InputTokenAmountParameters)
    assert amount.params.token == ADDRESS
    assert amount.params.tokenPath is None
    # 'to' is absent in approve, but present in transfer: no spurious default warning.
    assert warnings == []


def test_date_defaults(artifact: dict[str, Any]) -> None:
    result = generate(
        artifact,
        project_defaults={"custom:clearsig-format": "amount=date", "custom:clearsig-date-encoding": "amount=timestamp"},
        devdoc={"custom:clearsig-date-encoding": "amount=blockheight"},
    )
    for format in result.display.formats.values():
        amount = leaf(format.fields[0])
        assert amount.format == FieldFormat.DATE
        assert amount.params is not None
        assert amount.params.model_dump(mode="json") == {"encoding": "blockheight"}


def test_defaults_do_not_inherit_other_tags(artifact: dict[str, Any]) -> None:
    defaults = {
        "custom:clearsig-intent": "Ignored",
        "custom:clearsig-label": "amount=Ignored",
    }
    assert generate(artifact, project_defaults=defaults, devdoc=defaults) == generate(artifact)


def test_unmatched_defaults_warn_once(artifact: dict[str, Any]) -> None:
    warnings: list[str] = []
    assert generate(
        artifact,
        project_defaults={"custom:clearsig-format": "absent=raw"},
        devdoc={"custom:clearsig-token-path": "missing=@.to"},
        warnings=warnings,
    ) == generate(artifact)
    assert len(warnings) == 2
    assert warnings[0].startswith("project:")
    assert warnings[1].startswith("contract:")


def test_cli_project_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, artifact: dict[str, Any]) -> None:
    # Project defaults also work with --abi alone, and are discovered from child directories.
    abi = tmp_path / "abi.json"
    abi.write_text(json.dumps(artifact["abi"]))
    (tmp_path / "erc7730.toml").write_text(
        '[generate]\n"custom:clearsig-format" = "amount=tokenAmount"\n"custom:clearsig-token-path" = "amount=@.to"\n'
    )
    child = tmp_path / "child"
    child.mkdir()
    monkeypatch.chdir(child)
    args = ["natspec", "--chain-id", "1", "--address", ADDRESS, "--abi", str(abi)]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    amount = json.loads(result.stdout)["display"]["formats"]["transfer(address to,uint256 amount)"]["fields"][0]
    assert amount["format"] == "tokenAmount"
    assert amount["params"] == {"tokenPath": "@.to"}
    assert result.stderr == ""
    override = child / "erc7730.toml"
    override.write_text('[generate]\n"custom:clearsig-format" = "amount=raw"\n')
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert (
        json.loads(result.stdout)["display"]["formats"]["transfer(address to,uint256 amount)"]["fields"][0]["format"]
        == "raw"
    )
    explicit = tmp_path / "explicit.toml"
    explicit.write_text('[generate]\n"custom:clearsig-format" = "amount=duration"\n')
    result = runner.invoke(app, [*args, "--config", str(explicit)])
    assert result.exit_code == 0, result.output
    assert (
        json.loads(result.stdout)["display"]["formats"]["transfer(address to,uint256 amount)"]["fields"][0]["format"]
        == "duration"
    )
    # Library calls never read ambient project configuration.
    assert (
        leaf(generate(artifact).display.formats["transfer(address to,uint256 amount)"].fields[1]).format
        == FieldFormat.RAW
    )


@pytest.mark.parametrize("contents", ["[broken", 'generate = "not a table"', None])
def test_invalid_project_config(tmp_path: Path, contents: str | None) -> None:
    path = tmp_path / "config.toml"
    if contents is not None:
        path.write_text(contents)
    result = CliRunner().invoke(
        app,
        [
            "natspec",
            "--chain-id",
            "1",
            "--address",
            ADDRESS,
            "--natspec",
            str(DATA / "natspec_artifact.json"),
            "--config",
            str(path),
        ],
    )
    assert result.exit_code == 1
    assert "config" in result.stderr
    assert result.stdout == ""


def test_invalid_method_override_keeps_defaults(artifact: dict[str, Any]) -> None:
    warnings: list[str] = []
    result = generate(
        artifact,
        project_defaults={"custom:clearsig-format": "amount=tokenAmount", "custom:clearsig-token-path": "amount=@.to"},
        devdoc={
            "methods": {
                TRANSFER: {"custom:clearsig-format": "amount=unknown", "custom:clearsig-token": "amount=invalid"}
            }
        },
        warnings=warnings,
    )
    amount = leaf(result.display.formats["transfer(address to,uint256 amount)"].fields[1])
    assert amount.format == FieldFormat.TOKEN_AMOUNT
    assert isinstance(amount.params, InputTokenAmountParameters)
    assert str(amount.params.tokenPath) == "@.to"
    assert len(warnings) == 2


def test_eip712_nested_defaults() -> None:
    schema = json.dumps(
        [
            {
                "primaryType": "Order",
                "types": {
                    "Order": [{"name": "details", "type": "Details"}],
                    "Details": [{"name": "amount", "type": "uint256"}],
                },
            }
        ]
    )
    result = generate_natspec_descriptor(
        1,
        ADDRESS,
        eip712_schema=schema,
        project_defaults={"custom:clearsig-format": "details.amount=tokenAmount"},
        devdoc={"custom:clearsig-token-path": "details.amount=@.to"},
    )
    amount = leaf(result.display.formats["Order(Details details)Details(uint256 amount)"].fields[0])
    assert amount.format == FieldFormat.TOKEN_AMOUNT
    assert isinstance(amount.params, InputTokenAmountParameters)
    assert str(amount.params.tokenPath) == "@.to"
    assert str(amount.path) == "#.details.amount"


def test_scoped_exclusions(artifact: dict[str, Any]) -> None:
    warnings: list[str] = []
    result = generate(
        artifact,
        project_defaults={"custom:clearsig-exclude": "to,absentEverywhere"},
        devdoc={"custom": {"clearsig-exclude": "spender,alsoAbsent"}},
        warnings=warnings,
    )
    transfer = result.display.formats["transfer(address to,uint256 amount)"]
    approve = result.display.formats["approve(address spender,uint256 amount)"]
    for format in (transfer, approve):
        assert leaf(format.fields[0]).visible == VisibilityRule.NEVER
        assert len(format.fields) == 2
        assert str(format.fields[1].path) == "#.amount"
        assert leaf(format.fields[1]).visible is None
    assert warnings == []


def test_overlapping_exclusions(artifact: dict[str, Any]) -> None:
    # Name aliases in different scopes still identify the same existing field.
    artifact["abi"][0]["inputs"][1]["name"] = "_amount"
    result = generate(
        artifact,
        project_defaults={"custom:clearsig-exclude": "amount"},
        devdoc={
            "custom:clearsig-exclude": "AMOUNT",
            "methods": {TRANSFER: {"custom:clearsig-exclude": "_amount", "custom:clearsig-format": "_amount=raw"}},
        },
    )
    transfer = result.display.formats["transfer(address to,uint256 _amount)"]
    assert leaf(transfer.fields[0]).visible == VisibilityRule.NEVER
    assert str(transfer.fields[0].path) == "#._amount"
    assert len(transfer.fields) == 2


@pytest.mark.parametrize("scope", ["project", "contract"])
def test_scoped_nested_exclusions(scope: str, artifact: dict[str, Any]) -> None:
    artifact["abi"][0]["inputs"] = [
        {
            "name": "order",
            "type": "tuple[]",
            "components": [
                {"name": "maker", "type": "address"},
                {"name": "amount", "type": "uint256"},
            ],
        }
    ]
    for name in ("order.amount", "order"):
        defaults = {"custom:clearsig-exclude": name}
        warnings: list[str] = []
        result = generate(
            artifact,
            project_defaults=defaults if scope == "project" else None,
            devdoc=defaults if scope == "contract" else None,
            warnings=warnings,
        )
        transfer = result.display.formats["transfer((address maker,uint256 amount)[] order)"]
        assert isinstance(transfer.fields[0], InputFieldGroup)
        group = transfer.fields[0]
        assert len(group.fields) == 2
        assert leaf(group.fields[1]).visible == VisibilityRule.NEVER
        assert leaf(group.fields[0]).visible == (VisibilityRule.NEVER if name == "order" else None)
        assert all(
            leaf(f).visible is None for f in result.display.formats["approve(address spender,uint256 amount)"].fields
        )
        assert warnings == []


@pytest.mark.parametrize("signature", [TRANSFER, "transfer(address to,uint256 amount)"])
def test_missing_method_exclusion_is_error(signature: str, artifact: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="exclude refers to missing parameter 'absent'"):
        generate(artifact, devdoc={"methods": {signature: {"custom:clearsig-exclude": "absent"}}})


def test_method_exclusion_on_empty_function(artifact: dict[str, Any]) -> None:
    artifact["abi"] = [{"type": "function", "name": "ping", "inputs": []}]
    with pytest.raises(ValueError, match="exclude refers to missing parameter 'amount'"):
        generate(artifact, devdoc={"methods": {"ping()": {"custom:clearsig-exclude": "amount"}}})
    warnings: list[str] = []
    generate(artifact, devdoc={"custom:clearsig-exclude": "amount"}, warnings=warnings)
    assert warnings == []


def test_cli_exclusions(tmp_path: Path, artifact: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    abis = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    path = tmp_path / "artifact.json"
    # Use project exclusions alone first, including a parameter absent from all methods.
    artifact["devdoc"]["methods"] = {}
    artifact["userdoc"]["methods"] = {}
    path.write_text(json.dumps(artifact))
    config = tmp_path / "erc7730.toml"
    config.write_text('[generate]\n"custom:clearsig-exclude" = "amount,absent"\n')
    args = ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(path), "--config", str(config)]
    runner = CliRunner()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    descriptor = json.loads(result.stdout)
    assert descriptor["display"]["formats"]["transfer(address to,uint256 amount)"]["fields"][1]["visible"] == "never"
    output = tmp_path / "calldata-exclusions.json"
    output.write_text(result.stdout)
    lint = runner.invoke(app, ["lint", "--strict", str(output), "--skip-abi-validation"])
    assert lint.exit_code == 1, lint.output
    assert "Invalid V2 JSON schema" in lint.output and "intent" in lint.output
    artifact["devdoc"]["methods"][TRANSFER] = {"custom:clearsig-exclude": "absent"}
    path.write_text(json.dumps(artifact))
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "exclude refers to missing parameter 'absent'" in result.stderr
    assert result.stdout == ""


@pytest.mark.parametrize("scope", ["project", "contract", "method"])
@pytest.mark.parametrize("spelling", ["addressName", "ADDRESS_NAME"])
def test_explicit_address_format_replaces_inferred_restrictions(
    artifact: dict[str, Any], scope: str, spelling: str
) -> None:
    tag = {"custom:clearsig-format": f"to={spelling} spender={spelling}"}
    scopes: dict[str, dict[str, Any]] = {
        "project": {"project_defaults": tag},
        "contract": {"devdoc": tag},
        "method": {
            "devdoc": {
                "methods": {
                    TRANSFER: {"custom:clearsig-format": f"to={spelling}"},
                    APPROVE: {"custom:clearsig-format": f"spender={spelling}"},
                }
            }
        },
    }
    kwargs = scopes[scope]
    inferred = generate(artifact)
    explicit = generate(artifact, **kwargs)
    for key in inferred.display.formats:
        original = leaf(inferred.display.formats[key].fields[0])
        updated = leaf(explicit.display.formats[key].fields[0])
        assert original.params is not None
        assert updated.format == FieldFormat.ADDRESS_NAME
        assert updated.params is not None
        assert updated.params.model_dump(exclude_none=True) == {"sources": ["local", "ens"]}
        assert updated.path == original.path
        assert updated.label == original.label


def test_invalid_address_format_keeps_inferred_restrictions(artifact: dict[str, Any]) -> None:
    warnings: list[str] = []
    result = generate(
        artifact, devdoc={"methods": {TRANSFER: {"custom:clearsig-format": "to=unknown"}}}, warnings=warnings
    )
    assert result.display == generate(artifact).display
    assert any("unknown format" in warning for warning in warnings)


def test_repeated_format_keeps_authored_parameters(artifact: dict[str, Any]) -> None:
    result = generate(
        artifact,
        project_defaults={
            "custom:clearsig-format": "amount=tokenAmount",
            "custom:clearsig-token-path": "amount=@.to",
        },
        devdoc={"methods": {TRANSFER: {"custom:clearsig-format": "amount=TOKEN_AMOUNT"}}},
    )
    amount = leaf(result.display.formats["transfer(address to,uint256 amount)"].fields[0])
    assert isinstance(amount.params, InputTokenAmountParameters)
    assert str(amount.params.tokenPath) == "@.to"


def test_address_format_clears_guess_but_preserves_authored_map(artifact: dict[str, Any]) -> None:
    result = generate(
        artifact,
        project_defaults={
            "maps": {"senders": {"values": {"1": ADDRESS}}},
            "custom:clearsig-map-ref": "to=senderAddress:senders(@.chainId)",
        },
        devdoc={"methods": {TRANSFER: {"custom:clearsig-format": "to=addressName"}}},
    )
    field = leaf(result.display.formats["transfer(address to,uint256 amount)"].fields[0])
    assert field.params is not None
    params = field.params.model_dump(mode="json", exclude_none=True)
    assert "types" not in params
    assert params["senderAddress"] == {"map": "$.metadata.maps.senders", "keyPath": "@.chainId"}


@pytest.mark.parametrize("nested", [False, True])
def test_kebab_case_annotation_vocabulary(nested: bool) -> None:
    """Compiler spellings map to schema names in both solc custom-tag shapes."""
    from erc7730.generate.natspec.display.annotations import TAGS, _tags

    compounds = {
        "amount-path": "amountPath",
        "callee-path": "calleePath",
        "chain-id": "chainId",
        "chain-id-path": "chainIdPath",
        "collection-path": "collectionPath",
        "date-encoding": "dateEncoding",
        "encryption-scheme": "encryptionScheme",
        "enum-ref": "enumRef",
        "fallback-label": "fallbackLabel",
        "if-not-in": "ifNotIn",
        "interpolated-intent": "interpolatedIntent",
        "map-ref": "mapRef",
        "must-match": "mustMatch",
        "native-currency-address": "nativeCurrencyAddress",
        "plaintext-type": "plaintextType",
        "selector-path": "selectorPath",
        "sender-address": "senderAddress",
        "spender-path": "spenderPath",
        "token-path": "tokenPath",
    }
    vocabulary = compounds | {tag: tag for tag in TAGS if tag.islower()}
    assert set(vocabulary.values()) == set(TAGS)
    tags = {f"clearsig-{name}": f"value for {name}" for name in vocabulary}
    doc: dict[str, Any] = {"custom": tags} if nested else {f"custom:{name}": value for name, value in tags.items()}
    assert _tags(doc) == {model_name: f"value for {name}" for name, model_name in vocabulary.items()}

    # The public vocabulary has one spelling; the old concatenated names are not aliases.
    old_tags = {f"clearsig-{name.replace('-', '')}": "ignored" for name in compounds}
    old_doc: dict[str, Any] = (
        {"custom": old_tags} if nested else {f"custom:{name}": value for name, value in old_tags.items()}
    )
    assert _tags(old_doc) == {}
