"""Annotation grammar compatibility and complete-input diagnostics."""

import json
from collections.abc import Callable
from typing import Any, Literal

import pytest

from erc7730.generate.natspec.display.annotations import validated_tags
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.generate.natspec.syntax import (
    parse_declarations,
    parse_group_declarations,
    parse_map_expression,
    parse_map_target,
    parse_pairs,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("", []),
        ("a=https://example.org/?x=y&z=2 b=raw", [("a", "https://example.org/?x=y&z=2"), ("b", "raw")]),
        (" \n ", []),
        ("a=Hello world, b=Second label", [("a", "Hello world"), ("b", "Second label")]),
        ("a=Hello, world\na=Again,", [("a", "Hello, world"), ("a", "Again")]),
        ('a="Say \\"hi\\", b=unchanged" b=raw', [("a", '"Say \\"hi\\", b=unchanged"'), ("b", "raw")]),
        ('a={"x": ["b=c", {"nested": true}]} b=[1, 2]', [("a", '{"x": ["b=c", {"nested": true}]}'), ("b", "[1, 2]")]),
        (
            "x=map(tokens, #.calls.[].token) y=chainId:chains(#.id)",
            [("x", "map(tokens, #.calls.[].token)"), ("y", "chainId:chains(#.id)")],
        ),
        ("@.value=amount #.calls.[].value=raw", [("@.value", "amount"), ("#.calls.[].value", "raw")]),
        ("x=[] y={} z=fn(a, inner(b))", [("x", "[]"), ("y", "{}"), ("z", "fn(a, inner(b))")]),
        (", a=1,, b=2,", [("a", "1"), ("b", "2")]),
    ],
)
def test_pairs_preserve_raw_values(text: str, expected: list[tuple[str, str]]) -> None:
    assert parse_pairs(text) == expected


@pytest.mark.parametrize(
    "text",
    ["garbage a=1", "=1", "a=", "a=, b=2", 'a="unterminated', "a=[1", "a={1]", "a=fn(x", 'a="valid" b=', "a=1 )"],
)
def test_pairs_reject_complete_malformed_tag(text: str) -> None:
    with pytest.raises(ValueError, match=r"clearsig-label syntax at line .*column"):
        parse_pairs(text, "clearsig-label")


def test_declarations_preserve_types_and_duplicates() -> None:
    values = {
        "text": 'a=b, "quoted"',
        "integer": 2,
        "float": 1.25,
        "boolean": True,
        "none": None,
        "array": [],
        "object": {"a": [1, False]},
    }
    text = "\n".join(f"{key}={json.dumps(value)}" for key, value in values.items())
    assert parse_declarations(text + ",integer=3,", "constant") == [
        ((key,), value) for key, value in values.items()
    ] + [(("integer",), 3)]
    assert parse_declarations("", "constant") == []
    assert parse_declarations('mode[00]="A" calls.[].mode[1]="B" orders.[0].mode[2]="C",', "enum") == [
        (("mode", "00"), "A"),
        (("calls.[].mode", "1"), "B"),
        (("orders.[0].mode", "2"), "C"),
    ]


@pytest.mark.parametrize(
    "kind,text",
    [
        ("constant", "a=1b=2"),
        ("constant", 'a="x"garbage'),
        ("constant", 'a="\\q"'),
        ("constant", "a={bad}"),
        ("constant", "a=[1,]"),
        ("enum", 'mode[-1]="A"'),
        ("enum", 'mode[0]="A"mode[1]="B"'),
    ],
)
def test_bad_declarations_report_context(kind: Literal["constant", "enum"], text: str) -> None:
    with pytest.raises(ValueError, match=rf"clearsig-{kind}.*line .*column"):
        parse_declarations(text, kind)


def test_groups_and_map_expressions() -> None:
    groups = parse_group_declarations('; g="A, B" fields=(a,b) iteration=bundled;\nh fields=(#.calls.[].value)')
    assert (groups[0].name, groups[0].label, groups[0].members, groups[0].iteration) == (
        "g",
        "A, B",
        ["a", "b"],
        "bundled",
    )
    assert (groups[1].label, groups[1].iteration) == (None, None)
    assert parse_group_declarations("") == []
    assert parse_map_target("tokens[0x123]") == ("tokens", "0x123")
    assert parse_map_expression("map(tokens, #.calls.[].token)") == ("token", "tokens", "#.calls.[].token")
    assert parse_map_expression("chainId:chains(#.network)", reference=True) == ("chainId", "chains", "#.network")


@pytest.mark.parametrize(
    "text",
    [
        "g fields=(a)h fields=(b)",
        "g fields=(a) garbage",
        "g fields=(a",
        'g="unterminated fields=(a)',
        'g="\\q" fields=(a)',
    ],
)
def test_invalid_groups(text: str) -> None:
    with pytest.raises(ValueError, match=r"clearsig-group.*line .*column"):
        parse_group_declarations(text)


@pytest.mark.parametrize("text", ["tokens", "tokens[]", "tokens[x][y]", "tokens[x]garbage"])
def test_invalid_map_targets(text: str) -> None:
    with pytest.raises(ValueError, match="clearsig-map syntax at line"):
        parse_map_target(text)


