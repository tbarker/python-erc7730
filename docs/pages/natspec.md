# Compiler NatSpec overlay

The [CLI](cli-natspec) and [Python library](library-generate) generate V2 descriptors
from ABI or EIP-712 schemas. `@notice` supplies intents, `@param` supplies labels,
and `@custom:clearsig-*` supplies explicit display rules.

## Inputs and defaults

`--natspec PATH` accepts compiler JSON: paired `userdoc`/`devdoc`, a raw document with
`kind: "user"` or `"dev"`, or an artifact containing docs at the root or in
`metadata.output`. Artifact ABI is used when `--abi` is omitted. Alternatively, use
`--userdoc` and `--devdoc`; these conflict with a `--natspec` containing both documents.
Library arguments accept JSON strings, bytes or dictionaries. Inheritance must already
be resolved in compiler docs.

```shell
forge build --extra-output userdoc --extra-output devdoc
erc7730 natspec --chain-id 1 --address 0x2222222222222222222222222222222222222222 \
 --natspec out/Token.sol/Token.json --owner "Example" --url https://example.com \
 > calldata-token.json
erc7730 lint --v2 --strict calldata-token.json
```

Method docs join by canonical signature, also accepting declarations with parameter
names. Unnamed inputs receive positional names. Missing documentation never hides
inputs. Amount-like integers stay `raw` unless assigned a currency formatter or
referenced by a calldata `amount-path`; address/date/duration heuristics still apply.

Project settings go under `[generate]` in `erc7730.toml`:

```toml
[generate]
"custom:clearsig-format" = "amount=tokenAmount deadline=date"
"custom:clearsig-token-path" = "amount=@.to"
"custom:clearsig-date-encoding" = "deadline=timestamp"
"custom:clearsig-exclude" = "nonce"
```

The CLI reads the nearest config or `--config PATH`, without merging parent files.
Library callers pass `project_defaults`. Flat `custom:clearsig-*` keys and nested
`custom` objects are accepted; flat keys win.

Precedence is **method > contract > project > heuristics**, per field/parameter.
Intent, labels, groups, inline enums and typed-data declarations are method-only;
owner, URL and constants are contract-only; maps are project/contract-level.
Exclusions accumulate and win: affected leaves become `visible: "never"`.
Missing project/contract exclusion targets are ignored; missing method targets fail.

## Annotation value syntax

Assignments use `field=value`, separated by whitespace or commas. Unquoted labels
can contain spaces: `recipient=Recipient address amount=Amount to send`.
Quoted strings preserve commas and assignment-like text. Parameters also accept
JSON values, paths and map expressions. Enum labels require JSON strings;
constants require JSON scalars. Repeated enum, constant and map tags need trailing
commas because solc concatenates their values without whitespace.

Malformed field-assignment syntax warns with a line/column and skips the whole tag
value. Malformed enum, constant, map-definition or group syntax fails generation.
Unknown tags are ignored. Invalid formats, parameters and unmatched fields warn.

## Tag reference

Names use kebab-case; values retain schema spelling (`tokenAmount`, `@.chainId`).

