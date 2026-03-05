from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field


class StockInput(BaseModel):
    ticker: str = Field(..., description="Stock ticker symbol (e.g., AAPL)")
    qty: int = Field(..., gt=0, description="Number of shares")
    currency: str = Field(default="USD", description="Currency code")


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


class StockGiftResult(BaseModel):
    ticker: str
    qty: int
    currency: str
    price_average: Decimal = Field(..., description="Average closing price over period")
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


class GiftCalculationResult(BaseModel):
    gift_date: date
    stocks: list[StockGiftResult]
    total_gift_amount_krw: Decimal = Field(..., description="Total gift amount in KRW")
    exchange_rate_date: date
