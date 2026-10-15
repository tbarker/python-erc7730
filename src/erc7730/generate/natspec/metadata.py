"""Contract-level metadata annotations, with explicit generation inputs taking precedence."""

from typing import Any

from erc7730.generate.natspec import NatSpec
from erc7730.generate.natspec.assignments import define_entry
from erc7730.generate.natspec.documents import custom_tag
from erc7730.generate.natspec.syntax import decoded, parse_declarations, parse_map_target, parse_pairs
from erc7730.model.input.v2.metadata import InputMapDefinition, InputMetadata, InputOwnerInfo
from erc7730.model.types import ScalarType

_MISSING = object()

METADATA_TAGS = ("owner", "url", "constant")


def _tags(doc: dict[str, Any]) -> dict[str, str]:
    result = {}
    for tag in METADATA_TAGS:
        key = f"clearsig-{tag}"
        value = custom_tag(doc, key, _MISSING)
        if value is _MISSING:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{key} must be a nonempty string")
        result[tag] = value.strip()
    return result


def _constants(text: str) -> dict[str, ScalarType | None]:
    result: dict[str, ScalarType | None] = {}
    for (name,), value in parse_declarations(text, "constant"):
        try:
            checked = InputMetadata(constants={name: value}).constants
        except ValueError as exc:
            raise ValueError(f"clearsig-constant {name} requires a valid JSON scalar: {exc}") from exc
        assert checked is not None  # nosec B101 - validated nonempty constants mapping
        define_entry(result, name, checked[name], f"clearsig-constant definition for {name}")
    return result


def apply_metadata_annotations(docs: NatSpec, metadata: InputMetadata) -> InputMetadata:
    """Read contract docs before method selection, rejecting misplaced metadata tags."""
    if _tags(docs.project_defaults):
        raise ValueError("clearsig-owner, clearsig-url and clearsig-constant must be declared at contract scope")
    owner = None
    info = None
    constants: dict[str, ScalarType | None] = {}
    for root in (docs.userdoc, docs.devdoc):
        for signature, method in root.get("methods", {}).items():
            if _tags(method):
                raise ValueError(f"{signature}: metadata annotations must be declared at contract scope")
        tags = _tags(root)
        if "owner" in tags:
            owner = tags["owner"]
        if "url" in tags:
            try:
                info = InputOwnerInfo.model_validate({"url": tags["url"]}, strict=False)
            except ValueError as exc:
                raise ValueError(f"clearsig-url requires a valid HTTP(S) URL: {exc}") from exc
        if "constant" in tags:
            constants.update(_constants(tags["constant"]))
    metadata = metadata.model_copy(
        update={
            "owner": metadata.owner if metadata.owner is not None else owner,
            "info": metadata.info if metadata.info is not None else info,
            "constants": (constants | (metadata.constants or {})) if constants else metadata.constants,
        }
    )
    maps = dict(metadata.maps or {})
    project_maps = docs.project_defaults.get("maps", {})
    if not isinstance(project_maps, dict):
        raise ValueError("generate.maps must be a table of map definitions")
    for name, definition in project_maps.items():
        maps[name] = InputMapDefinition.model_validate(definition, strict=False)
    for root in (docs.userdoc, docs.devdoc):
        declarations = custom_tag(root, "clearsig-map", "")
        if not isinstance(declarations, str):
            raise ValueError("clearsig-map declarations must be strings")
        for target, value in parse_pairs(declarations, "clearsig-map"):
            name, key = parse_map_target(target)
            parsed = decoded(value)
            definition = maps.get(name, InputMapDefinition(values={key: parsed}))
            maps[name] = definition.model_copy(update={"values": definition.values | {key: parsed}})
    if maps:
        metadata = metadata.model_copy(update={"maps": maps})
    if metadata.owner is None:
        owner = next(
            (
                author
                for key in ("author", "title")
                if isinstance(author := docs.devdoc.get(key), str) and author.strip()
            ),
            None,
        )
        if owner is not None:
            metadata = metadata.model_copy(update={"owner": owner})
    if metadata.contractName is None and isinstance(title := docs.devdoc.get("title"), str) and title.strip():
        metadata = metadata.model_copy(update={"contractName": title})
    return metadata