| Tag | Value | Effect |
| --- | --- | --- |
| `@custom:clearsig-example` | `params=(...) intent="..." [fields={...}]` | Authored display test example |
| `@custom:clearsig-owner` | `Protocol DAO` | Contract-level `metadata.owner` |
| `@custom:clearsig-url` | `https://example.org/` | Contract-level `metadata.info.url` |
| `@custom:clearsig-constant` | `feeDecimals=2, feeBase="%"` | Contract-level scalar constants in `metadata.constants` |
| `@custom:clearsig-typed-data` | `PrimaryType` | Method-only EIP-712 schema opt-in from compiler ABI |
| `@custom:clearsig-intent` | Short static phrase | Static intent fallback |
| `@custom:clearsig-interpolated-intent` | `{path}` template | Explicit interpolated intent; overrides notice translation |
| `@custom:clearsig-exclude` | `param,param` | Marks fields or every leaf of a struct `visible: "never"` |
| `@custom:clearsig-group` | `id[="Label"] fields=(param,param) [iteration=bundled]` | Creates a display group (method scope) |
| `@custom:clearsig-label` | `param=Label` | Overrides the parameter label |
| `@custom:clearsig-separator` | `param="Recipient {index}"` | Sets the heading before each array element |
| `@custom:clearsig-format` | `param=FieldFormat` | Overrides the formatter and supplies display order |
| `@custom:clearsig-token-path` | `param=@.to` | Sets tokenAmount's token path |
| `@custom:clearsig-token` | `param=address-or-ref` or `param=map(name,keyPath)` | Sets tokenAmount's token or map lookup |
| `@custom:clearsig-map` | `mapName[key]=value` | Defines contract-level map entries |
| `@custom:clearsig-map-ref` | `param=parameter:mapName(keyPath)` | Sets a supported formatter parameter to a map lookup |
| `@custom:clearsig-date-encoding` | `param=timestamp` or `param=blockheight` | Sets date encoding |
| `@custom:clearsig-types`, `clearsig-sources` | `to=["contract"]`, `to=["local"]` | Optional address-name restrictions; generated `addressName` sources default to `["local","ens"]` |
| `@custom:clearsig-sender-address` | `to=address-or-ref` | Sender address binding |
| `@custom:clearsig-base`, `clearsig-decimals`, `clearsig-prefix` | `fee="%"`, `fee=2`, `fee=false` | Unit formatting |
| `@custom:clearsig-threshold`, `clearsig-message` | `amount=0xffff`, `amount="Unlimited"` | Token-amount threshold and text |
| `@custom:clearsig-native-currency-address` | `amount=address` or address array | Native currency sentinels |
| `@custom:clearsig-chain-id`, `clearsig-chain-id-path` | `amount=1`, `amount=@.chainId` | Token chain binding |
| `@custom:clearsig-callee`, `clearsig-callee-path` | `data=address`, `data=#.target` | Embedded calldata destination |
| `@custom:clearsig-selector`, `clearsig-selector-path` | `data="0xa9059cbb"`, `data=#.selector` | Embedded calldata selector |
| `@custom:clearsig-amount`, `clearsig-amount-path` | `data=123`, `data=@.value` | Embedded call native value; `amount-path` also infers `amount` for an existing compatible field unless its formatter is explicit |
| `@custom:clearsig-spender`, `clearsig-spender-path` | `data=address`, `data=#.spender` | Embedded call sender binding |
| `@custom:clearsig-collection`, `clearsig-collection-path` | `id=address`, `id=#.collection` | NFT collection binding |
| `@custom:clearsig-enum` | `mode[0]="Stable", mode[1]="Variable"` | Defines a method-local enum and automatically sets its formatter and reference |
| `@custom:clearsig-enum-ref` | `mode=$.metadata.enums.modes` | Enum formatter's `$ref` |
| `@custom:clearsig-visible` | `field=always\|optional\|never` | Simple visibility |
| `@custom:clearsig-must-match` | `legacy=[0]` | Hide field and require one of these values |
| `@custom:clearsig-if-not-in` | `fee=[0]` | Display unless value is in this list |
| `@custom:clearsig-encryption-scheme` | `param=fhevm` | Sets `encryption.scheme` |
| `@custom:clearsig-plaintext-type` | `param=uint64` | Sets the decrypted Solidity type |
| `@custom:clearsig-fallback-label` | `param=[Encrypted amount]` | Sets the display fallback when decryption is unavailable |

Use schema format names or enum names such as `ADDRESS_NAME`. Targets include
`order.amount`; exact names win, then leading-underscore and case-insensitive matching.
Struct groups cannot receive leaf formatters.

`clearsig-format amount=tokenAmount to=addressName` also puts amount first.
The most specific nonempty format tag supplies order; unmentioned fields retain ABI
order and nested groups remain intact. Compiler JSON preserves order within a tag,
not between tags or `@param` lines.

## Intent and label templates

A plain notice's first sentence becomes static `intent`, capped at 60 characters.
``Send `amount` to `to` `` becomes `Send {amount} to {to}` and needs a static fallback:

```solidity
/// @notice Send `amount` tokens to `to`
/// @custom:clearsig-intent Send tokens
```

Custom static intents cap at 80 characters; templates warn above 80 but are preserved.
Translation supports nested fields, arrays, indices/slices and lengths, such as
`orders[0].maker`, `amounts[:2]` and `amounts.length`, plus `@.value` and metadata paths.
Array selectors become descriptor paths such as `{amounts.[0]}`.

For arithmetic, calls or computed indices, supply an explicit template:

```solidity
/// @notice Send `amount / 10**18` tokens to `to`
/// @custom:clearsig-interpolated-intent Send {amount} to {to}
/// @custom:clearsig-intent Send tokens
```

