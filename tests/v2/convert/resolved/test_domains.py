"""EIP-712 binding constraints survive input validation and resolution."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

ADDRESS = "0x1111111111111111111111111111111111111111"


def descriptor(key: str, fields: list[dict[str, Any]], context: dict[str, Any] | None = None) -> InputERC7730Descriptor:
    return InputERC7730Descriptor.model_validate(
        {
            "context": context or {"contract": {"deployments": [{"chainId": 1, "address": ADDRESS}]}},
            "metadata": {"owner": "Example", "maps": {"tokens": {"values": {"1": ADDRESS}}}},
            "display": {"formats": {key: {"intent": "Send", "fields": fields}}},
        },
        strict=False,
    )


@pytest.mark.parametrize(
    "binding", [{"domain": {"name": "Example", "version": "1"}}, {"domainSeparator": "0x" + "ab" * 32}]
)
def test_eip712_without_deployments(binding: dict[str, Any]) -> None:
    d = descriptor(
        "Message(uint256 value)", [{"path": "value", "label": "Value", "format": "raw"}], {"eip712": binding}
    )
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs
    assert d.model_dump(mode="json", exclude_none=True)["context"]["eip712"]["deployments"] == []


@pytest.mark.parametrize("binding", [{}, {"domain": {}}, {"deployments": []}])
def test_unbound_eip712_is_rejected(binding: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        descriptor("Message(uint256 value)", [], {"eip712": binding})


def test_custom_domain_constraints_survive_resolution() -> None:
    import jsonschema

    domain = {"application": "Example", "revision": 3, "salt": "0x" + "Ab" * 32}
    d = descriptor(
        "Message(uint256 value)", [{"path": "value", "label": "Value", "format": "raw"}], {"eip712": {"domain": domain}}
    )
    jsonschema.validate(json.loads(d.to_json_string()), json.loads(Path("specs/erc7730-v2.schema.json").read_text()))
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    assert json.loads(resolved.to_json_string())["context"]["eip712"]["domain"] == domain
    assert InputERC7730Descriptor.model_validate_json(d.to_json_string()) == d


@pytest.mark.parametrize("value", ["", "0x", "0x" + "00" * 31, "0x" + "00" * 33, "00" * 32, "0x" + "gg" * 32])
@pytest.mark.parametrize("field", ["salt", "domainSeparator"])
def test_domain_strings_remain_loadable(field: str, value: str) -> None:
    from erc7730.model.input.v2.context import InputEIP712
    from erc7730.model.resolved.v2.context import ResolvedEIP712

    binding: dict[str, Any] = {"domain": {"salt": value}} if field == "salt" else {field: value}
    binding["deployments"] = [{"chainId": 1, "address": ADDRESS}]
    models: tuple[type[BaseModel], ...] = (InputEIP712, ResolvedEIP712)
    for model in models:
        loaded = model.model_validate(binding, strict=False)
        assert loaded.model_dump(exclude_none=True) == binding
