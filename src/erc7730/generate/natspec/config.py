"""Project defaults for descriptor generation."""

import tomllib
from pathlib import Path
from typing import Any


def load_project_defaults(path: Path | None = None) -> dict[str, Any]:
    """Read [generate] from an explicit config or the nearest erc7730.toml.

    Discovery is a CLI convenience. Library callers pass defaults explicitly to
    generate_natspec_descriptor so its behavior does not depend on the working directory.
    """
    if path is None:
        current = Path.cwd()
        path = next(
            (candidate for parent in (current, *current.parents) if (candidate := parent / "erc7730.toml").is_file()),
            None,
        )
    if path is None:
        return {}
    try:
        with path.open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read generate config {path}: {exc}") from exc
    defaults = config.get("generate", {})
    if not isinstance(defaults, dict):
        raise ValueError(f"Invalid generate config {path}: [generate] must be a table.")
    # Compiler inputs are relative to the config file, not the invocation cwd.
    for key in ("natspec", "userdoc", "devdoc"):
        if key in defaults:
            if not isinstance(defaults[key], str):
                raise ValueError(f"Invalid generate config {path}: {key} must be a file path.")
            defaults[key] = str((path.parent / defaults[key]).resolve())
    return defaults
