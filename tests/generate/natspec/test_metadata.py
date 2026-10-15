"""Metadata annotations populate typed metadata and resolve formatter references."""

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_string_url import HttpUrl

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.metadata import InputMetadata, InputOwnerInfo
from erc7730.model.resolved.v2.display import ResolvedFieldDescription, ResolvedUnitParameters

ADDRESS = "0x1111111111111111111111111111111111111111"
ABI = json.dumps([{"type": "function", "name": "f", "inputs": [{"name": "fee", "type": "uint256"}]}])


def generate(devdoc: dict[str, Any], **kwargs: Any) -> InputERC7730Descriptor:
    return generate_natspec_descriptor(1, ADDRESS, abi=ABI, devdoc=devdoc, **kwargs)


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("typed", [False, True])
def test_metadata_and_constant_reference(nested: bool, typed: bool) -> None:
    tags = {
        "clearsig-owner": "Protocol DAO",
        "clearsig-url": "https://example.org/",
        "clearsig-constant": 'decimals=2, base="%", enabled=true, absent=null, ratio=1.5, sentinel="0x00",',
    }
    docs: dict[str, Any] = {"custom": tags} if nested else {f"custom:{k}": v for k, v in tags.items()}
    docs |= {
        "author": "Developer",
        "title": "Fee Contract",
        "methods": {
            "f(uint256)": {
                "custom:clearsig-format": "fee=unit",
                "custom:clearsig-base": "fee=$.metadata.constants.base",
                "custom:clearsig-decimals": "fee=$.metadata.constants.decimals",
            }
        },
    }
    if typed:
        docs["methods"]["f(uint256)"]["custom:clearsig-typed-data"] = "Fee"
    d = generate(docs)
    assert d.metadata.owner == "Protocol DAO"
    assert d.metadata.contractName == "Fee Contract"
    assert d.metadata.info is not None
    assert str(d.metadata.info.url) == "https://example.org/"
    assert d.metadata.constants == {
        "decimals": 2,
        "base": "%",
        "enabled": True,
        "absent": None,
        "ratio": 1.5,
        "sentinel": "0x00",
    }
    assert InputERC7730Descriptor.model_validate_json(d.to_json_string()) == d
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    field = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    assert isinstance(field.params, ResolvedUnitParameters)
    assert field.params.decimals == 2
    assert field.params.base == "%"


def test_explicit_metadata_wins_per_key_and_is_not_mutated() -> None:
    initial = InputMetadata(
        owner="Configured owner",
        info=InputOwnerInfo(url=HttpUrl("https://config.example/"), deploymentDate=datetime(2020, 1, 1, tzinfo=UTC)),
        constants={"decimals": 6, "disabled": None},
    )
    before = initial.model_copy(deep=True)
    d = generate(
        {
            "custom:clearsig-owner": "Annotated owner",
            "custom:clearsig-url": "https://annotation.example/",
            "custom:clearsig-constant": 'decimals=2 disabled=true message="Unlimited"',
        },
        metadata=initial,
    )
    assert d.metadata.owner == initial.owner
    assert d.metadata.info == initial.info
    assert d.metadata.constants == {"decimals": 6, "disabled": None, "message": "Unlimited"}
    assert initial == before


def test_owner_url_arguments_win_over_metadata_and_annotations() -> None:
    d = generate(
        {"custom:clearsig-owner": "Annotation", "custom:clearsig-url": "https://annotation.example/"},
        metadata=InputMetadata(owner="Configured", info=InputOwnerInfo(url=HttpUrl("https://config.example/"))),
        owner="Explicit",
        url=HttpUrl("https://explicit.example/"),
    )
    assert d.metadata.owner == "Explicit"
    assert d.metadata.info is not None
    assert str(d.metadata.info.url) == "https://explicit.example/"


