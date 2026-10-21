from __future__ import annotations

import json
import logging
from collections.abc import Generator
from typing import Any, assert_never

from caseswitcher import to_title
from pydantic import TypeAdapter
from pydantic_string_url import HttpUrl

from erc7730.common.abi import ABIDataType, compute_signature, get_functions
from erc7730.common.schema_types import validate_function_declaration
from erc7730.generate.natspec import JSONInput, parse_natspec
from erc7730.generate.natspec.display import apply_natspec
from erc7730.generate.natspec.eip712_bridge import bridge_methods, infer_schemas, message_docs
from erc7730.generate.natspec.examples import ExampleRenderer, run_natspec_examples
from erc7730.generate.natspec.metadata import apply_metadata_annotations
from erc7730.generate.schema_tree import (
    SchemaArray,
    SchemaLeaf,
    SchemaStruct,
    SchemaTree,
    abi_function_to_tree,
    eip712_encode_type,
    eip712_schema_to_tree,
    name_unnamed_inputs,
)
from erc7730.model.abi import ABI
from erc7730.model.context import EIP712Schema
from erc7730.model.display import AddressNameType
from erc7730.model.input.v2.context import (
    InputContract,
    InputContractContext,
    InputDeployment,
    InputDomain,
    InputEIP712,
    InputEIP712Context,
)
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.display import (
    InputAddressNameParameters,
    InputDateParameters,
    InputDisplay,
    InputField,
    InputFieldDescription,
    InputFieldGroup,
    InputFieldParameters,
    InputFormat,
)
from erc7730.model.input.v2.format import DateEncoding, FieldFormat
from erc7730.model.input.v2.metadata import InputMetadata, InputOwnerInfo
from erc7730.model.paths import ROOT_DATA_PATH, Array, ArrayElement, ArraySlice, DataPath, Field
from erc7730.model.paths.path_ops import data_path_append
from erc7730.model.types import Address


