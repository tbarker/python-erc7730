"""Validate merged descriptor JSON against the bundled published V2 schema."""

import json
from functools import cache
from importlib.resources import files
from typing import Any
from urllib.parse import urlparse

from jsonschema import Draft202012Validator, FormatChecker

from erc7730.common.output import OutputAdder

LATEST_V2_SCHEMA = "erc7730-v2.1.0.schema.json"
SUPPORTED_V2_SCHEMAS = frozenset({"erc7730-v2.0.0.schema.json", LATEST_V2_SCHEMA})


def schema_name(value: Any) -> str:
    """Resolve only bundled versions; never fetch a descriptor-supplied schema URL."""
    reference = value.get("$schema") if isinstance(value, dict) else None
    if reference is None:
        return LATEST_V2_SCHEMA
    if not isinstance(reference, str):
        raise ValueError("$schema must be a string")
    name = urlparse(reference).path.rsplit("/", 1)[-1]
    if name == "erc7730-v2.schema.json":
        return LATEST_V2_SCHEMA
    if name not in SUPPORTED_V2_SCHEMAS:
        raise ValueError(f"Unsupported V2 schema: {reference}; supported versions: 2.0.0, 2.1.0")
    return name


@cache
def _validator(name: str) -> Draft202012Validator:
    schema = json.loads(files("erc7730.lint.v2").joinpath(name).read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_json_schema(value: Any, out: OutputAdder) -> bool:
    try:
        validator = _validator(schema_name(value))
    except ValueError as exc:
        out.error(title="Unsupported V2 JSON schema", message=str(exc))
        return False
    valid = True
    for error in validator.iter_errors(value):
        valid = False
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        out.error(title="Invalid V2 JSON schema", message=f"{location}: {error.message}")
    return valid
