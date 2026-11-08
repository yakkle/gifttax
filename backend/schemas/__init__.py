"""Pydantic request, response, and calculation data contracts."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

type AssetType = Literal["stock", "etf"]
type RequestedAssetType = Literal["auto", "stock", "etf"]
type CurrencyCode = Literal["USD", "EUR", "JPY", "GBP", "CNY", "CHF", "CAD", "AUD"]


class StockInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL)")
    qty: int = Field(..., gt=0, description="Number of shares")
    currency: CurrencyCode = Field(default="USD", description="Currency code")
    asset_type: RequestedAssetType = "auto"

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        return value.upper() if isinstance(value, str) else value


class GiftCalculationInput(BaseModel):
    gift_date: date = Field(..., description="Date of gift (증여일)")
    stocks: list[StockInput] = Field(..., min_length=1, description="List of stocks to calculate")


class StockPrice(BaseModel):
    date: date
    close: Decimal


class ExchangeRate(BaseModel):
    date: date
    rate: Decimal


class PriceDataPoint(BaseModel):
    date: str
    close: str


class ExchangeRateEvidence(BaseModel):
    currency: str
    rate: Decimal
    actual_rate_date: date
    period_start: date
    period_end: date
    source_unit: int = 1
    source_url: str
    rates: list[PriceDataPoint] = Field(default_factory=list)


class StockGiftResult(BaseModel):
    ticker: str
    qty: int
    currency: str
    asset_type: AssetType = "stock"
    detection_method: Literal["auto", "manual"] = "manual"
    valuation_method: Literal["average_close", "previous_close"] = "average_close"
    valuation_price: Decimal | None = None
    price_date: date | None = None
    price_date_note: str | None = None
    price_source_url: str | None = None
    quote_currency: str | None = None
    price_multiplier: Decimal = Decimal(1)
    price_average: Decimal = Field(..., description="호환용 평가단가: 주식 평균종가 또는 ETF 적용종가")
    price_data: list[PriceDataPoint] = Field(
        default_factory=list, description="Price data used for calculation"
    )
    period_start: date
    period_end: date
    exchange_rate: Decimal = Field(..., description="Exchange rate on gift date")
    exchange_rate_date: date
    exchange_rate_data: list[PriceDataPoint] = Field(
        default_factory=list, description="Exchange rate data used"
    )
    gift_amount_krw: Decimal = Field(..., description="Gift amount in KRW")

    @model_validator(mode="after")
    def fill_valuation_price(self):
        if self.valuation_price is None:
            self.valuation_price = self.price_average
        return self


class GiftCalculationResult(BaseModel):
    gift_date: date
    stocks: list[StockGiftResult]
    total_gift_amount_krw: Decimal = Field(..., description="Total gift amount in KRW")
    estimated_tax: Decimal = Field(default=Decimal(0), description="Estimated gift tax in KRW")
    exchange_rate_date: date
    exchange_rate_evidence: list[ExchangeRateEvidence] = Field(default_factory=list)
    gift_pdf_file_id: str | None = Field(default=None, description="계산 증빙 PDF file ID")
    rate_pdf_file_id: str | None = Field(default=None, description="매매기준환율 PDF file ID")