def generate_natspec_descriptor(
    chain_id: int,
    contract_address: Address,
    abi: str | bytes | None = None,
    eip712_schema: str | bytes | None = None,
    owner: str | None = None,
    url: HttpUrl | None = None,
    natspec: JSONInput = None,
    userdoc: JSONInput = None,
    devdoc: JSONInput = None,
    warnings: list[str] | None = None,
    project_defaults: JSONInput = None,
    example_renderer: ExampleRenderer | None = None,
    eip712_domain: JSONInput = None,
    deployments: list[InputDeployment] | None = None,
    metadata: InputMetadata | None = None,
) -> InputERC7730Descriptor:
    """
    Generate an ERC-7730 v2 descriptor, including supported NatSpec intent templates.

    An explicit EIP-712 schema or method-level clearsig-typed-data annotations select message generation.
    Calldata generation and the typed-data bridge require a supplied ABI or compiler artifact.
    Generation never fetches an ABI from a remote service.

    :param chain_id: contract chain id
    :param contract_address: contract address
    :param abi: JSON ABI string or buffer representation (to generate a calldata descriptor)
    :param eip712_schema: JSON EIP-712 schema string or buffer representation (to generate an EIP-712 descriptor)
    :param eip712_domain: domain constraints as JSON/dict; requires a schema or clearsig-typed-data annotations
    :param deployments: complete binding list, including the chain/address used to obtain the ABI
    :param metadata: initial typed metadata, enriched by NatSpec; explicit owner/url arguments override its values
    :param owner: the display name of the owner or target of the contract / message to be clear signed
    :param url: URL with more info on the entity the user interacts with
    :param natspec: compiler userdoc/devdoc JSON or artifact (including an optional ABI)
    :param userdoc: optional split compiler user documentation JSON
    :param devdoc: optional split compiler developer documentation JSON
    :param warnings: optional diagnostic collector; otherwise diagnostics are logged
    :param project_defaults: project-level custom formatter tags, using the same keys as compiler NatSpec
    :param example_renderer: explicitly opt into example execution with this renderer
    :raises ValueError: NatSpec lint errors, invalid method exclusions, or conflicting inputs
    :return: a generated v2 ERC-7730 descriptor
    """

    docs = parse_natspec(natspec, userdoc, devdoc, project_defaults)
    metadata = metadata.model_copy(deep=True) if metadata is not None else _generate_metadata(owner=None, url=None)
    if owner is not None:
        metadata = metadata.model_copy(update={"owner": owner})
    if url is not None:
        info = metadata.info.model_copy(update={"url": url}) if metadata.info else InputOwnerInfo(url=url)
        metadata = metadata.model_copy(update={"info": info})
    metadata = apply_metadata_annotations(docs, metadata)
    if abi is None and eip712_schema is None and docs.abi is not None:
        abi = json.dumps(docs.abi)

    if selected := bridge_methods(docs):
        if eip712_schema is not None:
            raise ValueError("Cannot combine clearsig-typed-data annotations with an explicit EIP-712 schema.")
        eip712_schema = infer_schemas(abi, selected)
        docs = message_docs(docs, selected)
    if eip712_domain is not None and eip712_schema is None:
        raise ValueError("eip712_domain requires an EIP-712 schema or clearsig-typed-data annotation")
    context, trees = _generate_context(chain_id, contract_address, abi, eip712_schema)
    if eip712_domain is not None:
        if not isinstance(context, InputEIP712Context):
            raise ValueError("eip712_domain requires an EIP-712 schema")
        domain = (
            InputDomain.model_validate_json(eip712_domain)
            if isinstance(eip712_domain, str | bytes)
            else InputDomain.model_validate(eip712_domain, strict=False)
        )
        context = context.model_copy(update={"eip712": context.eip712.model_copy(update={"domain": domain})})
    if deployments is not None:
        bindings = TypeAdapter(list[InputDeployment]).validate_python(deployments, strict=False)
        keys = [(binding.chainId, binding.address.lower()) for binding in bindings]
        if not keys or (chain_id, contract_address.lower()) not in keys:
            raise ValueError("deployments must include the generation chain_id and contract_address")
        if len(set(keys)) != len(keys):
            raise ValueError("deployments contains duplicate chain/address pairs")
        if isinstance(context, InputContractContext):
            context = context.model_copy(
                update={"contract": context.contract.model_copy(update={"deployments": bindings})}
            )
        else:
            context = context.model_copy(update={"eip712": context.eip712.model_copy(update={"deployments": bindings})})
    display = _generate_display(trees)
    doc_keys = None
    if isinstance(context, InputEIP712Context):
        schemas = TypeAdapter(list[EIP712Schema]).validate_python(context.eip712.schemas, strict=False)
        doc_keys = {eip712_encode_type(schema): schema.primaryType for schema in schemas}
    if any(value is not None for value in (natspec, userdoc, devdoc, project_defaults)):
        display, metadata = apply_natspec(display, trees, docs, metadata, doc_keys=doc_keys)
    display = display.model_copy(
        update={
            "formats": {
                key: format.model_copy(update={"fields": _default_address_sources(format.fields)})
                for key, format in display.formats.items()
            }
        }
    )
    if isinstance(context, InputContractContext):
        # v2 consumers decode named paths from declaration keys; canonical keys
        # remain the NatSpec join index until the overlay has been applied.
        functions = get_functions(
            TypeAdapter(list[ABI]).validate_python(context.contract.abi, strict=False), include_read_only=True
        ).functions.values()
        declarations = {
            compute_signature(function): _function_declaration(function.model_dump()) for function in functions
        }
        for declaration in declarations.values():
            validate_function_declaration(declaration)
        display = display.model_copy(
            update={"formats": {declarations[key]: value for key, value in display.formats.items()}}
        )
        context = context.model_copy(update={"contract": context.contract.model_copy(update={"abi": None})})
    if warnings is not None:
        warnings.extend(docs.warnings)
    else:
        for message in docs.warnings:
            logging.getLogger(__name__).warning(message)
    descriptor = InputERC7730Descriptor.model_validate(
        {
            "$schema": "https://eips.ethereum.org/assets/eip-7730/erc7730-v2.1.0.schema.json",
            "context": context,
            "metadata": metadata,
            "display": display,
        }
    )

    if example_renderer is not None:
        report = run_natspec_examples(
            descriptor,
            natspec=natspec,
            userdoc=userdoc,
            devdoc=devdoc,
            config=docs.project_defaults.get("examples"),
            renderer=example_renderer,
            require_all=False,
        )
        for message in report.sanity_unavailable:
            if warnings is not None:
                warnings.append(message)
            else:
                logging.getLogger(__name__).warning(message)
    return descriptor


