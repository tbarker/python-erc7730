"""Compiler-preserved format pair order controls display, not parameter decoding."""

import json
from pathlib import Path

from typer.testing import CliRunner

from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.main import app

DATA = Path(__file__).parent / "data"
ADDRESS = "0x1111111111111111111111111111111111111111"


def test_compiled_order_library_and_cli() -> None:
    source = DATA / "ordering.artifact.json"
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=source.read_text())
    format = descriptor.display.formats["send(address to,uint256 amount,uint256 extra)"]
    assert [str(field.path) for field in format.fields] == ["#.amount", "#.to", "#.extra"]
    result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(source)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(descriptor.to_json_string())


def test_scope_precedence_and_invalid_pairs() -> None:
    docs = json.loads((DATA / "ordering.artifact.json").read_text())
    docs["devdoc"]["custom:clearsig-format"] = "extra=raw amount=raw"
    project = {"custom:clearsig-format": "to=raw extra=raw"}
    for method, expected in [
        ("to=unknown missing=raw extra=raw extra=RAW", ["extra", "to", "amount"]),
        ("", ["extra", "amount", "to"]),
    ]:
        docs["devdoc"]["methods"]["send(address,uint256,uint256)"]["custom:clearsig-format"] = method
        descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=docs, project_defaults=project)
        fields = next(iter(descriptor.display.formats.values())).fields
        assert [str(field.path).removeprefix("#.") for field in fields] == expected


def test_scalar_struct_fields_keep_order_when_compacted() -> None:
    abi = [
        {
            "type": "function",
            "name": "send",
            "inputs": [
                {"name": "other", "type": "uint256"},
                {
                    "name": "order",
                    "type": "tuple",
                    "components": [
                        {"name": "maker", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                    ],
                },
            ],
            "outputs": [],
        }
    ]
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=json.dumps(abi),
        devdoc={
            "methods": {
                "send(uint256,(address,uint256))": {
                    "custom:clearsig-format": "order.amount=raw order.maker=addressName",
                }
            }
        },
    )
    fields = next(iter(descriptor.display.formats.values())).model_dump(mode="json")["fields"]
    assert [field["path"] for field in fields] == ["#.order.amount", "#.order.maker", "#.other"]
