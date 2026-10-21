from abc import ABC
from collections.abc import Sequence
from typing import Any, assert_never

from eip712.model.schema import EIP712SchemaField, EIP712Type
from eth_abi.grammar import BasicType, TupleType, parse
from pydantic import Field

from erc7730.common.abi import ABIDataType
from erc7730.model.abi import Component, Function, InputOutput
from erc7730.model.base import Model
from erc7730.model.context import EIP712Schema


class SchemaNode(Model, ABC):
    """Represents a node in the tree defined by a function ABI / EIP-712 schema."""


class SchemaStruct(SchemaNode):
    """Schema node representing a function or a tuple."""

    components: dict[str, "SchemaTree"] = Field(title="Struct components")


class SchemaArray(SchemaNode):
    """Schema node representing an array."""

    component: "SchemaTree" = Field(title="Array element type")


class SchemaLeaf(SchemaNode):
    """Schema node representing a scalar type."""

    data_type: ABIDataType = Field(title="Data type")


#: A struct, array, or scalar node in an ABI or EIP-712 schema.
SchemaTree = SchemaStruct | SchemaArray | SchemaLeaf


def eip712_schema_to_tree(schema: EIP712Schema) -> SchemaTree:
    """
    Convert an EIP-712 schema to a schema tree.

    A schema tree is a tree representation of the EIP-712 schema, enriched with some metadata to ease crafting
    paths to access values in the message.

    :param schema: EIP-712 schema
    :return: Schema tree
    """
    if (primary_type_fields := schema.types.get(schema.primaryType)) is None:
        raise ValueError("Primary type not found in schema types")

    return _eip712_struct_type_to_tree(fields=primary_type_fields, types=schema.types, active=(schema.primaryType,))


def _eip712_struct_type_to_tree(
    fields: list[EIP712SchemaField], types: dict[EIP712Type, list[EIP712SchemaField]], active: tuple[str, ...]
) -> SchemaTree:
    """
    Convert a complex EIP-712 type to a schema tree node (can be the primary type directly).

    :param fields: type fields
    :param types: all schema types
    :return: Schema tree
    """
    return SchemaStruct(components={field.name: _eip712_field_to_tree(field, types, active) for field in fields})


def _eip712_field_to_tree(
    field: EIP712SchemaField, types: dict[EIP712Type, list[EIP712SchemaField]], active: tuple[str, ...]
) -> SchemaTree:
    """
    Convert an EIP-712 type to a schema tree node.

    :param field: ABI element (can be a single component, or a function input)
    :param types: all schema types
    :return: Schema tree
    """
    # EIP-712 identifiers may contain digits anywhere (e.g. V2DutchOrder).
    # eth_abi parses Solidity primitive widths, not arbitrary struct identifiers.
    base = field.type.split("[", 1)[0]
    if base in types:
        if base in active:
            raise ValueError(
                "Recursive EIP-712 schemas cannot be expanded into a finite display tree: "
                + " -> ".join((*active, base))
                + ". Write a v2 descriptor manually with bounded field paths."
            )
        component = _eip712_struct_type_to_tree(types[base], types, (*active, base))
        for _ in range(field.type.count("[")):
            component = SchemaArray(component=component)
        return component

    match parse(field.type):
        case TupleType():
            return _eip712_struct_type_to_tree(types[field.type], types, active)

        case BasicType() as tp:
            if tp.is_array:
                match tp.base:
                    case "tuple" | "struct":
                        component = _eip712_struct_type_to_tree(types[field.type], types, active)
                    case _:
                        component = _eip712_field_to_tree(
                            field=field.model_copy(update={"type": tp.item_type.to_type_str()}),
                            types=types,
                            active=active,
                        )

                return SchemaArray(component=component)

            match tp.base:
                case "tuple" | "struct":
                    return _eip712_struct_type_to_tree(types[field.type], types, active)
                case base if base in set(ABIDataType):
                    type_family = ABIDataType(base)
                case base_type:
                    if (base_type_fields := types.get(base_type)) is None:
                        raise Exception(f"Unexpected EIP-712 type: {base_type}")
                    if base_type in active:
                        raise ValueError(
                            "Recursive EIP-712 schemas cannot be expanded into a finite display tree: "
                            + " -> ".join((*active, base_type))
                            + ". Write a v2 descriptor manually with bounded field paths."
                        )
                    return _eip712_struct_type_to_tree(base_type_fields, types, (*active, base_type))

            return SchemaLeaf(data_type=type_family)

        case unknown:
            raise Exception(f"Unexpected EIP-712 type: {type(unknown)}")


