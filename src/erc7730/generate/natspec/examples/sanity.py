"""Bounded ABI mutations and independent assertions for display sanity checks.

This is a test oracle for simple formatters, not a wallet renderer. Unsupported
oracles are reported explicitly; the external renderer still handles display.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from eth_abi.abi import encode
from eth_abi.grammar import parse
from eth_utils.abi import collapse_if_tuple, function_signature_to_4byte_selector
from eth_utils.address import to_checksum_address

from erc7730.common.abi import ABIDataType, compute_signature, parse_signature
from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.examples.constants import (
    DEFAULT_EXAMPLE_ADDRESS,
    DESCRIPTOR_FILENAME,
    TRANSACTION_FROM_PATH,
)
from erc7730.generate.natspec.examples.maps import check_maps, lookup_map, map_variants
from erc7730.generate.natspec.examples.models import (
    ExampleCase,
    ExampleConfig,
    ExampleFixture,
    ExampleRenderer,
    RenderedDisplay,
)
from erc7730.generate.natspec.examples.results import render_results, replay_results
from erc7730.generate.natspec.examples.transactions import raw_transaction, transaction_container
from erc7730.generate.natspec.examples.typed_data import message_schema, signing_domain, typed_input
from erc7730.generate.natspec.examples.values import UnavailableError, named_value, read_values
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.model.input.v2.context import InputContractContext
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.input.v2.format import DateEncoding, FieldFormat, VisibilityRule
from erc7730.model.paths import ContainerPath, DataPath
from erc7730.model.resolved.display import ResolvedValueConstant, ResolvedValuePath
from erc7730.model.resolved.v2.display import (
    ResolvedDateParameters,
    ResolvedFieldDescription,
    ResolvedFormat,
    ResolvedTokenAmountParameters,
    ResolvedValueMap,
    ResolvedVisibilityConditions,
    iter_field_descriptions,
)

MAX_GENERATED_NODES = 512
MAX_ABI_DEPTH = 8
MAX_ARRAY_LENGTH = 16
MAX_TOKEN_DECIMALS = 255
MAX_UINT256_DECIMAL_EXPONENT = 77
MAX_TIMESTAMP = 253402300799  # 9999-12-31 23:59:59 UTC
DEFAULT_ENCRYPTED_LABEL = "[Encrypted]"
DEFAULT_UNLIMITED_LABEL = "Unlimited"


def _baseline(part: dict[str, Any], length: int = 2, depth: int = 0, budget: list[int] | None = None) -> Any:
    budget = [MAX_GENERATED_NODES] if budget is None else budget
    budget[0] -= 1
    if budget[0] < 0:
        raise UnavailableError(f"ABI value exceeds {MAX_GENERATED_NODES} generated nodes")
    if depth > MAX_ABI_DEPTH:
        raise UnavailableError("ABI nesting exceeds the sanity budget")
    type_ = parse(part["type"])
    if type_.is_array:
        size = type_.arrlist[-1][0] if type_.arrlist[-1] else length
        if size > MAX_ARRAY_LENGTH:
            raise UnavailableError(f"fixed arrays larger than {MAX_ARRAY_LENGTH} elements exceed the sanity budget")
        return [
            _baseline(part | {"type": type_.item_type.to_type_str()}, length, depth + 1, budget) for _ in range(size)
        ]
    if type_.base == "tuple":
        return [_baseline(child, length, depth + 1, budget) for child in part["components"]]
    if type_.base in (ABIDataType.UINT, ABIDataType.INT):
        return 1
    if type_.base == ABIDataType.ADDRESS:
        return DEFAULT_EXAMPLE_ADDRESS
    if type_.base == ABIDataType.BOOL:
        return False
    if type_.base == ABIDataType.STRING:
        return "Example"
    if type_.base == ABIDataType.BYTES:
        return bytes(range(type_.sub if type_.sub is not None else 32))
    raise UnavailableError(f"no sanity generator for {part['type']}")


def _mutations(part: dict[str, Any], value: Any, numbers: list[int]) -> Iterator[tuple[str, Any]]:
    type_ = parse(part["type"])
    if type_.is_array:
        if value:
            child = part | {"type": type_.item_type.to_type_str()}
            for name, changed in _mutations(child, value[0], numbers):
                yield f"first.{name}", [changed, *value[1:]]
    elif type_.base == "tuple":
        for index, child in enumerate(part["components"]):
            for name, changed in _mutations(child, value[index], numbers):
                yield f"{child['name']}.{name}", [*value[:index], changed, *value[index + 1 :]]
    elif type_.base in (ABIDataType.UINT, ABIDataType.INT):
        signed, bits = type_.base == ABIDataType.INT, type_.sub
        low, high = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
        for number in dict.fromkeys([0, 1, low, high, *numbers]):
            if isinstance(number, int) and not isinstance(number, bool) and low <= number <= high:
                yield str(number), number
    elif type_.base == ABIDataType.ADDRESS:
        for address in ["0x" + "00" * 20, "0x" + "22" * 20]:
            yield address, address
    elif type_.base == ABIDataType.BOOL:
        yield "true", True
    elif type_.base == ABIDataType.STRING:
        for index, text in enumerate(["", "x" * 256, "to Alice {amount}\n\u202e"]):
            yield f"text{index}", text
    elif type_.base == ABIDataType.BYTES:
        yield "zero-bytes", bytes(len(value))
        if type_.sub is None:
            yield "empty-bytes", b""
            yield "long-bytes", bytes(range(64))


def _decimal(value: int, decimals: int) -> str:
    if not 0 <= decimals <= MAX_TOKEN_DECIMALS:
        raise UnavailableError("token decimals exceed the sanity budget")
    whole, remainder = divmod(abs(value), 10**decimals)
    fraction = f"{remainder:0{decimals}d}".rstrip("0") if remainder else ""
    return ("-" if value < 0 else "") + str(whole) + ("." + fraction if fraction else "")


def _expected(
    field: ResolvedFieldDescription,
    values: list[Any],
    root: dict[str, Any],
    container: dict[str, Any],
    settings: ExampleConfig,
) -> list[str] | None:
    if field.encryption is not None:
        if settings.encryption_mode == "fallback":
            return [field.encryption.fallbackLabel or DEFAULT_ENCRYPTED_LABEL for _ in values]
        return None  # external decryption requires authored expected plaintext
    if field.format in (None, FieldFormat.RAW):
        return [
            str(v).lower() if isinstance(v, bool) else "0x" + v.hex() if isinstance(v, bytes) else str(v)
            for v in values
        ]
    if field.format == FieldFormat.DURATION and all(isinstance(v, int) and v >= 0 for v in values):
        return [f"{v // 3600:02d}:{v // 60 % 60:02d}:{v % 60:02d}" for v in values]
    if (
        field.format == FieldFormat.DATE
        and isinstance(field.params, ResolvedDateParameters)
        and field.params.encoding == DateEncoding.TIMESTAMP
    ):
        return [
            datetime.fromtimestamp(v, UTC).isoformat(sep=" ", timespec="seconds").replace("+00:00", "Z") for v in values
        ]
    if field.format == FieldFormat.ADDRESS_NAME:
        # Names have provider/type/source rules. Check unknown-address fallback only.
        if any(
            str(v).lower() in settings.data_provider.address_names or str(v).lower() in settings.data_provider.ens_names
            for v in values
        ):
            return None
        return [to_checksum_address(v) for v in values]
    if field.format == FieldFormat.TOKEN_AMOUNT and isinstance(field.params, ResolvedTokenAmountParameters):
        if isinstance(field.params.chainId, ResolvedValueMap):
            return None  # The fixture metadata provider is not indexed by chain.
        token = field.params.token
        if isinstance(token, ResolvedValueMap):
            keys = read_values(token.keyPath, root, container)
            if len(keys) != 1:
                return None
            token = lookup_map(token.values, keys[0])
        tokens = (
            read_values(token.path, root, container)
            if isinstance(token, ResolvedValuePath)
            else [token.value]
            if isinstance(token, ResolvedValueConstant)
            else []
        )
        if not tokens:
            return None
        result = []
        for index, value in enumerate(values):
            address = str(tokens[index] if len(tokens) > 1 else tokens[0]).lower()
            metadata = settings.data_provider.tokens.get(address)
            if not isinstance(value, int):
                return None
            if metadata is None:
                result.append(str(value))
                continue
            if field.params.nativeCurrencyAddress is not None:
                return None
            threshold = field.params.threshold
            if threshold is not None and value >= int(str(threshold), 16 if str(threshold).startswith("0x") else 10):
                result.append(f"{field.params.message or DEFAULT_UNLIMITED_LABEL} {metadata.symbol}")
            else:
                result.append(f"{_decimal(value, metadata.decimals)} {metadata.symbol}")
        return result
    return None


def run_sanity_examples(
    descriptor: InputERC7730Descriptor, settings: ExampleConfig, renderer: ExampleRenderer
) -> ExampleFixture:
    """Generate deterministic cases, check invariants, then replay through the runner."""
    fixture, expectations = _build_sanity_cases(descriptor, settings)
    if not fixture.tests:
        return fixture
    captured = _check_sanity_results(descriptor, settings, renderer, fixture, expectations)
    replay_results(descriptor, fixture, renderer, captured, context="Sanity")
    fixture.sanity_unavailable = list(dict.fromkeys(fixture.sanity_unavailable))
    return fixture


def _build_sanity_cases(
    descriptor: InputERC7730Descriptor, settings: ExampleConfig
) -> tuple[ExampleFixture, dict[str, tuple[ResolvedFormat, dict[str, Any], dict[str, Any]]]]:
    fixture = ExampleFixture(descriptor=DESCRIPTOR_FILENAME, data_provider=settings.data_provider, tests=[])
    typed = not isinstance(descriptor.context, InputContractContext)
    deployment = None
    typed_container: dict[str, Any] = {}
    if isinstance(descriptor.context, InputContractContext):
        if len(descriptor.context.contract.deployments) != 1:
            fixture.sanity_unavailable.append("Automatic cases currently require one deployment.")
            return fixture, {}
        deployment = descriptor.context.contract.deployments[0]
    else:
        try:
            _, _, typed_container = signing_domain(descriptor, settings)
        except ValueError as exc:
            fixture.sanity_unavailable.append(f"Automatic EIP-712 examples unavailable: {exc}")
            return fixture, {}
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    if resolved is None or out.has_errors:
        raise ValueError(f"Cannot generate sanity cases: {[item.message for item in out.outputs]}")
    ValidateSchemaLinter().lint(descriptor, resolved, out)
    if out.has_errors:
        raise ValueError(f"Invalid sanity descriptor: {[item.message for item in out.outputs]}")
    expectations: dict[str, tuple[ResolvedFormat, dict[str, Any], dict[str, Any]]] = {}
    for declaration in descriptor.display.formats:
        if typed:
            try:
                signature, _, parts = message_schema(declaration)
            except ValueError as exc:
                fixture.sanity_unavailable.append(f"{declaration}: {exc}")
                continue
            selector = b""
            fmt = resolved.display.formats[declaration]
        else:
            function = parse_signature(declaration)
            signature = compute_signature(function)
            selector = function_signature_to_4byte_selector(signature)
            fmt = resolved.display.formats["0x" + selector.hex()]
            parts = [part.model_dump() for part in function.inputs or []]
        if any(field.format == FieldFormat.CALL_DATA for field in iter_field_descriptions(fmt.fields)):
            fixture.sanity_unavailable.append(f"{signature}: embedded calls need authored valid inner calldata.")
            continue
        try:
            base = [_baseline(part) for part in parts]
        except UnavailableError as exc:
            fixture.sanity_unavailable.append(f"{signature}: {exc}")
            continue
        map_cases: list[tuple[str, list[Any]]] = []
        if typed:
            if descriptor.metadata.maps:
                fixture.sanity_unavailable.append(
                    f"{signature}: automatic typed-data map branch selection is unsupported."
                )
        else:
            base, map_cases, map_unavailable = map_variants(declaration, fmt, parts, base, settings.max_sanity_cases)
            fixture.sanity_unavailable.extend(map_unavailable)
        variants = _sanity_variants(parts, base, map_cases, fmt, settings, signature, fixture.sanity_unavailable)
        seen: set[bytes] = set()
        for name, values in variants:
            calldata = selector + encode([collapse_if_tuple(part) for part in parts], values)
            if calldata in seen:
                continue
            if len(seen) >= settings.max_sanity_cases:
                fixture.sanity_unavailable.append(
                    f"{signature}: additional mutations omitted at maxSanityCases={settings.max_sanity_cases}."
                )
                break
            seen.add(calldata)
            root = {part["name"]: named_value(part, value) for part, value in zip(parts, values, strict=True)}
            if typed:
                container = typed_container
            else:
                assert deployment is not None  # nosec B101 - internal invariant, not input validation
                container = transaction_container(deployment, settings)
            try:
                try:
                    check_maps(fmt, root, container)
                except ValueError as exc:
                    raise UnavailableError(f"{exc}; wallet rejection needs a map-aware rejection adapter") from exc
                for field in iter_field_descriptions(fmt.fields):
                    field_values = [field.value]
                    if isinstance(field.path, (DataPath, ContainerPath)):
                        field_values = read_values(field.path, root, container)
                        if field.format == FieldFormat.DATE and any(
                            not isinstance(v, int) or not 0 <= v <= MAX_TIMESTAMP for v in field_values
                        ):
                            raise UnavailableError("date mutation is outside the supported test calendar")
                    if (
                        isinstance(field.visible, ResolvedVisibilityConditions)
                        and field.visible.mustMatch is not None
                        and any(v not in field.visible.mustMatch for v in field_values)
                    ):
                        raise UnavailableError(
                            "mustMatch rejection diagnostics require a constraint-aware runner adapter"
                        )
            except UnavailableError as exc:
                fixture.sanity_unavailable.append(f"{signature}/{name}: {exc}")
                continue
            description = f"sanity: {signature} {name}"
            payload: dict[str, Any]
            if typed:
                payload = {"data": typed_input(declaration, values, descriptor, settings)}
            else:
                assert deployment is not None  # nosec B101 - internal invariant, not input validation
                payload = {"rawTx": raw_transaction(deployment, calldata), "from": container[TRANSACTION_FROM_PATH]}
            fixture.tests.append(
                ExampleCase.model_validate(
                    {"description": description, **payload, "expected": RenderedDisplay(intent="", fields=[])}
                )
            )
            expectations[description] = fmt, root, container
    return fixture, expectations


def _check_sanity_results(
    descriptor: InputERC7730Descriptor,
    settings: ExampleConfig,
    renderer: ExampleRenderer,
    fixture: ExampleFixture,
    expectations: dict[str, tuple[ResolvedFormat, dict[str, Any], dict[str, Any]]],
) -> dict[str, RenderedDisplay]:
    captured = render_results(descriptor, fixture, renderer, context="Sanity")
    for description, rendered in captured.items():
        fmt, root, container = expectations[description]
        _check_sanity_display(description, rendered, fmt, root, container, settings, fixture.sanity_unavailable)
    return captured


def _sanity_variants(
    parts: list[dict[str, Any]],
    base: list[Any],
    map_cases: list[tuple[str, list[Any]]],
    fmt: ResolvedFormat,
    settings: ExampleConfig,
    signature: str,
    unavailable: list[str],
) -> list[tuple[str, list[Any]]]:
    numbers = [59, 60, 3599, 3600, 1_700_000_000]
    for token in settings.data_provider.tokens.values():
        if token.decimals <= MAX_UINT256_DECIMAL_EXPONENT:
            unit = 10**token.decimals
            numbers.extend([unit - 1, unit, unit + 1])
    for field in iter_field_descriptions(fmt.fields):
        if isinstance(field.visible, ResolvedVisibilityConditions):
            for candidate in field.visible.ifNotIn or field.visible.mustMatch or []:
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    numbers.extend([candidate - 1, candidate, candidate + 1])
        if isinstance(field.params, ResolvedTokenAmountParameters) and field.params.threshold is not None:
            t = int(str(field.params.threshold), 16 if str(field.params.threshold).startswith("0x") else 10)
            numbers.extend([t - 1, t, t + 1])
    variants = [("baseline", base), *map_cases]
    for length in (0, 1, 3):
        try:
            variants.append((f"array-length-{length}", [_baseline(part, length) for part in parts]))
        except UnavailableError as exc:
            unavailable.append(f"{signature}: array-length-{length}: {exc}")
    for index, part in enumerate(parts):
        variants.extend(
            (f"{part['name']}.{name}", [*base[:index], changed, *base[index + 1 :]])
            for name, changed in _mutations(part, base[index], numbers)
        )
    return variants


def _check_sanity_display(
    description: str,
    rendered: RenderedDisplay,
    fmt: ResolvedFormat,
    root: dict[str, Any],
    container: dict[str, Any],
    settings: ExampleConfig,
    unavailable: list[str],
) -> None:
    intent = (
        fmt.intent if isinstance(fmt.intent, str) else ", ".join(f"{k}: {v}" for k, v in (fmt.intent or {}).items())
    )
    if rendered.intent != intent:
        raise ValueError(f"{description}: static intent changed")
    expected: dict[str, list[str]] = defaultdict(list)
    counts: dict[str, int] = defaultdict(int)
    unchecked: set[str] = set()
    optional: set[str] = set()
    for field in iter_field_descriptions(fmt.fields):
        values = (
            read_values(field.path, root, container)
            if isinstance(field.path, (DataPath, ContainerPath))
            else [field.value]
        )
        if field.visible == VisibilityRule.NEVER or (
            isinstance(field.visible, ResolvedVisibilityConditions) and field.visible.mustMatch is not None
        ):
            values = []
        elif isinstance(field.visible, ResolvedVisibilityConditions) and field.visible.ifNotIn is not None:
            values = [v for v in values if v not in field.visible.ifNotIn]
        if field.label is None:
            continue
        counts[field.label] += len(values)
        if field.visible == VisibilityRule.OPTIONAL:
            optional.add(field.label)
        oracle = _expected(field, values, root, container, settings)
        if oracle is not None:
            expected[field.label].extend(oracle)
        else:
            unchecked.add(field.label)
            unavailable.append(
                f"{description.split(' ', 2)[1]}: no independent {field.format} value oracle for {field.label}."
            )
    for label, count in counts.items():
        actual = [f.value for f in rendered.fields if f.label == label]
        if label in optional and not actual:
            continue
        if len(actual) != count:
            raise ValueError(f"{description}: field {label!r} count {len(actual)}, expected {count}")
        if label in expected and label not in unchecked and actual != expected[label]:
            raise ValueError(f"{description}: field {label!r} rendered {actual!r}, expected {expected[label]!r}")
    if fmt.interpolatedIntent is not None:
        # Cross-check interpolation against the renderer's separately formatted fields.
        template = fmt.interpolatedIntent
        replacements = {}
        for field in iter_field_descriptions(fmt.fields):
            if field.path is not None and field.label is not None:
                matches = [f.value for f in rendered.fields if f.label == field.label]
                if len(matches) == 1 and isinstance(matches[0], str):
                    replacements[str(field.path).removeprefix("#.")] = matches[0]
        from erc7730.common.templates import translate_template

        try:
            pieces: list[str] = []

            def substitute(path: str, pieces: list[str] = pieces, replacements: dict[str, str] = replacements) -> str:
                pieces.append(replacements[path.removeprefix("#.")])
                return str(len(pieces) - 1)

            indexed = translate_template(template, substitute, natspec=False, literal_backticks=True)
            wanted = indexed.format(*pieces)
            if rendered.interpolated_intent != wanted:
                raise ValueError(f"{description}: interpolated intent differs from separately rendered fields")
        except KeyError:
            unavailable.append(f"{description}: interpolation needs an array/constant oracle.")
