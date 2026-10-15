"""Typed-message inputs for the existing external example renderer."""

from __future__ import annotations

import re
from typing import Any

from eth_abi.abi import encode
from eth_abi.grammar import parse
from eth_utils.abi import collapse_if_tuple
from eth_utils.crypto import keccak
from pydantic import BaseModel

from erc7730.common.abi import ABIDataType, parse_encode_type
from erc7730.common.solidity_types import is_eip712_primitive
from erc7730.generate.natspec.examples.constants import (
    TRANSACTION_CHAIN_ID_PATH,
    TRANSACTION_FROM_PATH,
    TRANSACTION_TO_PATH,
    TRANSACTION_VALUE_PATH,
)
from erc7730.generate.natspec.examples.models import ExampleConfig
from erc7730.generate.natspec.examples.transactions import resolve_sender
from erc7730.model.input.v2.context import InputEIP712Context
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.paths import ContainerPath

_STANDARD_DOMAIN = {
    "name": "string",
    "version": "string",
    "chainId": "uint256",
    "verifyingContract": "address",
    "salt": "bytes32",
}


def message_schema(declaration: str) -> tuple[str, dict[str, list[dict[str, str]]], list[dict[str, Any]]]:
    """Recover message types from the descriptor's authoritative format key."""
    primary, definitions = parse_encode_type(declaration)
    types = {name: [{"type": t, "name": n} for t, n in members] for name, members in definitions.items()}

    def parts(name: str, active: tuple[str, ...]) -> list[dict[str, Any]]:
        if name in active:
            raise ValueError(f"Recursive message examples are unsupported: {name}")
        result = []
        for member in types[name]:
            base, *suffix = member["type"].split("[", 1)
            item: dict[str, Any] = dict(member)
            if base in types:
                item["type"] = "tuple" + ("[" + suffix[0] if suffix else "")
                item["components"] = parts(base, (*active, name))
            result.append(item)
        return result

    return primary, types, parts(primary, ())


def _wire(part: dict[str, Any], value: Any) -> Any:
    type_ = parse(part["type"])
    if type_.is_array:
        return [_wire(part | {"type": type_.item_type.to_type_str()}, child) for child in value]
    if type_.base == "tuple":
        return {p["name"]: _wire(p, v) for p, v in zip(part["components"], value, strict=True)}
    if isinstance(value, bytes):
        if type_.base == ABIDataType.BYTES and type_.sub is not None and len(value) != type_.sub:
            raise ValueError(f"{part['name']} requires exactly {type_.sub} bytes.")
        return "0x" + value.hex()
    if type_.base in (ABIDataType.UINT, ABIDataType.INT):
        return str(value)
    return value


def _container_references(value: Any) -> set[str]:
    if isinstance(value, ContainerPath):
        return {str(value)}
    if isinstance(value, BaseModel):
        return _container_references([getattr(value, name) for name in type(value).model_fields])
    if isinstance(value, dict):
        return _container_references(list(value.values()))
    if isinstance(value, list):
        return {reference for child in value for reference in _container_references(child)}
    return set()


