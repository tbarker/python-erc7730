# Official Uniswap registry round trips

Pinned source: [ethereum/clear-signing-erc7730-registry, commit
000841a1d7e96a4fc592c930ccc58cb6b3ad549e](https://github.com/ethereum/clear-signing-erc7730-registry/tree/000841a1d7e96a4fc592c930ccc58cb6b3ad549e/registry/uniswap).

These fixtures cover all six descriptors and their shared include. Tests run offline. Solidity sources are interface
stubs, not Uniswap implementations; they neither deploy nor verify contract behavior.

## Inputs and provenance

- `upstream/` preserves the seven original JSON files byte for byte.
- `*.sol` transcribes the input declarations and display rules into Solidity interfaces.
  `@notice` supplies intent, `@param` supplies root labels, and `clearsig-*` tags supply
  nested labels, formatters, parameters, exclusions and explicit iteration. The
  PermitTransferFrom notice uses a template plus a static intent fallback.
  `clearsig-owner` supplies `Uniswap Labs`; recipe metadata retains deployment-specific
  information and takes precedence over annotations where provided.
  Router recipients and the Permit2 spender rely on the generator's default
  `["local", "ens"]` address-name sources; redundant `clearsig-sources` tags are
  omitted while the generated source lists still match the published descriptors.
- `*.artifact.json` is real solc 0.8.30 ABI/userdoc/devdoc output. Compiler version and
  source SHA-256 are recorded; CI never installs or runs solc.
- `*.recipe.json` contains only public library metadata/deployment/domain inputs.
  The generated side never reads upstream display JSON and never
  patches the generated descriptor. `generate_natspec_descriptor` handles the whole overlay.
- `manifest.json` pins the commit, original checksums, source filenames,
  and the explicit generation exclusions described below.

## Omitted inputs are valid V2

The published descriptors omit 28 inputs across their 13 formats. This is not a V2
specification violation. Expected descriptors are loaded directly from `upstream/`,
expanding the shared include and canonicalizing calldata declaration whitespace only.
No corrected target copies or added hidden fields are used.

Our generator still bootstraps every input by default. The Solidity stubs therefore
use explicit exclusions to reproduce the registry's display choices; the resulting
`visible: "never"` entries and the upstream omissions both render nothing. The
manifest's `generation_exclusions` records these authoring choices, not registry defects.
No published display strings or transaction/message inputs are changed.

## Semantic checks

Each bundle is generated through the public library, serialized, reloaded, schema
validated, and compared through the existing V2 resolver. Generated and official
expected bundles both pass full V2 lint. Explorer I/O alone is replaced with the
compiled stub ABI for the synthetic comparison; all local checks run normally.

The semantic comparison retains visible field order, labels, formatter parameters,
thresholds, bindings, metadata, named groups and array iteration. It additionally
recognizes omission and unconditional hiding as producing no displayed field, and an
unlabeled logical sequential group as its children in the same position. Conditional
visibility (including `mustMatch`) is retained, as it has runtime behavior.
Negative controls change visibility, ordering, labels, token paths and grouping; a
bundled PermitBatch must differ from the sequential layout.

## Production fixes exercised

- EIP-712 struct lookup accepts names with embedded digits, including `V2DutchOrder`,
  without interpreting them as Solidity primitive widths.
- `clearsig-group allowances fields=(details.amount,details.expiration) iteration=sequential`
  expresses PermitBatch's unlabeled sequential array layout.
- NatSpec generation flattens redundant unlabeled scalar-struct wrappers, rebasing
  paths and parameters together. Named and array groups remain. Source annotations inside array groups use the
  published relative token reference (`token`), preserving the array-element scope.

## Reproduction

With solc installed separately:

```sh
node tests/generate/natspec/data/registry_uniswap/compile.cjs /absolute/path/to/node_modules/solc
.venv/bin/python -m pytest tests/generate/natspec/test_registry_uniswap.py --no-cov
```

Inspect a generated bundle using the same library path as the tests:

```sh
.venv/bin/python -c 'from tests.generate.natspec.registry_uniswap import assemble; print(assemble("calldata-UniswapV3Router02").to_json_string())'
```

This does not submit anything to the registry or replace author review.
