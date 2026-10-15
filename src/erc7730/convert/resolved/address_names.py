"""Validate resolved address-name lists, including scalar constant references."""

from collections.abc import Callable
from typing import Annotated, Any

from pydantic import Field, TypeAdapter, ValidationError

from erc7730.common.output import OutputAdder
from erc7730.model.display import AddressNameType


def resolve_name_lists(
    types: Any, sources: Any, resolve: Callable[[Any], Any], out: OutputAdder
) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    adapters: dict[str, TypeAdapter[Any]] = {
        "types": TypeAdapter(Annotated[list[AddressNameType], Field(min_length=1)]),
        "sources": TypeAdapter(Annotated[list[Annotated[str, Field(min_length=1)]], Field(min_length=1)]),
    }
    for name, value in (("types", types), ("sources", sources)):
        if value is None:
            continue
        resolved = resolve(value)
        if isinstance(resolved, str):
            resolved = [resolved]
        try:
            result[name] = adapters[name].validate_python(resolved, strict=False)
        except ValidationError as exc:
            return out.error(
                title=f"Invalid address-name {name}",
                message=f"{name} ({value}) must resolve to a nonempty list or a single valid string: {exc}",
            )
    return result
