"""Validate v2 display paths and formatters against local declarations."""

from collections.abc import Iterator
from typing import Literal, final, override

from pydantic import BaseModel

from erc7730.common.abi import compute_signature, parse_signature, signature_to_selector
from erc7730.common.output import OutputAdder
from erc7730.common.schema_types import (
    format_accepts_path,
    format_accepts_type,
    primitive_slice_width,
    schema_path_shape,
    schema_path_type,
    validate_function_declaration,
)
from erc7730.lint.v2 import ERC7730Linter
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.format import IterationStrategy
from erc7730.model.paths import ContainerField, ContainerPath, DataPath
from erc7730.model.resolved.display import ResolvedValueConstant, ResolvedValuePath
from erc7730.model.resolved.v2.context import ResolvedEIP712Context
from erc7730.model.resolved.v2.descriptor import ResolvedERC7730Descriptor
from erc7730.model.resolved.v2.display import (
    ResolvedCallDataParameters,
    ResolvedField,
    ResolvedFieldDescription,
    ResolvedFieldGroup,
    ResolvedNftNameParameters,
    ResolvedTokenAmountParameters,
    ResolvedTokenTickerParameters,
    ResolvedValueMap,
    iter_field_descriptions,
)


def _paths(value: object) -> Iterator[DataPath]:
    """Retain concrete selectors in fields and all resolved parameter references."""
    if isinstance(value, DataPath):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _paths(getattr(value, name))
    elif isinstance(value, list):
        for item in value:
            yield from _paths(item)


def _validate_bundled_groups(
    fields: list[ResolvedField], declaration: str, eip712: bool, out: OutputAdder, parent_depth: int = 0
) -> None:
    for field in fields:
        if not isinstance(field, ResolvedFieldGroup):
            continue
        depth = (
            len(schema_path_shape(declaration, eip712, field.path))
            if isinstance(field.path, DataPath)
            else parent_depth
        )
        if field.iteration == IterationStrategy.BUNDLED:
            sizes: set[int] = set()
            for child in field.fields:
                if isinstance(child, ResolvedFieldGroup) or not isinstance(child.path, DataPath):
                    continue
                shape = schema_path_shape(declaration, eip712, child.path)
                if len(shape) > depth and (size := shape[depth]) is not None:
                    sizes.add(size)
            if len(sizes) > 1:
                out.error(
                    title="Bundled array size mismatch",
                    message=f"{declaration}: bundled group {field.label or field.path} selects unequal "
                    f"fixed array lengths {sorted(sizes)}.",
                )
        _validate_bundled_groups(field.fields, declaration, eip712, out, depth)


ParameterType = Literal["address", "uint", "bytes4"]


def _accepts_parameter_type(expected: ParameterType, actual: str, width: int | None) -> bool:
    if width is not None:
        return width == 20 if expected == "address" else width == 4 if expected == "bytes4" else 0 < width <= 32
    if expected == "uint":
        return actual.startswith("uint") and actual[4:].isdigit()
    return actual == expected


def _parameter_references(
    field: ResolvedFieldDescription,
) -> Iterator[tuple[str, object, ParameterType]]:
    params = field.params
    if isinstance(params, ResolvedTokenAmountParameters):
        yield "tokenPath", params.token, "address"
    if isinstance(params, (ResolvedTokenAmountParameters, ResolvedTokenTickerParameters)):
        yield "chainIdPath", params.chainIdPath, "uint"
    if isinstance(params, ResolvedNftNameParameters):
        yield "collectionPath", params.collection, "address"
    if isinstance(params, ResolvedCallDataParameters):
        yield "calleePath", params.callee, "address"
        yield "spenderPath", params.spender, "address"
        yield "amountPath", params.amount, "uint"
        yield "selectorPath", params.selector, "bytes4"


