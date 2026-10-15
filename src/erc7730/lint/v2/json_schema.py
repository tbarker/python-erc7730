"""Validate merged descriptor JSON against the bundled published V2 schema."""

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from erc7730.common.output import OutputAdder


@cache
def _validator() -> Draft202012Validator:
    schema = json.loads(files("erc7730.lint.v2").joinpath("erc7730-v2.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())


def validate_json_schema(value: Any, out: OutputAdder) -> bool:
    valid = True
    for error in _validator().iter_errors(value):
        valid = False
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        out.error(title="Invalid V2 JSON schema", message=f"{location}: {error.message}")
    return valid
