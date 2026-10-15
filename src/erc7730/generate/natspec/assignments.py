"""Shared duplicate checks for annotation declarations."""

from typing import TypeVar

#: Type of the values in an annotation declaration.
Value = TypeVar("Value")


def define_entry(entries: dict[str, Value], key: str, value: Value, context: str) -> None:
    """Allow identical repeats, but never collapse distinct scalar types or values."""
    if key in entries and (type(entries[key]) is not type(value) or entries[key] != value):
        raise ValueError(f"conflicting {context}")
    entries[key] = value
