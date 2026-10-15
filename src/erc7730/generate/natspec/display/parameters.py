"""Compiler tag values validated through the descriptor's parameter models."""

from typing import Any

from pydantic import TypeAdapter

from erc7730.generate.natspec.syntax import decoded, parse_map_expression
from erc7730.model.input.v2.display import INPUT_PARAMETER_MODELS
from erc7730.model.input.v2.format import FieldFormat

PARAMETER_TAGS = (
    "tokenPath",
    "token",
    "dateEncoding",
    "mapRef",
    "types",
    "sources",
    "senderAddress",
    "base",
    "decimals",
    "prefix",
    "threshold",
    "message",
    "nativeCurrencyAddress",
    "chainId",
    "chainIdPath",
    "callee",
    "calleePath",
    "selector",
    "selectorPath",
    "amount",
    "amountPath",
    "spender",
    "spenderPath",
    "collection",
    "collectionPath",
    "enumRef",
)
ALTERNATIVES = ("token", "chainId", "callee", "selector", "amount", "spender", "collection")


def parameter_update(format: FieldFormat | None, tag: str, value: str) -> tuple[str, Any]:
    model = INPUT_PARAMETER_MODELS.get(format) if format is not None else None
    if model is None:
        raise ValueError(f"format {format} does not accept parameters")
    name = {"dateEncoding": "encoding", "enumRef": "ref"}.get(tag, tag)
    parsed = decoded(value)
    if tag == "mapRef" or (tag == "token" and value.startswith("map(")):
        name, map_name, key_path = parse_map_expression(value, reference=tag == "mapRef")
        parsed = {"map": "$.metadata.maps." + map_name, "keyPath": key_path}
    if name not in model.model_fields:
        raise ValueError(f"{tag} is not a parameter of {format}")
    # The schema encodes integer thresholds as strings, including hexadecimal.
    if name == "threshold" and not value.startswith('"'):
        parsed = value
    if isinstance(parsed, bool) and name in ("decimals", "chainId", "amount"):
        raise ValueError(f"{name} requires an integer, not a boolean")
    if name in ("decimals", "chainId", "amount") and isinstance(parsed, float):
        raise ValueError(f"{name} requires an integer")
    field = model.model_fields[name]
    parsed = TypeAdapter(field.rebuild_annotation()).validate_python(parsed, strict=False)
    return field.alias or name, parsed


def merge_parameter(params: dict[str, Any], name: str, value: Any) -> None:
    for base in ALTERNATIVES:
        if name == base:
            params.pop(base + "Path", None)
        elif name == base + "Path":
            params.pop(base, None)
    params[name] = value
