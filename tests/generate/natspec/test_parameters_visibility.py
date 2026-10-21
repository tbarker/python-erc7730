"""Formatter parameters and visibility are authored through the public overlay."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from erc7730.common import client
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.abi import ABI as ABI_MODEL

pytestmark = pytest.mark.usefixtures("local_explorer")

ADDRESS = "0x1111111111111111111111111111111111111111"
ABI = '[{"type":"function","name":"f","inputs":[{"name":"x","type":"uint256"},{"name":"to","type":"address"}]}]'


def field(tags: dict[str, str], **kwargs: Any) -> dict[str, Any]:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=ABI,
        devdoc={"methods": {"f(uint256,address)": tags}},
        **kwargs,
    )
    return next(
        leaf.model_dump(mode="json", exclude_none=True)
        for leaf in descriptor.display.formats["f(uint256 x,address to)"].fields
        if str(leaf.path) == "#.x"
    )


def test_unit_required_parameters_merge_across_scopes() -> None:
    result = field(
        {"custom:clearsig-base": 'x="%"'},
        project_defaults={
            "custom:clearsig-format": "x=unit",
            "custom:clearsig-decimals": "x=2",
            "custom:clearsig-prefix": "x=false",
        },
    )
    assert result["params"] == {"base": "%", "decimals": 2, "prefix": False}


def test_threshold_preserved_when_token_binding_changes() -> None:
    result = field(
        {"custom:clearsig-token": f"x={ADDRESS}", "custom:clearsig-message": 'x="Unlimited approval"'},
        project_defaults={
            "custom:clearsig-format": "x=tokenAmount",
            "custom:clearsig-token-path": "x=@.to",
            "custom:clearsig-threshold": "x=0xffff",
        },
    )
    assert result["params"] == {"token": ADDRESS, "threshold": "0xffff", "message": "Unlimited approval"}


def test_changing_format_discards_inherited_parameters() -> None:
    result = field(
        {"custom:clearsig-format": "x=raw"},
        project_defaults={"custom:clearsig-format": "x=unit", "custom:clearsig-base": "x=%"},
    )
    assert "params" not in result


def test_authored_types_survive_repeated_address_formatter() -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=ABI,
        project_defaults={
            "custom:clearsig-format": "to=addressName",
            "custom:clearsig-types": 'to=["contract"]',
            "custom:clearsig-sources": 'to=["ens","local"]',
        },
        devdoc={"methods": {"f(uint256,address)": {"custom:clearsig-format": "to=ADDRESS_NAME"}}},
    )
    to = descriptor.display.formats["f(uint256 x,address to)"].fields[0]
    assert to.model_dump(mode="json", exclude_none=True)["params"] == {
        "types": ["contract"],
        "sources": ["ens", "local"],
    }


@pytest.mark.parametrize("tag,value", [("decimals", "true"), ("decimals", "1.5"), ("base", "[]")])
def test_bad_override_keeps_valid_defaults(tag: str, value: str) -> None:
    warnings: list[str] = []
    result = field(
        {f"custom:clearsig-{tag}": f"x={value}"},
        warnings=warnings,
        project_defaults={
            "custom:clearsig-format": "x=unit",
            "custom:clearsig-base": "x=%",
            "custom:clearsig-decimals": "x=2",
        },
    )
    assert result["params"] == {"base": "%", "decimals": 2}
    assert warnings


@pytest.mark.parametrize(
    "tag,value,expected",
    [
        ("visible", "optional", "optional"),
        ("visible", "always", "always"),
        ("must-match", "[0,1]", {"mustMatch": [0, 1]}),
        ("if-not-in", "[0]", {"ifNotIn": [0]}),
    ],
)
def test_visibility_scope_override(tag: str, value: str, expected: Any) -> None:
    result = field(
        {f"custom:clearsig-{tag}": f"x={value}"},
        project_defaults={"custom:clearsig-visible": "x=never"},
    )
    assert result["visible"] == expected


def test_visibility_conflicts_are_errors() -> None:
    with pytest.raises(ValueError, match="conflicting method visibility"):
        field({"custom:clearsig-must-match": "x=[0]", "custom:clearsig-if-not-in": "x=[1]"})


@pytest.mark.parametrize("value", ["[]", "{}", "0"])
def test_invalid_condition_does_not_hide_field(value: str) -> None:
    warnings: list[str] = []
    result = field({"custom:clearsig-must-match": "x=" + value}, warnings=warnings)
    assert "visible" not in result
    assert warnings


def test_exclude_wins_over_visibility() -> None:
    result = field({"custom:clearsig-visible": "x=always"}, project_defaults={"custom:clearsig-exclude": "x"})
    assert result["visible"] == "never"


def test_complete_calldata_parameters_use_existing_model() -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps([{"type": "function", "name": "f", "inputs": [{"name": "data", "type": "bytes"}]}]),
        devdoc={
            "methods": {
                "f(bytes)": {
                    "custom:clearsig-format": "data=calldata",
                    "custom:clearsig-callee-path": "data=@.to",
                    "custom:clearsig-selector": 'data="0xa9059cbb"',
                    "custom:clearsig-amount": "data=123",
                    "custom:clearsig-spender": f"data={ADDRESS}",
                }
            }
        },
    )
    assert descriptor.display.formats["f(bytes data)"].fields[0].model_dump(mode="json", exclude_none=True)[
        "params"
    ] == {
        "calleePath": "@.to",
        "selector": "0xa9059cbb",
        "amount": 123,
        "spender": ADDRESS,
    }


def test_compiled_visibility_cli_and_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from erc7730.main import app

    source = Path(__file__).parent / "data/upstream_examples/example-visibility-rules.artifact.json"
    abis = TypeAdapter(list[ABI_MODEL]).validate_python(json.loads(source.read_text())["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=source.read_text())
    runner = CliRunner()
    result = runner.invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(source)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(descriptor.to_json_string())
    path = tmp_path / "calldata-visibility.json"
    path.write_text(result.stdout)
    lint = runner.invoke(app, ["lint", str(path), "--skip-abi-validation"])
    assert lint.exit_code == 0, lint.output