def signing_domain(
    descriptor: InputERC7730Descriptor, settings: ExampleConfig
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, Any]]:
    assert isinstance(descriptor.context, InputEIP712Context)  # nosec B101 - internal invariant, not input validation
    binding = descriptor.context.eip712
    constraints = binding.domain.model_dump(exclude_none=True) if binding.domain else {}
    domain = dict(settings.domain) if settings.domain is not None else dict(constraints)
    deployments = binding.deployments or []
    if settings.domain is None:
        if binding.domainSeparator:
            raise ValueError("Domain-separator bindings require examples.domain.")
        if len(deployments) == 1:
            domain.setdefault("chainId", deployments[0].chainId)
            domain.setdefault("verifyingContract", deployments[0].address)
        elif len(deployments) > 1:
            raise ValueError("Ambiguous deployments require examples.domain.")
    for name, expected in constraints.items():
        actual = domain.get(name)
        if name in ("verifyingContract", "salt") and isinstance(actual, str) and isinstance(expected, str):
            actual, expected = actual.lower(), expected.lower()
        if actual != expected:
            raise ValueError(f"examples.domain does not satisfy domain constraint {name}.")
    if deployments and not any(
        domain.get("chainId") == d.chainId and str(domain.get("verifyingContract", "")).lower() == d.address.lower()
        for d in deployments
    ):
        raise ValueError("examples.domain does not match a descriptor deployment.")
    members = settings.domain_types
    if members is None:
        if set(domain) - set(_STANDARD_DOMAIN):
            raise ValueError("Custom signing domain fields require examples.domainTypes.")
        members = [{"name": n, "type": t} for n, t in _STANDARD_DOMAIN.items() if n in domain]
    if any(set(m) != {"name", "type"} for m in members):
        raise ValueError("examples.domainTypes entries require exactly name and type.")
    if len({m.get("name") for m in members}) != len(members) or {m.get("name") for m in members} != set(domain):
        raise ValueError("examples.domainTypes must describe every domain field exactly once.")
    encoded_types, encoded_values = (
        ["bytes32"],
        [keccak(text="EIP712Domain(" + ",".join(f"{m['type']} {m['name']}" for m in members) + ")")],
    )
    for member in members:
        name, type_ = member["name"], member["type"]
        if name in _STANDARD_DOMAIN and type_ != _STANDARD_DOMAIN[name]:
            raise ValueError(f"Invalid standard domain type for {name}.")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
            raise ValueError("Invalid domain field name.")
        if not is_eip712_primitive(type_):
            raise ValueError("Custom example domain types must be EIP-712 primitives.")
        value = domain[name]
        if type_.startswith("bytes"):
            if not isinstance(value, str) or not re.fullmatch(r"0x(?:[0-9a-fA-F]{2})*", value):
                raise ValueError(f"Domain {name} requires a hex byte string.")
            value = bytes.fromhex(value[2:])
            if type_ != ABIDataType.BYTES and len(value) != int(type_[5:]):
                raise ValueError(f"Domain {name} requires exactly {type_[5:]} bytes.")
        if type_ in (ABIDataType.STRING, ABIDataType.BYTES):
            if type_ == ABIDataType.STRING:
                if not isinstance(value, str):
                    raise ValueError(f"Domain {name} requires a string.")
                value = keccak(text=value)
            else:
                value = keccak(value)
            encoded_types.append("bytes32")
        else:
            encoded_types.append(type_)
        encoded_values.append(value)
    separator = "0x" + keccak(encode(encoded_types, encoded_values)).hex()
    if binding.domainSeparator and separator.lower() != binding.domainSeparator.lower():
        raise ValueError("examples.domain does not match domainSeparator.")
    sender = resolve_sender(settings)
    references = _container_references(descriptor)
    if TRANSACTION_FROM_PATH in references and sender is None:
        raise ValueError("Signer-dependent typed-data examples require examples.sender.")
    container = {
        TRANSACTION_TO_PATH: domain.get("verifyingContract"),
        TRANSACTION_CHAIN_ID_PATH: domain.get("chainId"),
        TRANSACTION_FROM_PATH: sender,
        TRANSACTION_VALUE_PATH: 0,
    }
    for path in (TRANSACTION_TO_PATH, TRANSACTION_CHAIN_ID_PATH):
        if path in references and container[path] is None:
            raise ValueError(f"Typed-data display references {path}, but examples.domain does not supply it.")
    return domain, members, container


def typed_input(
    declaration: str, values: list[Any], descriptor: InputERC7730Descriptor, settings: ExampleConfig
) -> dict[str, Any]:
    primary, types, parts = message_schema(declaration)
    # Validate ranges, bytes lengths, fixed arrays and tuple arity before rendering.
    encode([collapse_if_tuple(part) for part in parts], values)
    domain, domain_types, container = signing_domain(descriptor, settings)
    # The runner matches domain constraints using JSON numbers (strict equality).
    # Message integers below are strings; reject unsafe domain numbers rather than round them.
    if any(isinstance(v, int) and abs(v) > 2**53 - 1 for v in domain.values()):
        raise ValueError("Example runner cannot safely represent domain integers above the JSON safe-integer range.")
    data = {
        "primaryType": primary,
        "types": types | {"EIP712Domain": domain_types},
        "domain": domain,
        "message": {p["name"]: _wire(p, v) for p, v in zip(parts, values, strict=True)},
    }
    if container[TRANSACTION_FROM_PATH] is not None:
        data["account"] = container[TRANSACTION_FROM_PATH]
    return data
