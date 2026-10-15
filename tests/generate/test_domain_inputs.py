"""Generation-specific domain regressions through the CLI and library."""

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.main import app
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

ADDRESS = "0x1111111111111111111111111111111111111111"


def test_eip712_generation_domain_library_and_cli(tmp_path: Path) -> None:
    schema = json.dumps([{"primaryType": "Message", "types": {"Message": [{"name": "value", "type": "uint256"}]}}])
    domain = {"name": "Example", "version": "2"}
    d = generate_natspec_descriptor(1, ADDRESS, eip712_schema=schema, eip712_domain=domain)
    assert d.model_dump(mode="json")["context"]["eip712"]["domain"]["name"] == "Example"
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(schema)
    domain_path = tmp_path / "domain.json"
    domain_path.write_text(json.dumps(domain))
    result = CliRunner().invoke(
        app,
        [
            "natspec",
            "--chain-id",
            "1",
            "--address",
            ADDRESS,
            "--schema",
            str(schema_path),
            "--eip712-domain",
            str(domain_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert InputERC7730Descriptor.model_validate_json(result.stdout) == d


def test_domain_requires_schema_without_fetching_abi(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_fetch(*args: Any) -> Any:
        pytest.fail("Invalid domain options should not trigger ABI fetching")

    monkeypatch.setattr("erc7730.generate.natspec.generate.get_contract_abis", unexpected_fetch)
    with pytest.raises(ValueError, match="eip712_domain requires"):
        generate_natspec_descriptor(1, ADDRESS, eip712_domain={"name": "Example"})
