"""해외 종목 조회 및 상품 유형 판별 데이터 계약."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas import AssetType, StockPrice

type DetectionStatus = Literal["detected", "needs_selection", "unsupported"]


class InstrumentMetadata(BaseModel):
    ticker: str
    instrument_type: str | None = None
    currency: str | None = None
    quote_currency: str | None = None
    price_multiplier: Decimal = Field(default=Decimal(1), gt=0)
    exchange_name: str | None = None
    exchange_timezone: str | None = None


class InstrumentDetection(InstrumentMetadata):
    asset_type: AssetType | None = None
    detection_status: DetectionStatus
    reason: Literal[
        "missing_type", "unknown_type", "metadata_unavailable", "unsupported_type"
    ] | None = None
    message: str | None = None


class InstrumentPriceHistory(BaseModel):
    metadata: InstrumentMetadata
    prices: list[StockPrice]


class InstrumentResolution(BaseModel):
    metadata: InstrumentMetadata
    asset_type: AssetType
    detection_method: Literal["auto", "manual"]