@pytest.mark.parametrize(
    "text,reference",
    [("map(tokens,)", False), ("map(tokens, x))", False), ("chains(x)", True), ("chainId:chains()", True)],
)
def test_invalid_map_expressions(text: str, reference: bool) -> None:
    with pytest.raises(ValueError, match=r"clearsig-.*syntax at line"):
        parse_map_expression(text, reference=reference)


def test_tag_validation_is_atomic_and_keeps_other_tags() -> None:
    tags = {"label": 'a=Updated b="unterminated', "format": "a=raw", "intent": "Send"}
    warnings: list[str] = []
    assert validated_tags(tags, "f(uint256)", warnings) == {"format": "a=raw", "intent": "Send"}
    assert "label" in tags
    assert len(warnings) == 1
    assert "f(uint256): ignoring label: clearsig-label syntax at line" in warnings[0]


@pytest.mark.parametrize("scope", ["project", "contract", "method"])
def test_generation_does_not_partially_apply_malformed_formats(scope: str) -> None:
    tags = {"custom:clearsig-format": '@.value=amount a=raw b="unterminated'}
    kwargs: dict[str, Any]
    if scope == "project":
        kwargs = {"project_defaults": tags}
    elif scope == "contract":
        kwargs = {"devdoc": tags}
    else:
        kwargs = {"devdoc": {"methods": {"f(uint256)": tags}}}
    abi = [{"name": "f", "type": "function", "inputs": [{"name": "a", "type": "uint256"}]}]
    warnings: list[str] = []
    result = generate_natspec_descriptor(1, "0x" + "11" * 20, abi=json.dumps(abi), warnings=warnings, **kwargs)
    baseline = generate_natspec_descriptor(1, "0x" + "11" * 20, abi=json.dumps(abi))
    assert result.display == baseline.display
    assert len(warnings) == 1
    assert "clearsig-format syntax at line" in warnings[0]


@pytest.mark.parametrize(
    "parse,text,line,column,context",
    [
        (lambda text: parse_declarations(text, "enum"), "mode[0]=", 1, 9, "mode[0]=\n        ^"),
        (lambda text: parse_declarations(text, "enum"), 'mode[0]="A"\nmode[1]=  ', 2, 11, "mode[1]=  \n          ^"),
        (lambda text: parse_declarations(text, "enum"), "mode[0]=\n", 2, 1, "\n^"),
        (lambda text: parse_declarations(text, "constant"), "x=", 1, 3, "x=\n  ^"),
        (parse_pairs, "x=[1\n  ", 2, 3, "  \n  ^"),
        (parse_group_declarations, "g fields=(a", 1, 12, "g fields=(a\n           ^"),
        (parse_map_target, "tokens[x", 1, 9, "tokens[x\n        ^"),
        (parse_map_expression, "map(tokens, x", 1, 14, "map(tokens, x\n             ^"),
    ],
)
def test_eof_locations_point_after_the_last_character(
    parse: Callable[[str], object], text: str, line: int, column: int, context: str
) -> None:
    with pytest.raises(ValueError) as error:
        parse(text)
    assert f"syntax at line {line}, column {column}: {context}" in str(error.value)


@pytest.mark.parametrize("separator", [" ", ",", ", ", "\n", "\r\n", "\t"])
@pytest.mark.parametrize("label", ["plain", "comma, name=value", 'quote " and slash \\', "line\nbreak", "Unicode é 🚀"])
@pytest.mark.parametrize("path", ["mode", "order.mode", "calls.[].mode", "orders.[0].calls.[].mode"])
def test_generated_quoted_assignments_and_enums(separator: str, label: str, path: str) -> None:
    quoted = json.dumps(label, ensure_ascii=False)
    assert parse_pairs(f"{path}={quoted}{separator}other=raw,") == [(path, quoted), ("other", "raw")]
    assert parse_declarations(f'{path}[0]={quoted}{separator}{path}[1]="Other",', "enum") == [
        ((path, "0"), label),
        ((path, "1"), "Other"),
    ]
    assert parse_declarations(f"label={quoted}{separator}count=2,", "constant") == [
        (("label",), label),
        (("count",), 2),
    ]


@pytest.mark.parametrize("separator", [" ", ", ", "\n"])
@pytest.mark.parametrize("depth", [1, 2, 4])
@pytest.mark.parametrize("label", ["x=y, z=w", '"quoted"', "backslash\\"])
def test_generated_nested_values(separator: str, depth: int, label: str) -> None:
    value: object = label
    for _ in range(depth):
        value = {"items": [value, {"literal": "other=ignored"}]}
    raw = json.dumps(value)
    assert parse_pairs(f"data={raw}{separator}other=raw") == [("data", raw), ("other", "raw")]
    assert parse_declarations(f"data={raw}{separator}other=null", "constant") == [
        (("data",), value),
        (("other",), None),
    ]


@pytest.mark.parametrize("separator", [" ", ",", "\n"])
@pytest.mark.parametrize("ending", ['"unterminated', "[1", '{"a": [1]', "map(tokens, #.calls.[].token", ""])
def test_generated_malformed_endings_skip_whole_tag(separator: str, ending: str) -> None:
    text = f"first=raw{separator}second={ending}"
    with pytest.raises(ValueError, match=r"syntax at line [1-9][0-9]*, column [1-9][0-9]*"):
        parse_pairs(text)
    warnings: list[str] = []
    assert validated_tags({"format": text, "label": "first=Unchanged"}, "method", warnings) == {
        "label": "first=Unchanged"
    }
    assert len(warnings) == 1
