"""Map lookup checks and bounded key mutations shared by example execution."""

from collections.abc import Iterator
from copy import deepcopy
from typing import Any

from eth_abi.abi import is_encodable

from erc7730.common.abi import ABIDataType
from erc7730.common.schema_types import schema_path_type
from erc7730.convert.resolved.v2.values import lookup_map_key
from erc7730.generate.natspec.examples.values import read_values
from erc7730.model.paths import ArrayElement, DataPath, Field
from erc7730.model.resolved.v2.display import ResolvedFormat, ResolvedValueMap, iter_field_descriptions


def map_references(format: ResolvedFormat) -> Iterator[ResolvedValueMap]:
    for field in iter_field_descriptions(format.fields):
        if field.params is not None:
            for name in type(field.params).model_fields:
                if isinstance(ref := getattr(field.params, name), ResolvedValueMap):
                    yield ref


def check_maps(format: ResolvedFormat, root: dict[str, Any], container: dict[str, Any]) -> None:
    for ref in map_references(format):
        keys = read_values(ref.keyPath, root, container)
        if len(keys) != 1:
            raise ValueError("Map key must select exactly one scalar value")
        lookup_map(ref.values, keys[0])


def map_variants(
    declaration: str, format: ResolvedFormat, parts: list[dict[str, Any]], base: list[Any], limit: int
) -> tuple[list[Any], list[tuple[str, list[Any]]], list[str]]:
    """Seed valid scalar argument keys, then exercise map entries and a missing key."""
    unavailable: list[str] = []
    plans = []
    for ref in map_references(format):
        if not isinstance(ref.keyPath, DataPath):
            unavailable.append(
                f"{declaration}: container map {ref.keyPath} is checked for the selected deployment/context only."
            )
            continue
        path = ref.keyPath
        type_ = schema_path_type(declaration, False, path)
        keys = list(ref.values)[:limit]
        if len(ref.values) > limit:
            unavailable.append(f"{declaration}: map entries exceed maxSanityCases={limit}.")

        def value(key: str, type_: str | None = type_) -> Any:
            if type_ and (type_.startswith("uint") or type_.startswith("int")):
                return int(key, 16 if key.startswith("0x") else 10)
            if type_ == ABIDataType.BOOL:
                if key not in ("true", "false"):
                    raise ValueError("boolean map key must be true or false")
                return key == "true"
            if type_ and type_.startswith("bytes"):
                return bytes.fromhex(key.removeprefix("0x"))
            return key

        try:
            converted = [(key, value(key)) for key in keys]
            if type_ is None or any(not is_encodable(type_, item) for _, item in converted):
                raise ValueError("map entries contain keys outside the ABI type")

            base = _set_map_key(base, converted[0][1], path, parts)
            # Include an unknown scalar key where the ABI domain has an unused value.
            candidates = [0, 1, len(ref.values) + 1, "__unmapped__", "0x" + "00" * 20, False, True]
            if type_.startswith("bytes"):
                candidates.append(bytes(int(type_[5:]) if type_[5:] else 1))
            for missing in candidates:
                if is_encodable(type_, missing) and map_key(missing) not in ref.values:
                    converted.append(("unmapped", missing))
                    break
            plans.append((path, converted))
        except (ValueError, StopIteration, IndexError, TypeError) as exc:
            unavailable.append(f"{declaration}: cannot generate map keys for {path}: {exc}")
    mutations = [
        (f"map-{path}-{key}", _set_map_key(base, value, path, parts))
        for path, converted in plans
        for key, value in converted
    ]
    return base, mutations, unavailable


def _set_map_key(values: list[Any], new: Any, path: DataPath, parts: list[dict[str, Any]]) -> list[Any]:
    """Copy arguments and replace the scalar selected by a concrete map-key path."""
    result = deepcopy(values)
    current, components = result, parts
    for index, element in enumerate(path.elements):
        if isinstance(element, Field):
            slot = next(i for i, part in enumerate(components) if part["name"] == element.identifier)
            components = components[slot].get("components", [])
        elif isinstance(element, ArrayElement):
            slot = element.index
        else:
            raise ValueError("map key mutation requires concrete selectors")
        if index == len(path.elements) - 1:
            current[slot] = new
        else:
            current = current[slot]
    return result


def map_key(value: Any) -> str:
    """Use JSON scalar spelling for lookup keys; never coerce objects to strings."""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, str | int):
        return str(value)
    raise ValueError("Map lookup keys must be scalar strings, bytes, booleans or integers")


def lookup_map(values: dict[str, Any], key: Any) -> Any:
    key = map_key(key)
    matched = lookup_map_key(values, key)
    if matched is None:
        raise ValueError(f"No map entry for key {key!r}; descriptor is invalid for this transaction")
    return values[matched]
