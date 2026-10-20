"""V2 generation and safe translation of compiler NatSpec intent templates."""

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
from pydantic import TypeAdapter
from typer.testing import CliRunner

from erc7730.common import client
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.main import app
from erc7730.model.abi import ABI
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

DATA = Path(__file__).parent / "data"
ADDRESS = "0x0000000000000000000000000000000000000001"
SIGNATURE = "transfer(address,uint256)"


@pytest.fixture
def artifact() -> dict[str, Any]:
    data = json.loads((DATA / "natspec_artifact.json").read_text())
    data["userdoc"]["methods"][SIGNATURE]["notice"] = "Send `amount` to `to`. Confirm this transfer."
    return data


def generate(artifact: dict[str, Any], **kwargs: Any) -> InputERC7730Descriptor:
    result = generate_natspec_descriptor(1, ADDRESS, natspec=artifact, **kwargs)
    assert InputERC7730Descriptor.model_validate_json(result.to_json_string()) == result
    return result


def test_natspec_template(artifact: dict[str, Any]) -> None:
    result = generate(artifact)
    format = result.display.formats["transfer(address to,uint256 amount)"]
    assert format.intent == "Send"
    assert format.interpolatedIntent == "Send {amount} to {to}. Confirm this transfer."
    assert result.metadata.contractName == "Test Token"
    assert result.schema_ is not None and "erc7730-v2.1.0.schema.json" in result.schema_
    schema = json.loads(Path("specs/erc7730-v2.schema.json").read_text())
    jsonschema.validate(json.loads(result.to_json_string()), schema)


def test_missing_static_intent_is_error(artifact: dict[str, Any]) -> None:
    del artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-intent"]
    with pytest.raises(ValueError, match="Add @custom:clearsig-intent"):
        generate(artifact)


def test_custom_template_priority_and_escaping(artifact: dict[str, Any]) -> None:
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = (
        "Deliver {amount} to {to}, marked {{gift}}"
    )
    format = generate(artifact).display.formats["transfer(address to,uint256 amount)"]
    assert format.intent == "Send"
    assert format.interpolatedIntent == "Deliver {amount} to {to}, marked {{gift}}"


def test_literal_braces_in_notice(artifact: dict[str, Any]) -> None:
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send `amount` labelled {gift} to `to`"
    assert (
        generate(artifact).display.formats["transfer(address to,uint256 amount)"].interpolatedIntent
        == "Send {amount} labelled {{gift}} to {to}"
    )
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send tokens labelled {gift}"
    assert generate(artifact).display.formats["transfer(address to,uint256 amount)"].interpolatedIntent is None


@pytest.mark.parametrize("custom", [False, True])
def test_templates_are_not_truncated(artifact: dict[str, Any], custom: bool) -> None:
    prefix = "Please transfer these tokens to the recipient specified in this transaction after reviewing the amount: "
    if custom:
        template = prefix + "{amount} to {to}"
        artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = template
    else:
        artifact["userdoc"]["methods"][SIGNATURE]["notice"] = prefix + "`amount` to `to`"
        template = prefix + "{amount} to {to}"
    warnings: list[str] = []
    format = generate(artifact, warnings=warnings).display.formats["transfer(address to,uint256 amount)"]
    assert format.interpolatedIntent == template
    assert any("without truncation" in warning for warning in warnings)


@pytest.mark.parametrize(
    "text", ["Send `amount * 2`", "Send `missing`", "Send `amount", "Send `to.toString()`", "Send ``"]
)
def test_unsupported_notice_requires_explicit_template(artifact: dict[str, Any], text: str) -> None:
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = text
    with pytest.raises(ValueError, match="@custom:clearsig-interpolated-intent"):
        generate(artifact)
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = "Send {amount}"
    assert (
        generate(artifact).display.formats["transfer(address to,uint256 amount)"].interpolatedIntent == "Send {amount}"
    )


@pytest.mark.parametrize("text", ["Send {amount", "Send {amount}}", "Send {}", "Send {amount:02}"])
def test_invalid_custom_templates(artifact: dict[str, Any], text: str) -> None:
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = text
    with pytest.raises(ValueError, match="@custom:clearsig-interpolated-intent"):
        generate(artifact)


@pytest.mark.parametrize("scope", ["project", "contract", "method"])
def test_excluded_template_references(artifact: dict[str, Any], scope: str) -> None:
    defaults = {"custom:clearsig-exclude": "amount"}
    if scope == "contract":
        artifact["devdoc"].update(defaults)
    elif scope == "method":
        artifact["devdoc"]["methods"][SIGNATURE].update(defaults)
    with pytest.raises(ValueError, match="excluded"):
        generate(artifact, project_defaults=defaults if scope == "project" else None)


