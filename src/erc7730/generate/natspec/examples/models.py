"""Wire models shared by authored and automatic example execution."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from erc7730.model.input.v2.descriptor import InputERC7730Descriptor
from erc7730.model.types import Address


class ExampleModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class RenderedField(ExampleModel):
    label: str
    value: str | RenderedDisplay


class RenderedDisplay(ExampleModel):
    intent: str
    interpolated_intent: str | None = Field(default=None, alias="interpolatedIntent")
    owner: str | None = None
    fields: list[RenderedField]


RenderedField.model_rebuild()


class ExampleCase(ExampleModel):
    description: str
    raw_tx: str | None = Field(default=None, alias="rawTx")
    data: dict[str, Any] | None = None
    expected: RenderedDisplay
    sender: str | None = Field(default=None, alias="from")

    @model_validator(mode="after")
    def exclusive_input(self) -> Self:
        if (self.raw_tx is None) == (self.data is None):
            raise ValueError("Example requires exactly one of rawTx or typed data.")
        if self.data is not None and self.sender is not None:
            raise ValueError("Typed example signer belongs in data.account.")
        return self


class TokenMetadata(ExampleModel):
    symbol: str
    decimals: int = Field(ge=0)
    name: str


class ExampleDataProvider(ExampleModel):
    tokens: dict[str, TokenMetadata] = Field(default_factory=dict)
    address_names: dict[str, str] = Field(default_factory=dict, alias="addressNames")
    ens_names: dict[str, str] = Field(default_factory=dict, alias="ensNames")
    nft_collection_names: dict[str, str] = Field(default_factory=dict, alias="nftCollectionNames")
    block_timestamps: dict[str, int] = Field(default_factory=dict, alias="blockTimestamps")

    @field_validator("tokens", "address_names", "ens_names", "nft_collection_names")
    @classmethod
    def normalize_addresses(cls, value: dict[str, Any]) -> dict[str, Any]:
        return {
            TypeAdapter(Address).validate_python(address, strict=False).lower(): entry
            for address, entry in value.items()
        }

    @field_validator("block_timestamps")
    @classmethod
    def validate_timestamps(cls, value: dict[str, int]) -> dict[str, int]:
        if any(not height.isdecimal() or timestamp < 0 for height, timestamp in value.items()):
            raise ValueError("Block timestamps require nonnegative integer heights and timestamps.")
        return value


class ExampleConfig(ExampleModel):
    """Shared input aliases and deterministic renderer data (no network lookups)."""

    automatic: bool = True
    encryption_mode: Literal["fallback", "external"] = Field(default="fallback", alias="encryptionMode")
    max_sanity_cases: int = Field(default=32, ge=1, le=128, alias="maxSanityCases")
    aliases: dict[str, str] = Field(default_factory=dict)
    data_provider: ExampleDataProvider = Field(default_factory=ExampleDataProvider, alias="dataProvider")
    sender: str | None = None
    domain: dict[str, Any] | None = None
    domain_types: list[dict[str, str]] | None = Field(default=None, alias="domainTypes")


class ExampleFixture(ExampleModel):
    descriptor: str
    data_provider: ExampleDataProvider = Field(alias="dataProvider")
    tests: list[ExampleCase]
    sanity_unavailable: list[str] = Field(default_factory=list, exclude=True)

    def to_json_string(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True, indent=2)


# A renderer consumes a provisional fixture and returns the registry runner's
# results object. Failures from comparison against provisional fields are normal;
# execution errors and the author's sentence assertion are handled below.
ExampleRenderer = Callable[[InputERC7730Descriptor, ExampleFixture], dict[str, Any]]
