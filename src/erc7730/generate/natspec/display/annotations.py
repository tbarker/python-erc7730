"""Parse display tags and apply encryption, formatting, and field parameters."""

from __future__ import annotations

import json
import re
from typing import Any

from eth_abi.exceptions import ParseError
from pydantic import TypeAdapter

from erc7730.common.schema_types import format_accepts_type
from erc7730.common.templates import translate_template
from erc7730.generate.natspec.display.fields import Nodes, _matches, _name, _node_type, replace_field
from erc7730.generate.natspec.display.parameters import PARAMETER_TAGS, merge_parameter, parameter_update
from erc7730.generate.natspec.documents import custom_tag
from erc7730.generate.natspec.syntax import decoded, parse_pairs
from erc7730.generate.schema_tree import SchemaTree
from erc7730.model.input.v2.display import (
    InputEncryptionParameters,
    InputFieldDescription,
    InputVisibilityConditions,
)
from erc7730.model.input.v2.format import FieldFormat, VisibilityRule
from erc7730.model.paths import Array, ArraySlice, ContainerPath, DataPath

ENCRYPTION_TAGS = ("encryptionScheme", "plaintextType", "fallbackLabel")
DEFAULT_TAGS = (*ENCRYPTION_TAGS, "format", *PARAMETER_TAGS, "separator", "visible", "mustMatch", "ifNotIn")
TAGS = ("group", "enum", "intent", "interpolatedIntent", "exclude", "label", *DEFAULT_TAGS)


def _tag_name(tag: str) -> str:
    """Convert a model property name to its compiler annotation name."""
    return "clearsig-" + re.sub(r"([A-Z])", r"-\1", tag).lower()


def _tags(doc: dict[str, Any]) -> dict[str, str]:
    tags = {}
    for tag in TAGS:
        name = _tag_name(tag)
        value = custom_tag(doc, name)
        if isinstance(value, str):
            tags[tag] = value
    return tags


def _exclusions(tags: dict[str, str]) -> list[str]:
    return [name for name in re.split(r"[\s,]+", tags.get("exclude", "")) if name]


def _field_update(field: InputFieldDescription, tag: str, value: str, data_type: str | None) -> InputFieldDescription:
    match tag:
        case "label":
            return field.model_copy(update={"label": value})
        case "separator":
            if value.startswith('"'):
                value = json.loads(value)
            if not isinstance(value, str):
                raise ValueError("separator must be a string")

            def index_reference(reference: str) -> str:
                if reference != "index":
                    raise ValueError("separator supports only {index} interpolation")
                return reference

            value = translate_template(value, index_reference, natspec=False, literal_backticks=True)
            return field.model_copy(update={"separator": value})
        case "format":
            format = next((f for f in FieldFormat if value in (f.value, f.name)), None)
            if format is None:
                raise ValueError(f"unknown format {value!r}")
            data_type = field.encryption.plaintextType if field.encryption is not None else data_type
            if data_type is not None and not format_accepts_type(format, data_type):
                raise ValueError(f"format {format.value} is not applicable to {data_type}")
            return field.model_copy(
                update={"format": format, "params": field.params if format == field.format else None}
            )
        case "visible":
            return field.model_copy(update={"visible": TypeAdapter(VisibilityRule).validate_python(decoded(value))})
        case "mustMatch" | "ifNotIn":
            condition = InputVisibilityConditions.model_validate({tag: decoded(value)}, strict=False)
            return field.model_copy(update={"visible": condition})
    return field


