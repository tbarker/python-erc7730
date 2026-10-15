"""Use annotated Solidity functions to describe EIP-712 messages.

Compiler NatSpec documents are keyed by function signature, while EIP-712
descriptors describe named message types. A method annotated with
``@custom:clearsig-typed-data Message`` explicitly bridges these representations:
its ABI inputs become the fields of the primary type ``Message``. Tuple inputs
become referenced struct types, using the compiler's ``internalType`` to recover
their names and retaining their array dimensions. The annotation is the author's
declaration of the message shape; the ABI alone cannot establish what a contract
actually hashes or signs.

Generation first selects the annotated methods and builds their schemas, then
copies their documentation under the corresponding primary type names. This lets
the existing display annotations and examples apply to typed messages through
the same generation pipeline. Each schema includes only its reachable structs;
conflicting definitions, unsupported types and recursive structs are rejected.
Signing-domain values are supplied separately from this message-shape bridge.
"""

import json
import re
from collections.abc import Sequence
from copy import deepcopy

from pydantic import TypeAdapter

from erc7730.common.abi import compute_signature
from erc7730.common.solidity_types import is_eip712_primitive
from erc7730.generate.natspec import NatSpec
from erc7730.generate.natspec.documents import custom_tag
from erc7730.model.abi import ABI, Component, Function, InputOutput

_MISSING = object()
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


def bridge_methods(docs: NatSpec) -> dict[str, str]:
    """Validate opt-in declarations, including misplaced and conflicting tags."""
    if any(
        custom_tag(root, "clearsig-typed-data", _MISSING) is not _MISSING
        for root in (docs.userdoc, docs.devdoc, docs.project_defaults)
    ):
        raise ValueError("clearsig-typed-data belongs on a method, not a contract or project.")
    selected: dict[str, str] = {}
    for doc in (docs.userdoc, docs.devdoc):
        for signature, method in doc.get("methods", {}).items():
            value = custom_tag(method, "clearsig-typed-data", _MISSING)
            if value is _MISSING:
                continue
            if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value.strip()):
                raise ValueError(f"{signature}: clearsig-typed-data requires one primary type name.")
            name = value.strip()
            if name == "EIP712Domain":
                raise ValueError("EIP712Domain is reserved for the signing domain.")
            if name in ("address", "bool", "string", "bytes") or re.fullmatch(r"(?:u?int|bytes)\d*", name):
                raise ValueError(f"Primary type name conflicts with an EIP-712 primitive: {name}")
            if signature in selected and selected[signature] != name:
                raise ValueError(f"Conflicting clearsig-typed-data declarations for {signature}.")
            selected[signature] = name
    if len(set(selected.values())) != len(selected):
        raise ValueError("Duplicate clearsig-typed-data primary type names.")
    return selected


def message_docs(docs: NatSpec, selected: dict[str, str]) -> NatSpec:
    """Copy docs and map only selected method entries to their primary types."""
    result = deepcopy(docs)
    for kind in ("userdoc", "devdoc"):
        doc = getattr(result, kind)
        methods = doc.get("methods", {})
        doc["methods"] = {name: methods[sig] for sig, name in selected.items() if sig in methods}
    return result


def infer_schemas(abi: str | bytes | None, selected: dict[str, str]) -> str:
    """Translate compiler tuples, preserving struct names and array dimensions."""
    if abi is None:
        raise ValueError("clearsig-typed-data requires an explicit compiler ABI or artifact ABI.")
    entries = TypeAdapter(list[ABI]).validate_json(abi)
    functions = {compute_signature(entry): entry for entry in entries if isinstance(entry, Function)}
    types: dict[str, list[dict[str, str]]] = {}

    def register(name: str, members: list[dict[str, str]]) -> None:
        if name in types and types[name] != members:
            raise ValueError(f"Conflicting EIP-712 definitions for {name}.")
        types[name] = members

    def fields(parts: Sequence[Component | InputOutput], active: tuple[str, ...]) -> list[dict[str, str]]:
        result = []
        names: set[str] = set()
        for part in parts:
            name = part.name
            if not _IDENTIFIER.fullmatch(name) or name in names:
                raise ValueError("EIP-712 fields require unique, nonempty identifiers.")
            names.add(name)
            match = re.fullmatch(r"([^\[]+)((?:\[(?:[1-9][0-9]*)?\])*)", part.type)
            if match is None:
                raise ValueError(f"Invalid EIP-712 field type: {part.type}")
            base, suffix = match.groups()
            if base == "tuple":
                internal = part.internalType or ""
                if not internal.startswith("struct "):
                    raise ValueError(f"{name}: tuple requires compiler internalType struct name.")
                base = internal.removeprefix("struct ").split("[", 1)[0].split(".")[-1]
                if not _IDENTIFIER.fullmatch(base) or base == "EIP712Domain":
                    raise ValueError(f"Invalid or reserved EIP-712 struct name: {base}")
                if base in active:
                    raise ValueError(f"Recursive EIP-712 struct cannot be expanded: {base}")
                if part.components is None:
                    raise ValueError(f"{name}: tuple requires compiler components.")
                register(base, fields(part.components, (*active, base)))
            elif not is_eip712_primitive(base):
                raise ValueError(f"Unsupported EIP-712 primitive: {base}")
            result.append({"name": name, "type": base + suffix})
        return result

    for signature, primary in selected.items():
        if signature not in functions:
            raise ValueError(f"clearsig-typed-data method is missing from compiler ABI: {signature}")
        register(primary, fields(functions[signature].inputs or [], (primary,)))
    schemas = []
    for primary in selected.values():
        reachable: dict[str, list[dict[str, str]]] = {}

        def visit(name: str, reachable: dict[str, list[dict[str, str]]] = reachable) -> None:
            if name in reachable:
                return
            reachable[name] = types[name]
            for part in types[name]:
                child = part["type"].split("[", 1)[0]
                if child in types:
                    visit(child)

        visit(primary)
        schemas.append({"primaryType": primary, "types": reachable})
    return json.dumps(schemas)
