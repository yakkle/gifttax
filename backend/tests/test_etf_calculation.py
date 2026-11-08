"""ETF 평가 경계, 자동 판별, 혼합 요청 및 실제 두 PDF 다운로드 계약."""

import io
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api import backend
from backend.integrations.scraper import smbs, yahoo
from backend.main import app
from backend.pdf.generator import exchange_rate_pdf, gift_calculation_pdf
from backend.schemas import GiftCalculationInput, StockInput, StockPrice
from backend.schemas.instruments import InstrumentMetadata, InstrumentPriceHistory
from backend.services import calculator
from backend.services.instruments import InstrumentError

GIFT_DATE = date(2025, 11, 10)
PRICE_DATE = date(2025, 11, 7)


@pytest.fixture
def market(monkeypatch):
    def metadata(ticker, kind="ETF", currency="USD"):
        return InstrumentMetadata(
            ticker=ticker, instrument_type=kind, currency=currency,
            quote_currency=currency, exchange_timezone="America/New_York",
        )

    state = SimpleNamespace(
        metadata={"QQQ": metadata("QQQ"), "AAPL": metadata("AAPL", "EQUITY")},
        prices={"QQQ": [(PRICE_DATE, Decimal(200))],
                "AAPL": [(date(2025, 7, 9), Decimal("100.005")),
                         (date(2025, 7, 10), Decimal("200.005"))]},
        history_metadata={},
    )

    def history(ticker, start, end):
        # 일부러 범위 밖 데이터도 넘겨 서비스의 평가 경계를 검증한다.
        return InstrumentPriceHistory(
            metadata=state.history_metadata.get(ticker, state.metadata[ticker]),
            prices=[StockPrice(date=day, close=value) for day, value in state.prices[ticker]],
        )

    state.lookup = Mock(side_effect=lambda ticker: state.metadata[ticker])
    state.history = Mock(side_effect=history)
    monkeypatch.setattr(yahoo, "get_instrument_metadata", state.lookup)
    monkeypatch.setattr(yahoo, "get_instrument_prices", state.history)
    monkeypatch.setattr(calculator, "get_current_date", lambda: GIFT_DATE)
    state.rate = Mock(side_effect=lambda day, currency: (Decimal(1300), day))
    monkeypatch.setattr(smbs, "get_exchange_rate", state.rate)
    monkeypatch.setattr(smbs, "get_exchange_rates", lambda start, end, currency: [(start + timedelta(days=1), Decimal(1300))])
    return state


def calculate(ticker="QQQ", gift_date=GIFT_DATE, **kwargs):
    return calculator.calculate_gift_amount(gift_date, ticker, 10, **kwargs)


def payload(stocks=None, gift_date=GIFT_DATE):
    return {"gift_date": gift_date.isoformat(), "stocks": stocks or [{"ticker": "QQQ", "qty": 10}]}


def test_etf_uses_recent_close_without_two_month_wait(market):
    result = calculate(ticker=" qqq ")
    assert result.ticker == "QQQ"
    assert result.asset_type == "etf"
    assert result.detection_method == "auto"
    assert result.valuation_method == "previous_close"
    assert result.valuation_price == result.price_average == Decimal(200)
    assert result.price_date == result.period_start == result.period_end == PRICE_DATE
    assert result.gift_amount_krw == Decimal(2600000)
    assert result.price_data[0].date == PRICE_DATE.isoformat()
    assert "이전 최근 거래일" in result.price_date_note
    assert result.price_source_url == yahoo.get_history_source_url("QQQ", PRICE_DATE, PRICE_DATE)
    market.history.assert_called_once_with("QQQ", GIFT_DATE - timedelta(days=30), GIFT_DATE)


@pytest.mark.parametrize(
    "gift_day,close_day,substituted",
    [(date(2025, 11, 7), date(2025, 11, 6), False),
     (date(2025, 11, 8), PRICE_DATE, False),
     (date(2025, 11, 9), PRICE_DATE, True),
     (GIFT_DATE, PRICE_DATE, True)],
)
def test_gift_and_previous_day_holidays(market, gift_day, close_day, substituted):
    market.prices["QQQ"] = [(close_day, Decimal(200))]
    result = calculate(gift_date=gift_day)
    assert result.price_date == close_day
    assert bool(result.price_date_note) == substituted
    assert result.exchange_rate_date == gift_day