def apply_encryption(
    signature: str, nodes: Nodes, actions: list[tuple[str, str, str]], warnings: list[str]
) -> list[tuple[str, str, str]]:
    # Resolve encryption as one annotation before checking formatter applicability.
    # Later scopes override individual properties, regardless of tag order.
    encryption_updates: dict[int, dict[str, str]] = {}
    for tag, name, value in actions:
        if tag not in ENCRYPTION_TAGS:
            continue
        matches = _matches(name, nodes)
        if not matches:
            warnings.append(f"{signature}: {tag} refers to missing parameter {name!r}.")
        for index in matches:
            field, _, _ = nodes[index]
            if isinstance(field, InputFieldDescription):
                encryption_updates.setdefault(index, {})["scheme" if tag == "encryptionScheme" else tag] = value
    for index, update in encryption_updates.items():
        field, path, _ = nodes[index]
        assert isinstance(field, InputFieldDescription)  # nosec B101 - internal invariant, not input validation
        try:
            values = field.encryption.model_dump(exclude_none=True) if field.encryption is not None else {}
            values.update(update)
            if not values.get("scheme", "").strip():
                raise ValueError("encryption requires encryptionScheme")
            encryption = InputEncryptionParameters.model_validate(values)
            updated = field.model_copy(update={"encryption": encryption})
            replace_field(nodes, index, updated)
        except (ValueError, ParseError) as exc:
            warnings.append(f"{signature}: ignoring encryption for {_name(path)}: {exc}")
    return [action for action in actions if action[0] not in ENCRYPTION_TAGS]


def apply_field_actions(
    signature: str, tree: SchemaTree, nodes: Nodes, actions: list[tuple[str, str, str]], warnings: list[str]
) -> tuple[list[DataPath | ContainerPath], dict[tuple[str, str], list[DataPath | ContainerPath]]]:
    """Apply field annotations and validate parameters after combining scopes."""
    excluded: list[DataPath | ContainerPath] = []
    applied_formats: dict[tuple[str, str], list[DataPath | ContainerPath]] = {}
    parameter_values = {
        i: field.params.model_dump(by_alias=True, exclude_none=True) if field.params is not None else {}
        for i, (field, _, _) in enumerate(nodes)
        if isinstance(field, InputFieldDescription)
    }
    authored_parameters: dict[int, set[str]] = {i: set() for i in parameter_values}
    for tag, name, value in actions:
        matches = _matches(name, nodes)
        if not matches:
            warnings.append(f"{signature}: {tag} refers to missing parameter {name!r}.")
        for index in matches:
            field, path, _ = nodes[index]
            if tag == "exclude":
                if path not in excluded:
                    excluded.append(path)
                continue
            if not isinstance(field, InputFieldDescription):
                continue
            try:
                if tag == "separator" and (
                    not isinstance(path, DataPath)
                    or not path.elements
                    or not isinstance(path.elements[-1], Array | ArraySlice)
                ):
                    raise ValueError("separator requires an array field")
                if tag in PARAMETER_TAGS:
                    name_, parsed = parameter_update(field.format, tag, value)
                    merge_parameter(parameter_values[index], name_, parsed)
                    authored_parameters[index].add(name_)
                    continue
                updated = _field_update(field, tag, value, _node_type(tree, path))
                if tag == "format":
                    if updated.format != field.format:
                        parameter_values[index] = {}
                        authored_parameters[index].clear()
                    if updated.format == FieldFormat.ADDRESS_NAME and "types" not in authored_parameters[index]:
                        parameter_values[index].pop("types", None)
            except ValueError as exc:
                warnings.append(f"{signature}: ignoring {tag} for {name}: {exc}")
                continue
            replace_field(nodes, index, updated)
            if tag == "format":
                applied_formats.setdefault((name, value), []).append(path)
    # Validate complete parameter models after combining scopes, so required
    # settings may be supplied separately (e.g. project decimals + method base).
    for index, values in parameter_values.items():
        field, path, _ = nodes[index]
        assert isinstance(field, InputFieldDescription)  # nosec B101 - internal invariant, not input validation
        try:
            raw = field.model_dump(by_alias=True, exclude_none=True)
            raw["params"] = values or None
            updated = InputFieldDescription.model_validate(raw, strict=False)
        except ValueError as exc:
            warnings.append(f"{signature}: ignoring parameters for {_name(path)}: {exc}")
            continue
        replace_field(nodes, index, updated)
    return excluded, applied_formats


def validated_tags(tags: dict[str, str], scope: str, warnings: list[str]) -> dict[str, str]:
    """Discard malformed assignment tags before any of their actions are applied."""
    tags = dict(tags)
    for tag in (*DEFAULT_TAGS, "label"):
        if tag not in tags:
            continue
        try:
            parse_pairs(tags[tag], _tag_name(tag))
        except ValueError as exc:
            warnings.append(f"{scope}: ignoring {tag}: {exc}")
            del tags[tag]
    return tags
