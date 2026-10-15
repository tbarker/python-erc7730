# Upstream ERC-7730 example round trips

These fixtures cover **all ten** `example-*.json` files from
[ethereum/ERCs, commit 30bfdf9cd3c6c31eb180dded09c2e162a2c248e2](https://github.com/ethereum/ERCs/tree/30bfdf9cd3c6c31eb180dded09c2e162a2c248e2/assets/erc-7730).
`upstream/` contains the imported targets. One target has locally corrected missing interpolation
formatters, documented in its `$comment` and below; the other nine retain the
upstream bytes. `manifest.json` retains published `upstream_sha256` digests and records
separate `fixture_sha256` digests for corrected targets, Solidity fixture names, and
explicit address substitutions.
Tests are offline and do not install or invoke a Solidity compiler.

## What the test exercises

Each standalone Solidity interface supplies functions, ABI types, and compiler
NatSpec. `@notice` supplies intent text/templates, `@param` supplies root labels,
and `clearsig-*` tags supply static fallbacks, formats, nested labels, token paths,
map definitions, formatter parameters, visibility, groups, separators, and exclusions. `*.artifact.json` files are real solc 0.8.30
output, with compiler version and source hashes. There is no Solidity parser in
Python, and no descriptor JSON is embedded in comments.

`ExampleArrayIteration` explicitly keeps `values=raw` to reproduce the published
example; otherwise its calldata `amount-path` binding now infers native amount
formatting. `ExampleAccountExecute` infers its amount from `clearsig-amount-path`.
Its contract-level calldata formatter and method-level recipient formatter preserve
the published recipient/value/calldata order without an explicit amount formatter.
Its `clearsig-url` annotation supplies the website, so its recipe needs no metadata.

The input side of each test uses only its compiler artifact and `*.recipe.json`:

1. The library `generate_natspec_descriptor` builds the ABI/EIP-712 tree and overlays docs.
2. Fixture configuration supplies typed `deployments` and `metadata` arguments to
   `generate_natspec_descriptor`, plus EIP-712 domains where applicable. All display fields
   and layouts come from production generation.
3. The descriptor is serialized, reloaded and validated against the V2 JSON schema.
4. Both generated and independently loaded upstream descriptors go through the
   package's existing V2 resolver, then their semantics are compared. The expected
   side explicitly adds the generator's `["local", "ens"]` source policy wherever
   an upstream `addressName` field omits sources. Explicit upstream lists remain
   unchanged; the comparison still detects missing or different generated sources.
5. Tests validate the generated V2 schema and require both generated descriptors
   and expected targets to pass the path/type and intent linters without errors.

**These tests exercise the public library generation API.** `*.recipe.json` files
now contain ordinary generation inputs; they are test fixture configuration, not
CLI config. The helper validates deployments and metadata with the package's models
and passes them to `generate_natspec_descriptor`. It returns the generated descriptor without
post-generation edits. Additional deployments, deployment dates, and token metadata
no longer require test-only patching. The CLI exposes a subset of these library inputs.

PermitSingle's unlabeled struct group resolves equivalently to the upstream flattened
fields. PermitBatch already has the required unlabeled array group. Neither requires
a layout override. Recipes cannot omit fields or override generated layout, labels,
formats, formatter parameters,
visibility, or separators. No expected JSON is read when assembling
the generated side.

Solidity has no compiler EIP-712 schema output. The two typed-data fixtures use
method-level `clearsig-typed-data` annotations. The production generator derives message
schemas from compiler ABI parameters, `internalType` names and tuple components, and
associates compiler docs with the declared primary types. The test-only bridge and
documentation remapping have been removed; no Solidity source is parsed.

## Coverage

| Upstream example | Solidity fixture | Main behavior |
| --- | --- | --- |
| `example-main` | `ExampleMain.sol` | Transfer, interpolation, multiple deployments |
| `example-erc20` | `ExampleErc20.sol` | Reusable approval fragment |
| `example-include` | `ExampleInclude.sol` | Include expansion and threshold override |
| `example-account-execute` | `ExampleAccountExecute.sol` | Nested calldata and native value |
| `example-array-iteration` | `ExampleArrayIteration.sol` | Bundled parallel arrays and nested calls |
| `example-eip712` | `ExampleEip712.sol` | PermitSingle/PermitBatch, nested structs and arrays |
| `example-userops-eip712` | `ExampleUseropsEip712.sol` | PackedUserOperation and visibility conditions |
| `example-maps` | `ExampleMaps.sol` | Chain-dependent token maps |
| `example-maps-pools` | `ExampleMapsPools.sol` | Pool token/share maps |
| `example-visibility-rules` | `ExampleVisibilityRules.sol` | Always/optional/never/mustMatch/ifNotIn |

## Explicit upstream limitations

Some upstream files are illustrations, not valid submission bundles:

- `example-account-execute` and `example-userops-eip712` use
  `0xYourImplementationAddress`. Fixtures bind this symbolic address to a fixed
  test address, recorded in the manifest.
- The Permit2 deployment and underlying-token map values contain 21-byte hex
  addresses. Their redundant leading zero byte is removed explicitly, preserving
  the numeric value; each substitution is recorded. Original address spellings remain
  in the target files and are substituted when loaded. The round-trip claim is relative to these instantiated inputs,
  not the invalid original address spellings.
- Two calldata declarations contain extra spaces after commas. The expected side
  canonicalizes that whitespace without changing parameter names or types.
- **Corrected target: `example-array-iteration`.** The published batch-call example
  omits `targets` and `values` although its intent interpolates both. The local target
  adds always-visible `targets.[]` (address-name) and `values.[]` (raw integer) fields,
  providing the intent's required formatters. Raw values remain base-unit
  integers; this correction does not infer a currency formatter.
- `example-eip712` is restored to the published bytes. Its omitted token inputs
  are permitted by V2; the stubs explicitly exclude them to suppress generation's
  heuristic fields. The former additions were tool-policy changes, not ERC fixes.
- The remaining array-iteration correction is required for its interpolated intent:
  referenced paths need always-visible formatters. Merely omitting other inputs
  does not require a correction.
- `example-erc20` is an include-only fragment. Its test compares display semantics
  in a synthetic carrier descriptor, because the fragment specifies no binding
  or owner to recreate.

## Meaning of semantic equality

Existing resolution handles selectors, relative paths, constants and map entries.
The comparison additionally normalizes schema URL spelling, editorial `$id` /
`$comment` / `$keyType`, explicit `visible: always`, equivalent whole-array
interpolation references, and labels/formatters on fields that are permanently
hidden. Omitted and unconditionally hidden fields both produce no display; conditional
visibility and validation such as `mustMatch` remain part of the comparison.

Field order, group structure, labels, iteration strategy, separators, visible
formatters and their parameters, thresholds, visibility conditions, bindings,
metadata and template wording are retained. Negative-control tests change these
properties and prove that meaningful differences are detected. There is no blanket
"ignore fields/metadata/params" normalization and no snapshot regeneration in CI.

## Reproducing compiler fixtures

With solc 0.8.30 installed **outside this package**, run:

```sh
node tests/generate/natspec/data/upstream_examples/compile.cjs /absolute/path/to/node_modules/solc
.venv/bin/python -m pytest tests/generate/natspec/test_upstream_examples.py -q --no-cov
```

`compile.cjs` rejects a different compiler version. Changing a source without
regenerating its artifact fails the source-hash check. Repeated map declarations
end with commas because solc concatenates repeated custom-tag values without
inserting a separator.

To inspect a recreated bundle:

```sh
.venv/bin/python -c 'from tests.generate.natspec.upstream_examples import assemble; print(assemble("example-main").to_json_string())'
```

This does not deploy contracts, execute on-chain logic, submit to a registry, or
assert that a wallet renderer supports every feature illustrated upstream.

The array-iteration example's native-value field, named bundled group, separators,
and percentage unit parameters all come from its compiler annotations. Address-name
restrictions, calldata bindings, thresholds, and visibility conditions in the other
examples also come from production tags. Metadata/length-field authoring in separate
intent tests remains outside these recipe cleanups.
