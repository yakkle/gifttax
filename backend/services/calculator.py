from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from backend.integrations.scraper import yahoo as scraper
from backend.integrations.scraper.smbs import SMBSError
from backend.schemas import (
    ExchangeRateEvidence,
    GiftCalculationInput,
    GiftCalculationResult,
    PriceDataPoint,
    RequestedAssetType,
    StockGiftResult,
)
from backend.schemas.instruments import InstrumentResolution
from backend.services import instruments
from backend.services.exchange_rates import (
    collect_exchange_rate_evidence,
    load_exchange_rate_evidence,
)
from backend.services.exchange_rates import (
    get_exchange_rate_pdf_period as get_exchange_rate_pdf_period,
)
from backend.services.price_valuation import get_price_valuation
from backend.tax import engine as tax_engine


class CalculationUnavailableError(Exception):
    def __init__(self, gift_date: date, available_from: date, ticker: str | None = None):
        self.gift_date = gift_date
        self.available_from = available_from
        self.ticker = ticker
        prefix = f"{ticker}: " if ticker else ""
        super().__init__(
            prefix + "증여일 기준 후 2개월 기간이 아직 지나지 않아 현재는 계산할 수 없습니다. "
            f"{available_from.isoformat()}부터 다시 시도해 주세요."
        )


def get_stock_price_display_period(gift_date: date) -> tuple[date, date]:
    return (
        gift_date - relativedelta(months=2) + timedelta(days=1),
        gift_date + relativedelta(months=2) - timedelta(days=1),
    )


def get_stock_price_fetch_period(gift_date: date) -> tuple[date, date]:
    start, end = get_stock_price_display_period(gift_date)
    return start, end + timedelta(days=1)


def get_calculation_available_from(gift_date: date) -> date:
    _, end = get_stock_price_display_period(gift_date)
    return end + timedelta(days=1)


def get_current_date() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def validate_calculation_availability(
    gift_date: date, today: date | None = None, ticker: str | None = None
) -> None:
    available_from = get_calculation_available_from(gift_date)
    if (today or get_current_date()) < available_from:
        raise CalculationUnavailableError(gift_date, available_from, ticker)


def _prepare_instrument(
    gift_date: date, ticker: str, currency: str, asset_type: RequestedAssetType
) -> InstrumentResolution:
    if gift_date > get_current_date():
        raise instruments.InstrumentError(
            "FUTURE_GIFT_DATE", "미래 증여일은 계산할 수 없습니다.", ticker, status_code=422
        )
    resolution = instruments.resolve_instrument(ticker, asset_type)
    instruments.validate_instrument_currency(resolution.metadata, currency)
    if resolution.asset_type == "stock":
        validate_calculation_availability(gift_date, ticker=resolution.metadata.ticker)
    return resolution


def calculate_gift_amount(
    gift_date: date,
    ticker: str,
    qty: int,
    currency: str = "USD",
    *,
    asset_type: RequestedAssetType = "auto",
    rate_cache: dict[str, ExchangeRateEvidence] | None = None,
    resolved_instrument: InstrumentResolution | None = None,
) -> StockGiftResult:
    currency = currency.upper()
    resolution = resolved_instrument or _prepare_instrument(gift_date, ticker, currency, asset_type)
    ticker = resolution.metadata.ticker
    if resolution.asset_type == "stock":
        period_start, period_end = get_stock_price_display_period(gift_date)
    else:
        period_start, period_end = gift_date - timedelta(days=30), gift_date - timedelta(days=1)
    valuation = get_price_valuation(resolution, currency, period_start, period_end, gift_date)

    # 당일 고시 환율 우선, 데이터가 없을 때만 이전 고시일로 검색한다.
    evidence = rate_cache.get(currency) if rate_cache is not None else None
    if evidence is None:
        try:
            evidence = load_exchange_rate_evidence(gift_date, currency)
        except (SMBSError, ValueError) as error:
            raise instruments.InstrumentError(
                "EXCHANGE_RATE_LOOKUP_FAILED", f"{ticker}: 환율 증빙을 조회하지 못했습니다.",
                ticker, status_code=503,
            ) from error
        if rate_cache is not None:
            rate_cache[currency] = evidence

    # 주식은 평균가 소수 둘째 자리 반올림, ETF는 종가 정밀도를 유지한다.
    # 최종 원화 금액에는 기존 원 단위 반올림을 적용한다.
    gift_amount = Decimal(round(valuation.price * Decimal(qty) * evidence.rate))
    return StockGiftResult(
        ticker=ticker,
        qty=qty,
        currency=currency,
        asset_type=resolution.asset_type,
        detection_method=resolution.detection_method,
        valuation_method="previous_close" if resolution.asset_type == "etf" else "average_close",
        valuation_price=valuation.price,
        price_average=valuation.price,
        price_date=valuation.price_date,
        price_date_note=valuation.note,
        price_source_url=scraper.get_history_source_url(ticker, valuation.start, valuation.end),
        quote_currency=valuation.metadata.quote_currency,
        price_multiplier=valuation.metadata.price_multiplier,
        price_data=[PriceDataPoint(date=p.date.isoformat(), close=str(p.close)) for p in valuation.prices],
        period_start=valuation.start,
        period_end=valuation.end,
        exchange_rate=evidence.rate,
        exchange_rate_date=evidence.actual_rate_date,
        exchange_rate_data=evidence.rates,
        gift_amount_krw=gift_amount,
    )


def calculate_total_gift(input_data: GiftCalculationInput) -> GiftCalculationResult:
    # 혼합 요청도 모든 종목의 계산 가능일을 먼저 검사한다.
    resolutions = [
        _prepare_instrument(input_data.gift_date, stock.ticker, stock.currency, stock.asset_type)
        for stock in input_data.stocks
    ]
    rates_by_currency: dict[str, ExchangeRateEvidence] = {}
    results = [
        calculate_gift_amount(
            input_data.gift_date, stock.ticker, stock.qty, stock.currency,
            rate_cache=rates_by_currency, resolved_instrument=resolution,
        )
        for stock, resolution in zip(input_data.stocks, resolutions, strict=True)
    ]
    total_amount = sum((result.gift_amount_krw for result in results), Decimal(0))
    return GiftCalculationResult(
        gift_date=input_data.gift_date,
        stocks=results,
        total_gift_amount_krw=total_amount,
        estimated_tax=tax_engine.calculate_gift_tax(total_amount),
        exchange_rate_date=results[0].exchange_rate_date,
        exchange_rate_evidence=collect_exchange_rate_evidence(results),
    )
