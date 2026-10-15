# Library usage

## Installation

The `erc7730` library is available as a [Python package on PyPI](https://pypi.org/project/erc7730). You can install it
using `pip`:

```bash
pip install --user erc7730
```

## Overview

A typical usage of the `erc7730` library is to load descriptors and compile them to a wallet manufacturer-specific
format:

```{mermaid}
---
title: Node
---
flowchart TD
   input_json@{ shape: doc, label: "ERC-7730 descriptor file" }
   input[input ERC-7730 descriptor]
   resolved[resolved ERC-7730 descriptor]
   vendor[wallet specific ERC-7730 descriptor]
   input_json -- load/validate --> input
   input -- resolve/validate --> resolved
   resolved -- convert --> vendor
```

## Packages

(library-generate)=
### `erc7730.generate`

`generate_descriptor` from `erc7730.generate.generate` retains the existing V1 API,
including positional arguments and `legal_name`.

`generate_natspec_descriptor` builds a V2 descriptor from an ABI or EIP-712 schema, optionally
using compiler NatSpec. See the [NatSpec guide](natspec.md) for annotation rules and defaults.

```python
from pathlib import Path

from erc7730.generate.natspec.generate import generate_natspec_descriptor
from pydantic_string_url import HttpUrl

warnings: list[str] = []
descriptor = generate_natspec_descriptor(
    chain_id=1,
    contract_address="0x0000000000000000000000000000000000000001",
    natspec=Path("out/Token.sol/Token.json").read_bytes(),
    owner="Example",
    url=HttpUrl("https://example.com"),
    warnings=warnings,
)
Path("calldata-token.json").write_text(descriptor.to_json_string())
```

| Argument | Accepted input / behavior |
| --- | --- |
| `abi`, `eip712_schema` | JSON strings or bytes; an EIP-712 schema selects message generation |
| `natspec` | JSON string, bytes, or dictionary: raw docs, paired docs, or an artifact |
| `userdoc`, `devdoc` | Optional split JSON strings, bytes, or dictionaries; conflict with `natspec` containing both docs |
| `project_defaults` | A mapping of custom tag keys, or its JSON string/bytes representation |
| `eip712_domain` | Domain constraints as a dictionary, JSON string or bytes; requires message generation |
| `warnings` | Optional `list[str]` populated with diagnostics; omitted collectors use Python logging |
| `owner`, `url` | Override supplied metadata and NatSpec fallbacks |
| `deployments` | Optional complete `list[InputDeployment]`, including the generation chain/address; duplicate pairs are rejected |
| `metadata` | Optional `InputMetadata` model: initial owner info, deployment date, token metadata and other V2 metadata, enriched by NatSpec |

Load file contents yourself: strings are interpreted as JSON, not filesystem paths.
The library does not discover project configuration. To use a TOML file explicitly:

```python
import tomllib

project_defaults = tomllib.loads(Path("erc7730.toml").read_text())["generate"]
# Pass project_defaults=project_defaults to generate_natspec_descriptor(...).
```

Generation errors raise `ValueError`; see [lint diagnostics](natspec-and-intent-checks).
Use `NatSpecExamples(...).run(descriptor)` or `run_natspec_examples(...)` to rerun checks;
the [example guide](natspec-examples) includes a complete library example.

#### EIP-712 domain constraints

Pass `eip712_domain` with an explicit schema or [annotated compiler ABI](eip-712-schema-bridge):

```python
descriptor = generate_natspec_descriptor(
    chain_id=1,
    contract_address="0x1111111111111111111111111111111111111111",
    eip712_schema=schema_json,
    eip712_domain={"name": "Example", "version": "2"},
)
```

#### Typed deployment and metadata inputs

Pass package models through `deployments` and `metadata`:

```python
from datetime import UTC, datetime
from pydantic import TypeAdapter
from pydantic_string_url import HttpUrl
from erc7730.model.input.v2.context import InputDeployment
from erc7730.model.input.v2.metadata import InputMetadata, InputOwnerInfo
from erc7730.model.metadata import TokenInfo

address = "0x2222222222222222222222222222222222222222"
descriptor = generate_natspec_descriptor(
    1, address, natspec=compiler_artifact_json,
    deployments=[
        InputDeployment(chainId=1, address=address),
        InputDeployment(chainId=137, address=address),
    ],
    metadata=InputMetadata(
        info=InputOwnerInfo(
            url=TypeAdapter(HttpUrl).validate_python("https://example.org"),
            deploymentDate=datetime(2020, 1, 1, tzinfo=UTC),
        ),
        token=TokenInfo(name="Example Token", ticker="EXA", decimals=6),
    ),
)
```

`deployments` replaces the default binding and must include the generation chain/address;
duplicate pairs are rejected. Caller models are copied. A deployment date requires a URL
in `InputOwnerInfo`. Configured calldata examples run for each deployment.

### `erc7730.model`

The `erc7730.model` package implements an object model mapping for ERC-7730 descriptors using
[pydantic](https://docs.pydantic.dev), allowing to easily read/write/transform descriptors.

#### input and resolved forms

Descriptors can be manipulated in 2 forms:
 - *"Input" form*: the descriptor document as defined in the ERC-7730 specification, after `include` tags have been
   resolved. It is possible to save back the descriptor back to the original descriptor document. 
 - *"Resolved" form*: the descriptor after pre-processing:
    - URLs have been fetched
    - Contract addresses have been normalized to lowercase
    - References have been inlined
    - Constants have been inlined
    - Field definitions have been inlined
    - Nested fields have been flattened where possible
    - Selectors have been converted to 4 bytes form
   This form is the most adapted to be used by tools and applications.

```{eval-rst}
.. autosummary::
 :nosignatures:
 
 erc7730.model.input.descriptor.InputERC7730Descriptor
 erc7730.model.resolved.descriptor.ResolvedERC7730Descriptor
```

#### Legacy V1 input data model

```{eval-rst}
.. autopydantic_model:: erc7730.model.input.descriptor.InputERC7730Descriptor
 :noindex:
 :model-show-config-summary: False
 :model-show-field-summary: False
```

#### Legacy V1 resolved data model

```{eval-rst}
.. autopydantic_model:: erc7730.model.resolved.descriptor.ResolvedERC7730Descriptor
 :noindex:
 :model-show-config-summary: False
 :model-show-field-summary: False
```

### `erc7730.lint`

The `erc7730.lint` package implements the `erc7730 lint` command. The main interface is `ERC7730Linter`:

```{eval-rst}
.. autoclass:: erc7730.lint.ERC7730Linter
 :members:
```

The package contains several linter implementations:

```{eval-rst}
.. autosummary::
 :nosignatures:
 
 erc7730.lint.lint_validate_abi.ValidateABILinter
 erc7730.lint.lint_validate_display_fields.ValidateDisplayFieldsLinter
 erc7730.lint.lint_transaction_type_classifier.ClassifyTransactionTypeLinter
```

### `erc7730.convert`

The `erc7730.convert` package implements the `erc7730 convert` command. The main interface is `ERC7730Converter`:

```{eval-rst}
.. autoclass:: erc7730.convert.ERC7730Converter
 :members:
```

The package contains several converter implementations:

```{eval-rst}
.. autosummary::
 :nosignatures:
 
 erc7730.convert.resolved.convert_erc7730_input_to_resolved.ERC7730InputToResolved
 erc7730.convert.ledger.eip712.convert_eip712_to_erc7730.EIP712toERC7730Converter
 erc7730.convert.ledger.eip712.convert_erc7730_to_eip712.ERC7730toEIP712Converter
 erc7730.convert.calldata.convert_erc7730_input_to_calldata.erc7730_descriptor_to_calldata_descriptors
```

#### Runtime maps

V2 resolution retains runtime lookups as `ResolvedValueMap`.
Constant keys resolve only their selected entry.
`lookup_map_value(reference.values, key)` from `erc7730.convert.resolved.v2.values`
returns a validated constant or `None` for an unknown key. See [map authoring](dynamic-maps).
