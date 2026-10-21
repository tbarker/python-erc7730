"""Compiler-authored logical groups preserve field meanings and membership."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from erc7730.common.output import ListOutputAdder
from erc7730.convert.resolved.v2.convert_erc7730_input_to_resolved import ERC7730InputToResolved
from erc7730.generate.natspec.generate import generate_natspec_descriptor
from erc7730.lint.v2.lint_validate_intent import ValidateIntentLinter
from erc7730.main import app
from erc7730.model.input.v2.display import InputFieldGroup

SOURCE = Path(__file__).parent / "data/groups.artifact.json"
ADDRESS = "0x1111111111111111111111111111111111111111"
SEND = "send(address maker,address recipient,uint256 amount)"


def test_compiler_groups_library_cli_and_resolver() -> None:
    descriptor = generate_natspec_descriptor(1, ADDRESS, natspec=SOURCE.read_text())
    amount, group = descriptor.display.formats[SEND].fields
    assert str(amount.path) == "#.amount"
    assert isinstance(group, InputFieldGroup)
    assert group.label == "Parties"
    assert group.path is None
    assert [str(field.path) for field in group.fields] == ["#.recipient", "#.maker"]
    assert [field.label for field in group.fields] == ["Recipient", "Sender"]
    arrays = descriptor.display.formats["distribute(uint256[] recipients,uint256[] percentages)"].fields
    assert len(arrays) == 1
    assert isinstance(arrays[0], InputFieldGroup)
    assert arrays[0].iteration == "bundled"
    result = CliRunner().invoke(app, ["natspec", "--chain-id", "1", "--address", ADDRESS, "--natspec", str(SOURCE)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(descriptor.to_json_string())
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateIntentLinter().lint(descriptor, resolved, out)
    assert not out.has_errors, out.outputs


@pytest.mark.parametrize(
    "tag, error",
    [
        ('g="Group" fields=(missing)', "missing or ambiguous"),
        ('g="Group" fields=(maker,maker)', "duplicate membership"),
        ('g="One" fields=(maker); h="Two" fields=(maker)', "duplicate membership"),
        ('g="One" fields=(maker); g="Two" fields=(recipient)', "duplicate group identifier"),
        ('g="Group" fields=(maker) iteration=bundled', "requires an array"),
        ('g="Group" fields=(maker) iteration=wrong', "IterationStrategy"),
        ('g="Group" fields=()', "nonempty"),
        ('g="Group" fields=(maker) unexpected=true', "group syntax"),
    ],
)
def test_invalid_groups_are_natspec_lint_errors(tag: str, error: str) -> None:
    docs = json.loads(SOURCE.read_text())
    docs["devdoc"]["methods"]["send(address,address,uint256)"]["custom:clearsig-group"] = tag
    with pytest.raises(ValueError, match=error):
        generate_natspec_descriptor(1, ADDRESS, natspec=docs)


def test_multiple_groups_follow_existing_positions() -> None:
    docs = json.loads(SOURCE.read_text())
    docs["devdoc"]["methods"]["send(address,address,uint256)"]["custom:clearsig-group"] = (
        'p="Parties" fields=(recipient,maker); a="Amount" fields=(amount)'
    )
    result = generate_natspec_descriptor(1, ADDRESS, natspec=docs)
    assert [field.label for field in result.display.formats[SEND].fields] == ["Amount", "Parties"]


def test_nested_members_rebase_formatter_paths() -> None:
    abi = [
        {
            "type": "function",
            "name": "send",
            "inputs": [
                {
                    "name": "order",
                    "type": "tuple",
                    "components": [
                        {"name": "token", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "nonce", "type": "uint256"},
                    ],
                },
                {"name": "recipient", "type": "address"},
            ],
            "outputs": [],
        }
    ]
    doc = {
        "methods": {
            "send((address,uint256,uint256),address)": {
                "custom:clearsig-intent": "Send",
                "custom:clearsig-interpolated-intent": "Send {order.amount}",
                "custom:clearsig-format": "order.amount=tokenAmount",
                "custom:clearsig-token-path": "order.amount=token",
                "custom:clearsig-group": 'payment="Payment" fields=(order.amount,recipient)',
            }
        }
    }
    descriptor = generate_natspec_descriptor(1, ADDRESS, abi=json.dumps(abi), devdoc=doc)
    group, *remainder = next(iter(descriptor.display.formats.values())).fields
    assert isinstance(group, InputFieldGroup)
    assert [str(field.path) for field in group.fields] == ["#.order.amount", "#.recipient"]
    assert group.fields[0].model_dump(mode="json", exclude_none=True)["params"] == {"tokenPath": "#.order.token"}
    assert [str(field.path) for field in remainder] == ["#.order.token", "#.order.nonce"]
    out = ListOutputAdder()
    resolved = ERC7730InputToResolved().convert(descriptor, out)
    assert resolved is not None, out.outputs
    ValidateIntentLinter().lint(descriptor, resolved, out)
    assert not out.has_errors, out.outputs


def test_excluded_group_member_is_error() -> None:
    docs = json.loads(SOURCE.read_text())
    docs["devdoc"]["methods"]["send(address,address,uint256)"]["custom:clearsig-exclude"] = "maker"
    with pytest.raises(ValueError, match="not a displayed leaf"):
        generate_natspec_descriptor(1, ADDRESS, natspec=docs)


@pytest.mark.parametrize("scope", ["project", "contract"])
def test_group_scope_requires_method(scope: str) -> None:
    tag = {"custom:clearsig-group": 'g="Group" fields=(amount)'}
    docs = json.loads(SOURCE.read_text())
    if scope == "contract":
        docs["devdoc"].update(tag)
    with pytest.raises(ValueError, match="must be declared on a method"):
        generate_natspec_descriptor(1, ADDRESS, natspec=docs, project_defaults=tag if scope == "project" else None)


def test_scalar_group_compaction_preserves_named_groups_and_rebases_parameters() -> None:
    from pydantic import TypeAdapter

    from erc7730.generate.natspec.display.groups import flatten_struct_groups
    from erc7730.model.input.v2.display import InputField

    fields = TypeAdapter(list[InputField]).validate_python(
        [
            {
                "path": "order",
                "fields": [
                    {"path": "amount", "label": "Amount", "format": "tokenAmount", "params": {"tokenPath": "token"}},
                    {
                        "path": "outputs.[]",
                        "fields": [
                            {
                                "path": "amount",
                                "label": "Output",
                                "format": "tokenAmount",
                                "params": {"tokenPath": "token"},
                            },
                        ],
                    },
                    {
                        "path": "info",
                        "label": "Details",
                        "fields": [{"path": "nonce", "label": "Nonce", "format": "raw"}],
                    },
                ],
            },
        ],
        strict=False,
    )
    amount, outputs, info = flatten_struct_groups(fields)
    assert str(amount.path) == "#.order.amount"
    assert amount.model_dump(mode="json")["params"]["tokenPath"] == "#.order.token"
    assert isinstance(outputs, InputFieldGroup)
    assert str(outputs.path) == "#.order.outputs.[]"
    assert str(outputs.fields[0].path) == "amount"
    assert outputs.fields[0].model_dump(mode="json")["params"]["tokenPath"] == "token"
    assert isinstance(info, InputFieldGroup) and info.label == "Details"
    assert str(info.path) == "#.order.info"
    assert str(info.fields[0].path) == "nonce"
