"""JUnit reports reflect actual lint outcomes without changing exit policy."""

import json
from pathlib import Path
from xml.etree.ElementTree import parse

import pytest
from typer.testing import CliRunner

from erc7730.common.output import ListOutputAdder, OutputAdder
from erc7730.generate.natspec.examples import NatSpecExamples
from erc7730.generate.natspec.examples.models import ExampleFixture
from erc7730.lint.v2 import ERC7730Linter
from erc7730.lint.v2.lint import lint_file
from erc7730.lint.v2.report import JUnitReport
from erc7730.main import app
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.resolved.v2.descriptor import ResolvedERC7730Descriptor


class WarningLinter(ERC7730Linter):
    def lint(
        self, input_descriptor: InputERC7730Descriptor, descriptor: ResolvedERC7730Descriptor, out: OutputAdder
    ) -> None:
        out.warning(title="Review", message="A < B & C\x00")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "calldata-example.json"
    path.write_text(
        json.dumps(
            {
                "$schema": "https://eips.ethereum.org/assets/eip-7730/erc7730-v2.schema.json",
                "context": {"contract": {"deployments": [{"chainId": 1, "address": "0x" + "11" * 20}]}},
                "metadata": {"owner": "Example"},
                "display": {
                    "formats": {
                        "f(uint256 value)": {
                            "intent": "Send",
                            "fields": [
                                {"path": "value", "label": "Value", "format": "raw"},
                            ],
                        }
                    }
                },
            }
        )
    )
    return path


def test_warnings_are_visible_and_unrun_examples_skipped(source: Path, tmp_path: Path) -> None:
    report, out = JUnitReport(), ListOutputAdder()
    lint_file(source, WarningLinter(), out, report=report, strict=True)
    path = tmp_path / "reports/lint.xml"
    report.write(path)
    root = parse(path).getroot()
    assert root.get("failures") == "0"
    assert root.get("skipped") == "1"
    assert out.has_warnings and not out.has_errors
    assert root.find(".//testcase[@name='Examples']/skipped") is not None
    log = root.find(".//testcase[@name='WarningLinter']/system-out")
    assert log is not None and log.text == "WARNING: Review: A < B & C\ufffd"


@pytest.mark.parametrize("bad_json", [True, False])
def test_failures_skip_prerequisite_dependents(source: Path, tmp_path: Path, bad_json: bool) -> None:
    source.write_text("{" if bad_json else '{"context": 42}')
    report, out = JUnitReport(), ListOutputAdder()
    lint_file(source, WarningLinter(), out, report=report, strict=True)
    path = tmp_path / "lint.xml"
    report.write(path)
    root = parse(path).getroot()
    assert root.get("failures") == "1"
    assert out.has_errors
    failed = "Load JSON" if bad_json else "Published V2 schema"
    assert root.find(f".//testcase[@name='{failed}']/failure") is not None
    assert root.find(".//testcase[@name='WarningLinter']/skipped") is not None


class VerifiedExamples(NatSpecExamples):
    def run(self, descriptor: InputERC7730Descriptor) -> ExampleFixture:
        return ExampleFixture.model_validate(
            {
                "descriptor": "descriptor.json",
                "dataProvider": {},
                "tests": [
                    {"description": "authored transfer", "rawTx": "0x01", "expected": {"intent": "Send", "fields": []}},
                    {"description": "sanity: zero", "rawTx": "0x02", "expected": {"intent": "Send", "fields": []}},
                ],
                "sanity_unavailable": ["No independent address oracle"],
            }
        )


def test_executed_examples_and_unavailable_sanity(source: Path) -> None:
    report = JUnitReport()
    lint_file(source, WarningLinter(), ListOutputAdder(), examples=VerifiedExamples(), report=report)
    names = {result.name: result for result in report.results}
    assert names["Example: authored transfer"].skipped is None
    assert names["Example: sanity: zero"].skipped is None
    assert names["Unavailable sanity check 1"].skipped == "No independent address oracle"


def test_cli_writes_report_on_failure(source: Path, tmp_path: Path) -> None:
    source.write_text("{")
    path = tmp_path / "lint.xml"
    result = CliRunner().invoke(app, ["lint", "--v2", str(source), "--junit-xml", str(path)])
    assert result.exit_code == 1, result.output
    assert parse(path).getroot().get("failures") == "1"


def test_missing_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "lint.xml"
    result = CliRunner().invoke(app, ["lint", "--v2", str(tmp_path / "missing.json"), "--junit-xml", str(path)])
    assert result.exit_code == 1
    assert parse(path).getroot().find(".//testcase[@name='Find descriptors']/failure") is not None


class FailedExamples(NatSpecExamples):
    def run(self, descriptor: InputERC7730Descriptor) -> ExampleFixture:
        raise ValueError("Renderer unavailable")


def test_failed_examples_never_report_individual_passes(source: Path) -> None:
    report, out = JUnitReport(), ListOutputAdder()
    lint_file(source, WarningLinter(), out, examples=FailedExamples(), report=report)
    assert out.has_errors
    assert not any(result.name.startswith("Example:") for result in report.results)
    assert next(result for result in report.results if result.name == "Resolution").skipped is not None
