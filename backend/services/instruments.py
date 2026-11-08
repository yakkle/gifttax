"""외부 종목 메타정보를 바탕으로 지원하는 평가 유형을 판별한다."""

import re

from backend.integrations.scraper import yahoo
from backend.schemas.instruments import AssetType, InstrumentDetection, InstrumentMetadata

INSTRUMENT_TYPES: dict[str, AssetType] = {"EQUITY": "stock", "ETF": "etf"}
UNSUPPORTED_INSTRUMENT_TYPES = {
    "MUTUALFUND", "INDEX", "FUTURE", "CRYPTOCURRENCY", "BOND", "ETN", "OPTION",
    "CURRENCY", "WARRANT",
}


class InstrumentError(Exception):
    def __init__(self, code: str, message: str, ticker: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.ticker = ticker
        self.status_code = status_code


def normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.^=_-]{0,63}", normalized):
        raise InstrumentError("INVALID_TICKER", "종목 코드를 확인해 주세요.", normalized)
    return normalized


def detect_instrument(metadata: InstrumentMetadata) -> InstrumentDetection:
    """알려진 미지원 유형은 수동 선택 대상으로 취급하지 않는다."""
    asset_type = INSTRUMENT_TYPES.get(metadata.instrument_type)
    if asset_type:
        return InstrumentDetection(
            **metadata.model_dump(), asset_type=asset_type, detection_status="detected"
        )
    if metadata.instrument_type in UNSUPPORTED_INSTRUMENT_TYPES:
        return InstrumentDetection(
            **metadata.model_dump(),
            detection_status="unsupported",
            reason="unsupported_type",
            message="해외 상장 주식과 ETF만 지원합니다.",
        )
    return InstrumentDetection(
        **metadata.model_dump(),
        detection_status="needs_selection",
        reason="unknown_type" if metadata.instrument_type else "missing_type",
        message="상품 유형을 확인할 수 없습니다. 주식 또는 ETF를 선택해 주세요.",
    )


def lookup_instrument(ticker: str) -> InstrumentDetection:
    normalized = normalize_ticker(ticker)
    try:
        metadata = yahoo.get_instrument_metadata(normalized)
    except yahoo.InvalidTickerError as error:
        raise InstrumentError(
            "INVALID_TICKER", f"종목 코드를 찾을 수 없습니다: {normalized}", normalized
        ) from error
    except yahoo.YahooFinanceError:
        return InstrumentDetection(
            ticker=normalized,
            detection_status="needs_selection",
            reason="metadata_unavailable",
            message="종목 정보를 조회하지 못했습니다. 다시 시도하거나 주식 또는 ETF를 선택해 주세요.",
        )
    return detect_instrument(metadata)
