"""Shared filenames, renderer statuses and transaction defaults for examples."""

from erc7730.model.paths import ContainerField, ContainerPath

DESCRIPTOR_FILENAME = "descriptor.json"
EXAMPLES_FILENAME = "examples.tests.json"
RESULTS_FILENAME = "results.json"

# Renderer result status, not a credential.
RUNNER_PASS = "pass"  # nosec B105
RUNNER_FAIL = "fail"

DEFAULT_EXAMPLE_ADDRESS = "0x1111111111111111111111111111111111111111"
EXAMPLE_GAS_LIMIT = 1_000_000
EIP1559_TRANSACTION_PREFIX = b"\x02"

TRANSACTION_TO_PATH = str(ContainerPath(field=ContainerField.TO))
TRANSACTION_FROM_PATH = str(ContainerPath(field=ContainerField.FROM))
TRANSACTION_VALUE_PATH = str(ContainerPath(field=ContainerField.VALUE))
TRANSACTION_CHAIN_ID_PATH = str(ContainerPath(field=ContainerField.CHAIN_ID))