def test_nested_and_ambiguous_templates(artifact: dict[str, Any]) -> None:
    artifact["abi"] = [
        {
            "type": "function",
            "name": "submit",
            "inputs": [
                {
                    "name": name,
                    "type": "tuple",
                    "components": [{"name": "maker", "type": "address"}, {"name": "amount", "type": "uint256"}],
                }
                for name in ("order", "other")
            ],
        }
    ]
    signature = "submit((address,uint256),(address,uint256))"
    artifact["devdoc"]["methods"] = {signature: {"custom:clearsig-intent": "Submit"}}
    artifact["userdoc"]["methods"] = {signature: {"notice": "Submit `order.amount` from `order.maker`"}}
    format = generate(artifact).display.formats[
        "submit((address maker,uint256 amount) order,(address maker,uint256 amount) other)"
    ]
    assert format.interpolatedIntent == "Submit {order.amount} from {order.maker}"
    artifact["userdoc"]["methods"][signature]["notice"] = "Submit `amount`"
    with pytest.raises(ValueError, match="ambiguous"):
        generate(artifact)


def test_template_aliases(artifact: dict[str, Any]) -> None:
    artifact["abi"][0]["inputs"][0]["name"] = "_to"
    assert (
        generate(artifact).display.formats["transfer(address _to,uint256 amount)"].interpolatedIntent
        == "Send {amount} to {_to}. Confirm this transfer."
    )


def test_eip712_template_and_type_key(tmp_path: Path) -> None:
    schemas = [
        {
            "primaryType": "Order",
            "types": {
                "Order": [{"name": "details", "type": "Details"}],
                "Details": [{"name": "amount", "type": "uint256"}],
                "Unused": [{"name": "unused", "type": "bool"}],
            },
        }
    ]
    result = generate_natspec_descriptor(
        1,
        ADDRESS,
        eip712_schema=json.dumps(schemas),
        userdoc={"methods": {"Order": {"notice": "Sign for `details.amount`"}}},
        devdoc={"methods": {"Order": {"custom:clearsig-intent": "Order"}}},
    )
    format = result.display.formats["Order(Details details)Details(uint256 amount)"]
    assert format.intent == "Order"
    assert format.interpolatedIntent == "Sign for {details.amount}"
    path = tmp_path / "eip712-order.json"
    path.write_text(result.to_json_string())
    lint = CliRunner().invoke(app, ["lint", "--strict", str(path)])
    assert lint.exit_code == 0, lint.output


def test_zero_argument_intent(artifact: dict[str, Any]) -> None:
    artifact["abi"] = [{"type": "function", "name": "claim", "inputs": []}]
    artifact["userdoc"]["methods"] = {"claim()": {"notice": "Claim rewards"}}
    format = generate(artifact).display.formats["claim()"]
    assert format.intent == "Claim rewards"
    assert format.fields == []


def test_cli_v2_and_lint(artifact: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # v2 lint fetches reference ABIs; supply the fixture for a deterministic integration test.
    abis = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact))
    result = CliRunner().invoke(
        app,
        [
            "natspec",
            "--chain-id",
            "1",
            "--address",
            ADDRESS,
            "--natspec",
            str(path),
            "--owner",
            "Example",
            "--url",
            "https://example.com",
        ],
    )
    assert result.exit_code == 0, result.output
    descriptor = InputERC7730Descriptor.model_validate_json(result.stdout)
    assert descriptor.display.formats["transfer(address to,uint256 amount)"].interpolatedIntent is not None
    assert descriptor.metadata.info is not None
    assert descriptor.metadata.info.url == "https://example.com"
    output = tmp_path / "calldata-template.json"
    output.write_text(result.stdout)
    lint = CliRunner().invoke(app, ["lint", "--strict", str(output)])
    assert lint.exit_code == 0, lint.output


@pytest.mark.parametrize("notice", [None, "Send `amount * 2`", "Send `amount`"])
def test_template_without_static_intent_requires_tag(artifact: dict[str, Any], notice: str | None) -> None:
    artifact["devdoc"]["methods"][SIGNATURE].pop("custom:clearsig-intent")
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = "Send {amount}"
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = notice
    with pytest.raises(ValueError, match="Add @custom:clearsig-intent"):
        generate(artifact)