def test_userdoc_devdoc_and_flat_key_precedence() -> None:
    d = generate(
        {
            "custom:clearsig-owner": "Dev",
            "custom": {"clearsig-owner": "Nested"},
            "custom:clearsig-url": "https://dev.example/",
            "custom:clearsig-constant": "a=2",
        },
        userdoc={
            "custom:clearsig-owner": "User",
            "custom:clearsig-url": "https://user.example/",
            "custom:clearsig-constant": "a=1 b=false",
        },
    )
    assert d.metadata.owner == "Dev"
    assert d.metadata.info is not None
    assert str(d.metadata.info.url) == "https://dev.example/"
    assert d.metadata.constants == {"a": 2, "b": False}


@pytest.mark.parametrize(
    "tag,value",
    [
        ("owner", " "),
        ("owner", 123),
        ("url", None),
        ("constant", ""),
        ("url", "not-a-url"),
        ("url", "ftp://example.org/"),
        ("constant", "missing-equals"),
        ("constant", "bad-name=1"),
        ("constant", "x=unquoted"),
        ("constant", "x=[]"),
        ("constant", "x={}"),
        ("constant", "x=NaN"),
        ("constant", "x=Infinity"),
        ("constant", "x=1,x=2"),
        ("constant", "x=true,x=1"),
        ("constant", 'x="valid"garbage'),
        ("constant", 'x="unterminated'),
    ],
)
def test_invalid_metadata_fails_generation(tag: str, value: Any) -> None:
    with pytest.raises(ValueError, match="clearsig-"):
        generate({f"custom:clearsig-{tag}": value})


@pytest.mark.parametrize("tag,value", [("owner", "Owner"), ("url", "https://example.org/"), ("constant", "x=1")])
@pytest.mark.parametrize("scope", ["method", "project"])
def test_only_contract_scope_is_allowed(tag: str, value: str, scope: str) -> None:
    tags = {f"custom:clearsig-{tag}": value}
    with pytest.raises(ValueError, match="contract scope"):
        generate(
            {"methods": {"f(uint256)": tags}} if scope == "method" else {},
            project_defaults=tags if scope == "project" else None,
        )


def test_unused_typed_method_still_rejects_metadata_annotation() -> None:
    with pytest.raises(ValueError, match="contract scope"):
        generate(
            {
                "methods": {
                    "f(uint256)": {"custom:clearsig-typed-data": "Fee"},
                    "unused()": {"custom:clearsig-owner": "Wrong scope"},
                }
            }
        )


def test_quoted_labels_and_identical_duplicate_constants() -> None:
    label = 'Unlimited, mode="all"'
    d = generate({"custom:clearsig-constant": f"message={json.dumps(label)},x=1,x=1,"})
    assert d.metadata.constants == {"message": label, "x": 1}


def test_absent_metadata_preserves_existing_fallbacks() -> None:
    d = generate({"author": "Author", "title": "Title", "custom": []})
    assert d.metadata.owner == "Author"
    assert d.metadata.contractName == "Title"
    assert d.metadata.info is None
    assert d.metadata.constants is None


@pytest.mark.parametrize("entrypoint", ["library", "cli"])
def test_compiler_artifact_and_cli(entrypoint: str, tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import hashlib
    from pathlib import Path

    from typer.testing import CliRunner

    from erc7730.main import app

    data = Path(__file__).parent / "data"
    artifact = json.loads((data / "metadata-annotations.artifact.json").read_text())
    assert artifact["compilerVersion"].startswith("0.8.30+")
    assert artifact["sourceSha256"] == hashlib.sha256((data / "MetadataAnnotations.sol").read_bytes()).hexdigest()
    if entrypoint == "library":
        d = generate_natspec_descriptor(1, ADDRESS, natspec=artifact)
    else:
        monkeypatch.chdir(tmp_path)
        path = tmp_path / "artifact.json"
        path.write_text(json.dumps(artifact))
        result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(path)])
        assert result.exit_code == 0, result.output
        d = InputERC7730Descriptor.model_validate_json(result.stdout)
    assert d.metadata.owner == "Protocol DAO"
    assert d.metadata.contractName == "Fee Controller"
    assert d.metadata.info is not None
    assert str(d.metadata.info.url) == "https://example.org/"
    assert d.metadata.constants == {"feeBase": "%", "feeDecimals": 2}
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    field = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    params = field.params
    assert isinstance(params, ResolvedUnitParameters)
    assert params.base == "%" and params.decimals == 2
