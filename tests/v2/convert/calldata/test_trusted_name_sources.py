"""Explicit naming policies survive both Ledger exporters without broadening."""

import json
from typing import Any

import pytest

from erc7730.common.output import ListOutputAdder
from erc7730.convert.calldata.convert_erc7730_input_to_calldata import erc7730_descriptor_to_calldata_descriptors
from erc7730.convert.calldata.convert_erc7730_v2_input_to_calldata import erc7730_v2_descriptor_to_calldata_descriptors
from erc7730.convert.calldata.trusted_names import convert_name_sources
from erc7730.model.calldata.types import TrustedNameSource as Source
from erc7730.model.calldata.types import TrustedNameType as NameType
from erc7730.model.input.descriptor import InputERC7730Descriptor as DescriptorV1
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor as DescriptorV2


def export(version: int, params: dict[str, Any] | None, constants: dict[str, Any] | None = None) -> Any:
    contract: dict[str, Any] = {"deployments": [{"chainId": 1, "address": "0x" + "11" * 20}]}
    if version == 1:
        contract["abi"] = [{"type": "function", "name": "f", "inputs": [{"name": "to", "type": "address"}]}]
    field = {"path": "to", "label": "To", "format": "addressName", "params": params}
    raw = json.dumps(
        {
            "context": {"contract": contract},
            "metadata": {"owner": "Example", "constants": constants},
            "display": {"formats": {"f(address to)": {"intent": "Send", "fields": [field]}}},
        }
    )
    return (
        erc7730_descriptor_to_calldata_descriptors(DescriptorV1.model_validate_json(raw))
        if version == 1
        else erc7730_v2_descriptor_to_calldata_descriptors(DescriptorV2.model_validate_json(raw))
    )


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("type_", ["eoa", "contract", "token"])
@pytest.mark.parametrize(
    "sources,expected",
    [
        (["local"], [Source.LOCAL_ADDRESS_BOOK, Source.MULTISIG_ADDRESS_BOOK]),
        (["ENS", "ens"], [Source.ENS]),
        (["local", "ens"], [Source.LOCAL_ADDRESS_BOOK, Source.MULTISIG_ADDRESS_BOOK, Source.ENS]),
    ],
)
def test_explicit_sources_are_exact(version: int, type_: str, sources: list[str], expected: list[Source]) -> None:
    descriptors = export(version, {"types": [type_], "sources": sources})
    assert len(descriptors) == 1
    assert descriptors[0].fields[0].param.sources == expected


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("sources", [["unknown"], ["ens", "unknown"]])
def test_unknown_sources_fail_export(version: int, sources: list[str]) -> None:
    assert export(version, {"sources": sources}) == []


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize(
    "params,expected",
    [
        ({"sources": None}, list(Source)),
        ({"types": ["contract"]}, [Source.CRYPTO_ASSET_LIST]),
        ({"types": ["eoa"]}, [Source.ENS, Source.UNSTOPPABLE_DOMAIN, Source.FREENAME]),
    ],
)
def test_omitted_sources_preserve_defaults(version: int, params: dict[str, Any] | None, expected: list[Source]) -> None:
    assert export(version, params)[0].fields[0].param.sources == expected


def test_context_default_and_explicit_empty_policy() -> None:
    out = ListOutputAdder()
    assert convert_name_sources([NameType.CONTEXT_ADDRESS], None, out) == [Source.DYNAMIC_RESOLVER]
    assert convert_name_sources([], [], out) is None
    assert out.has_errors
    assert export(2, None)[0].fields[0].param.sources == list(Source)


@pytest.mark.parametrize("version", [1, 2])
def test_source_and_type_references_reach_export(version: int) -> None:
    descriptors = export(
        version,
        {"sources": "$.metadata.constants.source", "types": "$.metadata.constants.type"},
        {"source": "ens", "type": "contract"},
    )
    assert descriptors[0].fields[0].param.sources == [Source.ENS]
    assert descriptors[0].fields[0].param.types == [NameType.SMART_CONTRACT]


@pytest.mark.parametrize("version", [1, 2])
def test_invalid_reference_fails_export(version: int) -> None:
    assert export(version, {"sources": "$.metadata.constants.source"}, {"source": 3}) == []
