"""Compare V2 display paths with reference ABIs."""

from collections.abc import Sequence
from typing import final, override

from erc7730.common import client
from erc7730.common.abi import compute_signature, get_functions, parse_signature, signature_to_selector
from erc7730.common.output import OutputAdder
from erc7730.lint.v2 import ERC7730Linter
from erc7730.lint.v2.path_schemas import compute_format_schema_paths
from erc7730.model.abi import Component, Function, InputOutput
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.paths.path_ops import data_path_starts_with
from erc7730.model.paths.path_schemas import compute_abi_schema_paths
from erc7730.model.resolved.v2.context import ResolvedContractContext, ResolvedEIP712Context
from erc7730.model.resolved.v2.descriptor import ResolvedERC7730Descriptor


@final
class ValidateDisplayFieldsLinter(ERC7730Linter):
    """Validate declared paths/types offline and check declared fields against reference ABIs when available."""

    @override
    def lint(
        self, input_descriptor: InputERC7730Descriptor, descriptor: ResolvedERC7730Descriptor, out: OutputAdder
    ) -> None:
        match descriptor.context:
            case ResolvedEIP712Context():
                pass  # no ABI comparison for EIP-712 messages
            case ResolvedContractContext():
                self._validate_contract_display_fields(input_descriptor, descriptor, out)

    @classmethod
    def _validate_contract_display_fields(
        cls, input_descriptor: InputERC7730Descriptor, descriptor: ResolvedERC7730Descriptor, out: OutputAdder
    ) -> None:
        context = descriptor.context
        if not isinstance(context, ResolvedContractContext):
            return

        if (deployments := context.contract.deployments) is None:
            return

        # Try to fetch ABI from Sourcify or Etherscan for the first deployment that succeeds
        reference_abis = None
        explorer_url = None
        for deployment in deployments:
            try:
                if (abis := client.get_contract_abis(deployment.chainId, deployment.address)) is None:
                    continue
            except Exception as e:
                out.warning(
                    title="Could not fetch ABI",
                    message=f"Fetching reference ABI for chain id {deployment.chainId} failed, display fields will "
                    f"not be validated against ABI: {e}",
                )
                continue

            reference_abis = get_functions(abis)
            try:
                explorer_url = str(client.get_contract_explorer_url(deployment.chainId, deployment.address))
            except NotImplementedError:
                explorer_url = f"<chain id {deployment.chainId} address {deployment.address}>"
            break

        if reference_abis is None:
            return

        if reference_abis.proxy:
            return out.info(
                title="Proxy contract",
                message=f"Contract {explorer_url} is likely to be a proxy, validation of display fields skipped",
            )

        # The declared names also identify unnamed tuple members in the reference
        # ABI. Preserve reference names where present, filling only blank names.
        declared_abis_by_selector = parse_declared_abis(input_descriptor)
        abi_paths_by_selector = {
            selector: compute_abi_schema_paths(cls._with_declared_names(abi, declared_abis_by_selector.get(selector)))
            for selector, abi in reference_abis.functions.items()
        }

        # Validate display field paths against ABI paths
        for selector, fmt in descriptor.display.formats.items():
            if selector not in abi_paths_by_selector:
                out.warning(
                    title="Unknown selector",
                    message=f"Selector {selector} in display formats not found in reference ABI (see {explorer_url}). "
                    f"This could indicate a custom function or a stale descriptor.",
                )
                continue

            format_paths = compute_format_schema_paths(fmt)
            abi_paths = abi_paths_by_selector[selector]

            # Check for display fields referencing non-existent ABI paths.
            # A format path is valid if it matches an ABI path exactly OR is a prefix of one
            # (e.g. defining a field for an array root covers all nested elements).
            for path in format_paths.data_paths - abi_paths:
                if not any(data_path_starts_with(abi_path, path) for abi_path in abi_paths):
                    out.error(
                        title="Invalid display field",
                        message=f"A display field is defined for `{path}`, but it does not exist in function "
                        f"{selector} ABI (see {explorer_url}). Please check the field path is valid.",
                    )

            # Check for ABI paths without corresponding display fields.
            # An ABI path is covered if it matches a format path exactly OR a format path is a prefix of it
            # (e.g. a field defined for an array root covers all descendant paths).
            for path in abi_paths - format_paths.data_paths:
                if not any(data_path_starts_with(path, fmt_path) for fmt_path in format_paths.data_paths):
                    out.warning(
                        title="Missing display field",
                        message=f"No display field is defined for path `{path}` in function {selector} "
                        f"(see {explorer_url}).",
                    )

        # Check selector exhaustiveness: all ABI functions should have display formats
        for selector, abi in reference_abis.functions.items():
            if selector not in descriptor.display.formats:
                out.warning(
                    title="Missing display format",
                    message=f"Function {compute_signature(abi)} (selector: {selector}) exists in reference ABI "
                    f"(see {explorer_url}) but has no display format defined in the descriptor.",
                )

    @classmethod
    def _with_declared_names(cls, abi: Function, declared: Function | None) -> Function:
        if declared is None or compute_signature(abi) != compute_signature(declared):
            return abi

        def merge(
            parameters: Sequence[InputOutput | Component], names: Sequence[InputOutput | Component]
        ) -> list[InputOutput | Component]:
            result: list[InputOutput | Component] = []
            for parameter, named in zip(parameters, names, strict=True):
                result.append(
                    parameter.model_copy(
                        update={
                            "name": parameter.name or named.name,
                            "components": merge(parameter.components, named.components)
                            if parameter.components is not None and named.components is not None
                            else parameter.components,
                        }
                    )
                )
            return result

        return abi.model_copy(update={"inputs": merge(abi.inputs or [], declared.inputs or [])})


def parse_declared_abis(input_descriptor: InputERC7730Descriptor) -> dict[str, Function]:
    """
    Parse the function signatures declared as display format keys, indexed by selector.

    Format keys that are already selectors declare no parameter name, and are skipped.

    :param input_descriptor: input descriptor the linted descriptor was resolved from
    :return: declared ABI functions, by selector
    """
    declared_abis: dict[str, Function] = {}
    for format_id in input_descriptor.display.formats:
        if format_id.startswith("0x"):
            continue
        try:
            declared_abi = parse_signature(format_id)
        except ValueError:
            continue  # invalid signatures are reported by the resolution step
        declared_abis[signature_to_selector(compute_signature(declared_abi))] = declared_abi
    return declared_abis
