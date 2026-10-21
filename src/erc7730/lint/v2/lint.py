import os
from collections.abc import Iterator
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from rich import print

from erc7730.common.json import read_json_with_includes
from erc7730.common.output import (
    AddFileOutputAdder,
    BufferAdder,
    ConsoleOutputAdder,
    DropFileOutputAdder,
    GithubAnnotationsAdder,
    ListOutputAdder,
    OutputAdder,
)
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.examples import NatSpecExamples
from erc7730.lint.v2 import ERC7730Linter, MultiLinter
from erc7730.lint.v2.json_schema import validate_json_schema
from erc7730.lint.v2.lint_transaction_type_classifier import ClassifyTransactionTypeLinter
from erc7730.lint.v2.lint_validate_display_fields import ValidateDisplayFieldsLinter
from erc7730.lint.v2.lint_validate_eip712_keys import ValidateEIP712KeysLinter
from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter
from erc7730.lint.v2.lint_validate_map_keys import ValidateMapKeysLinter
from erc7730.lint.v2.lint_validate_max_length import ValidateMaxLengthLinter
from erc7730.lint.v2.lint_validate_schema import ValidateSchemaLinter
from erc7730.lint.v2.report import CheckResult, JUnitReport
from erc7730.list.list import get_erc7730_files
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor


def lint_all_and_print_errors(
    paths: list[Path],
    gha: bool = False,
    examples: NatSpecExamples | None = None,
    report: JUnitReport | None = None,
    *,
    strict: bool = False,
) -> bool:
    """Lint all ERC-7730 v2 descriptor files at given paths and print results."""
    out = GithubAnnotationsAdder() if gha else DropFileOutputAdder(delegate=ConsoleOutputAdder())

    count = lint_all(paths, out, examples=examples, report=report, strict=strict)

    if out.has_errors:
        print(f"[bold][red]checked {count} v2 descriptor files, some errors found ❌[/red][/bold]")
        return False

    if out.has_warnings:
        print(f"[bold][yellow]checked {count} v2 descriptor files, some warnings found ⚠️[/yellow][/bold]")
        return True

    print(f"[bold][green]checked {count} v2 descriptor files, no errors found ✅[/green][/bold]")
    return True


def lint_all(
    paths: list[Path],
    out: OutputAdder,
    examples: NatSpecExamples | None = None,
    report: JUnitReport | None = None,
    *,
    strict: bool = False,
) -> int:
    """
    Lint all ERC-7730 v2 descriptor files at given paths.

    Paths can be files or directories, in which case all JSON files in the directory are recursively linted.

    :param paths: paths to apply linter on
    :param out: output adder
    :param examples: compiler examples to run for each descriptor before descriptor lint
    :param report: optional JUnit collector; write it after lint completes
    :param strict: opt into published-schema, local type and intent validation
    :return: number of files checked
    """
    linter = MultiLinter(
        [
            ValidateDisplayFieldsLinter(),
            *([ValidateSchemaLinter(), ValidateIntentLinter()] if strict else []),
            ValidateEIP712KeysLinter(),
            ValidateMapKeysLinter(),
            ClassifyTransactionTypeLinter(),
            ValidateMaxLengthLinter(),
        ]
    )

    if report is None:
        files = list(get_erc7730_files(*paths, out=out))
    else:
        files = []
        with report.check(Path("discovery"), "Find descriptors", out) as checks:
            files = list(get_erc7730_files(*paths, out=checks))

    if len(files) <= 1 or not (root_path := os.path.commonpath(files)):
        root_path = None

    def label(f: Path) -> Path | None:
        return f.relative_to(root_path) if root_path is not None else None

    if len(files) > 1:
        print(f"🔍 checking {len(files)} v2 descriptor files…\n")

    with ThreadPoolExecutor() as executor:
        for future in (
            executor.submit(lint_file, file, linter, out, label(file), examples, report, strict=strict)
            for file in files
        ):
            future.result()

    return len(files)


def lint_file(
    path: Path,
    linter: ERC7730Linter,
    out: OutputAdder,
    show_as: Path | None = None,
    examples: NatSpecExamples | None = None,
    report: JUnitReport | None = None,
    *,
    strict: bool = False,
) -> None:
    """
    Lint a single ERC-7730 v2 descriptor file.

    :param path: ERC-7730 v2 descriptor file path
    :param show_as: if provided, print this label instead of the file path
    :param linter: v2 linter instance
    :param out: error handler
    :param examples: compiler example inputs and renderer; failures become lint errors
    """

    label = path if show_as is None else show_as
    file_out = AddFileOutputAdder(delegate=out, file=path)

    collector = report if report is not None else JUnitReport()
    linters = linter.linters if isinstance(linter, MultiLinter) else [linter]
    pending = ["Load JSON", *(["Published V2 schema"] if strict else []), "Input model", "Examples", "Resolution"]
    pending.extend(type(check).__name__ for check in linters)

    with BufferAdder(file_out, prolog=f"➡️ checking [bold]{label}[/bold]…", epilog="") as output:

        @contextmanager
        def phase(name: str) -> Iterator[ListOutputAdder]:
            with collector.check(path, name, output) as checks:
                yield checks
            pending.remove(name)

        try:
            value = None
            with phase("Load JSON") as checks:
                value = read_json_with_includes(path, merge_display_fields=True)
            if checks.has_errors:
                return
            if strict:
                with phase("Published V2 schema") as checks:
                    validate_json_schema(value, checks)
                if checks.has_errors:
                    return
            input_descriptor = None
            with phase("Input model") as checks:
                input_descriptor = InputERC7730Descriptor.model_validate(value, strict=False)
            if input_descriptor is None or checks.has_errors:
                return
            if examples is None:
                collector.skip(path, "Examples", "No compiler examples or example configuration supplied")
                pending.remove("Examples")
            else:
                fixture = None
                with phase("Examples") as checks:
                    fixture = examples.run(input_descriptor)
                    for message in fixture.sanity_unavailable:
                        checks.warning(title="Sanity check not exercised", message=message)
                if fixture is None or checks.has_errors:
                    return
                for case in fixture.tests:
                    collector.add(CheckResult(str(path), "Example: " + case.description, 0))
                for index, message in enumerate(fixture.sanity_unavailable):
                    collector.skip(path, f"Unavailable sanity check {index + 1}", message)
            resolved_descriptor = None
            with phase("Resolution") as checks:
                resolved_descriptor = ERC7730InputToResolved().convert(input_descriptor, checks)
            if resolved_descriptor is None or checks.has_errors:
                return
            for check in linters:
                with phase(type(check).__name__) as checks:
                    check.lint(input_descriptor, resolved_descriptor, checks)
        finally:
            for name in pending:
                collector.skip(path, name, "Not run because a prerequisite failed")
