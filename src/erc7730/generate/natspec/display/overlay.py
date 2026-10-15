"""Apply scoped NatSpec display annotations to generated field trees."""

from __future__ import annotations

from collections import defaultdict

from erc7730.generate.natspec import NatSpec
from erc7730.generate.natspec.display.annotations import (
    DEFAULT_TAGS,
    _exclusions,
    _field_update,
    _tags,
    apply_encryption,
    apply_field_actions,
    validated_tags,
)
from erc7730.generate.natspec.display.fields import _matches, _name, _node_type, _walk
from erc7730.generate.natspec.display.groups import _hide_excluded, _order_fields, apply_groups, flatten_struct_groups
from erc7730.generate.natspec.display.inference import _infer_calldata_amounts, _inline_enums
from erc7730.generate.natspec.display.intent import apply_intent_template, is_template, static_intent
from erc7730.generate.natspec.syntax import parse_pairs
from erc7730.generate.schema_tree import SchemaTree
from erc7730.model.input.v2.display import (
    InputDisplay,
    InputFieldDescription,
    InputFormat,
)
from erc7730.model.input.v2.metadata import InputMetadata
from erc7730.model.paths import ContainerField, ContainerPath, DataPath
from erc7730.model.paths.path_parser import to_path


def apply_natspec(
    display: InputDisplay,
    trees: dict[str, SchemaTree],
    docs: NatSpec,
    metadata: InputMetadata,
    *,
    doc_keys: dict[str, str] | None = None,
) -> tuple[InputDisplay, InputMetadata]:
    """Overlay existing nodes, collecting warnings and enforcing NatSpec lint rules.

    An exclusion naming a missing parameter on a specific method raises ValueError.
    Project/contract exclusions silently skip methods without the named parameter.
    """
    display = display.model_copy(deep=True)
    # Defaults span multiple methods: report a miss only if no method matches.
    scopes = [
        ("project", validated_tags(_tags(docs.project_defaults), "project", docs.warnings)),
        ("contract", validated_tags(_tags(docs.userdoc) | _tags(docs.devdoc), "contract", docs.warnings)),
    ]
    defaults = [
        (scope, tag, name, value)
        for scope, tags in scopes
        for tag in DEFAULT_TAGS
        for name, value in parse_pairs(tags.get(tag, ""))
    ]
    matched_defaults: set[tuple[str, str, str, str]] = set()
    errors: list[str] = [
        f"{scope}: @custom:clearsig-{tag} must be declared on a method."
        for scope, scope_tags in scopes
        for tag in ("group", "enum")
        if scope_tags.get(tag, "").strip()
    ]
    for signature, tree in trees.items():
        format, metadata = _apply_method(
            signature,
            tree,
            display.formats.get(signature),
            docs,
            scopes,
            metadata,
            doc_key=doc_keys.get(signature, signature) if doc_keys is not None else signature,
            typed=doc_keys is not None,
            matched_defaults=matched_defaults,
            errors=errors,
        )
        if format is not None:
            display.formats[signature] = format
    for scope, tag, name, value in defaults:
        if (scope, tag, name, value) not in matched_defaults:
            docs.warnings.append(f"{scope}: {tag} refers to missing parameter {name!r}.")
    if errors:
        raise ValueError("NatSpec lint errors:\n" + "\n".join(errors))
    return display, metadata


