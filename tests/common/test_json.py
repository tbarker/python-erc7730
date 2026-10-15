"""Include merging keeps generic data independent of V2 display policy."""

import json
from pathlib import Path
from typing import Any

import pytest

from erc7730.common.json import read_json_with_includes, read_jsons_with_includes
from erc7730.model.input.v2.descriptor import InputERC7730Descriptor


def test_v2_merges_only_display_fields(tmp_path: Path) -> None:
    base: dict[str, Any] = {
        "metadata": {"constants": {"payload": {"fields": [{"path": "x"}]}}},
        "display": {
            "formats": {
                "f()": {
                    "fields": [
                        {"path": "order", "fields": [{"path": "amount", "label": "Amount", "format": "raw"}]},
                        {"path": "to", "label": "To", "format": "raw"},
                    ]
                }
            }
        },
    }
    child = {
        "includes": "base.json",
        "metadata": {"constants": {"payload": {"fields": []}}},
        "display": {
            "formats": {
                "f()": {
                    "fields": [
                        {"path": "order", "fields": [{"path": "amount", "label": "Quantity"}]},
                    ]
                }
            }
        },
    }
    (tmp_path / "base.json").write_text(json.dumps(base))
    path = tmp_path / "child.json"
    path.write_text(json.dumps(child))
    v2 = read_json_with_includes(path, merge_display_fields=True)
    assert v2["metadata"]["constants"]["payload"]["fields"] == []
    fields = v2["display"]["formats"]["f()"]["fields"]
    assert len(fields) == 2
    assert fields[0]["fields"] == [{"path": "amount", "label": "Quantity", "format": "raw"}]
    # Generic and legacy loaders keep ordinary array replacement.
    generic = read_json_with_includes(path)
    assert generic["display"] == child["display"]
    assert read_jsons_with_includes([path]) == generic
    assert read_jsons_with_includes([path], merge_display_fields=True) == v2


def test_v2_model_load_selects_display_policy(tmp_path: Path) -> None:
    base = {
        "context": {"contract": {"deployments": [{"chainId": 1, "address": "0x" + "11" * 20}]}},
        "metadata": {"owner": "Example"},
        "display": {
            "formats": {
                "f(uint256 amount)": {
                    "intent": "Send",
                    "fields": [
                        {"path": "amount", "label": "Amount", "format": "raw"},
                    ],
                }
            }
        },
    }
    (tmp_path / "base.json").write_text(json.dumps(base))
    path = tmp_path / "child.json"
    path.write_text(
        json.dumps(
            {
                "includes": "base.json",
                "display": {
                    "formats": {
                        "f(uint256 amount)": {"fields": [{"path": "amount", "label": "Quantity"}]},
                    }
                },
            }
        )
    )
    descriptor = InputERC7730Descriptor.load(path)
    assert descriptor.display.formats["f(uint256 amount)"].fields[0].model_dump()["format"] == "raw"
    assert InputERC7730Descriptor.load_or_none(path) == descriptor
    assert InputERC7730Descriptor.load_or_none(tmp_path / "absent.json") is None


def test_http_includes_merge_fields_and_nested_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from erc7730.common import client

    documents: dict[str, dict[str, Any]] = {
        "https://example.com/sub/parent.json": {
            "includes": "../base.json",
            "display": {"formats": {"f": {"fields": [{"path": "to", "params": {"sources": ["ens"]}}]}}},
        },
        "https://example.com/base.json": {
            "display": {
                "formats": {
                    "f": {
                        "fields": [
                            {"path": "to", "label": "To", "params": {"types": ["wallet"]}},
                            {"path": "amount", "label": "Amount"},
                        ]
                    }
                }
            }
        },
    }

    def fetch(model: object, url: object) -> dict[str, Any]:
        return documents[str(url)]

    monkeypatch.setattr(client, "get", fetch)
    local = tmp_path / "child.json"
    local.write_text(
        json.dumps(
            {
                "includes": "https://example.com/sub/parent.json",
                "display": {
                    "formats": {
                        "f": {"fields": [{"path": "to", "label": "Recipient"}, {"path": "extra", "label": "Extra"}]}
                    }
                },
            }
        )
    )
    fields = read_json_with_includes(local, merge_display_fields=True)["display"]["formats"]["f"]["fields"]
    assert [f["path"] for f in fields] == ["to", "amount", "extra"]
    assert fields[0] == {"path": "to", "label": "Recipient", "params": {"types": ["wallet"], "sources": ["ens"]}}


def test_include_cycle(tmp_path: Path) -> None:
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text('{"includes": "b.json"}')
    b.write_text('{"includes": "a.json"}')
    with pytest.raises(ValueError, match="Circular ERC-7730 include"):
        read_json_with_includes(a)


def test_remote_include_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fetch(model: object, url: object) -> dict[str, Any]:
        return {"includes": "self.json"}

    monkeypatch.setattr("erc7730.common.client.get", fetch)
    file = tmp_path / "local.json"
    file.write_text('{"includes": "https://example.com/self.json"}')
    with pytest.raises(ValueError, match="Circular ERC-7730 include"):
        read_json_with_includes(file)


def test_reused_include_is_not_a_cycle(tmp_path: Path) -> None:
    (tmp_path / "base.json").write_text('{"metadata": {"owner": "Example"}}')
    (tmp_path / "left.json").write_text('{"includes": "base.json"}')
    (tmp_path / "right.json").write_text('{"includes": "base.json"}')
    file = tmp_path / "child.json"
    file.write_text('{"includes": ["left.json", "right.json"]}')
    assert read_json_with_includes(file)["metadata"]["owner"] == "Example"
