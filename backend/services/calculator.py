from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from backend.integrations.scraper import yahoo as scraper
from backend.schemas import (
    ExchangeRateEvidence,
    GiftCalculationInput,
    GiftCalculationResult,
    PriceDataPoint,
    StockGiftResult,
)
from backend.services.exchange_rates import (
    collect_exchange_rate_evidence,
    load_exchange_rate_evidence,
)
from backend.services.exchange_rates import (
    get_exchange_rate_pdf_period as get_exchange_rate_pdf_period,
)
from backend.tax import engine as tax_engine


class CalculationUnavailableError(Exception):
    def __init__(self, gift_date: date, available_from: date):
        self.gift_date = gift_date
        self.available_from = available_from
        super().__init__(
            "증여일 기준 후 2개월 기간이 아직 지나지 않아 현재는 계산할 수 없습니다. "
            f"{available_from.isoformat()}부터 다시 시도해 주세요."
        )


def get_stock_price_display_period(gift_date: date) -> tuple[date, date]:
    period_start = gift_date - relativedelta(months=2) + timedelta(days=1)
    period_end = gift_date + relativedelta(months=2) - timedelta(days=1)
    return period_start, period_end


def get_stock_price_fetch_period(gift_date: date) -> tuple[date, date]:
    period_start, display_period_end = get_stock_price_display_period(gift_date)
    return period_start, display_period_end + timedelta(days=1)


def get_calculation_available_from(gift_date: date) -> date:
    _, display_period_end = get_stock_price_display_period(gift_date)
    return display_period_end + timedelta(days=1)


def validate_calculation_availability(gift_date: date, today: date | None = None) -> None:
    current_date = today or date.today()
    available_from = get_calculation_available_from(gift_date)

    if current_date < available_from:
        raise CalculationUnavailableError(gift_date, available_from)


def calculate_gift_amount(
    gift_date: date,
    ticker: str,
    qty: int,
    currency: str = "USD",
    *,
    rate_cache: dict[str, ExchangeRateEvidence] | None = None,
) -> StockGiftResult:
    validate_calculation_availability(gift_date)

    # 표시용 기간: 증여일 기준 전후 2개월
    # 조회용 종료일은 Yahoo Finance가 end date를 포함하지 않으므로 +1일 추가
    period_start, period_end = get_stock_price_display_period(gift_date)
    _, fetch_period_end = get_stock_price_fetch_period(gift_date)

    prices = scraper.get_stock_prices(ticker, period_start, fetch_period_end)

    if not prices:
        raise ValueError(f"No price data found for {ticker}")

    price_sum = Decimal(0)
    price_count = 0

    for price_date, price in prices:
        price_sum += price
        price_count += 1

    # 평균종가는 소수점 2자리로 반올림
    average_price = Decimal(round(price_sum / price_count, 2)) if price_count > 0 else Decimal(0)

    price_data = [PriceDataPoint(date=str(pd[0]), close=str(pd[1])) for pd in prices]

    # 당일 고시 환율 우선, 데이터가 없을 때만 이전 고시일로 검색한다.
    currency = currency.upper()
    evidence = rate_cache.get(currency) if rate_cache is not None else None
    if evidence is None:
        evidence = load_exchange_rate_evidence(gift_date, currency)
        if rate_cache is not None:
            rate_cache[currency] = evidence
    rate_value, actual_rate_date = evidence.rate, evidence.actual_rate_date

    # 증여금액 = 반올림된 평균종가 × 수량 × 환율 (원 단위 반올림)
    gift_amount = Decimal(round(average_price * Decimal(qty) * rate_value))

    return StockGiftResult(
        ticker=ticker,
        qty=qty,
        currency=currency,
        price_average=average_price,
        price_data=price_data,
        period_start=period_start,
        period_end=period_end,
        exchange_rate=rate_value,
        exchange_rate_date=actual_rate_date,
        exchange_rate_data=evidence.rates,
        gift_amount_krw=gift_amount,
    )


def calculate_total_gift(
    input_data: GiftCalculationInput,
) -> GiftCalculationResult:
    results: list[StockGiftResult] = []
    total_amount = Decimal(0)
    actual_exchange_rate_date = None
    validate_calculation_availability(input_data.gift_date)
    rates_by_currency: dict[str, ExchangeRateEvidence] = {}

    for stock in input_data.stocks:
        currency = stock.currency.upper()
        result = calculate_gift_amount(
            gift_date=input_data.gift_date,
            ticker=stock.ticker,
            qty=stock.qty,
            currency=currency,
            rate_cache=rates_by_currency,
        )
        results.append(result)
        total_amount += result.gift_amount_krw
        if actual_exchange_rate_date is None:
            actual_exchange_rate_date = result.exchange_rate_date

    estimated_tax = tax_engine.calculate_gift_tax(total_amount)

    return GiftCalculationResult(
        gift_date=input_data.gift_date,
        stocks=results,
        total_gift_amount_krw=total_amount,
        estimated_tax=estimated_tax,
        exchange_rate_date=actual_exchange_rate_date or input_data.gift_date,
        exchange_rate_evidence=collect_exchange_rate_evidence(results),
    )