def test_plain_notice_supplies_static_intent(artifact: dict[str, Any]) -> None:
    artifact["devdoc"]["methods"][SIGNATURE].pop("custom:clearsig-intent")
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send tokens"
    format = generate(artifact).display.formats["transfer(address to,uint256 amount)"]
    assert format.intent == "Send tokens"
    assert format.interpolatedIntent is None
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = "Send {amount}"
    format = generate(artifact).display.formats["transfer(address to,uint256 amount)"]
    assert format.intent == "Send tokens"
    assert format.interpolatedIntent == "Send {amount}"


def test_param_template_requires_label_not_intent(artifact: dict[str, Any]) -> None:
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send tokens"
    artifact["devdoc"]["methods"][SIGNATURE]["params"]["amount"] = "Amount: `amount / 10**18`"
    with pytest.raises(ValueError, match="@custom:clearsig-label amount="):
        generate(artifact)
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-label"] = "amount=Amount"
    format = generate(artifact).display.formats["transfer(address to,uint256 amount)"]
    assert format.fields[0].label == "Amount"
    assert format.interpolatedIntent is None


def test_cli_template_lint_errors(artifact: dict[str, Any], tmp_path: Path) -> None:
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send `amount * 2`"
    artifact["devdoc"]["methods"][SIGNATURE].pop("custom:clearsig-intent")
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(artifact))
    result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(path)])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "@custom:clearsig-interpolated-intent" in result.stderr
    assert "@custom:clearsig-intent" in result.stderr


@pytest.mark.parametrize("intent", [None, "   ", "Send", {"en": "Send"}, {"en": " "}])
def test_descriptor_lint_requires_static_intent(
    artifact: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, intent: Any
) -> None:
    abis = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    descriptor = generate(artifact)
    descriptor.display.formats["transfer(address to,uint256 amount)"] = descriptor.display.formats[
        "transfer(address to,uint256 amount)"
    ].model_copy(update={"intent": intent})
    path = tmp_path / "calldata-template.json"
    path.write_text(descriptor.to_json_string())
    result = CliRunner().invoke(app, ["lint", "--strict", str(path)])
    valid = intent in ("Send", {"en": "Send"})
    assert result.exit_code == (0 if valid else 1), result.output
    if not valid:
        assert "Invalid V2 JSON schema" in result.output and "intent" in result.output


@pytest.mark.parametrize(
    "reference", ["@.value", "amounts.[]", "amounts.[0]", "amounts.[0:2]", "$.metadata.constants.symbol"]
)
def test_explicit_template_uses_descriptor_path_vocabulary(artifact: dict[str, Any], reference: str) -> None:
    # Explicit tags preserve descriptor syntax; formatter/schema checks happen in lint.
    text = "Send {" + reference + "} with `literal backticks` and {{braces}}"
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = text
    result = generate(artifact)
    assert result.display.formats["transfer(address to,uint256 amount)"].interpolatedIntent == text


def test_explicit_missing_reference_is_lint_error(artifact: dict[str, Any], tmp_path: Path) -> None:
    artifact["devdoc"]["methods"][SIGNATURE]["custom:clearsig-interpolated-intent"] = "Send {missing}"
    path = tmp_path / "calldata-test.json"
    path.write_text(generate(artifact).to_json_string())
    result = CliRunner().invoke(app, ["lint", "--strict", str(path), "--skip-abi-validation"])
    assert result.exit_code == 1
    assert "Invalid interpolated intent" in result.output


