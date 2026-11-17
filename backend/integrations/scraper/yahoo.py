from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from curl_cffi import requests
from curl_cffi.requests.exceptions import RequestException

from backend.schemas import StockPrice
from backend.schemas.instruments import InstrumentMetadata, InstrumentPriceHistory


class YahooFinanceError(Exception):
    pass


class InvalidTickerError(Exception):
    pass


def _get_instrument_chart(ticker: str, params: dict) -> dict:
    symbol = quote(ticker.strip().upper(), safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
    try:
        with requests.Session(impersonate="chrome") as session:
            response = session.get(url, params=params, timeout=15)
    except RequestException as error:
        raise YahooFinanceError(f"종목 정보를 조회하지 못했습니다: {ticker}") from error

    if response.status_code == 404:
        raise InvalidTickerError(f"종목 코드를 찾을 수 없습니다: {ticker}")
    if response.status_code != 200:
        raise YahooFinanceError(f"종목 정보 조회 실패: {ticker} ({response.status_code})")

    try:
        chart = response.json()["chart"]
        if chart.get("error"):
            if chart["error"].get("code") == "Not Found":
                raise InvalidTickerError(f"종목 코드를 찾을 수 없습니다: {ticker}")
            raise YahooFinanceError(f"종목 정보 조회 실패: {ticker}")
        result = chart["result"][0]
        if not isinstance(result, dict):
            raise TypeError("Invalid chart result")
        return result
    except (ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise YahooFinanceError(f"종목 정보 응답을 확인할 수 없습니다: {ticker}") from error


def _metadata_from_chart(ticker: str, result: dict) -> InstrumentMetadata:
    meta = result.get("meta") or {}
    if not isinstance(meta, dict):
        raise YahooFinanceError(f"종목 메타정보를 확인할 수 없습니다: {ticker}")

    def text(key: str) -> str | None:
        value = meta.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    quote_currency = text("currency")
    # GBp는 파운드(GBP)의 1/100 단위이므로 대문자 변환 전에 구분한다.
    is_pence = quote_currency in {"GBp", "GBX"}
    currency = "GBP" if is_pence else quote_currency
    return InstrumentMetadata(
        ticker=ticker.strip().upper(),
        instrument_type=text("instrumentType"),
        currency=currency,
        quote_currency=quote_currency,
        price_multiplier=Decimal("0.01") if is_pence else Decimal(1),
        exchange_name=text("exchangeName"),
        exchange_timezone=text("exchangeTimezoneName"),
    )


def get_instrument_metadata(ticker: str) -> InstrumentMetadata:
    result = _get_instrument_chart(ticker, {"range": "5d", "interval": "1d"})
    return _metadata_from_chart(ticker, result)


def _parse_instrument_prices(
    result: dict, metadata: InstrumentMetadata, start_date: date, end_date: date
) -> list[StockPrice]:
    if not metadata.exchange_timezone or not metadata.currency:
        raise YahooFinanceError("시세의 거래소 시간대 또는 통화 정보가 없습니다.")
    try:
        exchange_timezone = ZoneInfo(metadata.exchange_timezone)
        timestamps = result.get("timestamp") or []
        if not timestamps:
            return []
        closes = result["indicators"]["quote"][0]["close"]
        prices = []
        for timestamp, close in zip(timestamps, closes, strict=True):
            if close is None:
                continue
            price_date = datetime.fromtimestamp(timestamp, exchange_timezone).date()
            price = Decimal(str(close)) * metadata.price_multiplier
            if not price.is_finite() or price <= 0:
                raise ValueError("Invalid closing price")
            if start_date <= price_date < end_date:
                prices.append(StockPrice(date=price_date, close=price))
        return sorted(prices, key=lambda item: item.date)
    except (
        ZoneInfoNotFoundError, ValueError, TypeError, KeyError, IndexError,
        OverflowError, OSError, InvalidOperation,
    ) as error:
        raise YahooFinanceError(f"종가 데이터를 확인할 수 없습니다: {metadata.ticker}") from error


def get_instrument_prices(
    ticker: str, start_date: date, end_date: date
) -> InstrumentPriceHistory:
    """거래소 날짜 기준 [start_date, end_date)의 종가를 기준 통화로 반환한다."""
    # UTC 요청 경계와 거래소 날짜 경계의 차이를 흡수한 뒤 실제 날짜로 필터링한다.
    period1 = int(datetime.combine(start_date - timedelta(days=1), datetime.min.time(), UTC).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), UTC).timestamp())
    result = _get_instrument_chart(
        ticker, {"period1": period1, "period2": period2, "interval": "1d"}
    )
    metadata = _metadata_from_chart(ticker, result)
    return InstrumentPriceHistory(
        metadata=metadata,
        prices=_parse_instrument_prices(result, metadata, start_date, end_date),
    )


def get_stock_price(
    ticker: str,
    target_date: date,
    country: str = "United States",
) -> Decimal:
    period_start = target_date - timedelta(days=60)
    period_end = target_date + timedelta(days=60)

    prices = get_stock_prices(ticker, period_start, period_end)

    if not prices:
        raise YahooFinanceError(f"No price data found for {ticker}")

    for price_date, price in prices:
        if price_date == target_date:
            return price

    nearest_date = min(prices, key=lambda x: abs(x[0] - target_date))
    return nearest_date[1]


def get_stock_prices(
    ticker: str,
    start_date: date,
    end_date: date,
    country: str = "United States",
) -> list[tuple[date, Decimal]]:
    history = get_instrument_prices(ticker, start_date, end_date)
    return [(point.date, point.close) for point in history.prices]


def get_history_source_url(ticker: str, start_date: date, end_date: date) -> str:
    """사용자에게 표시하는 종료일을 포함하는 종가 출처 링크."""
    period1 = int(datetime.combine(start_date, datetime.min.time(), UTC).timestamp())
    period2 = int(datetime.combine(end_date + timedelta(days=1), datetime.min.time(), UTC).timestamp())
    symbol = quote(ticker, safe="")
    return f"https://finance.yahoo.com/quote/{symbol}/history/?period1={period1}&period2={period2}"
