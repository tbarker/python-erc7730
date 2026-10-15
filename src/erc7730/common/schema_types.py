"""V2 formatter applicability and bounded lookup in declared structured data."""

import re
from typing import Any

from erc7730.common.abi import ABIDataType, parse_encode_type, parse_signature
from erc7730.model.input.v2.format import FieldFormat
from erc7730.model.paths import Array, ArrayElement, ArraySlice, DataPath, Field


def format_accepts_type(format: FieldFormat | None, type_: str) -> bool:
    """Check v2 format families; array formatters apply to their elements."""
    base = re.sub(r"\d+$", "", type_.split("[", 1)[0])
    if format in (None, FieldFormat.RAW):
        return True
    if base in (ABIDataType.UINT, ABIDataType.INT):
        return format in {
            FieldFormat.AMOUNT,
            FieldFormat.TOKEN_AMOUNT,
            FieldFormat.NFT_NAME,
            FieldFormat.DATE,
            FieldFormat.DURATION,
            FieldFormat.UNIT,
            FieldFormat.ENUM,
            FieldFormat.CHAIN_ID,
        }
    if base == ABIDataType.ADDRESS:
        return format in (FieldFormat.ADDRESS_NAME, FieldFormat.TOKEN_TICKER)
    if base == ABIDataType.BYTES:
        return format in (FieldFormat.CALL_DATA, FieldFormat.INTEROPERABLE_ADDRESS_NAME)
    return False


def _in_bounds(element: Array | ArrayElement | ArraySlice, size: int | None) -> bool:
    if size is None:
        return True  # dynamic lengths require a concrete message to validate
    if isinstance(element, ArrayElement):
        return -size <= element.index < size
    if isinstance(element, ArraySlice):
        start = element.start if element.start is not None else 0
        end = element.end if element.end is not None else size
        start = start + size if start < 0 else start
        end = end + size if end < 0 else end
        return 0 <= start < end <= size
    return True