@pytest.mark.parametrize("offset,accepted", [(1, True), (30, True), (31, False), (0, False), (-1, False)])
def test_etf_search_includes_exactly_previous_30_calendar_days(market, offset, accepted):
    chosen = GIFT_DATE - timedelta(days=offset)
    market.prices["QQQ"] = [(chosen, Decimal(200))]
    if accepted:
        assert calculate().price_date == chosen
    else:
        with pytest.raises(InstrumentError, match="QQQ") as caught:
            calculate()
        assert caught.value.code == "PRICE_DATA_UNAVAILABLE"
        market.rate.assert_not_called()


def test_etf_ignores_today_future_and_older_prices_and_sorts(market):
    market.prices["QQQ"] = [
        (GIFT_DATE, Decimal(999)), (PRICE_DATE, Decimal("200.12345")),
        (GIFT_DATE + timedelta(days=1), Decimal(9999)),
        (GIFT_DATE - timedelta(days=31), Decimal(1)),
        (PRICE_DATE - timedelta(days=1), Decimal(100)),
    ]
    result = calculate()
    assert result.valuation_price == result.price_average == Decimal("200.12345")
    assert result.gift_amount_krw == Decimal(2601605)
    assert len(result.price_data) == 1


def test_stock_preserves_average_rounding_period_and_old_request(market):
    result = calculator.calculate_total_gift(GiftCalculationInput(**payload(
        [{"ticker": "AAPL", "qty": 10}], gift_date=date(2025, 7, 10)
    ))).stocks[0]
    assert result.asset_type == "stock"
    assert result.valuation_method == "average_close"
    assert result.price_average == result.valuation_price == Decimal("150.00")
    assert result.price_date is None
    assert result.period_start == date(2025, 5, 11)
    assert result.period_end == date(2025, 9, 9)
    assert result.gift_amount_krw == Decimal(1950000)


@pytest.mark.parametrize("selected", ["auto", "stock", "etf"])
def test_future_gift_rejected_before_any_lookup(market, selected):
    with pytest.raises(InstrumentError) as caught:
        calculate(gift_date=GIFT_DATE + timedelta(days=1), asset_type=selected)
    assert caught.value.code == "FUTURE_GIFT_DATE"
    market.lookup.assert_not_called()
    market.history.assert_not_called()
    market.rate.assert_not_called()


@pytest.mark.parametrize("ticker,selected", [("QQQ", "stock"), ("AAPL", "etf")])
def test_explicit_type_cannot_override_detected_type(market, ticker, selected):
    with pytest.raises(InstrumentError) as caught:
        calculate(ticker=ticker, asset_type=selected)
    assert caught.value.code == "ASSET_TYPE_MISMATCH"
    market.history.assert_not_called()


@pytest.mark.parametrize("kind", [None, "UNKNOWN"])
@pytest.mark.parametrize("selected", ["stock", "etf"])
def test_manual_choice_allowed_when_type_unknown(market, kind, selected):
    market.metadata["QQQ"].instrument_type = kind
    if selected == "stock":
        market.prices["QQQ"] = [(date(2025, 9, 1), Decimal(200))]
    result = calculate(gift_date=date(2025, 9, 1), asset_type=selected) if selected == "stock" else calculate(asset_type=selected)
    assert result.detection_method == "manual"
    assert result.asset_type == selected


def test_missing_type_requires_selection(market):
    market.metadata["QQQ"].instrument_type = None
    with pytest.raises(InstrumentError) as caught:
        calculate()
    assert caught.value.code == "ASSET_TYPE_REQUIRED"
    market.history.assert_not_called()


def test_metadata_network_failure_allows_explicit_choice(market):
    market.lookup.side_effect = yahoo.YahooFinanceError("timeout")
    assert calculate(asset_type="etf").detection_method == "manual"


@pytest.mark.parametrize("selected", ["auto", "stock", "etf"])
@pytest.mark.parametrize("kind", ["INDEX", "MUTUALFUND", "ETN", "CRYPTOCURRENCY"])
def test_unsupported_type_cannot_be_bypassed(market, selected, kind):
    market.metadata["QQQ"].instrument_type = kind
    with pytest.raises(InstrumentError) as caught:
        calculate(asset_type=selected)
    assert caught.value.code == "UNSUPPORTED_INSTRUMENT"
    market.history.assert_not_called()


