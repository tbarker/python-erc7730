"""Constants and enums share quoting, separator and duplicate semantics."""

import json
from typing import Any

import pytest

from erc7730.generate.natspec.generate import generate_natspec_descriptor


@pytest.mark.parametrize("separator", [",", ", ", "\n", " "])
def test_both_declarations_preserve_quoted_delimiters(separator: str) -> None:
    label = 'Stable, mode="fixed"'
    d = generate_natspec_descriptor(
        1,
        "0x" + "11" * 20,
        abi='[{"name":"f","type":"function","inputs":[{"name":"mode","type":"uint8"}]}]',
        devdoc={
            "custom:clearsig-constant": f"label={json.dumps(label)}{separator}count=2,",
            "methods": {
                "f(uint8)": {"custom:clearsig-enum": f'mode[0]={json.dumps(label)}{separator}mode[1]="Variable",'}
            },
        },
    )
    assert d.metadata.constants == {"label": label, "count": 2}
    assert d.metadata.enums is not None
    assert next(iter(d.metadata.enums.values())) == {"0": label, "1": "Variable"}


@pytest.mark.parametrize("tag,prefix", [("enum", "mode[0]"), ("constant", "name")])
@pytest.mark.parametrize("suffix", ['="unterminated', '="A"garbage', "=Unquoted", '="A",broken'])
def test_both_declarations_reject_malformed_input(tag: str, prefix: str, suffix: str) -> None:
    tags = {f"custom:clearsig-{tag}": prefix + suffix}
    docs: dict[str, Any] = {"methods": {"f(uint8)": tags}} if tag == "enum" else tags
    with pytest.raises(ValueError, match=f"clearsig-{tag}"):
        generate_natspec_descriptor(
            1,
            "0x" + "11" * 20,
            abi='[{"name":"f","type":"function","inputs":[{"name":"mode","type":"uint8"}]}]',
            devdoc=docs,
        )