def schema_path_type(declaration: str, eip712: bool, path: DataPath) -> str | None:
    """Walk only a requested path, so recursive EIP-712 declarations remain finite.

    Return None for missing fields or statically impossible selectors. Runtime
    bounds of dynamic arrays/bytes remain the renderer's responsibility.
    """
    types: dict[str, list[dict[str, Any]]] = {}
    if eip712:
        primary, definitions = parse_encode_type(declaration)
        types = {
            name: [{"type": type_, "name": member} for type_, member in members]
            for name, members in definitions.items()
        }
        members = types[primary]
    else:
        members = [part.model_dump() for part in parse_signature(declaration).inputs or []]
    current: dict[str, Any] | None = None
    for index, element in enumerate(path.elements):
        type_ = current["type"] if current else ""
        if isinstance(element, Field):
            if current is not None:
                if type_.endswith("]") or type_ in (ABIDataType.BYTES, ABIDataType.STRING):
                    if element.identifier == "length":
                        current = {"type": "uint256"}
                        continue
                    return None
                members = current.get("components") or types.get(type_, [])
            current = next((member.copy() for member in members if member["name"] == element.identifier), None)
            if current is None:
                return None
        elif current is None:
            return None
        elif type_.endswith("]"):
            start = type_.rindex("[")
            size = type_[start + 1 : -1]
            if not _in_bounds(element, int(size) if size else None):
                return None
            current = current | {"type": type_[:start]}
        else:
            # A primitive selector addresses bytes and must end the path.
            if index != len(path.elements) - 1:
                return None
            match = re.fullmatch(r"(bytes|uint|int)(\d*)", type_)
            if match:
                family, width = match.groups()
                size = (
                    (int(width or 256) // 8)
                    if family in (ABIDataType.UINT, ABIDataType.INT)
                    else (int(width) if width else None)
                )
            elif type_ == ABIDataType.STRING:
                size = None
            else:
                return None
            if not _in_bounds(element, size):
                return None
    return current["type"] if current is not None else None


def format_accepts_path(format: FieldFormat | None, declaration: str, eip712: bool, path: DataPath) -> bool:
    """Primitive byte slices are formatted as the selected bytes, not the whole value."""
    type_ = schema_path_type(declaration, eip712, path)
    if type_ is None:
        return False
    if not path.elements or isinstance(path.elements[-1], Field):
        return format_accepts_type(format, type_)
    parent = schema_path_type(declaration, eip712, path.model_copy(update={"elements": path.elements[:-1]}))
    if parent is None or parent.endswith("]"):
        return format_accepts_type(format, type_)  # selecting array elements retains their Solidity type
    width = primitive_slice_width(declaration, eip712, path)
    if format in (FieldFormat.ADDRESS_NAME, FieldFormat.TOKEN_TICKER):
        return width == 20
    if width is not None and 0 < width <= 32 and format_accepts_type(format, "uint256"):
        return True
    return format_accepts_type(format, "bytes")


def primitive_slice_width(declaration: str, eip712: bool, path: DataPath) -> int | None:
    """Known byte width of an explicit primitive selector, excluding array selectors."""
    if not path.elements or isinstance(path.elements[-1], Field):
        return None
    parent = schema_path_type(declaration, eip712, path.model_copy(update={"elements": path.elements[:-1]}))
    if parent is None or parent.endswith("]"):
        return None
    element = path.elements[-1]
    width = None
    if isinstance(element, ArrayElement):
        width = 1
    elif isinstance(element, ArraySlice):
        match = re.fullmatch(r"(bytes|uint|int)(\d+)", parent)
        size = None if match is None else int(match[2]) // (8 if match[1] in (ABIDataType.UINT, ABIDataType.INT) else 1)
        start = element.start if element.start is not None else 0
        end = element.end
        if size is not None:
            start = start + size if start < 0 else start
            end = size if end is None else end + size if end < 0 else end
        if end is not None and (start >= 0) == (end >= 0):
            width = end - start
        elif end is None and start < 0:
            width = -start
    return width


def validate_function_declaration(declaration: str) -> None:
    """Validate named ABI declarations without imposing a whitespace style."""
    from eth_abi.grammar import parse

    function = parse_signature(declaration)
    if function.name is None:
        raise ValueError("A v2 function declaration requires a function name")

    def check_names(parts: list[dict[str, Any]]) -> None:
        names = [part["name"] for part in parts]
        if any(not name for name in names):
            raise ValueError("Named parameters are required for display paths")
        if len(names) != len(set(names)):
            raise ValueError("Duplicate parameter names make display paths ambiguous")
        for part in parts:
            if part.get("components"):
                check_names(part["components"])

    check_names([part.model_dump() for part in function.inputs or []])

    def parameter(part: dict[str, Any]) -> str:
        type_ = part["type"]
        if type_.startswith("tuple"):
            type_ = "(" + ",".join(parameter(child) for child in part["components"] or []) + ")" + type_[5:]
        else:
            base = type_.split("[", 1)[0]
            if base in (ABIDataType.UINT, ABIDataType.INT, "byte", ABIDataType.FIXED, ABIDataType.UFIXED):
                raise ValueError(f"Noncanonical Solidity type {type_}; use an explicit canonical type")
            if re.fullmatch(r"address|bool|string|bytes[0-9]*|u?int[0-9]+|u?fixed[0-9]+x[0-9]+", base) is None:
                raise ValueError(f"Unknown ABI type {type_}; use its canonical Solidity ABI type")
            parse(type_).validate()
        return type_ + " " + part["name"]

    named = function.name + "(" + ",".join(parameter(part.model_dump()) for part in function.inputs or []) + ")"
    if "".join(named.split()) != "".join(declaration.split()):
        raise ValueError("Named parameters are required for display paths")


def schema_path_shape(declaration: str, eip712: bool, path: DataPath) -> list[int | None]:
    """Array dimensions selected by a path, including implicit trailing arrays."""
    shape: list[int | None] = []
    for index, element in enumerate(path.elements):
        if isinstance(element, Field):
            continue
        parent = schema_path_type(declaration, eip712, path.model_copy(update={"elements": path.elements[:index]}))
        if parent is None or not parent.endswith("]") or isinstance(element, ArrayElement):
            continue
        size_text = parent[parent.rindex("[") + 1 : -1]
        size = int(size_text) if size_text else None
        if isinstance(element, ArraySlice):
            if size is not None:
                start, end, _ = slice(element.start, element.end).indices(size)
                size = max(0, end - start)
            elif element.start is not None and element.end is not None and element.start >= 0 and element.end >= 0:
                size = element.end - element.start
        shape.append(size)
    type_ = schema_path_type(declaration, eip712, path) or ""
    while type_.endswith("]"):
        start = type_.rindex("[")
        shape.append(int(type_[start + 1 : -1]) if type_[start + 1 : -1] else None)
        type_ = type_[:start]
    return shape
