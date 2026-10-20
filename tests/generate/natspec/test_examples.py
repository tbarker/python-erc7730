"""Compiler JSON example annotations execute through generation and lint APIs.

Source fixture declarations (CI consumes JSON, never compiles Solidity):
    /// @notice Send `amount` to `to`
    /// @custom:clearsig-intent Send
    /// @custom:clearsig-example params=(Alice,1500000) intent="Send 1.5 USDC to Alice"
    function transfer(address to, uint256 amount) external;
"""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import rlp
from eth_abi.abi import decode
from eth_utils.abi import function_signature_to_4byte_selector
from typer.testing import CliRunner

from erc7730.common.output import ConsoleOutputAdder
from erc7730.generate.natspec.examples import (
    CommandExampleRunner,
    ExampleFixture,
    NatSpecExamples,
    run_natspec_examples,
)
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint import lint_all
from erc7730.main import app
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

DATA = Path(__file__).parent / "data"
ADDRESS = "0x2222222222222222222222222222222222222222"
ALICE = "0x1111111111111111111111111111111111111111"
TRANSFER = "transfer(address,uint256)"
APPROVE = "approve(address,uint256)"
CONFIG = {
    "automatic": False,  # Fixed-output stubs exercise authored examples only.
    "aliases": {"Alice": ALICE},
    "dataProvider": {
        "tokens": {ADDRESS: {"symbol": "USDC", "decimals": 6, "name": "USD Coin"}},
        "addressNames": {ALICE: "Alice"},
    },
}


@pytest.fixture
def artifact() -> dict[str, Any]:
    data = json.loads((DATA / "natspec_artifact.json").read_text())
    data["userdoc"]["methods"][TRANSFER]["notice"] = "Send `amount` to `to`"
    data["devdoc"]["methods"][TRANSFER]["custom:clearsig-example"] = (
        'params=(Alice,1500000) intent="Send 1.5 USDC to Alice"'
    )
    data["devdoc"]["methods"][APPROVE]["custom:clearsig-example"] = (
        'params=(amount=1500000,spender=Alice) intent="Approve"'
    )
    return data


