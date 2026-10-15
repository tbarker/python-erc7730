"""Typed parsing helpers shared by clearsig annotation consumers."""

import json
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from typing import Any, Literal

from lark import Lark, Tree, UnexpectedInput
from lark.exceptions import UnexpectedEOF, UnexpectedToken

from erc7730.generate.natspec.syntax.grammar import GRAMMAR
from erc7730.model.input.v2.format import IterationStrategy


def decoded(value: str) -> Any:
    """JSON arrays/objects/scalars, or unquoted strings and path references."""
    try:
        return json.loads(value)
    except ValueError:
        return value


@cache
def _parser(start: str) -> Lark:
    # Enum paths may themselves contain array selectors before the final ordinal.
    # Earley resolves that shared prefix without a regex for the complete path.
    return Lark(
        GRAMMAR,
        start=start,
        parser="earley" if start == "enums" else "lalr",
        propagate_positions=True,
        maybe_placeholders=False,
    )


def _parse(text: str, start: str, tag: str) -> Tree:
    try:
        return _parser(start).parse(text)
    except UnexpectedInput as exc:
        if isinstance(exc, UnexpectedEOF) or (isinstance(exc, UnexpectedToken) and exc.token.type == "$END"):
            # Earley uses -1 for EOF; LALR points at the previous token instead.
            last_line = text.rsplit("\n", 1)[-1]
            line, column = text.count("\n") + 1, len(last_line) + 1
            context = last_line + "\n" + " " * len(last_line) + "^"
        else:
            line, column = exc.line, exc.column
            context = exc.get_context(text).strip()
        raise ValueError(f"{tag} syntax at line {line}, column {column}: {context}") from None


def _separated(text: str, entries: list[Tree], tag: str) -> None:
    for previous, current in pairwise(entries):
        if not text[previous.meta.end_pos : current.meta.start_pos]:
            raise ValueError(
                f"{tag} entries must be separated at line {current.meta.line}, column {current.meta.column}"
            )


def parse_pairs(text: str, tag: str = "clearsig annotation") -> list[tuple[str, str]]:
    """Keep raw values, order, and duplicates; parse the entire tag before returning."""
    tree = _parse(text, "pairs", tag)
    return [
        (str(pair.children[0]), text[pair.children[1].meta.start_pos : pair.children[1].meta.end_pos])
        for pair in tree.children
    ]


def parse_declarations(text: str, kind: Literal["constant", "enum"]) -> list[tuple[tuple[str, ...], Any]]:
    tag = f"clearsig-{kind}"
    tree = _parse(text, kind + "s", tag)
    _separated(text, tree.children, tag)
    result = []
    for entry in tree.children:
        # The grammar validates boundaries; the standard decoder supplies JSON types.
        raw = text[entry.meta.start_pos : entry.meta.end_pos]
        target, value = raw.split("=", 1)
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise ValueError(f"{tag} JSON at line {entry.meta.line}, column {entry.meta.column}: {exc}") from None
        parts: tuple[str, ...] = (target.strip(),)
        if kind == "enum":
            field, ordinal = entry.children[:2]
            parts = (text[field.meta.start_pos : field.meta.end_pos], str(ordinal))
        result.append((parts, parsed))
    return result


@dataclass(frozen=True)
class GroupDeclaration:
    name: str
    label: str | None
    members: list[str]
    iteration: IterationStrategy | None


def parse_group_declarations(text: str) -> list[GroupDeclaration]:
    tree = _parse(text, "groups", "clearsig-group")
    _separated(text, tree.children, "clearsig-group")
    result = []
    for group in tree.children:
        options = {str(child.data): child.children for child in group.children[1:]}
        try:
            label = json.loads(str(options["label"][0])) if "label" in options else None
        except ValueError as exc:
            raise ValueError(
                f"clearsig-group JSON at line {group.meta.line}, column {group.meta.column}: {exc}"
            ) from None
        result.append(
            GroupDeclaration(
                str(group.children[0]),
                label,
                [str(member) for member in options["members"]],
                IterationStrategy(str(options["iteration"][0])) if "iteration" in options else None,
            )
        )
    return result


def parse_map_target(text: str) -> tuple[str, str]:
    tree = _parse(text, "map_target", "clearsig-map")
    return str(tree.children[0]), str(tree.children[1])


def parse_map_expression(text: str, *, reference: bool = False) -> tuple[str, str, str]:
    start, tag = ("map_ref", "clearsig-map-ref") if reference else ("map_expression", "clearsig-token")
    children = [str(child) for child in _parse(text, start, tag).children]
    if reference:
        return children[0], children[1], children[2]
    return "token", children[0], children[1]