Each reference needs a valid path and exactly one always-visible formatter.
References do not create fields. Explicit templates preserve backticks; doubled braces
escape literal braces. A templated `@param` requires a static `clearsig-label` override.
Descriptor lint requires a static intent for every format, even undocumented drafts.

## Complex example

```solidity
// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.30;

/// @title Example Token
/// @author Example
/// @custom:clearsig-format amount=tokenAmount
/// @custom:clearsig-token-path amount=@.to
/// @custom:clearsig-exclude nonce
interface Token {
    struct Order { address maker; uint256 amount; uint256 deadline; }

    /// @notice Send `amount` to `to`
    /// @param to Recipient
    /// @param amount Amount
    /// @custom:clearsig-intent Send tokens
    /// @custom:clearsig-example params=(Alice,1500000) intent="Send 1.5 USDC to Alice"
    function transfer(address to, uint256 amount) external;

    /// @notice Settle an order
    /// @param order Order to settle
    /// @param fee Processing fee
    /// @param nonce Replay protection
    /// @custom:clearsig-format order.amount=tokenAmount order.maker=addressName order.deadline=date fee=unit
    /// @custom:clearsig-token-path order.amount=@.to
    /// @custom:clearsig-date-encoding order.deadline=timestamp
    /// @custom:clearsig-label order.amount=Amount order.maker=Maker order.deadline=Deadline fee=Fee
    /// @custom:clearsig-base fee="%"
    /// @custom:clearsig-decimals fee=2
    /// @custom:clearsig-if-not-in fee=[0]
    /// @custom:clearsig-group settlement="Settlement" fields=(order.amount,order.maker)
    /// @custom:clearsig-example params=((Alice,1500000,1700000000),0,42) intent="Settle an order" fields={"Amount":"1.5 USDC","Maker":"Alice"}
    function settle(Order calldata order, uint256 fee, uint256 nonce) external;

    /// @notice Distribute fees
    /// @param recipients Recipient ID
    /// @param percentages Fee
    /// @custom:clearsig-format recipients=raw percentages=raw
    /// @custom:clearsig-group fees="Recipients and Fees" fields=(recipients,percentages) iteration=bundled
    /// @custom:clearsig-example params=([1,2],[25,75]) intent="Distribute fees"
    function distribute(uint256[] calldata recipients, uint256[] calldata percentages) external;
}
```

Save as `Token.sol`, compile as above, and configure test data in `erc7730.toml`:

```toml
[generate]
natspec = "out/Token.sol/Token.json"

[generate.examples]
maxSanityCases = 32

[generate.examples.aliases]
Alice = "0x1111111111111111111111111111111111111111"

[generate.examples.dataProvider.addressNames]
"0x1111111111111111111111111111111111111111" = "Alice"

[generate.examples.dataProvider.tokens."0x2222222222222222222222222222222222222222"]
symbol = "USDC"
decimals = 6
name = "USD Coin"
```

Aliases resolve input arguments; `addressNames` controls displayed names.

(natspec-examples)=
## Running examples: CLI and library

Examples compare the rendered intent exactly. Optional `fields={"Label":"Expected text"}`
checks field values; each asserted label must appear exactly once.
Arguments may be positional or fully named: `params=(amount=1500000,to=Alice)`.
Supply hidden inputs too. Values support raw-unit integers, booleans, quoted strings,
hex addresses/bytes, aliases, arrays and positional tuples. Repeat tags for multiple cases.

Example execution requires a compatible renderer supplied by the user. The default
command is `clear-signing-test-runner`; override it with `--example-runner`:

```shell
erc7730 natspec --chain-id 1 --address 0x2222222222222222222222222222222222222222 \
 --owner "Example" --example-runner 'node /path/to/dist/cli.js' > calldata-token.json
erc7730 lint --v2 --strict calldata-token.json --example-runner 'node /path/to/dist/cli.js' \
 --junit-xml reports/lint.xml
```

Both commands discover the config above; compiler paths are relative to that file.
CLI inputs override config. Inline examples activate testing; supplying a renderer
also enables automatic cases. Lint needs compiler inputs to rerun authored examples.

```python
import tomllib
from pathlib import Path
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.generate.natspec.examples import CommandExampleRunner, NatSpecExamples

compiler_json = Path("out/Token.sol/Token.json").read_bytes()
defaults = tomllib.loads(Path("erc7730.toml").read_text())["generate"]
renderer = CommandExampleRunner(["node", "/path/to/dist/cli.js"])
descriptor = generate_natspec_descriptor(
    1, "0x2222222222222222222222222222222222222222",
    natspec=compiler_json, project_defaults=defaults, example_renderer=renderer,
)
examples = NatSpecExamples(natspec=compiler_json, config=defaults["examples"], renderer=renderer)
report = examples.run(descriptor)  # Explicit rerun after editing, if needed.
```