def renderer(descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
    """Deterministic runner protocol stub."""
    cases = []
    for case in fixture.tests:
        transfer = case.description.startswith("transfer(")
        rendered: dict[str, Any] = {
            "intent": "Send" if transfer else "Approve",
            "owner": descriptor.metadata.owner,
            "fields": [{"label": "Recipient" if transfer else "Spender", "value": "Alice"}],
        }
        if transfer:
            rendered["interpolatedIntent"] = "Send 1.5 USDC to Alice"
            rendered["fields"].append({"label": "Amount to send", "value": "1.5 USDC"})
        cases.append({"description": case.description, "status": "pass", "rendered": rendered})
    return {"cases": cases}


def generate(artifact: dict[str, Any], **kwargs: Any) -> InputERC7730Descriptor:
    return generate_natspec_descriptor(
        1, ADDRESS, natspec=artifact, project_defaults={"examples": CONFIG}, example_renderer=renderer, **kwargs
    )


def test_generation_runs_examples_and_library_can_rerun(artifact: dict[str, Any]) -> None:
    descriptor = generate(artifact)
    report = run_natspec_examples(descriptor, natspec=artifact, config=CONFIG, renderer=renderer)
    assert len(report.tests) == 2
    assert report.tests[0].expected.interpolated_intent == "Send 1.5 USDC to Alice"
    # Check the encoded values against an independent ABI decoder, including order
    # reversal in the named example. The fixed arguments end the unsigned envelope
    # immediately before its empty access-list RLP marker (c0).
    for case, signature in zip(report.tests, (TRANSFER, APPROVE), strict=True):
        assert case.raw_tx is not None
        raw = bytes.fromhex(case.raw_tx[2:])
        start = raw.index(function_signature_to_4byte_selector(signature))
        assert decode(["address", "uint256"], raw[start + 4 : -1]) == (ALICE, 1500000)
    assert "clearsig-example" not in descriptor.to_json_string()


@pytest.mark.parametrize("entrypoint", ["generation", "library", "lint"])
def test_wrong_sentence_fails_every_entrypoint(artifact: dict[str, Any], entrypoint: str, tmp_path: Path) -> None:
    descriptor = generate(artifact)
    artifact["devdoc"]["methods"][TRANSFER]["custom:clearsig-example"] = 'params=(Alice,1500000) intent="Wrong"'
    if entrypoint == "lint":
        path = tmp_path / "calldata-token.json"
        path.write_text(descriptor.to_json_string())
        out = ConsoleOutputAdder()
        assert lint_all([path], out, examples=NatSpecExamples(natspec=artifact, config=CONFIG, renderer=renderer)) == 1
        assert out.has_errors
    else:
        with pytest.raises(ValueError, match="expected intent 'Wrong'"):
            if entrypoint == "generation":
                generate(artifact)
            else:
                run_natspec_examples(descriptor, natspec=artifact, config=CONFIG, renderer=renderer)


@pytest.mark.parametrize(
    "tag,match",
    [
        ('params=(Alice) intent="Send"', "ABI requires"),
        ('params=(Bob,1500000) intent="Send"', "Unknown address alias"),
        ('params=(to=Alice,to=Alice) intent="Send"', "without duplicates"),
        ('params=(to=Alice,1500000) intent="Send"', "Unsupported example value"),
        ('params=(Alice,-1) intent="Send"', "Invalid @custom"),
        ('params=(Alice,2**18) intent="Send"', "Invalid @custom"),
        ('params=(Alice,1500000) intent=""', "must not be empty"),
    ],
)
def test_invalid_example(artifact: dict[str, Any], tag: str, match: str) -> None:
    artifact["devdoc"]["methods"][TRANSFER]["custom:clearsig-example"] = tag
    with pytest.raises(ValueError, match=match):
        generate(artifact)


def test_missing_coverage_and_repeated_tags(artifact: dict[str, Any]) -> None:
    method = artifact["devdoc"]["methods"][TRANSFER]
    method["custom:clearsig-example"] *= 2
    descriptor = generate(artifact)
    report = NatSpecExamples(natspec=artifact, config=CONFIG, renderer=renderer).run(descriptor)
    assert len(report.tests) == 3
    del artifact["devdoc"]["methods"][APPROVE]["custom:clearsig-example"]
    descriptor = generate(artifact)
    partial = run_natspec_examples(descriptor, natspec=artifact, config=CONFIG, renderer=renderer, require_all=False)
    assert len(partial.tests) == 2
    with pytest.raises(ValueError, match=r"Missing.*approve"):
        NatSpecExamples(natspec=artifact, config=CONFIG, renderer=renderer).run(descriptor)


def test_array_tuple_bytes_bool_and_nested_custom() -> None:
    inputs = [
        {
            "name": "items",
            "type": "tuple[]",
            "components": [
                {"name": "who", "type": "address"},
                {"name": "amounts", "type": "uint256[]"},
                {"name": "enabled", "type": "bool"},
                {"name": "data", "type": "bytes"},
            ],
        }
    ]
    signature = "submit((address,uint256[],bool,bytes)[])"
    data: dict[str, Any] = {
        "abi": [{"type": "function", "name": "submit", "inputs": inputs}],
        "devdoc": {
            "methods": {
                signature: {
                    "custom:clearsig-intent": "Submit",
                    "custom": {"clearsig-example": 'params=([(Alice,[1,0xff],true,0x1234)]) intent="Submit"'},
                },
            }
        },
    }
    seen = []

    def nested_renderer(descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        seen.append(fixture)
        return {
            "cases": [
                {
                    "description": fixture.tests[0].description,
                    "status": "pass",
                    "rendered": {"intent": "Submit", "fields": []},
                }
            ]
        }

    generate_natspec_descriptor(
        1, ADDRESS, natspec=data, project_defaults={"examples": CONFIG}, example_renderer=nested_renderer
    )
    raw_tx = seen[0].tests[0].raw_tx
    assert raw_tx is not None
    raw = bytes.fromhex(raw_tx[2:])
    assert raw[0] == 2
    chain_id, nonce, priority_fee, max_fee, gas, to, value, calldata, access_list = rlp.decode(raw[1:])
    assert (chain_id, nonce, priority_fee, max_fee, gas, to, value, access_list) == (
        b"\x01",
        b"",
        b"",
        b"",
        (1_000_000).to_bytes(3, "big"),
        bytes.fromhex(ADDRESS[2:]),
        b"",
        [],
    )
    assert calldata[:4] == function_signature_to_4byte_selector(signature)
    assert decode(["(address,uint256[],bool,bytes)[]"], calldata[4:]) == (((ALICE, (1, 255), True, b"\x12\x34"),),)


@pytest.mark.parametrize("failure", ["missing", "duplicate", "error", "unstable", "warning"])
def test_runner_failures_are_not_silenced(artifact: dict[str, Any], failure: str) -> None:
    descriptor = generate(artifact)
    count = 0

    def broken(descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        nonlocal count
        count += 1
        result = renderer(descriptor, fixture)
        match failure:
            case "missing":
                result["cases"].pop()
            case "duplicate":
                result["cases"][1] = copy.deepcopy(result["cases"][0])
            case "error":
                result["cases"][0]["status"] = "error"
            case "unstable" if count == 2:
                result["cases"][0]["rendered"]["fields"] = []
            case "warning" if count == 2:
                result["cases"][0]["status"] = "fail"
        return result

    with pytest.raises(ValueError):
        run_natspec_examples(descriptor, natspec=artifact, config=CONFIG, renderer=broken)


def test_missing_runner_is_actionable(artifact: dict[str, Any]) -> None:
    descriptor = generate(artifact)
    with pytest.raises(ValueError, match="Cannot render NatSpec examples"):
        run_natspec_examples(
            descriptor,
            natspec=artifact,
            config=CONFIG,
            renderer=CommandExampleRunner(["/nonexistent/erc7730-test-runner"]),
        )


def test_cli_generate_and_lint_run_examples(
    artifact: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic import TypeAdapter

    from erc7730.common import client
    from erc7730.model.abi import ABI

    calls: list[ExampleFixture] = []

    def checked_renderer(self: CommandExampleRunner, d: InputERC7730Descriptor, f: ExampleFixture) -> dict[str, Any]:
        calls.append(f)
        return renderer(d, f)

    monkeypatch.setattr(CommandExampleRunner, "__call__", checked_renderer)
    monkeypatch.setattr(
        client, "get_contract_abis", lambda *args: TypeAdapter(list[ABI]).validate_python(artifact["abi"])
    )
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "artifact.json"
    source.write_text(json.dumps(artifact))
    config = tmp_path / "erc7730.toml"
    config.write_text(
        f'[generate]\nnatspec="artifact.json"\n[generate.examples]\nautomatic=false\n[generate.examples.aliases]\nAlice="{ALICE}"\n'
    )
    cli = CliRunner()
    result = cli.invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS])
    assert result.exit_code == 0, result.output
    path = tmp_path / "calldata-token.json"
    path.write_text(result.stdout)
    result = cli.invoke(app, ["lint", str(path)])
    assert result.exit_code == 0, result.output
    assert calls == []  # Config and inline tags alone do not launch a renderer.
    artifact["devdoc"]["methods"][TRANSFER]["custom:clearsig-example"] = 'params=(Alice,1500000) intent="Wrong"'
    source.write_text(json.dumps(artifact))
    for args in [["lint", str(path)], ["natspec", "--chain-id", "1", "--address", ADDRESS]]:
        result = cli.invoke(app, [*args, "--natspec", str(source), "--example-runner", "test-renderer"])
        assert result.exit_code == 1, result.output
        assert "Wrong" in result.output
    assert not list(tmp_path.rglob("*.tests.json"))


def test_lint_does_not_silently_skip_configured_examples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "erc7730.toml").write_text("[generate.examples]\n")
    result = CliRunner().invoke(app, ["lint", "calldata-token.json", "--v2"])
    assert result.exit_code == 1
    assert "not a file or directory" in result.output


def test_three_function_compiler_fixture() -> None:
    artifact = json.loads((DATA / "natspec_examples_artifact.json").read_text())

    def three_function_renderer(descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        result = renderer(descriptor, fixture)
        result["cases"][0]["rendered"] = {
            "intent": "Settle order",
            "owner": "Test Token",
            "fields": [
                {"label": "Maker", "value": "Alice"},
                {"label": "Amount", "value": "1.5 USDC"},
                {"label": "Deadline", "value": "2023-11-14 22:13:20Z"},
            ],
        }
        return result

    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        natspec=artifact,
        project_defaults={"examples": CONFIG},
        example_renderer=three_function_renderer,
    )
    report = NatSpecExamples(natspec=artifact, config=CONFIG, renderer=three_function_renderer).run(descriptor)
    assert len(report.tests) == 3
    raw_tx = report.tests[0].raw_tx
    assert raw_tx is not None
    raw = bytes.fromhex(raw_tx[2:])
    selector = function_signature_to_4byte_selector("settle((address,uint256,uint256),uint256)")
    start = raw.index(selector)
    assert decode(["(address,uint256,uint256)", "uint256"], raw[start + 4 : -1]) == ((ALICE, 1500000, 1700000000), 42)
    assert report.tests[1].expected.interpolated_intent == "Send 1.5 USDC to Alice"
    assert report.tests[2].expected.intent == "Approve"


@pytest.mark.parametrize("missing_all", [False, True])
def test_missing_examples_generate_but_fail_lint(
    artifact: dict[str, Any],
    missing_all: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del artifact["devdoc"]["methods"][APPROVE]["custom:clearsig-example"]
    if missing_all:
        del artifact["devdoc"]["methods"][TRANSFER]["custom:clearsig-example"]

    calls: list[int] = []

    def checked_renderer(descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        calls.append(len(fixture.tests))
        return renderer(descriptor, fixture)

    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        natspec=artifact,
        project_defaults={"examples": CONFIG},
        example_renderer=checked_renderer,
    )
    assert calls == ([] if missing_all else [1, 1])
    path = tmp_path / "calldata-token.json"
    path.write_text(descriptor.to_json_string())
    out = ConsoleOutputAdder()
    lint_all([path], out, examples=NatSpecExamples(natspec=artifact, config=CONFIG, renderer=checked_renderer))
    assert out.has_errors

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(CommandExampleRunner, "__call__", lambda self, d, f: checked_renderer(d, f))
    (tmp_path / "artifact.json").write_text(json.dumps(artifact))
    (tmp_path / "erc7730.toml").write_text(
        f'[generate]\nnatspec="artifact.json"\n[generate.examples]\nautomatic=false\n[generate.examples.aliases]\nAlice="{ALICE}"\n'
    )
    cli = CliRunner()
    generated = cli.invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS])
    assert generated.exit_code == 0, generated.output
    linted = cli.invoke(app, ["lint", str(path), "--config", "erc7730.toml", "--example-runner", "test-renderer"])
    assert linted.exit_code == 1
    assert "Missing @custom:clearsig-example" in linted.output


