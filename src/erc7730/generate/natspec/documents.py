"""Load and normalize compiler NatSpec JSON documents."""

import json
from dataclasses import dataclass, field
from typing import Any

from lark.exceptions import LarkError

from erc7730.common.abi import reduce_signature

JSONInput = str | bytes | dict[str, Any] | None


@dataclass
class NatSpec:
    userdoc: dict[str, Any] = field(default_factory=dict)
    devdoc: dict[str, Any] = field(default_factory=dict)
    project_defaults: dict[str, Any] = field(default_factory=dict)
    abi: list[Any] | None = None
    warnings: list[str] = field(default_factory=list)
    _present: set[str] = field(default_factory=set, repr=False)


def _object(value: Any, warnings: list[str]) -> dict[Any, Any]:
    # Library callers can supply malformed dictionaries, including non-string keys.
    # Keep keys untrusted until the method index validates them.
    if value is None:
        return {}
    if isinstance(value, str | bytes):
        try:
            value = json.loads(value)
        except (ValueError, UnicodeError):
            warnings.append("Ignoring invalid NatSpec JSON.")
            return {}
    if not isinstance(value, dict):
        warnings.append("Ignoring NatSpec value: expected a JSON object.")
        return {}
    return value


def _extract(value: dict[str, Any], docs: NatSpec) -> None:
    # Embedded metadata can itself be a JSON string. Top-level docs take precedence.
    if "metadata" in value:
        _extract(_object(value["metadata"], docs.warnings), docs)
    if "output" in value:
        _extract(_object(value["output"], docs.warnings), docs)
    if isinstance(value.get("abi"), list):
        docs.abi = value["abi"]
    for name in ("userdoc", "devdoc"):
        if name in value:
            docs._present.add(name)
            setattr(docs, name, _object(value[name], docs.warnings))
    if value.get("kind") in ("user", "dev"):
        docs._present.add("userdoc" if value["kind"] == "user" else "devdoc")
        setattr(docs, "userdoc" if value["kind"] == "user" else "devdoc", value)


def _index(doc: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    result = dict(doc)
    methods = _object(doc.get("methods"), warnings)
    indexed: dict[str, Any] = {}
    for key, value in methods.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            warnings.append("Ignoring malformed NatSpec method.")
            continue
        canonical = key
        if "(" in key:
            try:
                canonical = reduce_signature(key)
            except (ValueError, TypeError, LarkError):
                warnings.append(f"Ignoring invalid NatSpec signature: {key}")
                continue
        # Canonical keys win over declaration aliases regardless of insertion order.
        if canonical not in indexed or canonical == key:
            indexed[canonical] = value
    result["methods"] = indexed
    return result


def parse_natspec(
    natspec: JSONInput = None,
    userdoc: JSONInput = None,
    devdoc: JSONInput = None,
    project_defaults: JSONInput = None,
) -> NatSpec:
    """Accept raw docs, paired docs or an artifact, collecting best-effort diagnostics.

    A full pair plus split inputs is an ambiguous invocation and raises ValueError.
    Malformed/incomplete documentation itself is ignored with warnings.
    """
    docs = NatSpec()
    docs.project_defaults = _object(project_defaults, docs.warnings)
    _extract(_object(natspec, docs.warnings), docs)
    if docs._present == {"userdoc", "devdoc"} and (userdoc is not None or devdoc is not None):
        raise ValueError("Cannot combine split userdoc/devdoc with --natspec containing both documents.")
    for name, value in (("userdoc", userdoc), ("devdoc", devdoc)):
        if value is not None:
            existing = getattr(docs, name)
            incoming = _object(value, docs.warnings)
            merged = existing | incoming
            merged["methods"] = _object(existing.get("methods"), docs.warnings) | _object(
                incoming.get("methods"), docs.warnings
            )
            setattr(docs, name, merged)
        setattr(docs, name, _index(getattr(docs, name), docs.warnings))
    return docs


def custom_tag(doc: dict[str, Any], name: str, default: Any = None) -> Any:
    """Read a compiler custom tag, preferring the flat spelling even when null."""
    nested = doc.get("custom", {})
    return doc.get(f"custom:{name}", nested.get(name, default) if isinstance(nested, dict) else default)
