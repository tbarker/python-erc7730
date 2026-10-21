"""Static wallet intents and translation of compiler NatSpec templates."""

from __future__ import annotations

import re
from typing import Any

from erc7730.common.templates import translate_template
from erc7730.generate.natspec.display.fields import Nodes, _resolve_reference, _walk
from erc7730.model.input.v2.display import InputFieldDescription, InputFormat
from erc7730.model.input.v2.format import VisibilityRule
from erc7730.model.paths import DataPath
from erc7730.model.paths.path_parser import to_path

MAX_INTENT_LENGTH = 80
NOTICE_INTENT_LENGTH = 60


def cap_intent(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    cut = value[:limit]
    return cut.rsplit(" ", 1)[0] if " " in cut and not value[limit].isspace() else cut.rstrip()


def is_template(value: str) -> bool:
    return any(character in value for character in "`{}")


def static_intent(custom: str | None, notice: str | None, signature: str, warnings: list[str]) -> str | None:
    """Never strip expressions into misleading literal prose."""
    custom = custom if custom and custom.strip() else None
    notice = notice if notice and notice.strip() else None
    if custom and not is_template(custom):
        if len(custom) > MAX_INTENT_LENGTH:
            warnings.append(f"{signature}: custom intent truncated to {MAX_INTENT_LENGTH} characters.")
        return cap_intent(custom, MAX_INTENT_LENGTH)
    if custom or (notice and "`" in notice):
        return None
    if notice:
        notice = " ".join(notice.split())
        warnings.append(f"{signature}: notice used as intent; review wallet wording.")
        return cap_intent(re.split(r"(?<=[.!?])\s+", notice, maxsplit=1)[0], NOTICE_INTENT_LENGTH)
    return None


def apply_intent_template(
    format: InputFormat,
    tags: dict[str, str],
    notice: Any,
    intent: str | None,
    signature: str,
    warnings: list[str],
    errors: list[str],
) -> InputFormat:
    """Translate intent references after field visibility and exclusions are applied."""
    custom = tags.get("interpolatedIntent", "").strip()
    if tags.get("intent") and is_template(tags["intent"]):
        errors.append(
            f"{signature}: @custom:clearsig-intent must be static; "
            "use @custom:clearsig-interpolated-intent for templates."
        )
    source = custom or notice
    if isinstance(source, str) and (custom or "`" in source):
        visible = [
            node
            for node in _walk(format.fields, DataPath(absolute=True, elements=[]))
            if isinstance(node[0], InputFieldDescription) and node[0].visible in (None, VisibilityRule.ALWAYS)
        ]

        try:

            def resolve(reference: str, explicit: bool = bool(custom), nodes: Nodes = visible) -> str:
                return str(to_path(reference)) if explicit else _resolve_reference(reference, nodes=nodes)

            template = translate_template(
                source,
                resolve,
                natspec=not bool(custom),
                literal_backticks=bool(custom),
            )
        except ValueError as exc:
            errors.append(
                f"{signature}: cannot translate intent template: {exc}. "
                "Add or correct @custom:clearsig-interpolated-intent using {path} references."
            )
        else:
            format = format.model_copy(update={"interpolatedIntent": template})
            warnings.append(f"{signature}: intent template generated; review wording and formatted values.")
            if len(template) > MAX_INTENT_LENGTH:
                warnings.append(
                    f"{signature}: intent template exceeds {MAX_INTENT_LENGTH} characters; "
                    "preserved without truncation."
                )
        if intent is None:
            errors.append(
                f"{signature}: missing static intent. "
                "Add @custom:clearsig-intent with a short, static action description."
            )
    return format