def _default_address_sources(fields: list[InputField]) -> list[InputField]:
    """Fill omitted address-name sources after all authored formatter overrides."""
    result: list[InputField] = []
    for field in fields:
        if isinstance(field, InputFieldGroup):
            field = field.model_copy(update={"fields": _default_address_sources(field.fields)})
        elif isinstance(field, InputFieldDescription) and field.format == FieldFormat.ADDRESS_NAME:
            params = field.params
            if params is None:
                field = field.model_copy(update={"params": InputAddressNameParameters(sources=["local", "ens"])})
            elif isinstance(params, InputAddressNameParameters) and params.sources is None:
                field = field.model_copy(update={"params": params.model_copy(update={"sources": ["local", "ens"]})})
        result.append(field)
    return result


def _generate_metadata(owner: str | None, url: HttpUrl | None) -> InputMetadata:
    info = InputOwnerInfo(url=url) if url is not None else None
    return InputMetadata(owner=owner, info=info)


def _generate_context(
    chain_id: int, contract_address: Address, abi: str | bytes | None, eip712_schema: str | bytes | None
) -> tuple[InputContractContext | InputEIP712Context, dict[str, SchemaTree]]:
    if eip712_schema is not None:
        return _generate_context_eip712(chain_id, contract_address, eip712_schema)
    return _generate_context_calldata(chain_id, contract_address, abi)


def _generate_context_eip712(
    chain_id: int, contract_address: Address, eip712_schema: str | bytes
) -> tuple[InputEIP712Context, dict[str, SchemaTree]]:
    schemas = TypeAdapter(list[EIP712Schema]).validate_json(eip712_schema)

    context = InputEIP712Context(
        eip712=InputEIP712(
            schemas=[schema.model_dump(mode="json") for schema in schemas],
            deployments=[InputDeployment(chainId=chain_id, address=contract_address)],
        )
    )

    trees = {eip712_encode_type(schema): eip712_schema_to_tree(schema) for schema in schemas}

    return context, trees


def _generate_context_calldata(
    chain_id: int, contract_address: Address, abi: str | bytes | None
) -> tuple[InputContractContext, dict[str, SchemaTree]]:
    if abi is None:
        raise ValueError("NatSpec calldata generation requires an ABI or a compiler artifact containing an ABI.")
    abis = TypeAdapter(list[ABI]).validate_json(abi)

    functions = [
        name_unnamed_inputs(function) for function in get_functions(abis, include_read_only=True).functions.values()
    ]

    context = InputContractContext(
        contract=InputContract(
            abi=[function.model_dump(mode="json") for function in functions],
            deployments=[InputDeployment(chainId=chain_id, address=contract_address)],
        )
    )

    trees = {compute_signature(function): abi_function_to_tree(function) for function in functions}

    return context, trees


def _generate_display(trees: dict[str, SchemaTree]) -> InputDisplay:
    return InputDisplay(formats=_generate_formats(trees))


def _generate_formats(trees: dict[str, SchemaTree]) -> dict[str, InputFormat]:
    formats: dict[str, InputFormat] = {}
    for name, tree in trees.items():
        formats[name] = InputFormat(fields=list(_generate_fields(schema=tree, path=ROOT_DATA_PATH)))
    return formats