Pass `examples` to `lint_all(..., examples=examples)` to run them during lint.
An `ExampleRenderer` callable can replace the subprocess adapter. See
[example failures](natspec-example-failures) and [JUnit reports](junit-lint-reports).

(automatic-sanity-examples)=
## Automatic sanity checks

Automatic cases exercise numeric/time boundaries, arrays, nested fields, address
fallbacks, visibility and interpolation. `[generate.examples]` accepts
`automatic=true` and `maxSanityCases=32` (1–128 per function).
With `automatic=false`, example-enabled lint requires an authored example per function.
`sanity_unavailable` and CLI warnings identify unsupported checks and budget limits.

(encrypted-fields-and-examples)=
## Encryption

For encrypted `bytes32 amount`, use `clearsig-encryption-scheme amount=fhevm`,
`clearsig-plaintext-type amount=uint64`, and
`clearsig-fallback-label amount=[Encrypted amount]`. A scheme is required; plaintext
Solidity types must be canonical and determine formatter compatibility.

`fields={"Amount":"[Encrypted amount]"}` checks fallback rendering, the default
`encryptionMode="fallback"`. For a decrypting renderer, set
`generate.examples.encryptionMode="external"` and assert decrypted text instead.
Automatic plaintext checks then report an unavailable oracle.

(metadata-annotations)=
## Contract metadata

```solidity
/// @title Fee Controller
/// @author Contract Developer
/// @custom:clearsig-owner Protocol DAO
/// @custom:clearsig-url https://example.org/
/// @custom:clearsig-constant feeBase="%",
/// @custom:clearsig-constant feeDecimals=2,
interface FeeController {
    /// @notice Set fee
    /// @custom:clearsig-format fee=unit
    /// @custom:clearsig-base fee=$.metadata.constants.feeBase
    /// @custom:clearsig-decimals fee=$.metadata.constants.feeDecimals
    function setFee(uint256 fee) external;
}
```

`@title` supplies the contract name. Owner falls back to `@author`, then `@title`.
Precedence is **explicit owner/URL arguments > supplied metadata > annotations**.
Constants merge by key; supplied values win, including `null`. Devdoc overrides userdoc.

Owner must be nonempty and URL must be HTTP(S). Constants use identifier names and
JSON scalars; quote hex values and paths, e.g. `sentinel="0x00"`. Conflicting repeated
constants, malformed values and tags outside contract scope fail generation, even when
overridden by explicit inputs. Identical repeated constants are allowed.

(nested-calldata)=
## Nested calldata and native amounts

`amount-path` identifies the forwarded native value and infers the referenced field's
`amount` formatter:

```solidity
struct Call {
    address target;
    uint256 value;
    bytes data;
}

/// @notice Execute calls
/// @custom:clearsig-format calls.data=calldata
/// @custom:clearsig-callee-path calls.data=target
/// @custom:clearsig-amount-path calls.data=value
function executeBatch(Call[] calldata calls) external payable;
```

Here `target` and `value` are relative to each `Call` instance. Absolute paths must
include array traversal, e.g. `#.calls.[].value`. Parallel arrays also work with
bindings such as `datas=values.[]`. Address fields already default to `addressName`
with `["local", "ens"]` sources.

Inference uses the final valid binding. Explicit formatters at any scope, including
`raw`, take precedence. It adds no fields or ordering hints and leaves visibility intact.
A constant `clearsig-amount` does not infer a formatter.

(inline-enums)=
## Inline enums

```solidity
/// @custom:clearsig-enum mode[0]="Stable", mode[1]="Variable"
function borrow(uint8 mode) external;
```

Generation creates `metadata.enums`, the enum formatter and its reference, scoped
by function signature and field path. Solidity enum members are not inferred.
Ordinals must be nonnegative decimal uint256 values; labels are nonempty JSON strings.
Nested targets use `orders.mode[0]="Stable"`; the final brackets specify the enum value.
Missing/ambiguous targets, incompatible types and conflicting labels fail generation.

Inline enums override inherited formats. A different method-level formatter or an
explicit `clearsig-enum-ref` conflicts; exclusions still win.

To reuse supplied `metadata.enums`, combine `clearsig-format mode=enum` with
`clearsig-enum-ref mode=$.metadata.enums.modes`.

