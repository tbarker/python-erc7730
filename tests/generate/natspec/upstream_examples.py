"""Independent fixture assembly and semantic comparison for upstream examples.

Assembly reads compiler artifacts and authored recipes, never expected descriptors.
Recipes supply bindings and extra metadata. Display fields come entirely from generation.
"""

import json
import re
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from erc7730.common.output import ListOutputAdder
from erc7730.common.templates import translate_template
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.context import InputDeployment
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.metadata import InputMetadata
from erc7730.model.paths import DataPath
from erc7730.model.paths.path_parser import to_path

DATA = Path(__file__).parent / "data" / "upstream_examples"
MANIFEST = json.loads((DATA / "manifest.json").read_text())


def assemble(name: str) -> InputERC7730Descriptor:
    artifact = json.loads((DATA / f"{name}.artifact.json").read_text())
    recipe = json.loads((DATA / f"{name}.recipe.json").read_text())
    typed = "eip712" in recipe["context"]
    binding = recipe["context"]["eip712" if typed else "contract"]
    deployment = binding["deployments"][0]
    warnings: list[str] = []
    generated = generate_natspec_descriptor(
        deployment["chainId"],
        deployment["address"],
        natspec=artifact,
        eip712_domain=binding.get("domain") if typed else None,
        deployments=TypeAdapter(list[InputDeployment]).validate_python(binding["deployments"], strict=False),
        metadata=InputMetadata.model_validate(recipe["metadata"], strict=False),
        warnings=warnings,
    )
    assert not any("ignoring" in warning for warning in warnings), warnings
    assert not recipe.get("formats"), "Recipes cannot alter generated display fields"
    return generated


def semantic(descriptor: InputERC7730Descriptor, *, fragment: bool = False) -> dict[str, Any]:
    """Resolve paths/includes/constants, retaining all observable display decisions."""
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None and not out.has_errors, out.outputs
    value = json.loads(resolved.to_json_string())

    def clean(item: Any) -> Any:
        if isinstance(item, list):
            return [clean(child) for child in item]
        if not isinstance(item, dict):
            return item
        if item.get("visible") == "never":
            return {key: item[key] for key in ("path", "value", "visible") if key in item}
        return {
            key: [clean(field) for field in child if not (isinstance(field, dict) and field.get("visible") == "never")]
            if key == "fields" and isinstance(child, list)
            else clean(child)
            for key, child in item.items()
            if key not in ("$id", "$comment", "$keyType") and not (key == "visible" and child == "always")
        }

    value = clean(value)
    if "$schema" in value:
        value["$schema"] = value["$schema"].rsplit("/", 1)[-1]
    for fmt in value["display"]["formats"].values():
        paths: set[str] = set()

        def collect(fields: list[dict[str, Any]], paths: set[str] = paths) -> None:
            for field in fields:
                if "fields" in field:
                    collect(field["fields"])
                elif isinstance(field.get("path"), str):
                    paths.add(field["path"])

        collect(fmt["fields"])

        def reference(text: str, paths: set[str] = paths) -> str:
            path = to_path(text)
            if isinstance(path, DataPath):
                text = str(path.model_copy(update={"absolute": True}))
                if text + ".[]" in paths:
                    text += ".[]"
                return text
            return str(path)

        if "interpolatedIntent" in fmt:
            fmt["interpolatedIntent"] = translate_template(
                fmt["interpolatedIntent"], reference, natspec=False, literal_backticks=True
            )
    return value["display"] if fragment else value


def expected_document(name: str) -> InputERC7730Descriptor:
    from erc7730.common.json import read_json_with_includes

    entry = MANIFEST["examples"][name]
    source = read_json_with_includes(DATA / "upstream" / f"{name}.json", merge_display_fields=True)

    def substitute(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: substitute(child) for key, child in value.items()}
        if isinstance(value, list):
            return [substitute(child) for child in value]
        return entry["substitutions"].get(value, value) if isinstance(value, str) else value

    source = substitute(source)
    source["display"]["formats"] = {
        re.sub(r",\s*", ",", key): value for key, value in source["display"]["formats"].items()
    }
    if entry["fragment"]:
        source |= {
            "context": {"contract": {"deployments": [{"chainId": 1, "address": "0x" + "11" * 20}]}},
            "metadata": {"owner": "Fixture"},
        }
    return InputERC7730Descriptor.model_validate(source, strict=False)
