from datetime import date, timedelta
from decimal import Decimal

from curl_cffi import requests


class YahooFinanceError(Exception):
    pass


class InvalidTickerError(Exception):
    pass


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
    symbol = ticker.upper()

    period1 = int(start_date.strftime("%s"))
    period2 = int(end_date.strftime("%s"))

    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

    session = requests.Session(impersonate="chrome")
    response = session.get(
        url,
        params={
            "period1": period1,
            "period2": period2,
            "interval": "1d",
        },
    )

    if response.status_code == 404:
        raise InvalidTickerError(f"종목 코드를 찾을 수 없습니다: {ticker}")

    if response.status_code != 200:
        raise YahooFinanceError(f"Failed to fetch data for {ticker}: {response.status_code}")

    data = response.json()

    if "chart" not in data:
        raise InvalidTickerError(f"종목 코드를 찾을 수 없습니다: {ticker}")

    if not data["chart"].get("result"):
        raise InvalidTickerError(f"종목 코드를 찾을 수 없습니다: {ticker}")

    result = data["chart"]["result"][0]

    if "timestamp" not in result:
        raise InvalidTickerError(f"종목 코드를 찾을 수 없습니다: {ticker}")

    timestamps = result["timestamp"]
    quotes = result["indicators"]["quote"][0]

    results: list[tuple[date, Decimal]] = []

    for i, ts in enumerate(timestamps):
        close = quotes["close"][i]
        if close is not None:
            price_date = date.fromtimestamp(ts)
            close_price = Decimal(str(close))
            results.append((price_date, close_price))

    results.sort(key=lambda x: x[0])

    return results
