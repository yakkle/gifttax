from datetime import date, timedelta
from decimal import Decimal

import requests
from bs4 import BeautifulSoup


class InvestingError(Exception):
    pass


def get_stock_price(
    ticker: str,
    target_date: date,
    country: str = "United States",
) -> Decimal:
    period_start = target_date - timedelta(days=60)
    period_end = target_date + timedelta(days=60)

    prices = get_stock_prices(ticker, period_start, period_end, country)

    if not prices:
        raise InvestingError(f"No price data found for {ticker}")

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
    url = f"https://www.investing.com/equities/{ticker.lower()}-historical-data"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7/537.36) AppleWebKit (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    params = {
        "from_date": start_date.strftime("%m/%d/%Y"),
        "to_date": end_date.strftime("%m/%d/%Y"),
    }

    response = requests.get(url, headers=headers, params=params, timeout=30)

    if response.status_code != 200:
        raise InvestingError(f"Failed to fetch data for {ticker}: {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.find("table", {"id": "historical-prices"})
    if not table:
        raise InvestingError(f"Price table not found for {ticker}")

    rows = table.find("tbody").find_all("tr") if table.find("tbody") else []

    results: list[tuple[date, Decimal]] = []

    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            date_text = cells[0].get_text(strip=True)
            close_text = cells[4].get_text(strip=True)

            try:
                parsed_date = parse_investing_date(date_text)
                price = Decimal(close_text.replace(",", ""))
                results.append((parsed_date, price))
            except Exception:
                continue

    results.sort(key=lambda x: x[0])

    return results


def parse_investing_date(date_str: str) -> date:
    months = {
        "Jan": 1,
        "Feb": 2,
        "Mar": 3,
        "Apr": 4,
        "May": 5,
        "Jun": 6,
        "Jul": 7,
        "Aug": 8,
        "Sep": 9,
        "Oct": 10,
        "Nov": 11,
        "Dec": 12,
    }

    parts = date_str.replace(",", "").split()
    if len(parts) == 3:
        month = months.get(parts[0])
        day = int(parts[1])
        year = int(parts[2])
        if month:
            return date(year, month, day)

    raise ValueError(f"Invalid date format: {date_str}")
