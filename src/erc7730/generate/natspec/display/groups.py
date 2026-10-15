"""Presentation groups over existing generated fields."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from operator import itemgetter
from typing import Any

from pydantic import BaseModel

from erc7730.generate.natspec.display.fields import Nodes
from erc7730.generate.natspec.syntax import GroupDeclaration, parse_group_declarations
from erc7730.model.input.v2.display import InputField, InputFieldDescription, InputFieldGroup
from erc7730.model.input.v2.format import FieldFormat, VisibilityRule
from erc7730.model.paths import Array, ContainerPath, DataPath
from erc7730.model.paths.path_ops import data_path_concat, data_path_starts_with


def parse_groups(text: str) -> list[GroupDeclaration]:
    """Parse declarations separated by semicolons, including solc-concatenated tags."""
    groups = parse_group_declarations(text)
    names: set[str] = set()
    for declaration in groups:
        name, label, members = declaration.name, declaration.label, declaration.members
        if name in names:
            raise ValueError(f"duplicate group identifier {name!r}")
        if (label is not None and not label.strip()) or not members or not all(members):
            raise ValueError(f"group {name!r} requires a nonempty member list and, when supplied, a nonempty label")
        names.add(name)
    return groups


def _absolute(value: Any, prefix: DataPath) -> Any:
    """Rebase typed path references, including formatter parameters and map keys."""
    if isinstance(value, DataPath):
        return data_path_concat(prefix, value)
    if isinstance(value, BaseModel):
        return value.model_copy(
            update={key: _absolute(getattr(value, key), prefix) for key in type(value).model_fields}
        )
    if isinstance(value, list):
        return [_absolute(item, prefix) for item in value]
    if isinstance(value, dict):
        return {key: _absolute(item, prefix) for key, item in value.items()}
    return value


def apply_groups(
    fields: list[InputField],
    text: str,
    nodes: Nodes,
    match_names: Callable[[str, Nodes], list[int]],
) -> list[InputField]:
    """Create flat, root-level groups; validate every membership before editing."""
    selections, used = _select_group_members(text, nodes, match_names)

    replacements: dict[int, list[InputFieldGroup]] = defaultdict(list)
    for group, selected in sorted(selections, key=lambda item: min(item[1])):
        children: list[InputField] = []
        positions = []
        for index in selected:
            field, path, _ = nodes[index]
            assert isinstance(field, InputFieldDescription)  # nosec B101 - internal invariant, not input validation
            if isinstance(path, DataPath):
                assert isinstance(field.path, DataPath)  # nosec B101 - internal invariant, not input validation
                prefix = DataPath(absolute=True, elements=path.elements[: -len(field.path.elements)])
                children.append(_absolute(field, prefix))
            else:
                children.append(field)
            positions.append(
                next(
                    i
                    for i, root in enumerate(fields)
                    if root.path == path
                    or (
                        isinstance(root.path, DataPath)
                        and isinstance(path, DataPath)
                        and data_path_starts_with(path, root.path)
                    )
                )
            )
        replacements[min(positions)].append(
            InputFieldGroup(label=group.label, iteration=group.iteration, fields=children)
        )
    removed = {id(nodes[i][0]) for i in used}

    result: list[InputField] = []
    for i, field in enumerate(fields):
        result.extend(replacements.get(i, []))
        if (retained := _retain_field(field, removed)) is not None:
            result.append(retained)
    return result


def _select_group_members(
    text: str, nodes: Nodes, match_names: Callable[[str, Nodes], list[int]]
) -> tuple[list[tuple[GroupDeclaration, list[int]]], set[int]]:
    """Resolve memberships in declaration order before changing the tree."""
    selections: list[tuple[GroupDeclaration, list[int]]] = []
    used: set[int] = set()
    for group in parse_groups(text):
        selected = []
        for member in group.members:
            matches = match_names(member, nodes)
            if len(matches) != 1:
                raise ValueError(f"group {group.name!r}: member {member!r} is missing or ambiguous")
            index = matches[0]
            field, path, _ = nodes[index]
            indices = (
                [
                    i
                    for i, (leaf, child, _) in enumerate(nodes)
                    if isinstance(leaf, InputFieldDescription)
                    and isinstance(child, DataPath)
                    and isinstance(path, DataPath)
                    and data_path_starts_with(child, path)
                ]
                if isinstance(field, InputFieldGroup)
                else [index]
            )
            for i in indices:
                if i in used:
                    raise ValueError(f"group {group.name!r}: duplicate membership for {member!r}")
                leaf = nodes[i][0]
                if not isinstance(leaf, InputFieldDescription) or leaf.visible == VisibilityRule.NEVER:
                    raise ValueError(f"group {group.name!r}: {member!r} is not a displayed leaf")
                used.add(i)
                selected.append(i)
        if not selected:
            raise ValueError(f"group {group.name!r} has no displayed leaves")
        if group.iteration is not None and not any(
            isinstance(path, DataPath) and any(isinstance(element, Array) for element in path.elements)
            for _, path, _ in (nodes[i] for i in selected)
        ):
            raise ValueError(f"group {group.name!r}: iteration requires an array member")
        selections.append((group, selected))

    return selections, used


def _retain_field(field: InputField, removed: set[int]) -> InputField | None:
    """Remove selected leaves and groups left without children."""
    if id(field) in removed:
        return None
    if isinstance(field, InputFieldGroup):
        children = [retained for child in field.fields if (retained := _retain_field(child, removed)) is not None]
        return field.model_copy(update={"fields": children}) if children else None
    return field


def flatten_struct_groups(
    fields: list[InputField], prefix: DataPath | None = None, *, lifted: bool = False
) -> list[InputField]:
    """Remove unlabeled scalar wrappers without changing array iteration or paths.

    Rebase moved leaves and their formatter references together. Real array and
    named groups retain their scope; untouched children can keep relative paths.
    """
    from erc7730.model.paths import ArrayElement, Field

    prefix = prefix if prefix is not None else DataPath(absolute=True, elements=[])
    result: list[InputField] = []
    for field in fields:
        if not isinstance(field, InputFieldGroup):
            result.append(_absolute(field, prefix) if lifted else field)
            continue
        path = data_path_concat(prefix, field.path) if isinstance(field.path, DataPath) else prefix
        scalar = (
            isinstance(field.path, DataPath)
            and bool(path.elements)
            and isinstance(path.elements[-1], Field | ArrayElement)
            and field.label is None
            and field.iteration is None
        )
        children = flatten_struct_groups(field.fields, path, lifted=scalar)
        if scalar:
            result.extend(children)
        else:
            result.append(field.model_copy(update={"path": path if lifted else field.path, "fields": children}))
    return result


def _order_fields(
    fields: list[InputField], parent: DataPath, order: list[DataPath | ContainerPath]
) -> list[InputField]:
    """Order siblings by their first named leaf without breaking up groups."""
    ranked: list[tuple[int, InputField]] = []
    for field in fields:
        rank = len(order)
        if isinstance(field.path, DataPath):
            path = DataPath(absolute=True, elements=[*parent.elements, *field.path.elements])
            rank = next(
                (
                    i
                    for i, named in enumerate(order)
                    if isinstance(named, DataPath) and data_path_starts_with(named, path)
                ),
                rank,
            )
            if isinstance(field, InputFieldGroup):
                field = field.model_copy(update={"fields": _order_fields(field.fields, path, order)})
        elif isinstance(field.path, ContainerPath):
            rank = next((i for i, named in enumerate(order) if named == field.path), rank)
        ranked.append((rank, field))
    return [field for _, field in sorted(ranked, key=itemgetter(0))]


def _hide_excluded(
    fields: list[InputField], parent: DataPath, excluded: list[DataPath | ContainerPath]
) -> list[InputField]:
    result: list[InputField] = []
    for field in fields:
        path = (
            DataPath(absolute=True, elements=[*parent.elements, *field.path.elements])
            if isinstance(field.path, DataPath)
            else parent
        )
        if isinstance(field, InputFieldGroup):
            field = field.model_copy(update={"fields": _hide_excluded(field.fields, path, excluded)})
        elif any(
            field.path == prefix
            if isinstance(prefix, ContainerPath)
            else isinstance(field.path, DataPath) and data_path_starts_with(path, prefix)
            for prefix in excluded
        ):
            field = InputFieldDescription(path=field.path, format=FieldFormat.RAW, visible=VisibilityRule.NEVER)
        result.append(field)
    return result
