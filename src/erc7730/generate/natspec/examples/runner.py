"""Run function-level NatSpec examples as in-memory v2 display tests.

Only example values are parsed here, never Solidity source. Display rendering is
supplied by a registry-compatible runner rather than duplicated in this package.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - explicitly configured external renderer
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from eth_abi.abi import encode
from eth_abi.exceptions import EncodingError
from eth_abi.grammar import parse
from eth_utils.abi import collapse_if_tuple, function_signature_to_4byte_selector
from lark import Lark, Tree
from lark.exceptions import LarkError

from erc7730.common.abi import ABIDataType, compute_signature, parse_signature
from erc7730.common.schema_types import validate_function_declaration
from erc7730.generate.natspec import JSONInput, NatSpec, parse_natspec
from erc7730.generate.natspec.documents import custom_tag
from erc7730.generate.natspec.eip712_bridge import bridge_methods, message_docs
from erc7730.generate.natspec.examples.constants import (
    DESCRIPTOR_FILENAME,
    EXAMPLES_FILENAME,
    RESULTS_FILENAME,
)
from erc7730.generate.natspec.examples.maps import check_maps
from erc7730.generate.natspec.examples.models import (
    ExampleCase,
    ExampleConfig,
    ExampleFixture,
    ExampleRenderer,
    RenderedDisplay,
)
from erc7730.generate.natspec.examples.results import render_results, replay_results
from erc7730.generate.natspec.examples.sanity import run_sanity_examples
from erc7730.generate.natspec.examples.transactions import raw_transaction, resolve_sender, transaction_container
from erc7730.generate.natspec.examples.typed_data import message_schema, signing_domain, typed_input
from erc7730.generate.natspec.examples.values import named_value
from erc7730.model.input.v2.context import InputContractContext
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor

DEFAULT_RUNNER_COMMAND = ("clear-signing-test-runner",)
DEFAULT_RUNNER_TIMEOUT_SECONDS = 60


class CommandExampleRunner:
    """Adapter for `clear-signing-test-runner FILE --output RESULTS`.

    The command is an explicit caller setting, never read from NatSpec. Arguments
    are executed without a shell. Install a registry-compatible runner separately.
    """

    def __init__(
        self, command: Sequence[str] = DEFAULT_RUNNER_COMMAND, timeout: float = DEFAULT_RUNNER_TIMEOUT_SECONDS
    ):
        if not command:
            raise ValueError("An example runner command is required.")
        self.command = list(command)
        self.timeout = timeout

    def __call__(self, descriptor: InputERC7730Descriptor, fixture: ExampleFixture) -> dict[str, Any]:
        with TemporaryDirectory(prefix="erc7730-examples-") as directory:
            root = Path(directory)
            (root / DESCRIPTOR_FILENAME).write_text(descriptor.to_json_string())
            temporary = fixture.model_copy(update={"descriptor": DESCRIPTOR_FILENAME})
            (root / EXAMPLES_FILENAME).write_text(temporary.to_json_string())
            output = root / RESULTS_FILENAME
            try:
                result = subprocess.run(  # nosec B603 - caller command, shell=False; never from NatSpec
                    [*self.command, str(root / EXAMPLES_FILENAME), "--output", str(output)],
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )
                if result.returncode:
                    raise ValueError(f"Example runner failed: {result.stderr or result.stdout}")
                payload = json.loads(output.read_text())
            except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
                raise ValueError(f"Cannot render NatSpec examples: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("Example runner must return a JSON results object.")
            return payload


_GRAMMAR = Lark(
    r"""
    start: example+
    example: "params" "=" "(" arguments? ")" "intent" "=" ESCAPED_STRING field_expectations?
    field_expectations: "fields" "=" "{" field_expectation ("," field_expectation)* "}"
    field_expectation: ESCAPED_STRING ":" ESCAPED_STRING
    arguments: argument ("," argument)*
    ?argument: NAME "=" value -> named
             | value
    ?value: ESCAPED_STRING -> string
          | HEX -> hex_value
          | SIGNED_INT -> integer
          | "true" -> true
          | "false" -> false
          | NAME -> alias
          | "[" [value ("," value)*] "]" -> sequence
          | "(" [value ("," value)*] ")" -> sequence
    HEX.2: /0x[0-9a-fA-F]+/
    NAME: /[a-zA-Z_][a-zA-Z_0-9]*/
    %import common.ESCAPED_STRING
    %import common.SIGNED_INT
    %import common.WS
    %ignore WS
    """,
    parser="lalr",
    maybe_placeholders=False,
)


def _value(node: Tree[Any], component: dict[str, Any], aliases: dict[str, str]) -> Any:
    data_type = component["type"]
    parsed_type = parse(data_type)
    if parsed_type.is_array:
        if node.data != "sequence":
            raise ValueError(f"Expected an array for {component['name']}.")
        inner = component | {"type": parsed_type.item_type.to_type_str()}
        return [_value(child, inner, aliases) for child in node.children if isinstance(child, Tree)]
    if data_type == "tuple":
        parts = component["components"]
        if node.data != "sequence" or len(node.children) != len(parts):
            raise ValueError(f"Expected {len(parts)} tuple values for {component['name']}.")
        return [_value(child, part, aliases) for child, part in zip(node.children, parts, strict=True)]
    match node.data:
        case "string":
            value = json.loads(str(node.children[0]))
        case "integer":
            value = int(str(node.children[0]))
        case "hex_value":
            value = str(node.children[0])
        case "true" | "false":
            value = node.data == "true"
        case "alias":
            name = str(node.children[0])
            if data_type != ABIDataType.ADDRESS or name not in aliases:
                raise ValueError(f"Unknown address alias {name!r}; configure generate.examples.aliases.")
            value = aliases[name]
        case _:
            raise ValueError(f"Unsupported example value for {component['name']}.")
    if data_type.startswith("bytes") and isinstance(value, str) and value.startswith("0x"):
        return bytes.fromhex(value[2:])
    if data_type.startswith(("uint", "int")) and isinstance(value, str) and value.startswith("0x"):
        return int(value, 16)
    return value


def _arguments(tree: Tree[Any], inputs: list[dict[str, Any]], aliases: dict[str, str]) -> list[Any]:
    nodes = tree.children
    if nodes and all(isinstance(node, Tree) and node.data == "named" for node in nodes):
        named = {str(node.children[0]): node.children[1] for node in nodes if isinstance(node, Tree)}
        if len(named) != len(nodes) or set(named) != {part["name"] for part in inputs}:
            raise ValueError("Named example parameters must match every ABI input exactly, without duplicates.")
        nodes = [named[part["name"]] for part in inputs]
    if len(nodes) != len(inputs):
        raise ValueError(f"Example has {len(nodes)} parameters; ABI requires {len(inputs)}.")
    return [_value(node, part, aliases) for node, part in zip(nodes, inputs, strict=True)]


def run_natspec_examples(
    descriptor: InputERC7730Descriptor,
    *,
    natspec: JSONInput = None,
    userdoc: JSONInput = None,
    devdoc: JSONInput = None,
    config: ExampleConfig | dict[str, Any] | None = None,
    renderer: ExampleRenderer | None = None,
    require_all: bool = True,
) -> ExampleFixture:
    """ABI-encode examples, assert authored sentences and snapshot rendered fields.

    Automatic sanity cases run by default. With automatic disabled and require_all
    (the lint default), every displayed function needs an authored example.
    Generation disables this coverage check. Repeated tags (compiler-joined
    with whitespace) produce multiple cases. Example errors raise ValueError;
    generation calls this automatically when examples are supplied.
    `intent` in an example asserts interpolatedIntent when the descriptor declares
    one, otherwise static intent. This function neither submits nor writes files.
    """
    settings = config if isinstance(config, ExampleConfig) else ExampleConfig.model_validate(config or {})
    if isinstance(descriptor.context, InputContractContext) and len(descriptor.context.contract.deployments) != 1:
        combined = ExampleFixture(descriptor=DESCRIPTOR_FILENAME, data_provider=settings.data_provider, tests=[])
        for binding in descriptor.context.contract.deployments:
            scoped = descriptor.model_copy(
                update={
                    "context": descriptor.context.model_copy(
                        update={"contract": descriptor.context.contract.model_copy(update={"deployments": [binding]})}
                    )
                }
            )
            report = run_natspec_examples(
                scoped,
                natspec=natspec,
                userdoc=userdoc,
                devdoc=devdoc,
                config=settings,
                renderer=renderer,
                require_all=require_all,
            )
            prefix = f"{binding.chainId}:{binding.address}"
            combined.tests.extend(
                case.model_copy(update={"description": f"{prefix}: {case.description}"}) for case in report.tests
            )
            combined.sanity_unavailable.extend(f"{prefix}: {message}" for message in report.sanity_unavailable)
        return combined
    docs = parse_natspec(natspec, userdoc, devdoc)
    fixture, sentences, expected_fields, templated = _build_examples(descriptor, docs, settings, require_all)
    runner = renderer or CommandExampleRunner()
    if fixture.tests:
        captured = _check_examples(descriptor, fixture, runner, sentences, expected_fields, templated)
        replay_results(descriptor, fixture, runner, captured)
    if settings.automatic:
        automatic = run_sanity_examples(descriptor, settings, runner)
        fixture.tests.extend(automatic.tests)
        fixture.sanity_unavailable.extend(automatic.sanity_unavailable)
    return fixture


def _build_examples(
    descriptor: InputERC7730Descriptor, docs: NatSpec, settings: ExampleConfig, require_all: bool
) -> tuple[ExampleFixture, dict[str, str], dict[str, dict[str, str]], set[str]]:
    """Encode authored examples and collect their display expectations."""
    typed = not isinstance(descriptor.context, InputContractContext)
    deployment = (
        descriptor.context.contract.deployments[0] if isinstance(descriptor.context, InputContractContext) else None
    )
    if typed and (selected := bridge_methods(docs)):
        docs = message_docs(docs, selected)
    resolved_maps = None
    if descriptor.metadata.maps:
        from erc7730.common.output import ListOutputAdder
        from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved

        out = ListOutputAdder()
        resolved_maps = ERC7730InputToResolved().convert(descriptor, out)
        if resolved_maps is None or out.has_errors:
            raise ValueError(f"Invalid example maps: {[item.message for item in out.outputs]}")
    cases: list[ExampleCase] = []
    sentences: dict[str, str] = {}
    expected_fields: dict[str, dict[str, str]] = {}
    templated: set[str] = set()
    for declaration, display_format in descriptor.display.formats.items():
        if typed:
            signature, _, inputs = message_schema(declaration)
        else:
            validate_function_declaration(declaration)
            function = parse_signature(declaration)
            signature = compute_signature(function)
            inputs = [part.model_dump() for part in function.inputs or []]
        user_method = docs.userdoc.get("methods", {}).get(signature, {})
        dev_method = docs.devdoc.get("methods", {}).get(signature, {})
        tag = custom_tag(dev_method, "clearsig-example") or custom_tag(user_method, "clearsig-example")
        if tag is None or (isinstance(tag, str) and not tag.strip()):
            if require_all and not settings.automatic:
                raise ValueError(f"Missing @custom:clearsig-example for {signature}.")
            continue
        if not isinstance(tag, str):
            raise ValueError(f"Invalid @custom:clearsig-example for {signature}: expected a string.")
        try:
            examples = _GRAMMAR.parse(tag)
            for index, example in enumerate(examples.children, 1):
                assert isinstance(example, Tree)  # nosec B101 - internal invariant, not input validation
                args = next(
                    (child for child in example.children if isinstance(child, Tree) and child.data == "arguments"),
                    Tree("arguments", []),
                )
                assert isinstance(args, Tree)  # nosec B101 - internal invariant, not input validation
                values = _arguments(args, inputs, settings.aliases)
                if resolved_maps is not None:
                    resolved_format = resolved_maps.display.formats[
                        declaration if typed else "0x" + function_signature_to_4byte_selector(signature).hex()
                    ]
                    if typed:
                        _, _, container = signing_domain(descriptor, settings)
                    else:
                        assert deployment is not None  # nosec B101 - internal invariant, not input validation
                        container = transaction_container(deployment, settings)
                    check_maps(
                        resolved_format,
                        {part["name"]: named_value(part, value) for part, value in zip(inputs, values, strict=True)},
                        container,
                    )
                payload = _example_payload(declaration, signature, inputs, values, descriptor, settings)
                sentence = json.loads(str(next(child for child in example.children if not isinstance(child, Tree))))
                if not sentence.strip():
                    raise ValueError("Example intent must not be empty.")
                description = f"{signature} example {index}"
                sentences[description] = sentence
                expectations = {}
                for child in example.children:
                    if isinstance(child, Tree) and child.data == "field_expectations":
                        for pair in child.children:
                            assert isinstance(pair, Tree)  # nosec B101 - internal invariant, not input validation
                            label, text = (json.loads(str(value)) for value in pair.children)
                            if label in expectations:
                                raise ValueError(f"Duplicate example field label {label!r}")
                            expectations[label] = text
                expected_fields[description] = expectations
                if display_format.interpolatedIntent is not None:
                    templated.add(description)
                cases.append(
                    ExampleCase.model_validate(
                        {
                            "description": description,
                            **payload,
                            "expected": RenderedDisplay(intent="", fields=[]),
                        }
                    )
                )
        except (LarkError, EncodingError, ValueError, TypeError, KeyError) as exc:
            raise ValueError(f"Invalid @custom:clearsig-example for {signature}: {exc}") from exc
    fixture = ExampleFixture(descriptor=DESCRIPTOR_FILENAME, data_provider=settings.data_provider, tests=cases)
    return fixture, sentences, expected_fields, templated


def _check_examples(
    descriptor: InputERC7730Descriptor,
    fixture: ExampleFixture,
    renderer: ExampleRenderer,
    sentences: dict[str, str],
    expected_fields: dict[str, dict[str, str]],
    templated: set[str],
) -> dict[str, RenderedDisplay]:
    """Check authored expectations and capture the complete rendered displays."""
    by_description = render_results(descriptor, fixture, renderer)
    for description, rendered in by_description.items():
        actual = rendered.interpolated_intent if description in templated else rendered.intent
        if actual != sentences[description]:
            raise ValueError(f"Example {description}: expected intent {sentences[description]!r}, rendered {actual!r}.")
        for label, expected in expected_fields[description].items():
            matches = [field.value for field in rendered.fields if field.label == label]
            if matches != [expected]:
                raise ValueError(
                    f"Example {description}: expected field {label!r} = {expected!r}, rendered {matches!r}."
                )
    return by_description


@dataclass
class NatSpecExamples:
    """Reusable example inputs for generation and library linting."""

    natspec: JSONInput = None
    userdoc: JSONInput = None
    devdoc: JSONInput = None
    config: ExampleConfig | dict[str, Any] | None = None
    renderer: ExampleRenderer | None = None

    def run(self, descriptor: InputERC7730Descriptor) -> ExampleFixture:
        return run_natspec_examples(
            descriptor,
            natspec=self.natspec,
            userdoc=self.userdoc,
            devdoc=self.devdoc,
            config=self.config,
            renderer=self.renderer,
        )


def has_examples(natspec: JSONInput = None, userdoc: JSONInput = None, devdoc: JSONInput = None) -> bool:
    """Whether supplied compiler documents declare any function example tags."""
    docs = parse_natspec(natspec, userdoc, devdoc)
    return any(
        custom_tag(method, "clearsig-example") is not None
        for doc in (docs.userdoc, docs.devdoc)
        for method in doc.get("methods", {}).values()
    )


def _example_payload(
    declaration: str,
    signature: str,
    inputs: list[dict[str, Any]],
    values: list[Any],
    descriptor: InputERC7730Descriptor,
    settings: ExampleConfig,
) -> dict[str, Any]:
    payload: dict[str, Any]
    if not isinstance(descriptor.context, InputContractContext):
        payload = {"data": typed_input(declaration, values, descriptor, settings)}
    else:
        deployment = descriptor.context.contract.deployments[0]
        types = [collapse_if_tuple(part) for part in inputs]
        calldata = function_signature_to_4byte_selector(signature) + encode(types, values)
        payload = {
            "rawTx": raw_transaction(deployment, calldata),
            "from": resolve_sender(settings),
        }
    return payload
