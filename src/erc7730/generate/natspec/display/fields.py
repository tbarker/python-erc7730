"""Traverse schema fields and resolve annotation names and intent references."""

from __future__ import annotations

import re
from collections.abc import Iterator

from erc7730.generate.schema_tree import SchemaArray, SchemaLeaf, SchemaStruct, SchemaTree
from erc7730.model.input.v2.display import (
    InputField,
    InputFieldGroup,
)
from erc7730.model.paths import Array, ArrayElement, ArraySlice, ContainerField, ContainerPath, DataPath, Field
from erc7730.model.paths.path_ops import data_path_concat
from erc7730.model.paths.path_parser import to_path

#: Display nodes with their absolute paths and sibling fields.
Nodes = list[tuple[InputField, DataPath | ContainerPath, list[InputField]]]


def replace_field(nodes: Nodes, index: int, updated: InputField) -> None:
    """Replace a field in both the display tree and its traversal entry."""
    field, path, siblings = nodes[index]
    siblings[siblings.index(field)] = updated
    nodes[index] = updated, path, siblings


def _walk(
    fields: list[InputField], parent: DataPath
) -> Iterator[tuple[InputField, DataPath | ContainerPath, list[InputField]]]:
    for field in fields:
        if isinstance(field, InputFieldGroup) and field.path is None:
            yield from _walk(field.fields, parent)
            continue
        if isinstance(field.path, ContainerPath):
            yield field, field.path, fields
            continue
        if not isinstance(field.path, DataPath):
            continue
        path = data_path_concat(parent, field.path)
        yield field, path, fields
        if isinstance(field, InputFieldGroup):
            yield from _walk(field.fields, path)


def _name(path: DataPath | ContainerPath) -> str:
    if isinstance(path, ContainerPath):
        return str(path)
    return ".".join(element.identifier for element in path.elements if isinstance(element, Field))


def _matches(name: str, nodes: list[tuple[InputField, DataPath | ContainerPath, list[InputField]]]) -> list[int]:
    if name.startswith("@"):
        return [i for i, (_, path, _) in enumerate(nodes) if isinstance(path, ContainerPath) and str(path) == name]
    name = name.removeprefix("#.").removeprefix("$.")
    names = [_name(path) if isinstance(path, DataPath) else "" for _, path, _ in nodes]
    candidates = (names, [name.rsplit(".", 1)[-1] for name in names])
    for normalize in (
        lambda s: s,
        lambda s: ".".join(p.lstrip("_") for p in s.split(".")),
        lambda s: ".".join(p.lstrip("_").lower() for p in s.split(".")),
    ):
        requested = normalize(name)
        for aliases in candidates:
            found = [i for i, candidate in enumerate(aliases) if normalize(candidate) == requested]
            if found:
                return found
    return []


def _node_type(tree: SchemaTree, path: DataPath | ContainerPath) -> str | None:
    if isinstance(path, ContainerPath):
        return "uint256" if path.field in (ContainerField.VALUE, ContainerField.CHAIN_ID) else "address"
    for element in path.elements:
        if isinstance(element, Field) and isinstance(tree, SchemaStruct):
            tree = tree.components[element.identifier]
        elif not isinstance(element, Field) and isinstance(tree, SchemaArray):
            tree = tree.component
        else:
            return None
    return tree.data_type.value if isinstance(tree, SchemaLeaf) else None


def _resolve_reference(
    reference: str, *, nodes: list[tuple[InputField, DataPath | ContainerPath, list[InputField]]]
) -> str:
    # Normalize conventional adjacent subscripts to the descriptor parser's syntax.
    # Parsing paths, rather than evaluating expressions, keeps computed indices out.
    path = to_path(re.sub(r"(?<=[A-Za-z0-9_\]])\[", ".[", reference))
    if not isinstance(path, DataPath):
        return str(path)  # The ordinary intent linter checks container/metadata formatters.
    matches = _matches(_name(path), nodes)
    length = False
    if not matches and path.elements and path.elements[-1] == Field(identifier="length"):
        length = True
        path = path.model_copy(update={"elements": path.elements[:-1]})
        matches = _matches(_name(path), nodes)
    if len(matches) != 1:
        raise ValueError(f"reference {reference!r} is missing, excluded, or ambiguous")
    _, canonical, _ = nodes[matches[0]]
    assert isinstance(canonical, DataPath)  # nosec B101 - internal invariant, not input validation
    # Retain canonical ABI names (including alias matching) and any unmentioned
    # parent groups, substituting only the requested selectors.
    field_count = sum(isinstance(element, Field) for element in path.elements)
    fields = [index for index, element in enumerate(canonical.elements) if isinstance(element, Field)]
    if not field_count or field_count > len(fields):
        raise ValueError(f"unsupported reference {reference!r}")
    start = fields[-field_count]
    elements = list(canonical.elements[:start])
    requested = list(path.elements)
    for element in canonical.elements[start:]:
        if isinstance(element, Field):
            if not requested or not isinstance(requested.pop(0), Field):
                raise ValueError(f"unsupported reference {reference!r}")
            elements.append(element)
        elif requested and isinstance(requested[0], Array | ArrayElement | ArraySlice):
            elements.append(requested.pop(0))
        elif not length or requested:
            elements.append(element)
    if any(isinstance(element, Field) for element in requested):
        raise ValueError(f"unsupported reference {reference!r}")
    elements.extend(requested)
    if length:
        elements.append(Field(identifier="length"))
    return str(DataPath(absolute=False, elements=elements))