@pytest.mark.parametrize("history_kind,code", [("INDEX", "UNSUPPORTED_INSTRUMENT"), ("EQUITY", "ASSET_TYPE_MISMATCH")])
def test_manual_fallback_rechecks_type_in_price_response(market, history_kind, code):
    market.history_metadata["QQQ"] = market.metadata["QQQ"].model_copy(update={"instrument_type": history_kind})
    market.lookup.side_effect = yahoo.YahooFinanceError("timeout")
    with pytest.raises(InstrumentError) as caught:
        calculate(asset_type="etf")
    assert caught.value.code == code
    market.rate.assert_not_called()


@pytest.mark.parametrize("at_history", [False, True])
def test_currency_mismatch_rejected_before_fx(market, at_history):
    if at_history:
        market.history_metadata["QQQ"] = market.metadata["QQQ"].model_copy(update={"currency": "EUR"})
    else:
        market.metadata["QQQ"].currency = "EUR"
    with pytest.raises(InstrumentError) as caught:
        calculate()
    assert caught.value.code == "CURRENCY_MISMATCH"
    market.rate.assert_not_called()


@pytest.mark.parametrize("stocks", [[{"ticker": "QQQ", "qty": 10}, {"ticker": "AAPL", "qty": 10}],
                                    [{"ticker": "AAPL", "qty": 10}, {"ticker": "QQQ", "qty": 10}]])
