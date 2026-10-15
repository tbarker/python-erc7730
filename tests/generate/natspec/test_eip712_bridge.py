"""Production bridge tests; artifacts are real compiler output."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from erc7730.generate.natspec import parse_natspec
from erc7730.generate.natspec.eip712_bridge import bridge_methods, infer_schemas
from erc7730.generate.natspec.examples import ExampleConfig, run_natspec_examples
from erc7730.generate.natspec.examples.typed_data import message_schema, signing_domain, typed_input
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.main import app
from erc7730.model.input.v2.context import InputContractContext, InputEIP712Context

ADDRESS = "0x2222222222222222222222222222222222222222"
DATA = Path(__file__).parent / "data"


def artifact() -> dict[str, Any]:
    value = json.loads((DATA / "typed-messages.artifact.json").read_text())
    for method in value["devdoc"]["methods"].values():
        method.pop("custom:clearsig-example", None)
    return value


def test_compiler_source_and_generation() -> None:
    source = json.loads((DATA / "typed-messages.artifact.json").read_text())
    assert source["sourceSha256"] == hashlib.sha256((DATA / "TypedMessages.sol").read_bytes()).hexdigest()
    docs = artifact()
    before = deepcopy(docs)
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=docs)
    assert docs == before
    assert isinstance(descriptor.context, InputEIP712Context)
    assert set(descriptor.display.formats) == {
        "Permit(uint256 quantity)",
        "Batch(Order[] orders)Order(address maker,uint256 quantity)",
        "Signed(uint256 quantity)",
    }
    assert descriptor.display.formats["Permit(uint256 quantity)"].interpolatedIntent == "Permit {quantity}"
    assert message_schema("Batch(Order[] orders)Order(address maker,uint256 quantity)")[2][0]["type"] == "tuple[]"


@pytest.mark.parametrize("split", [False, True])
def test_cli_library_parity(split: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    docs = artifact()
    expected = generate_natspec_descriptor(1, ADDRESS, natspec=docs, eip712_domain={"name": "Example"})
    args = ["natspec", "--chain-id", "1", "--address", ADDRESS]
    if split:
        for key in ("abi", "userdoc", "devdoc"):
            path = tmp_path / f"{key}.json"
            path.write_text(json.dumps(docs[key]))
            args.extend([f"--{key}", str(path)])
    else:
        path = tmp_path / "artifact.json"
        path.write_text(json.dumps(docs))
        args.extend(["--natspec", str(path)])
    domain = tmp_path / "domain.json"
    domain.write_text('{"name":"Example"}')
    result = CliRunner().invoke(app, [*args, "--eip712-domain", str(domain)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(expected.to_json_string())


def test_explicit_schema_conflict_and_unchanged_calldata() -> None:
    docs = artifact()
    with pytest.raises(ValueError, match="explicit EIP-712 schema"):
        generate_natspec_descriptor(1, ADDRESS, natspec=docs, eip712_schema="[]")
    for method in docs["devdoc"]["methods"].values():
        method.pop("custom:clearsig-typed-data", None)
    # Remove message-only signer display to focus on unannotated selection.
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=docs)
    assert isinstance(descriptor.context, InputContractContext)
    assert "unrelated(address recipient)" in descriptor.display.formats


@pytest.mark.parametrize("value", ["", "Two Names", 1, None, "EIP712Domain", "uint256"])
def test_invalid_annotation(value: Any) -> None:
    with pytest.raises(ValueError):
        bridge_methods(parse_natspec(devdoc={"methods": {"f()": {"custom:clearsig-typed-data": value}}}))


def test_misplaced_duplicate_and_conflicting_annotations() -> None:
    roots: list[dict[str, Any]] = [
        {"custom:clearsig-typed-data": "Message"},
        {"custom": {"clearsig-typed-data": "Message"}},
    ]
    for root in roots:
        with pytest.raises(ValueError, match="method"):
            bridge_methods(parse_natspec(devdoc=root))
    with pytest.raises(ValueError, match="Duplicate"):
        bridge_methods(
            parse_natspec(devdoc={"methods": {k: {"custom:clearsig-typed-data": "Message"} for k in ("f()", "g()")}})
        )
    with pytest.raises(ValueError, match="Conflicting"):
        bridge_methods(
            parse_natspec(
                userdoc={"methods": {"f()": {"custom:clearsig-typed-data": "A"}}},
                devdoc={"methods": {"f()": {"custom:clearsig-typed-data": "B"}}},
            )
        )


def test_missing_abi_and_method() -> None:
    with pytest.raises(ValueError, match="compiler ABI"):
        infer_schemas(None, {"f()": "Message"})
    with pytest.raises(ValueError, match="missing"):
        infer_schemas("[]", {"f()": "Message"})


@pytest.mark.parametrize(
    "part",
    [
        {"name": "", "type": "uint256"},
        {"name": "n", "type": "function"},
        {"name": "n", "type": "tuple", "components": []},
        {"name": "n", "type": "tuple", "internalType": "struct Message", "components": []},
        {"name": "n", "type": "tuple", "internalType": "struct EIP712Domain", "components": []},
    ],
)
def test_invalid_structures(part: dict[str, Any]) -> None:
    from eth_utils.abi import collapse_if_tuple

    function: dict[str, Any] = {"type": "function", "name": "f", "inputs": [part]}
    with pytest.raises(ValueError):
        infer_schemas(json.dumps([function]), {"f(" + collapse_if_tuple(part) + ")": "Message"})


def test_overloads_shared_structs_and_dimensions() -> None:
    parts = [
        {
            "name": "n",
            "type": "tuple[][2]",
            "internalType": "struct C.Item[][2]",
            "components": [{"name": "count", "type": "uint64", "internalType": "Alias"}],
        }
    ]
    functions: list[dict[str, Any]] = [
        {"type": "function", "name": "f", "inputs": parts},
        {"type": "function", "name": "f", "inputs": [{"name": "x", "type": "uint256"}]},
    ]
    schemas = json.loads(infer_schemas(json.dumps(functions), {"f((uint64)[][2])": "Batch", "f(uint256)": "Single"}))
    assert schemas[0]["types"]["Batch"] == [{"name": "n", "type": "Item[][2]"}]
    assert schemas[1]["types"] == {"Single": [{"name": "x", "type": "uint256"}]}
    functions.append({"type": "function", "name": "g", "inputs": parts})
    infer_schemas(json.dumps(functions), {"f((uint64)[][2])": "Batch", "g((uint64)[][2])": "Other"})
    changed = deepcopy(functions)
    changed[2]["inputs"] = deepcopy(changed[2]["inputs"])
    changed[2]["inputs"][0]["components"][0]["name"] = "different"
    with pytest.raises(ValueError, match="Conflicting"):
        infer_schemas(json.dumps(changed), {"f((uint64)[][2])": "Batch", "g((uint64)[][2])": "Other"})


def test_domain_and_message_validation() -> None:
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=artifact(), eip712_domain={"name": "Example"})
    settings = ExampleConfig(sender=ADDRESS)
    domain, _, _ = signing_domain(descriptor, settings)
    assert domain == {"name": "Example", "chainId": 1, "verifyingContract": ADDRESS}
    data = typed_input("Permit(uint256 quantity)", [2**255], descriptor, settings)
    assert data["message"]["quantity"] == str(2**255)
    assert data["account"] == ADDRESS
    with pytest.raises(ValueError, match=r"examples\.sender"):
        signing_domain(descriptor, ExampleConfig())
    with pytest.raises(ValueError, match="constraint name"):
        signing_domain(descriptor, ExampleConfig(domain={"name": "Wrong"}))
    with pytest.raises(ValueError, match="deployment"):
        signing_domain(
            descriptor, ExampleConfig(domain={"name": "Example", "chainId": 2, "verifyingContract": ADDRESS})
        )


def test_authored_examples_never_silently_skip() -> None:
    docs = json.loads((DATA / "typed-messages.artifact.json").read_text())
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=artifact())
    with pytest.raises(ValueError, match=r"examples\.sender"):
        run_natspec_examples(descriptor, natspec=docs)


def test_explicit_domains_and_separator_constraints() -> None:
    from eth_abi.abi import encode
    from eth_utils.crypto import keccak

    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=artifact())
    assert isinstance(descriptor.context, InputEIP712Context)
    # Independent fixed one-member domain hashing, not the production helper.
    separator = (
        "0x"
        + keccak(
            encode(["bytes32", "bytes32"], [keccak(text="EIP712Domain(string name)"), keccak(text="Example")])
        ).hex()
    )
    descriptor = descriptor.model_copy(
        update={
            "context": descriptor.context.model_copy(
                update={
                    "eip712": descriptor.context.eip712.model_copy(
                        update={"deployments": None, "domainSeparator": separator}
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match=r"require examples\.domain"):
        signing_domain(descriptor, ExampleConfig(sender=ADDRESS))
    domain, _, _ = signing_domain(descriptor, ExampleConfig(sender=ADDRESS, domain={"name": "Example"}))
    assert domain == {"name": "Example"}
    with pytest.raises(ValueError, match="domainSeparator"):
        signing_domain(descriptor, ExampleConfig(sender=ADDRESS, domain={"name": "Wrong"}))


def test_custom_domain_types_and_ambiguous_deployments() -> None:
    from erc7730.model.input.v2.context import InputDeployment

    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=artifact(), eip712_domain={"purpose": "Example"})
    assert isinstance(descriptor.context, InputEIP712Context)
    domain = {"purpose": "Example", "chainId": 1, "verifyingContract": ADDRESS}
    with pytest.raises(ValueError, match="domainTypes"):
        signing_domain(descriptor, ExampleConfig(sender=ADDRESS, domain=domain))
    types = [
        {"name": "purpose", "type": "string"},
        {"name": "chainId", "type": "uint256"},
        {"name": "verifyingContract", "type": "address"},
    ]
    settings = ExampleConfig.model_validate({"sender": ADDRESS, "domain": domain, "domainTypes": types})
    assert signing_domain(descriptor, settings)[0] == domain
    descriptor = descriptor.model_copy(
        update={
            "context": descriptor.context.model_copy(
                update={
                    "eip712": descriptor.context.eip712.model_copy(
                        update={
                            "deployments": [
                                InputDeployment(chainId=1, address=ADDRESS),
                                InputDeployment(chainId=2, address=ADDRESS),
                            ]
                        }
                    )
                }
            )
        }
    )
    with pytest.raises(ValueError, match="Ambiguous"):
        signing_domain(descriptor, ExampleConfig(sender=ADDRESS))
    assert signing_domain(descriptor, settings)[0] == domain
    with pytest.raises(ValueError, match="every domain field"):
        signing_domain(
            descriptor, ExampleConfig.model_validate({"sender": ADDRESS, "domain": domain, "domainTypes": types[:1]})
        )


def test_nested_annotation_and_sole_struct_preservation() -> None:
    docs = {"methods": {"f((uint256))": {"custom": {"clearsig-typed-data": "Message"}}}}
    selected = bridge_methods(parse_natspec(devdoc=docs))
    abi = [
        {
            "type": "function",
            "name": "f",
            "inputs": [
                {
                    "name": "order",
                    "type": "tuple",
                    "internalType": "struct C.Order",
                    "components": [{"name": "count", "type": "uint256"}],
                }
            ],
        }
    ]
    schemas = json.loads(infer_schemas(json.dumps(abi), selected))
    assert schemas[0]["types"]["Message"] == [{"name": "order", "type": "Order"}]


def test_fixed_array_and_integer_bounds_in_examples() -> None:
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=artifact())
    settings = ExampleConfig(sender=ADDRESS)
    from eth_abi.exceptions import EncodingError

    with pytest.raises(EncodingError):
        typed_input("Message(uint8[2] quantities)", [[1]], descriptor, settings)
    with pytest.raises(EncodingError):
        typed_input("Message(uint8 quantity)", [256], descriptor, settings)


def test_exact_bytes_and_literal_container_text() -> None:
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        eip712_schema=json.dumps(
            [{"primaryType": "Message", "types": {"Message": [{"name": "data", "type": "bytes32"}]}}]
        ),
        owner="The literal @.from is not a signer reference",
    )
    signing_domain(descriptor, ExampleConfig())
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        typed_input("Message(bytes32 data)", [b"\x01"], descriptor, ExampleConfig())
    with pytest.raises(ValueError, match="exactly 32 bytes"):
        signing_domain(descriptor, ExampleConfig(domain={"chainId": 1, "verifyingContract": ADDRESS, "salt": "0x01"}))
