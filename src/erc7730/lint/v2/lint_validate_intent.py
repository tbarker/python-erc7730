"""Validate static intents and interpolation against declared schemas and formatters."""

from typing import Any, final, override

from erc7730.common.abi import compute_signature, parse_signature, signature_to_selector
from erc7730.common.output import OutputAdder
from erc7730.common.schema_types import schema_path_type
from erc7730.common.templates import translate_template
from erc7730.lint.v2 import ERC7730Linter
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.display import InputField, InputFieldGroup
from erc7730.model.input.v2.format import VisibilityRule
from erc7730.model.paths import Array, ArrayElement, ArraySlice, ContainerPath, DataPath, DescriptorPath, Field
from erc7730.model.paths.path_parser import to_path
from erc7730.model.resolved.v2.context import ResolvedEIP712Context
from erc7730.model.resolved.v2.descriptor import ResolvedERC7730Descriptor
from erc7730.model.resolved.v2.display import (
    ResolvedFieldDescription,
    iter_field_descriptions,
)


def _covers(format_path: DataPath, reference: DataPath, declaration: str, eip712: bool) -> bool:
    """A wildcard formatter covers its selected elements, but not unrelated paths."""
    # Root array formatters implicitly apply to every element, including nested
    # dimensions. Only add selectors for declared arrays, never scalar prefixes.
    type_ = schema_path_type(declaration, eip712, format_path) or ""
    while type_.endswith("]"):
        format_path = format_path.model_copy(update={"elements": [*format_path.elements, Array()]})
        type_ = type_[: type_.rindex("[")]
    type_ = schema_path_type(declaration, eip712, reference) or ""
    while type_.endswith("]"):
        reference = reference.model_copy(update={"elements": [*reference.elements, Array()]})
        type_ = type_[: type_.rindex("[")]
    elements = reference.elements
    if format_path.elements and isinstance(format_path.elements[-1], Array) and format_path.elements[:-1] == elements:
        return True  # interpolation of the whole formatted array
    if len(format_path.elements) != len(elements):
        return False
    for formatted, requested in zip(format_path.elements, elements, strict=True):
        if formatted == requested:
            continue
        if isinstance(formatted, Array) and isinstance(requested, Array | ArrayElement | ArraySlice):
            continue
        if (
            isinstance(formatted, ArraySlice)
            and isinstance(requested, ArrayElement)
            and requested.index >= 0
            and (formatted.start is None or 0 <= formatted.start <= requested.index)
            and (formatted.end is None or requested.index < formatted.end)
        ):
            continue
        return False
    return True


def _schema_contains(declaration: str, eip712: bool, path: DataPath) -> bool:
    return schema_path_type(declaration, eip712, path) is not None


def _constant_formatters(
    fields: list[InputField],
    path: DescriptorPath,
    descriptor: InputERC7730Descriptor,
) -> list[Any]:
    """Retain descriptor-path provenance that constant resolution removes."""
    matches = []
    for field in fields:
        if isinstance(field, InputFieldGroup):
            matches.extend(_constant_formatters(field.fields, path, descriptor))
        elif field.path == path or field.value == path:
            matches.append(field.visible)
    return matches


@final
class ValidateIntentLinter(ERC7730Linter):
    @override
    def lint(
        self, input_descriptor: InputERC7730Descriptor, descriptor: ResolvedERC7730Descriptor, out: OutputAdder
    ) -> None:
        eip712 = isinstance(descriptor.context, ResolvedEIP712Context)
        declarations = {}
        for key in input_descriptor.display.formats:
            try:
                identifier = key if eip712 else signature_to_selector(compute_signature(parse_signature(key)))
                declarations[identifier] = key
            except ValueError:
                continue  # resolution reports malformed declarations
        for signature, format in descriptor.display.formats.items():
            intent = format.intent
            valid_intent = bool(intent) and (
                all(key.strip() and value.strip() for key, value in intent.items())
                if isinstance(intent, dict)
                else bool(intent and intent.strip())
            )
            if not valid_intent:
                out.error(
                    title="Missing static intent",
                    message=f"{signature}: a nonempty static intent is required. "
                    "Add intent to the descriptor, or @custom:clearsig-intent to its compiler NatSpec.",
                )
            if format.interpolatedIntent is None:
                continue
            declaration = declarations.get(signature)
            fields = list(iter_field_descriptions(format.fields))

            def validate(
                reference: str,
                declaration: str | None = declaration,
                fields: list[ResolvedFieldDescription] = fields,
            ) -> str:
                path = to_path(reference)
                if isinstance(path, DataPath):
                    if declaration is None or not _schema_contains(declaration, eip712, path):
                        raise ValueError(f"{reference!r} does not exist in the declared schema")
                    matches = [
                        field.visible
                        for field in fields
                        if isinstance(field.path, DataPath) and _covers(field.path, path, declaration, eip712)
                    ]
                elif isinstance(path, ContainerPath):
                    matches = [field.visible for field in fields if field.path == path]
                else:
                    value: Any = input_descriptor.model_dump(mode="json", by_alias=True)
                    for element in path.elements:
                        try:
                            value = value[element.identifier if isinstance(element, Field) else element.index]
                        except (KeyError, IndexError, TypeError) as exc:
                            raise ValueError(f"{reference!r} does not exist in the descriptor") from exc
                    if isinstance(value, dict | list) or value is None:
                        raise ValueError(f"{reference!r} is not a scalar constant")
                    source = input_descriptor.display.formats.get(declaration or "")
                    matches = _constant_formatters(source.fields, path, input_descriptor) if source else []
                if len(matches) != 1:
                    raise ValueError(f"{reference!r} requires exactly one corresponding field formatter")
                if matches[0] not in (None, VisibilityRule.ALWAYS):
                    raise ValueError(f"{reference!r} must reference an always-visible field")
                return reference

            try:
                if not format.interpolatedIntent.strip():
                    raise ValueError("interpolatedIntent must not be empty")
                translate_template(format.interpolatedIntent, validate, natspec=False, literal_backticks=True)
            except ValueError as exc:
                out.error(title="Invalid interpolated intent", message=f"{signature}: {exc}.")