def _apply_method(
    signature: str,
    tree: SchemaTree,
    format: InputFormat | None,
    docs: NatSpec,
    scopes: list[tuple[str, dict[str, str]]],
    metadata: InputMetadata,
    *,
    doc_key: str,
    typed: bool,
    matched_defaults: set[tuple[str, str, str, str]],
    errors: list[str],
) -> tuple[InputFormat | None, InputMetadata]:
    user = docs.userdoc.get("methods", {}).get(doc_key, {})
    dev = docs.devdoc.get("methods", {}).get(doc_key, {})
    tags = validated_tags(_tags(user) | _tags(dev), signature, docs.warnings)
    if format is not None:
        _add_container_fields(format, tree, [*(value for _, value in scopes), tags], signature, typed, docs.warnings)
    nodes = list(_walk(format.fields, DataPath(absolute=True, elements=[]))) if format is not None else []
    for scope, scope_tags in [*scopes, ("method", tags)]:
        visibility_tags: dict[int, set[str]] = defaultdict(set)
        for tag in ("visible", "mustMatch", "ifNotIn"):
            for name, _ in parse_pairs(scope_tags.get(tag, "")):
                for index in _matches(name, nodes):
                    visibility_tags[index].add(tag)
        for index, choices in visibility_tags.items():
            if len(choices) > 1:
                errors.append(f"{signature}: conflicting {scope} visibility tags for {_name(nodes[index][1])}.")
    method_exclusions = _exclusions(tags)
    # Validate against the original fields, including methods with no inputs,
    # before any inherited exclusions remove fields from the display.
    for name in method_exclusions:
        if not _matches(name, nodes):
            raise ValueError(f"{signature}: exclude refers to missing parameter {name!r}.")
    if format is None:
        if tags.get("enum", "").strip():
            errors.append(f"{signature}: enum annotation has no fields to bind.")
        return None, metadata
    notice = user.get("notice")
    intent = static_intent(tags.get("intent"), notice if isinstance(notice, str) else None, signature, docs.warnings)
    if intent is not None:
        format = format.model_copy(update={"intent": intent})
    params = dev.get("params", {})
    actions = (
        [("label", name, label) for name, label in params.items() if isinstance(name, str) and isinstance(label, str)]
        if isinstance(params, dict)
        else []
    )
    # A dynamic parameter description cannot be used as a static wallet label.
    label_overrides = {
        index
        for name, label in parse_pairs(tags.get("label", ""))
        if label.strip() and not is_template(label)
        for index in _matches(name, nodes)
    }
    for _, name, label in actions:
        if "`" in label and any(index not in label_overrides for index in _matches(name, nodes)):
            errors.append(
                f"{signature}: @param {name} contains a template. Add @custom:clearsig-label {name}=<static label>."
            )
    actions = [action for action in actions if "`" not in action[2]]
    # Resolve each layer against actual nodes before applying it. This preserves
    # per-field overrides even when one scope uses a different name alias.
    for scope, scope_tags in scopes:
        for tag in DEFAULT_TAGS:
            for name, value in parse_pairs(scope_tags.get(tag, "")):
                if _matches(name, nodes):
                    matched_defaults.add((scope, tag, name, value))
                    actions.append((tag, name, value))
    for tag in (*DEFAULT_TAGS, "label"):
        actions.extend((tag, name, value) for name, value in parse_pairs(tags.get(tag, "")))
    # Exclusions are cumulative and applied last, so display annotations never
    # reintroduce an excluded field. Broad exclusions may have no matches at all.
    actions.extend(
        ("exclude", name, "") for _, scope_tags in scopes for name in _exclusions(scope_tags) if _matches(name, nodes)
    )
    actions.extend(("exclude", name, "") for name in method_exclusions)
    actions = apply_encryption(signature, nodes, actions, docs.warnings)
    try:
        metadata, enum_actions = _inline_enums(signature, tags, nodes, tree, metadata)
        actions.extend(enum_actions)
    except ValueError as exc:
        errors.append(f"{signature}: @custom:clearsig-enum: {exc}.")
    excluded, applied_formats = apply_field_actions(signature, tree, nodes, actions, docs.warnings)
    _infer_calldata_amounts(format.fields, tree, [path for paths in applied_formats.values() for path in paths])
    # A more specific format annotation supplies the complete ordering hint.
    ordering = ""
    for scope_tags in [tags, *(value for _, value in reversed(scopes))]:
        if scope_tags.get("format", "").strip():
            ordering = scope_tags["format"]
            break
    order = [path for pair in parse_pairs(ordering) for path in applied_formats.get(pair, [])]
    root = DataPath(absolute=True, elements=[])
    fields = _order_fields(format.fields, root, order)
    fields = _hide_excluded(fields, root, excluded)
    format = format.model_copy(update={"fields": fields})
    format = apply_intent_template(format, tags, notice, intent, signature, docs.warnings, errors)
    if group_tags := tags.get("group", "").strip():
        try:
            format = format.model_copy(
                update={
                    "fields": apply_groups(
                        format.fields,
                        group_tags,
                        list(_walk(format.fields, DataPath(absolute=True, elements=[]))),
                        _matches,
                    )
                }
            )
        except ValueError as exc:
            errors.append(f"{signature}: @custom:clearsig-group: {exc}.")
    return format.model_copy(update={"fields": flatten_struct_groups(format.fields)}), metadata


def _add_container_fields(
    format: InputFormat,
    tree: SchemaTree,
    scopes: list[dict[str, str]],
    signature: str,
    typed: bool,
    warnings: list[str],
) -> None:
    # Only a valid explicit formatter can introduce a container field.
    for scope_tags in scopes:
        for name, value in parse_pairs(scope_tags.get("format", "")):
            if not name.startswith("@"):
                continue
            try:
                path = to_path(name)
                if not isinstance(path, ContainerPath):
                    raise ValueError("expected a supported container path")
                field = InputFieldDescription(
                    path=path,
                    label={
                        ContainerField.VALUE: "Value",
                        ContainerField.FROM: "From",
                        ContainerField.TO: "To",
                        ContainerField.CHAIN_ID: "Chain ID",
                    }[path.field],
                )
                field = _field_update(field, "format", value, _node_type(tree, path))
                if not any(existing.path == path for existing in format.fields):
                    format.fields.append(field)
                    if typed and path.field == ContainerField.VALUE:
                        warnings.append(
                            f"{signature}: EIP-712 transfers no native currency; @.value may render as zero."
                        )
            except ValueError as exc:
                warnings.append(f"{signature}: ignoring container format for {name}: {exc}")
