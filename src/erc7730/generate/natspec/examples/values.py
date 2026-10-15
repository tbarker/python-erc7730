"""Value traversal shared by example checks."""

from typing import Any

from eth_abi.grammar import parse

from erc7730.model.paths import Array, ArrayElement, ArraySlice, ContainerPath, DataPath, Field


class UnavailableError(ValueError):
    """A concrete case or independent oracle cannot be exercised by this adapter."""


def named_value(part: dict[str, Any], value: Any) -> Any:
    type_ = parse(part["type"])
    if type_.is_array:
        return [named_value(part | {"type": type_.item_type.to_type_str()}, item) for item in value]
    if type_.base == "tuple":
        return {child["name"]: named_value(child, item) for child, item in zip(part["components"], value, strict=True)}
    return value


def _flatten(value: Any) -> list[Any]:
    return [leaf for item in value for leaf in _flatten(item)] if isinstance(value, list) else [value]


def read_values(path: DataPath | ContainerPath, root: dict[str, Any], container: dict[str, Any]) -> list[Any]:
    if isinstance(path, ContainerPath):
        return [container[str(path)]]
    values: list[Any] = [root]
    try:
        for element in path.elements:
            selected = []
            for value in values:
                if isinstance(element, Field):
                    selected.append(
                        len(value)
                        if element.identifier == "length" and isinstance(value, (bytes, list, str))
                        else value[element.identifier]
                    )
                elif isinstance(element, ArrayElement):
                    selected.append(bytes([value[element.index]]) if isinstance(value, bytes) else value[element.index])
                elif isinstance(element, (Array, ArraySlice)):
                    if isinstance(value, list):
                        selected.extend(value if isinstance(element, Array) else value[element.start : element.end])
                    elif isinstance(value, bytes):
                        selected.append(value if isinstance(element, Array) else value[element.start : element.end])
                    else:
                        raise UnavailableError("primitive slicing of non-byte values needs a byte-layout oracle")
            values = selected
        return [leaf for value in values for leaf in _flatten(value)]
    except (KeyError, IndexError, TypeError) as exc:
        raise UnavailableError(f"mutation does not supply {path}") from exc
