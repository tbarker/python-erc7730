"""Address lookup defaults remain optional and overridable through every scope."""

import json

import pytest

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.v2.display import InputAddressNameParameters, InputFieldDescription, InputFieldGroup

ADDRESS = "0x1111111111111111111111111111111111111111"
ABI = json.dumps([{"type": "function", "name": "send", "inputs": [{"name": "to", "type": "address"}]}])


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("typed", [False, True])
def test_default_without_sources_annotation(explicit: bool, typed: bool) -> None:
    tags = {"custom:clearsig-format": "to=addressName"} if explicit else {}
    if typed:
        tags["custom:clearsig-typed-data"] = "Send"
    warnings: list[str] = []
    d = generate_natspec_descriptor(1, ADDRESS, abi=ABI, devdoc={"methods": {"send(address)": tags}}, warnings=warnings)
    field = next(iter(d.display.formats.values())).fields[0]
    assert isinstance(field, InputFieldDescription)
    assert isinstance(field.params, InputAddressNameParameters)
    assert field.params.sources == ["local", "ens"]
    assert not warnings
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is not None, out.outputs
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize("scope", ["project", "contract", "method"])
def test_sources_override_replaces_default(scope: str) -> None:
    project = {"custom:clearsig-sources": 'to=["local"]'}
    contract = {"custom:clearsig-sources": 'to=["ens"]'} if scope != "project" else {}
    method = {"custom:clearsig-format": "to=addressName"}
    if scope == "method":
        method["custom:clearsig-sources"] = 'to=["local"]'
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=ABI,
        project_defaults=project,
        devdoc={**contract, "methods": {"send(address)": method}},
    )
    field = next(iter(d.display.formats.values())).fields[0]
    assert isinstance(field, InputFieldDescription)
    assert isinstance(field.params, InputAddressNameParameters)
    assert field.params.sources == (["ens"] if scope == "contract" else ["local"])


def test_invalid_source_override_keeps_default() -> None:
    warnings: list[str] = []
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=ABI,
        warnings=warnings,
        devdoc={"methods": {"send(address)": {"custom:clearsig-sources": "to=[]"}}},
    )
    field = next(iter(d.display.formats.values())).fields[0]
    assert isinstance(field, InputFieldDescription)
    assert isinstance(field.params, InputAddressNameParameters)
    assert field.params.sources == ["local", "ens"]
    assert any("ignoring sources" in warning for warning in warnings)


def test_nested_array_defaults_and_other_formatters() -> None:
    abi = json.dumps(
        [
            {
                "type": "function",
                "name": "send",
                "inputs": [
                    {
                        "name": "orders",
                        "type": "tuple[]",
                        "components": [
                            {"name": "to", "type": "address"},
                            {"name": "token", "type": "address"},
                        ],
                    },
                ],
            }
        ]
    )
    d = generate_natspec_descriptor(
        1,
        ADDRESS,
        abi=abi,
        devdoc={"methods": {"send((address,address)[])": {"custom:clearsig-format": "orders.token=raw"}}},
    )
    group = next(iter(d.display.formats.values())).fields[0]
    assert isinstance(group, InputFieldGroup)
    fields = {str(field.path): field for field in group.fields}
    to = fields["to"]
    token = fields["token"]
    assert isinstance(to, InputFieldDescription)
    assert isinstance(to.params, InputAddressNameParameters)
    assert to.params.sources == ["local", "ens"]
    assert isinstance(token, InputFieldDescription)
    assert token.format == "raw"
    assert token.params is None