def test_mixed_recent_request_is_atomic_and_identifies_stock(market, stocks, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    response = TestClient(app).post("/api/calculate", json=payload(stocks))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "INSUFFICIENT_POST_GIFT_WINDOW"
    assert detail["ticker"] == "AAPL"
    assert detail["available_from"] == "2026-01-10"
    market.history.assert_not_called()
    market.rate.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_mixed_mature_request_uses_each_valuation_and_shared_fx(market):
    market.prices["QQQ"] = [(date(2025, 7, 9), Decimal(200))]
    result = calculator.calculate_total_gift(GiftCalculationInput(**payload(
        [{"ticker": "QQQ", "qty": 10}, {"ticker": "AAPL", "qty": 10}], date(2025, 7, 10)
    )))
    assert [s.valuation_method for s in result.stocks] == ["previous_close", "average_close"]
    assert result.total_gift_amount_krw == Decimal(4550000)
    assert len(result.exchange_rate_evidence) == 1
    market.rate.assert_called_once()


@pytest.mark.parametrize("error,status,code", [
    (yahoo.InvalidTickerError("NOTFOUND"), 400, "INVALID_TICKER"),
    (yahoo.YahooFinanceError("timeout"), 503, "PRICE_LOOKUP_FAILED"),
])
def test_price_failures_include_ticker(market, error, status, code):
    market.history.side_effect = error
    response = TestClient(app).post("/api/calculate", json=payload())
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["ticker"] == "QQQ"


def test_fx_failure_includes_ticker_and_does_not_create_files(market, tmp_path, monkeypatch):
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    market.rate.side_effect = smbs.SMBSError("timeout")
    response = TestClient(app).post("/api/calculate", json=payload())
    assert response.status_code == 503
    assert response.json()["detail"]["ticker"] == "QQQ"
    assert list(tmp_path.iterdir()) == []


def test_all_instruments_must_succeed_before_pdf_generation(market, monkeypatch):
    market.metadata["OTHER"] = market.metadata["QQQ"].model_copy(update={"ticker": "OTHER"})
    market.prices["OTHER"] = []
    gift = Mock()
    rate = Mock()
    monkeypatch.setattr(gift_calculation_pdf, "generate_pdf_gift_calculation", gift)
    monkeypatch.setattr(exchange_rate_pdf, "generate_pdf_exchange_rate_report", rate)
    response = TestClient(app).post("/api/calculate", json=payload(
        [{"ticker": "QQQ", "qty": 10}, {"ticker": "OTHER", "qty": 10}]
    ))
    assert response.status_code == 422
    assert response.json()["detail"]["ticker"] == "OTHER"
    gift.assert_not_called()
    rate.assert_not_called()


def test_second_pdf_failure_does_not_leave_first_file(market, monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(exchange_rate_pdf, "generate_pdf_exchange_rate_report", Mock(side_effect=RuntimeError("render failed")))
    assert TestClient(app).post("/api/calculate", json=payload()).status_code == 500
    assert list(tmp_path.iterdir()) == []


def test_recent_etf_request_downloads_both_pdfs(market, monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    client = TestClient(app)
    response = client.post("/api/calculate", json=payload())
    assert response.status_code == 200
    data = response.json()
    assert data["stocks"][0]["price_date"] == "2025-11-07"
    assert Decimal(data["total_gift_amount_krw"]) == Decimal(2600000)
    assert {p.stem for p in tmp_path.iterdir()} == {data["gift_pdf_file_id"], data["rate_pdf_file_id"]}
    for key in ["gift_pdf_file_id", "rate_pdf_file_id"]:
        downloaded = client.get(f'/api/download/{data[key]}')
        assert downloaded.status_code == 200
        assert downloaded.content.startswith(b"%PDF-")
    assert list(tmp_path.iterdir()) == []


def test_etf_pdf_shows_precise_price_date_reason_and_source(market, recorded_pdf):
    market.prices["QQQ"] = [(PRICE_DATE, Decimal("200.12345"))]
    result = calculator.calculate_total_gift(GiftCalculationInput(**payload()))
    output = io.BytesIO()
    gift_calculation_pdf.generate_pdf_gift_calculation(result, output)
    text = "\n".join(recorded_pdf[0].texts)
    assert output.getvalue().startswith(b"%PDF-")
    assert "ETF 종가 평가 근거" in text
    assert "2025-11-07" in text
    assert "200.12345 USD" in text
    assert "2,601,605 원" in text
    assert "이전 최근 거래일" in text
    assert "평균 종가" not in text
    assert result.stocks[0].price_source_url in recorded_pdf[0].links


def test_pence_etf_pdf_retains_normalized_price_and_conversion(market, recorded_pdf):
    market.metadata["QQQ"] = market.metadata["QQQ"].model_copy(update={
        "currency": "GBP", "quote_currency": "GBp", "price_multiplier": Decimal("0.01")
    })
    # 어댑터는 이미 GBp -> GBP를 환산한 가격을 반환한다. 서비스에서 재환산하지 않는다.
    market.prices["QQQ"] = [(PRICE_DATE, Decimal("10.1723"))]
    result = calculator.calculate_total_gift(GiftCalculationInput(**payload(
        [{"ticker": "QQQ", "qty": 10, "currency": "GBP"}]
    )))
    gift_calculation_pdf.generate_pdf_gift_calculation(result, io.BytesIO())
    text = "\n".join(recorded_pdf[0].texts)
    assert "10.1723 GBP" in text
    assert "GBp 종가 × 0.01 = GBP 종가" in text
    assert result.total_gift_amount_krw == Decimal(132240)


@pytest.mark.parametrize("bad", ["fund", "ETF", "", None])
def test_invalid_asset_type_rejected(bad):
    with pytest.raises(ValidationError):
        StockInput(ticker="QQQ", qty=10, asset_type=bad)


def test_real_yahoo_adapter_passes_close_and_pence_unit_to_calculation(monkeypatch):
    """통합 경로에서도 adjclose를 배제하고 GBp를 한 번만 환산한다."""
    from datetime import UTC, datetime

    response = Mock(status_code=200)
    response.json.return_value = {"chart": {"error": None, "result": [{
        "meta": {"instrumentType": "ETF", "currency": "GBp", "exchangeTimezoneName": "Europe/London"},
        "timestamp": [int(datetime(2025, 11, 7, 16, 30, tzinfo=UTC).timestamp())],
        "indicators": {"quote": [{"close": [1017.23]}], "adjclose": [{"adjclose": [999]}]},
    }]}}
    session = Mock()
    session.__enter__ = Mock(return_value=session)
    session.__exit__ = Mock(return_value=False)
    session.get.return_value = response
    monkeypatch.setattr(yahoo.requests, "Session", Mock(return_value=session))
    monkeypatch.setattr(calculator, "get_current_date", lambda: GIFT_DATE)
    monkeypatch.setattr(smbs, "get_exchange_rate", lambda *args: (Decimal(1300), GIFT_DATE))
    monkeypatch.setattr(smbs, "get_exchange_rates", lambda *args: [(GIFT_DATE, Decimal(1300))])
    result = calculate("ISF.L", currency="GBP")
    assert result.valuation_price == Decimal("10.1723")
    assert result.quote_currency == "GBp"
    assert result.price_date == PRICE_DATE
    assert result.gift_amount_krw == Decimal(132240)
    assert session.get.call_count == 2


def test_second_file_save_failure_cleans_up_first(market, monkeypatch, tmp_path):
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    original = backend._save_pdf

    def save(output, kind):
        if kind == "rate":
            raise OSError("storage unavailable")
        return original(output, kind)

    monkeypatch.setattr(backend, "_save_pdf", save)
    response = TestClient(app).post("/api/calculate", json=payload())
    assert response.status_code == 500
    assert list(tmp_path.iterdir()) == []
