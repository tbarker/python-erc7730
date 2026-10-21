"""Validate renderer responses and replay captured displays."""

from erc7730.generate.natspec.examples.constants import RUNNER_FAIL, RUNNER_PASS
from erc7730.generate.natspec.examples.models import ExampleFixture, ExampleRenderer, RenderedDisplay
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor


def render_results(
    descriptor: InputERC7730Descriptor,
    fixture: ExampleFixture,
    renderer: ExampleRenderer,
    *,
    context: str = "Example",
    require_pass: bool = False,
) -> dict[str, RenderedDisplay]:
    results = renderer(descriptor, fixture).get("cases")
    if not isinstance(results, list) or len(results) != len(fixture.tests):
        raise ValueError(f"{context} runner returned incomplete or excess results.")
    expected = {case.description for case in fixture.tests}
    captured: dict[str, RenderedDisplay] = {}
    for result in results:
        if not isinstance(result, dict):
            raise ValueError(f"Malformed {context.lower()} runner result.")
        description = result.get("description", "")
        if not isinstance(description, str):
            raise ValueError(f"{context} result description must be a string.")
        if description not in expected or description in captured:
            raise ValueError(f"Unexpected or duplicate {context.lower()} result: {description}.")
        if require_pass and result.get("status") != RUNNER_PASS:
            raise ValueError(f"{context} verification failed: {result}")
        if result.get("status") not in (RUNNER_PASS, RUNNER_FAIL) or result.get("rendered") is None:
            raise ValueError(
                f"{context} rendering failed: {description}: {result.get('message', result.get('status'))}"
            )
        captured[description] = RenderedDisplay.model_validate(result["rendered"])
    return captured


def replay_results(
    descriptor: InputERC7730Descriptor,
    fixture: ExampleFixture,
    renderer: ExampleRenderer,
    captured: dict[str, RenderedDisplay],
    *,
    context: str = "Example",
) -> None:
    """Require a passing replay of the complete captured display, including warnings."""
    for case in fixture.tests:
        case.expected = captured[case.description]
    replayed = render_results(descriptor, fixture, renderer, context=context, require_pass=True)
    for description, rendered in replayed.items():
        if rendered != captured[description]:
            raise ValueError(f"{context} rendering changed between runs: {description}.")
