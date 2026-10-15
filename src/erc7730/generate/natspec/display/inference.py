"""Generate inline enum definitions and infer calldata amount formats."""

from __future__ import annotations

import hashlib

from pydantic import TypeAdapter

from erc7730.common.schema_types import format_accepts_type
from erc7730.generate.natspec.assignments import define_entry
from erc7730.generate.natspec.display.annotations import _field_update
from erc7730.generate.natspec.display.fields import Nodes, _matches, _name, _node_type, _walk
from erc7730.generate.natspec.syntax import parse_declarations, parse_pairs
from erc7730.generate.schema_tree import SchemaTree
from erc7730.model.input.v2.display import (
    InputCallDataParameters,
    InputField,
    InputFieldDescription,
    InputFieldGroup,
)
from erc7730.model.input.v2.format import FieldFormat
from erc7730.model.input.v2.metadata import InputMetadata
from erc7730.model.metadata import EnumDefinition
from erc7730.model.paths import ContainerPath, DataPath
from erc7730.model.paths.path_ops import data_path_concat


def _inline_enums(
    signature: str, tags: dict[str, str], nodes: Nodes, tree: SchemaTree, metadata: InputMetadata
) -> tuple[InputMetadata, list[tuple[str, str, str]]]:
    """Bind method-local labels to leaves without inferring Solidity enum members."""
    declarations = tags.get("enum", "").strip()
    if not declarations:
        return metadata, []
    definitions: dict[int, dict[str, str]] = {}
    for (name, ordinal), label in parse_declarations(declarations, "enum"):
        if not isinstance(label, str) or not label.strip():
            raise ValueError("enum labels must be nonempty JSON strings")
        matches = _matches(name, nodes)
        if len(matches) != 1:
            raise ValueError(f"enum target {name!r} must match exactly one field")
        index = matches[0]
        field, path, _ = nodes[index]
        if not isinstance(field, InputFieldDescription):
            raise ValueError(f"enum target {name!r} must be a leaf field")
        _field_update(field, "format", "enum", _node_type(tree, path))
        if int(ordinal) >= 2**256:
            raise ValueError("enum ordinal must fit uint256")
        ordinal = str(int(ordinal))
        entries = definitions.setdefault(index, {})
        define_entry(entries, ordinal, label, f"enum labels for {name}[{ordinal}]")

    enums = dict(metadata.enums or {})
    actions: list[tuple[str, str, str]] = []
    for index, entries in definitions.items():
        _, path, _ = nodes[index]
        for tag in ("format", "enumRef"):
            for name, value in parse_pairs(tags.get(tag, "")):
                if index in _matches(name, nodes) and (
                    tag == "enumRef" or value not in (FieldFormat.ENUM.value, FieldFormat.ENUM.name)
                ):
                    raise ValueError(f"inline enum conflicts with {tag} for {name}")
        # Full signature and canonical path distinguish overloads and nested fields.
        enum_id = "enum_" + hashlib.sha256(f"{signature}:{path}".encode()).hexdigest()
        definition = TypeAdapter(EnumDefinition).validate_python(entries)
        if enum_id in enums and enums[enum_id] != definition:
            raise ValueError(f"generated enum conflicts with metadata entry {enum_id}")
        enums[enum_id] = definition
        actions.extend(
            (("format", _name(path), FieldFormat.ENUM.value), ("enumRef", _name(path), f"$.metadata.enums.{enum_id}"))
        )
    return InputMetadata.model_validate(metadata.model_dump(by_alias=True) | {"enums": enums}), actions


def _infer_calldata_amounts(
    fields: list[InputField], tree: SchemaTree, explicit_formats: list[DataPath | ContainerPath]
) -> None:
    """Infer native amounts from final calldata bindings without changing authored formats."""
    targets: list[DataPath | ContainerPath] = []

    def collect(fields: list[InputField], parent: DataPath) -> None:
        for field in fields:
            if isinstance(field, InputFieldGroup):
                prefix = data_path_concat(parent, field.path) if isinstance(field.path, DataPath) else parent
                collect(field.fields, prefix)
            elif (
                isinstance(field, InputFieldDescription)
                and field.format == FieldFormat.CALL_DATA
                and isinstance(field.params, InputCallDataParameters)
            ):
                match field.params.amountPath:
                    case DataPath() as path:
                        targets.append(data_path_concat(parent, path))
                    case ContainerPath() as path:
                        targets.append(path)

    collect(fields, DataPath(absolute=True, elements=[]))
    for field, path, siblings in _walk(fields, DataPath(absolute=True, elements=[])):
        if (
            isinstance(field, InputFieldDescription)
            and path in targets
            and path not in explicit_formats
            and (data_type := _node_type(tree, path)) is not None
            and format_accepts_type(FieldFormat.AMOUNT, data_type)
        ):
            siblings[siblings.index(field)] = _field_update(field, "format", "amount", data_type)