def abi_function_to_tree(function: Function) -> SchemaTree:
    """
    Convert a function ABI to a schema tree.

    A schema tree is a tree representation of the ABI of a function inputs, enriched with some metadata to ease
    crafting paths to access values in the serialized calldata.

    :param function: function ABI
    :return: Schema tree
    """
    return _abi_struct_component_to_tree(name_unnamed_inputs(function))


def _abi_struct_component_to_tree(inp: Function | InputOutput | Component) -> SchemaTree:
    """
    Convert a struct-like ABI component to a schema tree node (can be the top level function directly).

    :param inp: ABI element
    :return: Schema tree
    """

    # get inputs/components list based on argument type
    input_components: list[InputOutput | Component] = []
    match inp:
        case Function(inputs=inputs):
            if inputs is not None:
                input_components.extend(inputs)
        case InputOutput(components=inp_components):
            if inp_components is not None:
                input_components.extend(inp_components)
        case Component(components=inp_components):
            if inp_components is not None:
                input_components.extend(inp_components)
        case list() as eip712_fields:
            input_components.extend(eip712_fields)
        case _:
            assert_never(inp)

    return SchemaStruct(
        components={component.name: _abi_component_to_tree(component) for component in input_components}
    )


def _abi_component_to_tree(inp: InputOutput | Component) -> SchemaTree:
    """
    Convert an ABI component to a schema tree node.

    :param inp: ABI element (can be a single component, or a function input)
    :return: Schema tree
    """
    match parse(inp.type):
        case TupleType() as tp:
            if tp.is_array:
                # Handle multidimensional tuple arrays (e.g., tuple[][], tuple[][][])
                component = _abi_component_to_tree(inp.model_copy(update={"type": tp.item_type.to_type_str()}))
                return SchemaArray(component=component)
            return _abi_struct_component_to_tree(inp)

        case BasicType() as tp:
            if tp.is_array:
                # For all array types (including tuple/struct arrays), recursively process the inner type
                # to handle multidimensional arrays like address[][], tuple[][][], etc.
                component = _abi_component_to_tree(inp.model_copy(update={"type": tp.item_type.to_type_str()}))
                return SchemaArray(component=component)

            match tp.base:
                case "tuple" | "struct":
                    return _abi_struct_component_to_tree(inp)
                case base if base in set(ABIDataType):
                    type_family = ABIDataType(base)
                case unknown:
                    raise Exception(f"Unexpected ABI type: {unknown}")

            return SchemaLeaf(data_type=type_family)

        case unknown:
            raise Exception(f"Unexpected ABI type: {type(unknown)}")


def eip712_encode_type(schema: EIP712Schema) -> str:
    """Encode reachable EIP-712 types with dependencies in alphabetical order."""
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        visited.add(name)
        for field in schema.types[name]:
            child = field.type.split("[", 1)[0]
            if child in schema.types:
                visit(child)

    visit(schema.primaryType)
    return "".join(
        name + "(" + ",".join(f"{field.type} {field.name}" for field in schema.types[name]) + ")"
        for name in [schema.primaryType, *sorted(visited - {schema.primaryType})]
    )


def name_unnamed_inputs(function: Function) -> Function:
    """Assign stable, collision-free names to positional ABI inputs and tuple members."""

    def named(components: Sequence[InputOutput | Component]) -> list[InputOutput | Component]:
        names = [component.name for component in components if component.name]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate ABI parameter names in {function.name}.")
        used = set(names)
        result: list[InputOutput | Component] = []
        for index, component in enumerate(components):
            name = component.name
            if not name:
                name = f"_arg{index}"
                while name in used:
                    name = "_" + name
                used.add(name)
            updates: dict[str, Any] = {"name": name}
            if component.components is not None:
                updates["components"] = named(component.components)
            result.append(component.model_copy(update=updates))
        return result

    return function.model_copy(update={"inputs": named(function.inputs or [])})
