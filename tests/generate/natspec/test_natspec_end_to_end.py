"""Compiler JSON -> generation -> serialized schema validation -> descriptor lint.

The fixture models compiler output for an exchange with an Order tuple and transfer:

    /// @notice Settle `order.amount / 10**18` tokens for `order.maker` before `order.deadline`.
    /// @param order Order to settle
    /// @param nonce Replay protection
    /// @custom:clearsig-intent Settle order
    /// @custom:clearsig-interpolated-intent Settle {order.amount} for {order.maker} before {order.deadline}.
    /// @custom:clearsig-format order.amount=tokenAmount
    /// @custom:clearsig-token-path order.amount=@.to
    /// @custom:clearsig-date-encoding order.deadline=timestamp
    function settle(Order calldata order, uint256 nonce) external;

The fixture also exercises contract defaults, nested labels, a simple notice template,
and a templated @param with a static label override. CI never compiles Solidity.
"""

import json
import tomllib
from pathlib import Path

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
SETTLE = "settle((address maker,uint256 amount,uint256 deadline) order,uint256 nonce)"


@pytest.mark.parametrize("entrypoint", ["cli-artifact", "cli-split", "library"])
def test_complex_natspec_through_lint(entrypoint: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_bytes = (DATA / "natspec_complex_artifact.json").read_bytes()
    artifact = json.loads(artifact_bytes)
    # Only the external reference-ABI fetch is replaced. Parsing, overlay, model
    # serialization, published schema validation and all descriptor linters run.
    abis = TypeAdapter(list[ABI]).validate_python(artifact["abi"], strict=False)
    monkeypatch.setattr(client, "get_contract_abis", lambda *args: abis)
    monkeypatch.chdir(tmp_path)
    config = '[generate]\n"custom:clearsig-format" = "amount=amount"\n"custom:clearsig-exclude" = "salt"\n'
    (tmp_path / "erc7730.toml").write_text(config)
    runner = CliRunner()

    if entrypoint == "library":
        warnings: list[str] = []
        descriptor = generate_natspec_descriptor(
            1,
            ADDRESS,
            natspec=artifact_bytes,
            owner="Example",
            warnings=warnings,
            project_defaults=tomllib.loads(config)["generate"],
        )
        output = descriptor.to_json_string()
        assert any("intent template generated" in warning for warning in warnings)
    else:
        args = ["natspec", "--chain-id", "1", "--address", ADDRESS, "--owner", "Example"]
        if entrypoint == "cli-artifact":
            # Compiler metadata is itself serialized JSON in some artifacts.
            embedded = {
                "abi": artifact["abi"],
                "metadata": json.dumps(
                    {
                        "output": {
                            "userdoc": artifact["userdoc"],
                            "devdoc": artifact["devdoc"],
                        }
                    }
                ),
            }
            path = tmp_path / "artifact.json"
            path.write_text(json.dumps(embedded))
            args += ["--natspec", str(path)]
        else:
            for key in ("abi", "userdoc", "devdoc"):
                path = tmp_path / f"{key}.json"
                path.write_text(json.dumps(artifact[key]))
                args += [f"--{key}", str(path)]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert "intent template generated" in result.stderr
        output = result.stdout

    # Assert user-visible output rather than merely accepting a successful exit.
    descriptor = InputERC7730Descriptor.model_validate_json(output)
    document = json.loads(output)
    assert descriptor.metadata.owner == "Example"
    assert descriptor.metadata.contractName == "Order Exchange"
    settle = document["display"]["formats"][SETTLE]
    assert settle["intent"] == "Settle order"
    assert settle["interpolatedIntent"] == "Settle {order.amount} for {order.maker} before {order.deadline}."
    amount, maker, deadline, nonce = settle["fields"]
    assert (maker["path"], maker["label"]) == ("#.order.maker", "Maker")
    assert (amount["path"], amount["label"], amount["format"]) == ("#.order.amount", "Amount", "tokenAmount")
    assert amount["params"] == {"tokenPath": "@.to"}
    assert deadline["format"] == "date"
    assert deadline["params"] == {"encoding": "timestamp"}
    assert nonce["path"] == "#.nonce" and nonce["visible"] == "never"
    transfer = document["display"]["formats"]["transfer(address to,uint256 amount)"]
    assert transfer["intent"] == "Send tokens"
    assert transfer["interpolatedIntent"] == "Send {amount} to {to}."
    assert [field["label"] for field in transfer["fields"]] == ["Amount", "Recipient"]
    assert transfer["fields"][0]["format"] == "tokenAmount"

    schema = json.loads((DATA.parents[3] / "specs/erc7730-v2.schema.json").read_text())
    jsonschema.validate(document, schema)
    path = tmp_path / "calldata-complex-natspec.json"
    path.write_text(output)
    lint = runner.invoke(app, ["lint", str(path)])
    assert lint.exit_code == 0, lint.output
    assert "Could not fetch ABI" not in lint.output
