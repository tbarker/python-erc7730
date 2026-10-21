"""Optional JUnit XML evidence from the existing lint diagnostics."""

import re
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from xml.etree.ElementTree import Element, ElementTree, SubElement  # nosec B405 - writes XML; never parses input

from erc7730.common.output import ExceptionsToOutput, ListOutputAdder, Output, OutputAdder


@dataclass(frozen=True)
class CheckResult:
    file: str
    name: str
    duration: float
    outputs: tuple[Output, ...] = ()
    skipped: str | None = None


class JUnitReport:
    """Collect checks across files; write standard JUnit XML on demand.

    Errors are failures, warnings remain visible in system-out, and unexecuted
    checks are skipped. Example cases are recorded only after verified execution.
    """

    def __init__(self) -> None:
        self.results: list[CheckResult] = []
        self._lock = Lock()

    def add(self, result: CheckResult) -> None:
        with self._lock:
            self.results.append(result)

    def skip(self, file: Path, name: str, reason: str) -> None:
        self.add(CheckResult(str(file), name, 0, skipped=reason))

    @contextmanager
    def check(self, file: Path, name: str, out: OutputAdder) -> Iterator[ListOutputAdder]:
        """Capture the same diagnostics sent to the caller, including exceptions."""
        buffer = ListOutputAdder()
        start = perf_counter()
        with ExceptionsToOutput(buffer):
            yield buffer
        self.add(CheckResult(str(file), name, perf_counter() - start, tuple(buffer.outputs)))
        for output in buffer.outputs:
            out.add(output)

    def write(self, path: Path) -> None:
        """Write a report, including failures; never changes lint's exit policy."""
        suites: dict[str, list[CheckResult]] = defaultdict(list)
        with self._lock:
            for result in self.results:
                suites[result.file].append(result)
        root = Element("testsuites", name="ERC-7730 V2 lint")
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        elapsed = 0.0
        for file, checks in sorted(suites.items()):
            suite = SubElement(root, "testsuite", name=_xml_text(file))
            failures = sum(any(output.level == Output.Level.ERROR for output in check.outputs) for check in checks)
            skipped = sum(check.skipped is not None for check in checks)
            counts = {"tests": len(checks), "failures": failures, "errors": 0, "skipped": skipped}
            duration = sum(check.duration for check in checks)
            for key, value in counts.items():
                suite.set(key, str(value))
                totals[key] += value
            suite.set("time", f"{duration:.6f}")
            elapsed += duration
            for check in checks:
                case = SubElement(
                    suite,
                    "testcase",
                    name=_xml_text(check.name),
                    classname=_xml_text(file),
                    time=f"{check.duration:.6f}",
                )
                if check.skipped is not None:
                    SubElement(case, "skipped", message=_xml_text(check.skipped))
                errors = [output for output in check.outputs if output.level == Output.Level.ERROR]
                if errors:
                    SubElement(case, "failure", message=_xml_text(errors[0].title or "Lint failed")).text = _messages(
                        errors
                    )
                if check.outputs:
                    SubElement(case, "system-out").text = _messages(check.outputs)
        for key, value in totals.items():
            root.set(key, str(value))
        root.set("time", f"{elapsed:.6f}")
        path.parent.mkdir(parents=True, exist_ok=True)
        ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _xml_text(value: str) -> str:
    # User-authored diagnostics can contain characters forbidden by XML 1.0.
    return re.sub(r"[^\x09\x0a\x0d\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]", "\ufffd", value)


def _messages(outputs: list[Output] | tuple[Output, ...]) -> str:
    return _xml_text("\n".join(f"{output.level.name}: {output.title or ''}: {output.message}" for output in outputs))
