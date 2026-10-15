"""Resolve formatter parameters by their declared format."""

from typing import Any

import pytest
from pydantic import ValidationError

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
    "format,type_",
    [
        ("addressName", "address"),
        ("interoperableAddressName", "bytes"),
        ("tokenAmount", "uint256"),
        ("tokenTicker", "address"),
    ],
)
@pytest.mark.parametrize("params", [None, {}])
def test_optional_parameters(format: str, type_: str, params: dict[str, Any] | None) -> None:
    d = descriptor(f"f({type_} value)", [{"path": "value", "label": "Value", "format": format, "params": params}])
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    assert not out.has_errors, out.outputs
    assert type(d).model_validate_json(d.to_json_string()) == d


@pytest.mark.parametrize(
    "format,params",
    [
        ("date", {"token": ADDRESS}),
        ("raw", {"encoding": "timestamp"}),
        ("tokenTicker", {"token": ADDRESS}),
        ("tokenAmount", {"sources": ["ens"]}),
        ("addressName", {"chainId": 1}),
        ("duration", {"encoding": "timestamp"}),
    ],
)
def test_wrong_parameter_objects_rejected(format: str, params: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        descriptor("f(uint256 value)", [{"path": "value", "label": "Value", "format": format, "params": params}])
