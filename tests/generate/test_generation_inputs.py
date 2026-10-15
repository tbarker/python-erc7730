"""Typed library inputs used by the upstream fixture assembly."""

import json
from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter
from pydantic_string_url import HttpUrl

from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.context import InputContractContext, InputDeployment, InputEIP712Context
from erc7730.model.input.v2.metadata import InputMetadata, InputOwnerInfo
from erc7730.model.metadata import TokenInfo

ADDRESS = "0x1111111111111111111111111111111111111111"
ABI = json.dumps([{"type": "function", "name": "f", "inputs": []}])


@pytest.mark.parametrize("typed", [False, True])
def test_typed_bindings_and_metadata(typed: bool) -> None:
    bindings = [InputDeployment(chainId=1, address=ADDRESS), InputDeployment(chainId=137, address=ADDRESS)]
    date = datetime(2020, 1, 1, tzinfo=UTC)
    metadata = InputMetadata(
        owner="Configured",
        contractName="Configured contract",
        info=InputOwnerInfo(url=TypeAdapter(HttpUrl).validate_python("https://example.org"), deploymentDate=date),
        token=TokenInfo(name="Example Token", ticker="EXA", decimals=6),
    )
    original = metadata.model_dump_json()
    descriptor = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=ABI,
        deployments=bindings,
        metadata=metadata,
        owner="Explicit",
        url=TypeAdapter(HttpUrl).validate_python("https://example.com"),
        devdoc={
            "author": "NatSpec",
            "title": "NatSpec contract",
            "methods": {"f()": {"custom:clearsig-typed-data": "Message"} if typed else {}},
        },
    )
    context = descriptor.context
    assert isinstance(context, InputContractContext | InputEIP712Context)
    actual = context.contract.deployments if isinstance(context, InputContractContext) else context.eip712.deployments
    assert actual == bindings
    assert descriptor.metadata.owner == "Explicit"
    assert descriptor.metadata.contractName == "Configured contract"
    assert descriptor.metadata.info is not None
    assert descriptor.metadata.info.deploymentDate == date
    assert str(descriptor.metadata.info.url) == "https://example.com"
    assert descriptor.metadata.token == metadata.token
    assert metadata.model_dump_json() == original
    bindings.clear()
    assert actual is not None and len(actual) == 2


@pytest.mark.parametrize(
    "bindings",
    [
        [],
        [InputDeployment(chainId=2, address=ADDRESS)],
        [InputDeployment(chainId=1, address=ADDRESS), InputDeployment(chainId=1, address=ADDRESS)],
    ],
)
def test_invalid_binding_list(bindings: list[InputDeployment]) -> None:
    with pytest.raises(ValueError, match="deployments"):
        generate_natspec_descriptor(1, ADDRESS, abi=ABI, deployments=bindings)
