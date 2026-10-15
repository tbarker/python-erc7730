"""Compiler-document encryption overlays and independently asserted display examples."""

import json
from pathlib import Path
from typing import Any

import pytest

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.examples import ExampleFixture, NatSpecExamples
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

ADDRESS = "0x1111111111111111111111111111111111111111"
HANDLE = "0x" + "12" * 32


def artifact(examples: bool = False) -> dict[str, Any]:
    # Compiled once from data/EncryptedToken.sol with Solidity 0.8.30. No compiler
    # or real decryption keys are needed to run these tests.
    docs = json.loads((Path(__file__).parent / "data/natspec_encryption.json").read_text())
    if not examples:
        del docs["devdoc"]["methods"]["transferEncrypted(bytes32)"]["custom:clearsig-example"]
    return docs


def test_encryption_precedes_format_and_survives_resolution() -> None:
    d = generate_natspec_descriptor(1, ADDRESS, natspec=artifact())
    field = next(iter(d.display.formats.values())).model_dump(mode="json")["fields"][0]
    assert field["format"] == "tokenAmount"
    assert field["encryption"] == {"scheme": "fhevm", "plaintextType": "uint64", "fallbackLabel": "[Encrypted amount]"}
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    assert (
        next(iter(resolved.display.formats.values())).model_dump(mode="json")["fields"][0]["encryption"]
        == field["encryption"]
    )


@pytest.mark.parametrize("bad", ["uint7", "uint", "not a type"])
def test_invalid_plaintext_type_warns(bad: str) -> None:
    docs = artifact()
    docs["devdoc"]["methods"]["transferEncrypted(bytes32)"]["custom:clearsig-plaintext-type"] = f"amount={bad}"
    warnings: list[str] = []
    d = generate_natspec_descriptor(1, ADDRESS, natspec=docs, warnings=warnings)
    field = next(iter(d.display.formats.values())).model_dump(mode="json")["fields"][0]
    assert field["encryption"] is None
    assert field["format"] == "raw"
    assert any("ignoring encryption" in warning for warning in warnings)


def test_project_contract_method_precedence() -> None:
    docs = artifact()
    method = docs["devdoc"]["methods"]["transferEncrypted(bytes32)"]
    del method["custom:clearsig-encryption-scheme"]
    docs["devdoc"]["custom:clearsig-encryption-scheme"] = "amount=fhevm"
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        natspec=docs,
        project_defaults={
            "custom:clearsig-encryption-scheme": "amount=project-scheme",
            "custom:clearsig-plaintext-type": "amount=string",
        },
    )
    field = next(iter(d.display.formats.values())).model_dump(mode="json")["fields"][0]
    assert field["encryption"]["scheme"] == "fhevm"
    assert field["encryption"]["plaintextType"] == "uint64"
    assert field["format"] == "tokenAmount"


def test_renderer_assertions_for_decrypted_values_and_incorrect_fallback() -> None:
    docs = artifact(True)
    method = docs["devdoc"]["methods"]["transferEncrypted(bytes32)"]
    method["custom:clearsig-example"] = (
        f'params=({HANDLE}) intent="Send encrypted tokens" fields={{"Amount":"1.5 USDC"}}'
    )

    # This provider models a renderer's decrypted result, not cryptographic decryption.
    def decrypted(d: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        return {
            "cases": [
                {
                    "description": case.description,
                    "status": "pass",
                    "rendered": {
                        "intent": "Send encrypted tokens",
                        "fields": [{"label": "Amount", "value": "1.5 USDC"}],
                    },
                }
                for case in fixture.tests
            ]
        }

    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        natspec=docs,
        example_renderer=decrypted,
        project_defaults={"examples": {"encryptionMode": "external"}},
    )
    NatSpecExamples(natspec=docs, renderer=decrypted, config={"encryptionMode": "external"}).run(d)
    method["custom:clearsig-example"] = method["custom:clearsig-example"].replace("1.5 USDC", "[Encrypted amount]")
    with pytest.raises(ValueError, match="expected field"):
        NatSpecExamples(natspec=docs, renderer=decrypted, config={"encryptionMode": "external"}).run(d)


def test_nested_encrypted_array_members() -> None:
    docs = artifact()
    docs["abi"][0]["inputs"] = [
        {"name": "orders", "type": "tuple[]", "components": [{"name": "amount", "type": "bytes32"}]}
    ]
    method = docs["devdoc"]["methods"].pop("transferEncrypted(bytes32)")
    docs["devdoc"]["methods"]["transferEncrypted((bytes32)[])"] = {
        key: value.replace("amount=", "orders.amount=") for key, value in method.items()
    }
    d = generate_natspec_descriptor(1, ADDRESS, natspec=docs)
    field = next(iter(d.display.formats.values())).model_dump(mode="json")["fields"][0]["fields"][0]
    assert field["encryption"]["plaintextType"] == "uint64"
    assert field["format"] == "tokenAmount"


def test_missing_scheme_warns_without_installing_partial_annotation() -> None:
    docs = artifact()
    del docs["devdoc"]["methods"]["transferEncrypted(bytes32)"]["custom:clearsig-encryption-scheme"]
    warnings: list[str] = []
    d = generate_natspec_descriptor(1, ADDRESS, natspec=docs, warnings=warnings)
    assert next(iter(d.display.formats.values())).model_dump(mode="json")["fields"][0]["encryption"] is None
    assert any("encryption requires encryptionScheme" in warning for warning in warnings)


def test_example_cannot_assert_missing_or_duplicate_labels() -> None:
    docs = artifact(True)

    def missing(d: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        return {
            "cases": [
                {
                    "description": case.description,
                    "status": "pass",
                    "rendered": {"intent": "Send encrypted tokens", "fields": []},
                }
                for case in fixture.tests
            ]
        }

    with pytest.raises(ValueError, match="expected field"):
        generate_natspec_descriptor(1, ADDRESS, natspec=docs, example_renderer=missing)
    method = docs["devdoc"]["methods"]["transferEncrypted(bytes32)"]
    method["custom:clearsig-example"] = (
        f'params=({HANDLE}) intent="Send encrypted tokens" fields={{"Amount":"x","Amount":"y"}}'
    )
    with pytest.raises(ValueError, match="Duplicate example field label"):
        generate_natspec_descriptor(1, ADDRESS, natspec=docs, example_renderer=missing)
