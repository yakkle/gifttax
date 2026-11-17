"""상품 유형별 종가 선택과 평가단가 산정."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from backend.integrations.scraper import yahoo
from backend.schemas import StockPrice
from backend.schemas.instruments import InstrumentMetadata, InstrumentResolution
from backend.services.instruments import InstrumentError, validate_price_metadata


@dataclass(frozen=True)
class PriceValuation:
    price: Decimal
    prices: list[StockPrice]
    metadata: InstrumentMetadata
    start: date
    end: date
    price_date: date | None = None
    note: str | None = None


def get_price_valuation(
    resolution: InstrumentResolution, currency: str, start: date, end: date, gift_date: date
) -> PriceValuation:
    ticker = resolution.metadata.ticker
    try:
        history = yahoo.get_instrument_prices(ticker, start, end + timedelta(days=1))
    except yahoo.InvalidTickerError as error:
        raise InstrumentError("INVALID_TICKER", str(error), ticker) from error
    except yahoo.YahooFinanceError as error:
        raise InstrumentError(
            "PRICE_LOOKUP_FAILED", f"{ticker}: 종가를 조회하지 못했습니다.", ticker, status_code=503
        ) from error
    validate_price_metadata(resolution, history.metadata, currency)
    # 어댑터의 날짜 필터와 별도로 평가 경계를 지켜 당일·미래 가격을 배제한다.
    prices = sorted((p for p in history.prices if start <= p.date <= end), key=lambda p: p.date)
    if not prices:
        raise InstrumentError(
            "PRICE_DATA_UNAVAILABLE", f"{ticker}: 평가 기간의 종가 데이터가 없습니다.",
            ticker, status_code=422,
        )
    if resolution.asset_type == "stock":
        average = round(sum((p.close for p in prices), Decimal(0)) / len(prices), 2)
        return PriceValuation(average, prices, history.metadata, start, end)

    selected = prices[-1]
    note = None
    if selected.date < gift_date - timedelta(days=1):
        note = "증여일 전일 종가가 없어 이전 최근 거래일의 종가를 적용했습니다."
    return PriceValuation(
        selected.close, [selected], history.metadata, selected.date, selected.date,
        price_date=selected.date, note=note,
    )
