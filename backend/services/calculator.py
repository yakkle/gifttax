from datetime import date, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta

from backend.integrations.scraper import smbs
from backend.integrations.scraper import yahoo as scraper
from backend.models import (
    GiftCalculationInput,
    GiftCalculationResult,
    PriceDataPoint,
    StockGiftResult,
)
from backend.tax import engine as tax_engine


def calculate_gift_amount(
    gift_date: date,
    ticker: str,
    qty: int,
    currency: str = "USD",
) -> StockGiftResult:
    # 증여일 기준 전후 2개월
    # 전: gift_date - 2개월 + 1일
    # 후: gift_date + 2개월 - 1일
    # Yahoo Finance가 end date를 포함하지 않으므로 +1일 추가
    period_start = gift_date - relativedelta(months=2) + timedelta(days=1)
    period_end = gift_date + relativedelta(months=2) - timedelta(days=1) + timedelta(days=1)

    prices = scraper.get_stock_prices(ticker, period_start, period_end)

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

    # 환율: 직전영업일 기준 (주말/공휴일 고려하여 최대 30일 전까지 검색)
    rate_value, actual_rate_date = smbs.get_exchange_rate(gift_date, currency)

    # 환율 데이터 표시: 실제 환율 적용일 기준 전후 1일
    exchange_rate_start = actual_rate_date - timedelta(days=1)
    exchange_rate_end = actual_rate_date + timedelta(days=1)
    exchange_rate_data_raw = smbs.get_exchange_rates(
        exchange_rate_start, exchange_rate_end, currency
    )

    exchange_rate_data = [
        PriceDataPoint(date=str(rd[0]), close=str(rd[1])) for rd in exchange_rate_data_raw
    ]

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
        exchange_rate_data=exchange_rate_data,
        gift_amount_krw=gift_amount,
    )


def get_exchange_rate_pdf_period(actual_rate_date: date) -> tuple[date, date]:
    """환율 PDF 조회 기간 반환.

    실제 환율 적용일(actual_rate_date) 기준 전후 1일.
    actual_rate_date는 증여일 직전영업일로, 주말/공휴일을 건너뛴 실제 환율 데이터가 존재하는 날짜다.
    """
    return actual_rate_date - timedelta(days=1), actual_rate_date + timedelta(days=1)


def calculate_total_gift(
    input_data: GiftCalculationInput,
) -> GiftCalculationResult:
    results: list[StockGiftResult] = []
    total_amount = Decimal(0)
    actual_exchange_rate_date = None

    for stock in input_data.stocks:
        result = calculate_gift_amount(
            gift_date=input_data.gift_date,
            ticker=stock.ticker,
            qty=stock.qty,
            currency=stock.currency,
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
    )