@final
class ValidateSchemaLinter(ERC7730Linter):
    """Offline validation uses the full declarations retained in input format keys."""

    @override
    def lint(
        self, input_descriptor: InputERC7730Descriptor, descriptor: ResolvedERC7730Descriptor, out: OutputAdder
    ) -> None:
        eip712 = isinstance(descriptor.context, ResolvedEIP712Context)
        for declaration in input_descriptor.display.formats:
            try:
                if not eip712:
                    validate_function_declaration(declaration)
                key = declaration if eip712 else signature_to_selector(compute_signature(parse_signature(declaration)))
            except ValueError:
                out.error(
                    title="Invalid display field",
                    message=f"{declaration}: v2 local validation requires a named function declaration "
                    "as the format key.",
                )
                continue
            format = descriptor.display.formats.get(key)
            if format is None:
                continue
            _validate_bundled_groups(format.fields, declaration, eip712, out)
            path_types = {path: schema_path_type(declaration, eip712, path) for path in _paths(format)}
            for path, type_ in path_types.items():
                if type_ is None:
                    out.error(
                        title="Invalid display field",
                        message=f"{declaration}: `{path}` does not exist in the declared schema "
                        "or exceeds fixed bounds.",
                    )
            for field in iter_field_descriptions(format.fields):
                if field.params is not None:
                    for name in type(field.params).model_fields:
                        reference = getattr(field.params, name)
                        if isinstance(reference, ResolvedValueMap) and isinstance(reference.keyPath, DataPath):
                            key_type = path_types.get(reference.keyPath)
                            shape = schema_path_shape(declaration, eip712, reference.keyPath)
                            if key_type is None or key_type.startswith("(") or key_type.endswith("]") or shape:
                                out.error(
                                    title="Invalid map key",
                                    message=f"{declaration}: {name} map key must select a scalar value.",
                                )
                for name, reference, expected in _parameter_references(field):
                    if reference is None or isinstance(reference, ResolvedValueMap):
                        continue
                    path = reference.path if isinstance(reference, ResolvedValuePath) else reference
                    actual = None
                    compatible = True
                    if isinstance(path, DataPath):
                        actual = path_types[path]
                        if actual is not None:
                            width = primitive_slice_width(declaration, eip712, path)
                            parameter_shape = schema_path_shape(declaration, eip712, path)
                            field_shape = (
                                schema_path_shape(declaration, eip712, field.path)
                                if isinstance(field.path, DataPath)
                                else []
                            )
                            shapes_match = not parameter_shape or (
                                len(parameter_shape) == len(field_shape)
                                and all(
                                    a is None or b is None or a == b
                                    for a, b in zip(parameter_shape, field_shape, strict=True)
                                )
                            )
                            compatible = shapes_match and _accepts_parameter_type(
                                expected, actual.split("[", 1)[0], width
                            )
                    elif isinstance(path, ContainerPath):
                        actual = (
                            "uint256" if path.field in (ContainerField.VALUE, ContainerField.CHAIN_ID) else "address"
                        )
                        compatible = _accepts_parameter_type(expected, actual, None)
                    elif isinstance(reference, ResolvedValueConstant):
                        actual = f"constant {reference.value!r}"
                        size = reference.type_size
                        compatible = (
                            size == 20
                            if expected == "address"
                            else size == 4
                            if expected == "bytes4"
                            else size is not None and 0 < size <= 32 and not isinstance(reference.value, bool)
                        )
                        if expected in ("address", "bytes4"):
                            compatible = (
                                compatible and isinstance(reference.value, str) and reference.value.startswith("0x")
                            )
                    else:
                        actual = str(path)
                        compatible = False
                    if not compatible:
                        required = {
                            "address": "an address",
                            "uint": "an unsigned integer",
                            "bytes4": "a four-byte selector",
                        }[expected]
                        out.error(
                            title="Invalid token path type"
                            if name == "tokenPath"
                            else "Invalid formatter parameter type",
                            message=f"{declaration}: {name} `{path}` for {field.path} has type "
                            f"{actual}; expected {required} or a compatible primitive byte slice.",
                        )
                type_ = None
                if field.encryption is not None:
                    # The handle's ABI type does not describe the decrypted value.
                    type_ = field.encryption.plaintextType
                elif isinstance(field.path, DataPath):
                    type_ = path_types[field.path]
                elif isinstance(field.path, ContainerPath):
                    type_ = (
                        "uint256" if field.path.field in (ContainerField.VALUE, ContainerField.CHAIN_ID) else "address"
                    )
                compatible = (
                    format_accepts_path(field.format, declaration, eip712, field.path)
                    if field.encryption is None and isinstance(field.path, DataPath) and type_ is not None
                    else type_ is None or format_accepts_type(field.format, type_)
                )
                if not compatible:
                    out.error(
                        title="Inapplicable field format",
                        message=f"{declaration}: {field.path} has type {type_}, "
                        f"which cannot use format {field.format}.",
                    )
