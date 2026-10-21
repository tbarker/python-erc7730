"""Name lookup references validate as paths, then as resolved lists."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.address_names import resolve_name_lists
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.model.input.display import InputAddressNameParameters as V1Params
from erc7730.model.input.v2.display import InputAddressNameParameters, InputInteroperableAddressNameParameters
from erc7730.model.input.v2.metadata import InputMetadata
from erc7730.model.resolved.v2.display import (
    ResolvedAddressNameParameters,
    ResolvedFieldDescription,
    ResolvedInteroperableAddressNameParameters,
)


@pytest.mark.parametrize("format_,abi_type", [("addressName", "address"), ("interoperableAddressName", "bytes")])
@pytest.mark.parametrize("source", ["local", "ens"])
def test_scalar_constant_references(format_: str, abi_type: str, source: str) -> None:
    d = generate_natspec_descriptor(
        1,
        "0x" + "11" * 20,
        abi=json.dumps([{"type": "function", "name": "f", "inputs": [{"name": "to", "type": abi_type}]}]),
        devdoc={
            "custom:clearsig-constant": f'source="{source}" type="contract"',
            "methods": {
                f"f({abi_type})": {
                    "custom:clearsig-format": f"to={format_}",
                    "custom:clearsig-sources": "to=$.metadata.constants.source",
                    "custom:clearsig-types": "to=$.metadata.constants.type",
                }
            },
        },
    )
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(d, out)
    assert resolved is not None, out.outputs
    field = next(iter(resolved.display.formats.values())).fields[0]
    assert isinstance(field, ResolvedFieldDescription)
    params = field.params
    assert isinstance(params, (ResolvedAddressNameParameters, ResolvedInteroperableAddressNameParameters))
    assert params.sources == [source]
    assert params.types == ["contract"]


@pytest.mark.parametrize("value", [None, 123, True, ""])
@pytest.mark.parametrize("format_,abi_type", [("addressName", "address"), ("interoperableAddressName", "bytes")])
def test_incompatible_source_reference_reports_error(value: Any, format_: str, abi_type: str) -> None:
    d = generate_natspec_descriptor(
        1,
        "0x" + "11" * 20,
        abi=json.dumps([{"type": "function", "name": "f", "inputs": [{"name": "to", "type": abi_type}]}]),
        metadata=InputMetadata(constants={"bad": value}),
        devdoc={
            "methods": {
                f"f({abi_type})": {
                    "custom:clearsig-format": f"to={format_}",
                    "custom:clearsig-sources": "to=$.metadata.constants.bad",
                }
            }
        },
    )
    out = ListOutputAdder()
    assert ERC7730InputToResolved().convert(d, out) is None
    assert out.has_errors
    assert "Invalid address-name sources" in str(out.outputs)


@pytest.mark.parametrize("model", [V1Params, InputAddressNameParameters, InputInteroperableAddressNameParameters])
@pytest.mark.parametrize("field", ["types", "sources"])
def test_path_union_and_empty_list_validation(model: Any, field: str) -> None:
    params = model.model_validate({field: "$.metadata.constants.policy"}, strict=False)
    assert str(getattr(params, field)) == "$.metadata.constants.policy"
    with pytest.raises(ValidationError):
        model.model_validate({field: []})


def test_lists_and_missing_or_invalid_references() -> None:
    out = ListOutputAdder()
    assert resolve_name_lists(["contract"], ["ens", "local"], lambda v: v, out) == {
        "types": ["contract"],
        "sources": ["ens", "local"],
    }
    assert resolve_name_lists(None, "missing", lambda _: None, out) is None
    assert resolve_name_lists("invalid-type", None, lambda v: v, out) is None
    assert resolve_name_lists(None, [], lambda v: v, out) is None
    assert resolve_name_lists(None, [1], lambda v: v, out) is None
    assert out.has_errors
