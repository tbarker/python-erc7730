"""Transaction envelopes and container values shared by example execution."""

from typing import Any

import rlp
from pydantic import TypeAdapter

from erc7730.generate.natspec.examples.constants import (
    DEFAULT_EXAMPLE_ADDRESS,
    EIP1559_TRANSACTION_PREFIX,
    EXAMPLE_GAS_LIMIT,
    TRANSACTION_CHAIN_ID_PATH,
    TRANSACTION_FROM_PATH,
    TRANSACTION_TO_PATH,
    TRANSACTION_VALUE_PATH,
)
from erc7730.generate.natspec.examples.models import ExampleConfig
from erc7730.model.input.v2.context import InputDeployment
from erc7730.model.types import Address


def transaction_container(deployment: InputDeployment, settings: ExampleConfig) -> dict[str, Any]:
    return {
        TRANSACTION_CHAIN_ID_PATH: deployment.chainId,
        TRANSACTION_TO_PATH: deployment.address,
        TRANSACTION_VALUE_PATH: 0,
        TRANSACTION_FROM_PATH: resolve_sender(settings) or DEFAULT_EXAMPLE_ADDRESS,
    }


def raw_transaction(deployment: InputDeployment, calldata: bytes) -> str:
    raw = EIP1559_TRANSACTION_PREFIX + rlp.encode(
        [deployment.chainId, 0, 0, 0, EXAMPLE_GAS_LIMIT, bytes.fromhex(deployment.address[2:]), 0, calldata, []]
    )
    return "0x" + raw.hex()


def resolve_sender(settings: ExampleConfig) -> str | None:
    """Resolve a configured alias and validate the optional example sender."""
    if not settings.sender:
        return None
    sender = settings.aliases.get(settings.sender, settings.sender)
    return TypeAdapter(Address).validate_python(sender, strict=False)
