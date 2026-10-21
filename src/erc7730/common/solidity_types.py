"""Canonical Solidity type checks for annotations, descriptors and typed messages."""

import re
from typing import Annotated

from eth_abi.exceptions import ABITypeError, ParseError
from eth_abi.grammar import parse
from pydantic import AfterValidator


def validate_plaintext_type(value: str) -> str:
    if re.fullmatch(r"(?:address|bool|string|bytes[0-9]*|u?int[0-9]+)(?:\[[0-9]*\])*", value) is None:
        raise ValueError("plaintextType must use a canonical Solidity type")
    try:
        parse(value).validate()
    except (ABITypeError, ParseError) as exc:
        raise ValueError(f"Invalid canonical plaintextType {value!r}: {exc}") from exc
    return value


PlaintextType = Annotated[str, AfterValidator(validate_plaintext_type)]


_EIP712_PRIMITIVE = re.compile(
    r"(?:address|bool|string|bytes|bytes(?:[1-9]|[12][0-9]|3[0-2])|u?int(?:"
    + "|".join(map(str, range(8, 257, 8)))
    + r"))"
)


def is_eip712_primitive(value: str) -> bool:
    """Whether a scalar type is an EIP-712 primitive with canonical spelling."""
    return _EIP712_PRIMITIVE.fullmatch(value) is not None