(dynamic-maps)=
## Dynamic maps

Define entries in `[generate.maps.poolTokens.values]` or use a contract annotation:
`@custom:clearsig-map poolTokens[1]=0x1111111111111111111111111111111111111111`.

Use `clearsig-token amount=map(poolTokens,#.poolId)` or
`clearsig-map-ref amount=chainId:chains(#.destination)`. Supported parameters include
token/chain, sender, calldata bindings and NFT collection. Contract entries override
project entries by key. Map values must be scalars.
Keys select one scalar: integers use decimal strings, booleans `true`/`false`, bytes
`0x` hex. Missing keys invalidate the transaction; there is no default.
Ledger calldata export supports maps; deployment keys resolve to constants.
Legacy EIP-712 export does not support runtime maps.

(named-display-groups)=
## Groups and array headings

Method-only `clearsig-group id="Label" fields=(a,b)` moves existing fields into a root
display group, preserving their settings and rebasing paths. Omit the label for an
unlabeled group. Select structs or individual leaves; groups cannot contain other named
groups. Placement follows the earliest member; emptied/unlabeled scalar-struct wrappers
are removed. Use semicolons between multiple/repeated group declarations.

`iteration=bundled` pairs parallel array elements and requires equal lengths;
`iteration=sequential` displays each array in full. Iteration requires an array member.
Missing, ambiguous, duplicate, overlapping or excluded members are generation errors.

For per-element headings use `clearsig-separator recipients="Recipient {index}"`.
Only `{index}` and doubled literal braces are supported; scalar targets or invalid
patterns warn.

(container-display-fields)=
## Container values

Only an explicit valid format tag, such as `clearsig-format @.value=amount`, adds a
container display field. Labels/notices alone do not create fields. Supported paths:

| Path | Calldata | EIP-712 |
| --- | --- | --- |
| `@.from` | Sender | Signer |
| `@.to` | Destination contract | Verifying contract |
| `@.value` | Native currency value | No transfer; generation warns |
| `@.chainId` | Transaction chain | Verifying contract's chain |

Bare `value` names an input. Inline examples use zero-value transactions; a nonzero
payment test requires an explicit transaction supplied to the renderer.

(formatter-parameters-and-visibility)=
## Parameters and visibility

Generated `addressName` fields default to `sources: ["local", "ens"]`, whether their
formatter is inferred or explicit. Override with `clearsig-sources spender=["local"]`.

Source lists replace inherited lists. Sources/types may reference metadata constants;
a referenced string becomes a one-element list. Missing references, empty lists and
invalid values fail resolution. Ledger export preserves supported explicit sources
and rejects unsupported ones; omitted sources retain its type-derived defaults.

Parameter tags accept JSON values and metadata references. Thresholds accept decimal/hex
strings. Constant/path alternatives replace each other. Reselecting a formatter preserves
parameters; changing it clears incompatible settings. Explicit `addressName` clears
heuristic type restrictions but preserves authored types/sources. Invalid overrides
warn and retain earlier valid values; incomplete final parameter sets also warn.

`visible=always|optional|never`, `must-match=[...]` and `if-not-in=[...]` are alternative
settings; the latter two require nonempty lists. More-specific settings replace inherited
ones; conflicts within one scope fail. Exclusions win. Conditional/hidden fields cannot
supply interpolated-intent formatters.

(eip-712-schema-bridge)=
## EIP-712 bridge and examples

Method-level `@custom:clearsig-typed-data Permit` selects typed-message generation from
compiler ABI. Parameters become primary-type fields in ABI order; structs keep their
compiler `internalType` names and nesting, including a sole struct parameter. Only
annotated methods become messages. Notices, labels, display tags and examples follow
the method. Output uses full `encodeType` declarations with sorted dependent types.

The bridge cannot combine with an explicit schema. Duplicate primary types, conflicting
definitions, unnamed members, unsupported types and recursive expansion fail generation.
For an explicit EIP-712 schema, docs can instead join by primary type.

Typed examples use the same argument syntax; tuples become named objects and integers
become decimal strings. Set `generate.examples.sender` for `@.from`. One deployment
plus domain constraints can infer the domain; multiple deployments or domain-separator
bindings require a complete `generate.examples.domain`. `@.to`/`@.chainId` need the
corresponding domain values.

Custom primitive domain fields require an ordered `domainTypes` list; domain structs
and arrays are unsupported. Domain integers must fit the runner's JSON safe-integer
range; message integers retain full precision.
