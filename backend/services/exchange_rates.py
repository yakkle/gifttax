"""계산과 PDF가 공유할 환율 및 출처 근거를 준비한다."""

from datetime import date, timedelta
from decimal import Decimal
from urllib.parse import urlencode

from backend.integrations.scraper import smbs
from backend.schemas import ExchangeRateEvidence, PriceDataPoint, StockGiftResult


def get_exchange_rate_pdf_period(actual_rate_date: date) -> tuple[date, date]:
    """실제 고시일을 기준으로 증빙 조회 구간을 정한다."""
    return actual_rate_date - timedelta(days=1), actual_rate_date + timedelta(days=1)


def build_exchange_rate_evidence(
    currency: str, rate: Decimal, actual_rate_date: date, rates: list[PriceDataPoint]
) -> ExchangeRateEvidence:
    start, end = get_exchange_rate_pdf_period(actual_rate_date)
    params = {
        "StrSch_sYear": start.year,
        "StrSch_sMonth": f"{start.month:02d}",
        "StrSch_sDay": f"{start.day:02d}",
        "StrSch_eYear": end.year,
        "StrSch_eMonth": f"{end.month:02d}",
        "StrSch_eDay": f"{end.day:02d}",
        "tongwha_code": currency,
    }
    return ExchangeRateEvidence(
        currency=currency,
        rate=rate,
        actual_rate_date=actual_rate_date,
        period_start=start,
        period_end=end,
        source_unit=smbs.CURRENCY_UNITS.get(currency, 1),
        source_url=f"http://www.smbs.biz/ExRate/StdExRatePop.jsp?{urlencode(params)}",
        rates=sorted(rates, key=lambda item: item.date),
    )


def load_exchange_rate_evidence(gift_date: date, currency: str) -> ExchangeRateEvidence:
    currency = currency.upper()
    rate, actual_date = smbs.get_exchange_rate(gift_date, currency)
    start, end = get_exchange_rate_pdf_period(actual_date)
    rates = smbs.get_exchange_rates(start, end, currency)
    if (actual_date, rate) not in rates:
        raise smbs.SMBSError("계산에 적용한 환율을 증빙 조회 결과에서 확인할 수 없습니다.")
    data = [PriceDataPoint(date=day.isoformat(), close=str(value)) for day, value in rates]
    return build_exchange_rate_evidence(currency, rate, actual_date, data)


def collect_exchange_rate_evidence(stocks: list[StockGiftResult]) -> list[ExchangeRateEvidence]:
    groups: dict[tuple[str, date], ExchangeRateEvidence] = {}
    for stock in stocks:
        key = (stock.currency, stock.exchange_rate_date)
        if key not in groups:
            groups[key] = build_exchange_rate_evidence(
                stock.currency,
                stock.exchange_rate,
                stock.exchange_rate_date,
                stock.exchange_rate_data,
            )
    return list(groups.values())
