"""Pinned Uniswap inputs, independent compiler generation and semantic comparison."""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from erc7730.common.abi import compute_signature, parse_signature, signature_to_selector
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.context import InputDeployment, InputEIP712Context
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.metadata import InputMetadata
from tests.generate.natspec.upstream_examples import semantic

DATA = Path(__file__).parent / "data/registry_uniswap"
MANIFEST = json.loads((DATA / "manifest.json").read_text())
NAMES = sorted(MANIFEST["examples"])


def assemble(name: str) -> InputERC7730Descriptor:
    # Only compiler output and public library binding/metadata inputs are read.
    recipe = json.loads((DATA / f"{name}.recipe.json").read_text())
    assert set(recipe) == {"context", "metadata"}
    binding = recipe["context"].get("eip712", recipe["context"].get("contract"))
    deployments = TypeAdapter(list[InputDeployment]).validate_python(binding["deployments"], strict=False)
    warnings: list[str] = []
    descriptor = generate_natspec_descriptor(
        deployments[0].chainId,
        deployments[0].address,
        natspec=(DATA / f"{name}.artifact.json").read_text(),
        deployments=deployments,
        metadata=InputMetadata.model_validate(recipe["metadata"], strict=False),
        eip712_domain=binding.get("domain"),
        warnings=warnings,
    )
    assert all("notice used as intent" in w or "intent template generated" in w for w in warnings), warnings
    return descriptor


def expected(name: str) -> InputERC7730Descriptor:
    from erc7730.common.json import read_json_with_includes

    source = read_json_with_includes(DATA / "upstream" / f"{name}.json", merge_display_fields=True)
    source["display"]["formats"] = {re.sub(r",\s*", ",", key): fmt for key, fmt in source["display"]["formats"].items()}
    return InputERC7730Descriptor.model_validate(source, strict=False)


def comparison(descriptor: InputERC7730Descriptor) -> dict[str, Any]:
    """Preserve visible layout; omitted inputs and unconditional hiding render nothing.

    Hiding a struct equals hiding its leaves. Permanently hidden fields have no
    screen position. An unlabeled logical sequential group is equivalent to its
    children at the same position; array-scoped/bundled/named groups are retained.
    """
    result = semantic(descriptor)
    typed = isinstance(descriptor.context, InputEIP712Context)
    for declaration in descriptor.display.formats:
        key = declaration if typed else signature_to_selector(compute_signature(parse_signature(declaration)))
        fmt = result["display"]["formats"][key]

        def visible(fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
            values = []
            for field in fields:
                if field.get("visible") == "never":
                    continue
                elif "fields" in field:
                    children = visible(field["fields"])
                    if not children and not field.get("label"):
                        continue
                    if not field.get("path") and not field.get("label") and field.get("iteration") == "sequential":
                        values.extend(children)
                    else:
                        values.append(field | {"fields": children})
                else:
                    values.append(field)
            return values

        fmt["fields"] = visible(fmt["fields"])
    return result