def _generate_fields(schema: SchemaTree, path: DataPath) -> Generator[InputField, Any, Any]:
    match schema:
        case SchemaStruct(components=components) if path == ROOT_DATA_PATH:
            for name, component in components.items():
                if name:
                    yield from _generate_fields(component, data_path_append(path, Field(identifier=name)))

        case SchemaStruct(components=components):
            fields = [
                field
                for name, component in components.items()
                for field in _generate_fields(component, DataPath(absolute=False, elements=[Field(identifier=name)]))
                if name
            ]
            yield InputFieldGroup(path=path, fields=fields)

        case SchemaArray(component=component):
            # Accumulate all consecutive array dimensions
            array_dims = 1
            inner_component = component
            while isinstance(inner_component, SchemaArray):
                array_dims += 1
                inner_component = inner_component.component

            # Build path with all array dimensions
            path_with_arrays = path
            for _ in range(array_dims):
                path_with_arrays = data_path_append(path_with_arrays, Array())

            match inner_component:
                case SchemaStruct(components=components):
                    # For structs, create nested fields with all arrays in the path
                    fields = [
                        field
                        for name, sub_component in components.items()
                        for field in _generate_fields(
                            sub_component, DataPath(absolute=False, elements=[Field(identifier=name)])
                        )
                        if name
                    ]
                    yield InputFieldGroup(path=path_with_arrays, fields=fields)
                case SchemaLeaf():
                    # For basic types, directly yield with all arrays in the path
                    yield from _generate_fields(inner_component, path_with_arrays)
                case _:
                    assert_never(schema)

        case SchemaLeaf(data_type=data_type):
            name = _get_leaf_name(path)
            format, params = _generate_field(name, data_type)
            yield InputFieldDescription(path=path, label=name, format=format, params=params)

        case _:
            assert_never(schema)


def _generate_field(name: str, data_type: ABIDataType) -> tuple[FieldFormat, InputFieldParameters | None]:
    match data_type:
        case ABIDataType.UINT | ABIDataType.INT:
            # other applicable formats could be TOKEN_AMOUNT, UNIT or ENUM, but we can't tell

            if _contains_any_of(name, "duration"):
                return FieldFormat.DURATION, None

            if _contains_any_of(name, "height"):
                return FieldFormat.DATE, InputDateParameters(encoding=DateEncoding.BLOCKHEIGHT)

            if _contains_any_of(name, "deadline", "expiration", "until", "time", "timestamp"):
                return FieldFormat.DATE, InputDateParameters(encoding=DateEncoding.TIMESTAMP)

            return FieldFormat.RAW, None

        case ABIDataType.UFIXED | ABIDataType.FIXED:
            return FieldFormat.RAW, None

        case ABIDataType.ADDRESS:
            if _contains_any_of(name, "collection", "nft"):
                return FieldFormat.ADDRESS_NAME, InputAddressNameParameters(types=[AddressNameType.COLLECTION])

            if _contains_any_of(name, "spender"):
                return FieldFormat.ADDRESS_NAME, InputAddressNameParameters(types=[AddressNameType.CONTRACT])

            if _contains_any_of(name, "asset", "token"):
                return FieldFormat.ADDRESS_NAME, InputAddressNameParameters(types=[AddressNameType.TOKEN])

            if _contains_any_of(name, "from", "to", "owner", "recipient", "receiver", "account"):
                return FieldFormat.ADDRESS_NAME, InputAddressNameParameters(
                    types=[AddressNameType.EOA, AddressNameType.WALLET]
                )

            return FieldFormat.ADDRESS_NAME, InputAddressNameParameters(types=list(AddressNameType))

        case ABIDataType.BOOL:
            return FieldFormat.RAW, None

        case ABIDataType.BYTES:
            if _contains_any_of(name, "calldata"):
                return FieldFormat.CALL_DATA, None

            return FieldFormat.RAW, None

        case ABIDataType.STRING:
            return FieldFormat.RAW, None

        case _:
            assert_never(data_type)


def _get_leaf_name(path: DataPath) -> str:
    for element in reversed(path.elements):
        match element:
            case Field(identifier=name):
                return to_title(name).strip()
            case Array() | ArrayElement() | ArraySlice():
                continue
            case _:
                assert_never(element)
    return "unknown"


def _contains_any_of(name: str, *values: str) -> bool:
    name_lower = name.lower()
    return any(value in name_lower for value in values)


def _function_declaration(function: dict[str, Any]) -> str:
    def parameter(component: dict[str, Any]) -> str:
        data_type = component["type"]
        if data_type.startswith("tuple"):
            data_type = "(" + ",".join(parameter(child) for child in component["components"]) + ")" + data_type[5:]
        return data_type + (" " + component["name"] if component.get("name") else "")

    return function["name"] + "(" + ",".join(parameter(part) for part in function["inputs"]) + ")"