def test_generation_never_launches_renderer_implicitly(
    artifact: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected(*args: Any, **kwargs: Any) -> None:
        pytest.fail("Renderer launched without an explicit request")

    monkeypatch.setattr(CommandExampleRunner, "__call__", unexpected)
    assert generate_natspec_descriptor(1, ADDRESS, natspec=artifact, project_defaults={"examples": CONFIG})


@pytest.mark.parametrize("threshold", [1000, "0x3e8"])
@pytest.mark.parametrize("message", [None, "All"])
def test_token_threshold_is_inclusive(threshold: int | str, message: str | None) -> None:
    from erc7730.generate.natspec.examples.models import ExampleConfig
    from erc7730.generate.natspec.examples.sanity import _expected
    from erc7730.model.paths.path_parser import to_path
    from erc7730.model.resolved.v2.display import ResolvedFieldDescription

    field = ResolvedFieldDescription.model_validate(
        {
            "path": "#.amount",
            "label": "Amount",
            "format": "tokenAmount",
            "params": {
                "token": {"type": "path", "path": to_path("#.token")},
                "threshold": threshold,
                "message": message,
            },
        },
        strict=False,
    )
    expected = message or "Unlimited"
    assert _expected(field, [999, 1000, 1001], {"token": ADDRESS}, {}, ExampleConfig.model_validate(CONFIG)) == [
        "0.000999 USDC",
        f"{expected} USDC",
        f"{expected} USDC",
    ]
