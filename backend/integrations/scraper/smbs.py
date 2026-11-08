import re
from datetime import date, timedelta
from decimal import Decimal
from xml.etree import ElementTree

from curl_cffi import requests as curl_requests
from curl_cffi.requests.exceptions import RequestException

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

# StdExRate_xml.jsp의 JPY 원본 값은 100엔당 원화 금액이다.
CURRENCY_UNITS = {"JPY": 100}


class SMBSError(Exception):
    pass


def parse_xml_response(xml_text: str) -> list[tuple[date, Decimal]]:
    results: list[tuple[date, Decimal]] = []

    try:
        root = ElementTree.fromstring(xml_text.strip())
        if root.tag != "chart":
            raise ValueError("Expected chart response")
        for element in root.findall("set"):
            label = element.attrib["label"]
            if not re.fullmatch(r"\d{2}\.\d{2}\.\d{2}", label):
                raise ValueError("Invalid rate date")
            year, month, day = map(int, label.split("."))
            rate = Decimal(element.attrib["value"].replace(",", ""))
            if not rate.is_finite() or rate <= 0:
                raise ValueError("Invalid exchange rate")
            results.append((date(2000 + year, month, day), rate))
    except (ElementTree.ParseError, ValueError, KeyError, ArithmeticError) as error:
        raise SMBSError("환율 응답을 해석할 수 없습니다.") from error
    return sorted(results)


def get_exchange_rate(
    target_date: date,
    currency: str = "USD",
    max_search_days: int = 30,
) -> tuple[Decimal, date]:
    currency_code = CURRENCY_MAP.get(currency.upper())
    if not currency_code:
        raise ValueError(f"Unsupported currency: {currency}")

    for offset in range(max_search_days):
        search_date = target_date - timedelta(days=offset)
        start_date = search_date
        end_date = search_date

        rates = get_exchange_rates(start_date, end_date, currency)

        if rates:
            return rates[0][1], rates[0][0]

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

    try:
        with curl_requests.Session(impersonate="chrome") as session:
            response = session.get(url, params=params, timeout=30)
    except RequestException as error:
        raise SMBSError("환율 데이터를 조회하지 못했습니다.") from error

    if response.status_code != 200:
        raise SMBSError(f"Failed to fetch exchange rates: {response.status_code}")

    rates = parse_xml_response(response.text)
    if any(not start_date <= rate_date <= end_date for rate_date, _ in rates):
        raise SMBSError("조회 기간과 환율 응답 날짜가 일치하지 않습니다.")
    unit = Decimal(CURRENCY_UNITS.get(currency_code, 1))
    return [(rate_date, rate / unit) for rate_date, rate in rates]


def datetime_str_to_date(date_str: str) -> date:
    cleaned = date_str.replace(".", "-").strip()
    parts = cleaned.split("-")

    if len(parts) == 3:
        year, month, day = parts
        return date(int(year), int(month), int(day))

    raise ValueError(f"Invalid date format: {date_str}")
