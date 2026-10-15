"""Translate address-name source policies without widening explicit restrictions."""

from erc7730.common.output import OutputAdder
from erc7730.model.calldata.types import TrustedNameSource, TrustedNameType


def convert_name_sources(
    types: list[TrustedNameType], sources: list[str] | None, out: OutputAdder
) -> list[TrustedNameSource] | None:
    result: list[TrustedNameSource] = []
    if sources is not None:
        if not sources:
            return out.error(title="Invalid address-name sources", message="An explicit source list cannot be empty.")
        for source in sources:
            normalized = source.strip().lower()
            if normalized == "local":
                result.extend((TrustedNameSource.LOCAL_ADDRESS_BOOK, TrustedNameSource.MULTISIG_ADDRESS_BOOK))
            else:
                try:
                    result.append(TrustedNameSource(normalized))
                except ValueError:
                    return out.error(
                        title="Unsupported address-name source",
                        message=f'Ledger export cannot represent source "{source}"; '
                        "explicit restrictions cannot be ignored.",
                    )
    else:
        for type_ in types:
            match type_:
                case TrustedNameType.EOA | TrustedNameType.WALLET | TrustedNameType.COLLECTION:
                    result.extend(
                        (TrustedNameSource.ENS, TrustedNameSource.UNSTOPPABLE_DOMAIN, TrustedNameSource.FREENAME)
                    )
                case TrustedNameType.SMART_CONTRACT | TrustedNameType.TOKEN:
                    result.append(TrustedNameSource.CRYPTO_ASSET_LIST)
                case TrustedNameType.CONTEXT_ADDRESS:
                    result.append(TrustedNameSource.DYNAMIC_RESOLVER)
        if not result:
            return list(TrustedNameSource)
    return list(dict.fromkeys(result))
