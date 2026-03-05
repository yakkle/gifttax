import re
from datetime import date, timedelta
from decimal import Decimal

from curl_cffi import requests as curl_requests

CURRENCY_MAP = {
    "USD": "USD",
    "EUR": "EUR",
    "JPY": "JPY",
    "GBP": "GBP",
    "CNY": "CNY",
    "CHF": "CHF",
    "CAD": "CAD",
    "AUD": "AUD",
}


class SMBSError(Exception):
    pass


def parse_xml_response(xml_text: str) -> list[tuple[date, Decimal]]:
    results: list[tuple[date, Decimal]] = []

    pattern = r"<set[^>]*label='(\d{2}\.\d{2}\.\d{2})'[^>]*value='([^']+)'[^>]*>"
    matches = re.findall(pattern, xml_text)

    for label, value in matches:
        try:
            day_str = label.replace(".", "")
            year = 2000 + int(day_str[:2])
            month = int(day_str[2:4])
            day = int(day_str[4:6])
            parsed_date = date(year, month, day)
            rate = Decimal(value.replace(",", ""))
            results.append((parsed_date, rate))
        except (ValueError, IndexError):
            continue

    return results


def get_exchange_rate(
    target_date: date,
    currency: str = "USD",
    max_search_days: int = 30,
) -> tuple[Decimal, date]:
    currency_code = CURRENCY_MAP.get(currency.upper())
    if not currency_code:
        raise ValueError(f"Unsupported currency: {currency}")

    search_date = target_date
    for _ in range(max_search_days):
        start_date = search_date
        end_date = search_date

        rates = get_exchange_rates(start_date, end_date, currency)

        if rates:
            return rates[0][1], rates[0][0]

        search_date = search_date - timedelta(days=1)

    raise SMBSError(f"No exchange rate data found for {currency} within {max_search_days} days")


def get_exchange_rates(
    start_date: date,
    end_date: date,
    currency: str = "USD",
) -> list[tuple[date, Decimal]]:
    currency_code = CURRENCY_MAP.get(currency.upper())
    if not currency_code:
        raise ValueError(f"Unsupported currency: {currency}")

    url = "http://www.smbs.biz/ExRate/StdExRate_xml.jsp"
    params = {
        "arr_value": f"{currency_code}_{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
    }

    session = curl_requests.Session(impersonate="chrome", verify=False)
    response = session.get(url, params=params, timeout=30)

    if response.status_code != 200:
        raise SMBSError(f"Failed to fetch exchange rates: {response.status_code}")

    return parse_xml_response(response.text)


def datetime_str_to_date(date_str: str) -> date:
    cleaned = date_str.replace(".", "-").strip()
    parts = cleaned.split("-")

    if len(parts) == 3:
        year, month, day = parts
        return date(int(year), int(month), int(day))

    raise ValueError(f"Invalid date format: {date_str}")
