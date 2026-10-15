"""Inline-example parsing, execution and automatic display checks.

The public example API is re-exported here; implementation modules live alongside it.
"""

from erc7730.generate.natspec.examples.models import (
    ExampleCase,
    ExampleConfig,
    ExampleDataProvider,
    ExampleFixture,
    ExampleModel,
    ExampleRenderer,
    RenderedDisplay,
    RenderedField,
    TokenMetadata,
)
from erc7730.generate.natspec.examples.runner import (
    CommandExampleRunner,
    NatSpecExamples,
    has_examples,
    run_natspec_examples,
)

__all__ = [
    "CommandExampleRunner",
    "ExampleCase",
    "ExampleConfig",
    "ExampleDataProvider",
    "ExampleFixture",
    "ExampleModel",
    "ExampleRenderer",
    "NatSpecExamples",
    "RenderedDisplay",
    "RenderedField",
    "TokenMetadata",
    "has_examples",
    "run_natspec_examples",
]