@pytest.mark.parametrize(
    "reference", ["@.value", "amounts.[]", "amounts.[0]", "amounts.[0:2]", "$.metadata.constants.symbol"]
)
@pytest.mark.parametrize("notice", [False, True])
def test_extended_references_pass_descriptor_lint(reference: str, notice: bool) -> None:
    from erc7730.common.output import ListOutputAdder
    from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
    from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter

    abi = [{"type": "function", "name": "send", "inputs": [{"name": "amounts", "type": "uint256[]"}]}]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        userdoc={"methods": {"send(uint256[])": {"notice": "Send `" + reference.replace(".[", "[") + "`"}}}
        if notice
        else None,
        devdoc={
            "methods": {
                "send(uint256[])": {
                    "custom:clearsig-intent": "Send",
                    **({} if notice else {"custom:clearsig-interpolated-intent": "Send {" + reference + "}"}),
                    "custom:clearsig-format": "amounts=raw" + (" @.value=raw" if reference.startswith("@") else ""),
                }
            }
        },
    )
    assert d.display.formats["send(uint256[] amounts)"].interpolatedIntent == "Send {" + reference + "}"
    data = json.loads(d.to_json_string())
    if reference.startswith("$"):
        data["metadata"]["constants"] = {"symbol": "TEST"}
        data["display"]["formats"]["send(uint256[] amounts)"]["fields"].append(
            {"value": reference, "label": "Symbol", "format": "raw"}
        )
    d = InputERC7730Descriptor.model_validate(data, strict=False)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateIntentLinter().lint(d, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize(
    "source,expected",
    [
        ("amounts", "_Amounts.[]"),
        ("amounts[0]", "_Amounts.[0]"),
        ("amounts.[-1]", "_Amounts.[-1]"),
        ("#.amounts[0:2]", "_Amounts.[0:2]"),
        ("amounts[:2]", "_Amounts.[:2]"),
        ("amounts.length", "_Amounts.length"),
    ],
)
def test_notice_array_paths_preserve_abi_names(source: str, expected: str) -> None:
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps([{"type": "function", "name": "f", "inputs": [{"name": "_Amounts", "type": "uint256[]"}]}]),
        userdoc={"methods": {"f(uint256[])": {"notice": "Send `" + source + "`"}}},
        devdoc={"methods": {"f(uint256[])": {"custom:clearsig-intent": "Send"}}},
    )
    assert d.display.formats["f(uint256[] _Amounts)"].interpolatedIntent == "Send {" + expected + "}"


def test_notice_nested_array_selection() -> None:
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(
            [
                {
                    "type": "function",
                    "name": "f",
                    "inputs": [
                        {
                            "name": "orders",
                            "type": "tuple[]",
                            "components": [{"name": "maker", "type": "address"}, {"name": "amount", "type": "uint256"}],
                        }
                    ],
                }
            ]
        ),
        userdoc={"methods": {"f((address,uint256)[])": {"notice": "Send to `orders[0].maker`"}}},
        devdoc={"methods": {"f((address,uint256)[])": {"custom:clearsig-intent": "Send"}}},
    )
    assert next(iter(d.display.formats.values())).interpolatedIntent == "Send to {orders.[0].maker}"


@pytest.mark.parametrize("expression", ["amount[other]", "amount[1+1]", "amount / 10**6", "msg.value", "getAmount()"])
def test_notice_computations_remain_unsupported(artifact: dict[str, Any], expression: str) -> None:
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send `" + expression + "`"
    with pytest.raises(ValueError, match="clearsig-interpolated-intent"):
        generate(artifact)


def test_notice_container_reference_requires_formatter_in_lint(artifact: dict[str, Any], tmp_path: Path) -> None:
    artifact["userdoc"]["methods"][SIGNATURE]["notice"] = "Send `@.value`"
    path = tmp_path / "calldata-container.json"
    path.write_text(generate(artifact).to_json_string())
    result = CliRunner().invoke(app, ["lint", "--strict", str(path), "--skip-abi-validation"])
    assert result.exit_code == 1
    assert "corresponding field formatter" in result.output


@pytest.mark.parametrize("reference,valid", [("amounts[1]", True), ("amounts[2]", False), ("amounts.length", True)])
def test_notice_fixed_array_bounds_and_length_formatter(reference: str, valid: bool) -> None:
    from erc7730.common.output import ListOutputAdder
    from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
    from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter

    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps([{"type": "function", "name": "f", "inputs": [{"name": "amounts", "type": "uint256[2]"}]}]),
        userdoc={"methods": {"f(uint256[2])": {"notice": "Send `" + reference + "`"}}},
        devdoc={"methods": {"f(uint256[2])": {"custom:clearsig-intent": "Send"}}},
    )
    if reference.endswith("length"):
        data = json.loads(d.to_json_string())
        data["display"]["formats"]["f(uint256[2] amounts)"]["fields"].append(
            {"path": "amounts.length", "label": "Count", "format": "raw"}
        )
        d = InputERC7730Descriptor.model_validate(data, strict=False)
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    ValidateIntentLinter().lint(d, resolved, out)
    assert out.has_errors is not valid, out.outputs


def test_notice_eip712_array_reference() -> None:
    schema = [{"primaryType": "Message", "types": {"Message": [{"name": "amounts", "type": "uint256[]"}]}}]
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        eip712_schema=json.dumps(schema),
        userdoc={"methods": {"Message": {"notice": "Send `amounts[0]`"}}},
        devdoc={"methods": {"Message": {"custom:clearsig-intent": "Send"}}},
    )
    assert d.display.formats["Message(uint256[] amounts)"].interpolatedIntent == "Send {amounts.[0]}"
