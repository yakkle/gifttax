"""종목 판별 API와 시세 메타정보·단위·날짜 계약을 외부 호출 없이 검증한다."""

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from curl_cffi.requests.exceptions import RequestException
from fastapi.testclient import TestClient

from backend.integrations.scraper import yahoo
from backend.main import app
from backend.schemas.instruments import InstrumentMetadata
from backend.services.instruments import detect_instrument, lookup_instrument

OBSERVED_METADATA = {
    "AAPL": ("EQUITY", "USD", "NMS", "America/New_York"),
    "QQQ": ("ETF", "USD", "NGM", "America/New_York"),
    "EUNL.DE": ("ETF", "EUR", "GER", "Europe/Berlin"),
    "1306.T": ("ETF", "JPY", "JPX", "Asia/Tokyo"),
    "ISF.L": ("ETF", "GBp", "LSE", "Europe/London"),
}


@pytest.fixture
def chart_response():
    """직접 확인한 메타정보에 날짜 경계 검증용 고정 시세를 조합한다."""
    def build(symbol="QQQ"):
        kind, currency, exchange, timezone = OBSERVED_METADATA[symbol]
        return {
            "chart": {
                "error": None,
                "result": [{
                    "meta": {
                        "symbol": symbol,
                        "instrumentType": kind,
                        "currency": currency,
                        "exchangeName": exchange,
                        "exchangeTimezoneName": timezone,
                    },
                    "timestamp": [int(datetime(2025, 11, 7, 0, 30, tzinfo=UTC).timestamp())],
                    "indicators": {
                        "quote": [{"close": [1017.20]}],
                        "adjclose": [{"adjclose": [999.99]}],
                    },
                }],
            }
        }
    return build


@pytest.fixture
def yahoo_response():
    with patch.object(yahoo.requests, "Session") as session_factory:
        session = session_factory.return_value.__enter__.return_value
        response = Mock(status_code=200)
        session.get.return_value = response
        yield response, session


@pytest.mark.parametrize(
    "symbol,asset_type,currency,multiplier",
    [
        ("AAPL", "stock", "USD", "1"),
        ("QQQ", "etf", "USD", "1"),
        ("EUNL.DE", "etf", "EUR", "1"),
        ("1306.T", "etf", "JPY", "1"),
        ("ISF.L", "etf", "GBP", "0.01"),
    ],
)
def test_lookup_endpoint_detects_observed_instruments(
    chart_response, yahoo_response, symbol, asset_type, currency, multiplier
):
    response, session = yahoo_response
    response.json.return_value = chart_response(symbol)

    result = TestClient(app).get(f"/api/instruments/{symbol.lower()}")

    assert result.status_code == 200
    data = result.json()
    assert data["ticker"] == symbol
    assert data["detection_status"] == "detected"
    assert data["asset_type"] == asset_type
    assert data["currency"] == currency
    assert data["quote_currency"] == OBSERVED_METADATA[symbol][1]
    assert Decimal(data["price_multiplier"]) == Decimal(multiplier)
    assert data["exchange_timezone"] == OBSERVED_METADATA[symbol][3]
    assert data["reason"] is None
    assert session.get.call_args.kwargs["timeout"] == 15


@pytest.mark.parametrize("instrument_type", [None, "", "   "])
def test_missing_type_requires_manual_selection(chart_response, yahoo_response, instrument_type):
    response, _ = yahoo_response
    payload = chart_response()
    payload["chart"]["result"][0]["meta"]["instrumentType"] = instrument_type
    response.json.return_value = payload

    result = TestClient(app).get("/api/instruments/QQQ").json()

    assert result["detection_status"] == "needs_selection"
    assert result["reason"] == "missing_type"
    assert result["asset_type"] is None
    assert result["currency"] == "USD"


def test_missing_metadata_requires_manual_selection(yahoo_response):
    response, _ = yahoo_response
    response.json.return_value = {"chart": {"result": [{}], "error": None}}

    result = lookup_instrument(" qqq ")

    assert result.ticker == "QQQ"
    assert result.detection_status == "needs_selection"
    assert result.reason == "missing_type"
    assert result.currency is None


@pytest.mark.parametrize(
    "kind", ["MUTUALFUND", "INDEX", "FUTURE", "CRYPTOCURRENCY", "BOND", "ETN", "OPTION", "CURRENCY", "WARRANT"]
)
def test_known_other_types_cannot_offer_manual_selection(kind, yahoo_response, chart_response):
    response, _ = yahoo_response
    payload = chart_response()
    payload["chart"]["result"][0]["meta"]["instrumentType"] = kind
    response.json.return_value = payload

    result = TestClient(app).get("/api/instruments/QQQ").json()

    assert result["detection_status"] == "unsupported"
    assert result["asset_type"] is None
    assert result["reason"] == "unsupported_type"


def test_unknown_provider_type_requires_manual_selection(yahoo_response, chart_response):
    response, _ = yahoo_response
    payload = chart_response()
    payload["chart"]["result"][0]["meta"]["instrumentType"] = "UNRECOGNIZED"
    response.json.return_value = payload

    result = TestClient(app).get("/api/instruments/QQQ").json()

    assert result["detection_status"] == "needs_selection"
    assert result["reason"] == "unknown_type"
    assert result["asset_type"] is None


def test_not_found_endpoint_returns_invalid_ticker(yahoo_response):
    response, _ = yahoo_response
    response.status_code = 404

    result = TestClient(app).get("/api/instruments/INVALID123")

    assert result.status_code == 400
    assert result.json()["detail"]["code"] == "INVALID_TICKER"
    assert result.json()["detail"]["ticker"] == "INVALID123"


def test_provider_not_found_error_is_not_manual_selection(yahoo_response):
    response, _ = yahoo_response
    response.json.return_value = {
        "chart": {"result": None, "error": {"code": "Not Found", "description": "no data"}}
    }

    result = TestClient(app).get("/api/instruments/INVALID123")

    assert result.status_code == 400
    assert result.json()["detail"]["code"] == "INVALID_TICKER"


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_http_failure_offers_manual_selection(yahoo_response, status):
    response, _ = yahoo_response
    response.status_code = status

    result = TestClient(app).get("/api/instruments/QQQ")

    assert result.status_code == 200
    assert result.json()["detection_status"] == "needs_selection"
    assert result.json()["reason"] == "metadata_unavailable"
    assert result.json()["asset_type"] is None


def test_transport_failure_offers_manual_selection(yahoo_response):
    _, session = yahoo_response
    session.get.side_effect = RequestException("timeout")

    result = TestClient(app).get("/api/instruments/QQQ")

    assert result.status_code == 200
    assert result.json()["reason"] == "metadata_unavailable"
    assert result.json()["asset_type"] is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"chart": None}, {"chart": {"result": []}}, {"chart": {"result": [None]}},
     {"chart": {"result": [{"meta": ["invalid"]}]}}],
)
def test_malformed_metadata_offers_manual_selection(yahoo_response, payload):
    response, _ = yahoo_response
    response.json.return_value = payload

    result = lookup_instrument("QQQ")

    assert result.detection_status == "needs_selection"
    assert result.reason == "metadata_unavailable"


def test_non_json_response_offers_manual_selection(yahoo_response):
    response, _ = yahoo_response
    response.json.side_effect = ValueError("not JSON")

    assert lookup_instrument("QQQ").reason == "metadata_unavailable"


def test_invalid_ticker_format_does_not_call_provider(yahoo_response):
    _, session = yahoo_response

    result = TestClient(app).get("/api/instruments/QQQ%20ETF")

    assert result.status_code == 400
    assert result.json()["detail"]["code"] == "INVALID_TICKER"
    session.get.assert_not_called()


@pytest.mark.parametrize("quote_currency,multiplier", [("GBp", "0.01"), ("GBX", "0.01"), ("GBP", "1")])
def test_pence_prices_are_normalized_once(yahoo_response, chart_response, quote_currency, multiplier):
    response, _ = yahoo_response
    payload = chart_response("ISF.L")
    payload["chart"]["result"][0]["meta"]["currency"] = quote_currency
    response.json.return_value = payload

    result = yahoo.get_instrument_prices("ISF.L", date(2025, 11, 7), date(2025, 11, 8))

    assert result.metadata.currency == "GBP"
    assert result.metadata.quote_currency == quote_currency
    assert result.prices[0].close == Decimal("1017.20") * Decimal(multiplier)


@pytest.mark.parametrize("server_timezone", ["UTC", "Asia/Seoul", "America/Los_Angeles"])
def test_history_dates_use_exchange_timezone(
    yahoo_response, chart_response, monkeypatch, server_timezone
):
    response, session = yahoo_response
    payload = chart_response()
    chart = payload["chart"]["result"][0]
    chart["timestamp"] = [
        int(datetime(2025, 11, day, 0, 30, tzinfo=UTC).timestamp()) for day in [6, 7, 8]
    ]
    chart["indicators"]["quote"][0]["close"] = [100, 200, 300]
    response.json.return_value = payload

    try:
        with monkeypatch.context() as context:
            context.setenv("TZ", server_timezone)
            time.tzset()
            result = yahoo.get_instrument_prices("QQQ", date(2025, 11, 6), date(2025, 11, 7))
    finally:
        time.tzset()

    assert [(p.date, p.close) for p in result.prices] == [(date(2025, 11, 6), Decimal(200))]
    params = session.get.call_args.kwargs["params"]
    assert params["period1"] == int(datetime(2025, 11, 5, tzinfo=UTC).timestamp())
    assert params["period2"] == int(datetime(2025, 11, 8, tzinfo=UTC).timestamp())


def test_history_uses_close_not_adjusted_close(yahoo_response, chart_response):
    response, _ = yahoo_response
    response.json.return_value = chart_response()

    result = yahoo.get_instrument_prices("QQQ", date(2025, 11, 6), date(2025, 11, 7))

    assert result.prices[0].close == Decimal("1017.2")


@pytest.mark.parametrize("missing", ["exchangeTimezoneName", "currency"])
def test_history_requires_date_and_unit_metadata(yahoo_response, chart_response, missing):
    response, _ = yahoo_response
    payload = chart_response()
    del payload["chart"]["result"][0]["meta"][missing]
    response.json.return_value = payload

    with pytest.raises(yahoo.YahooFinanceError):
        yahoo.get_instrument_prices("QQQ", date(2025, 11, 6), date(2025, 11, 7))


def test_null_closes_are_not_prices(yahoo_response, chart_response):
    response, _ = yahoo_response
    payload = chart_response()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [None]
    response.json.return_value = payload

    result = yahoo.get_instrument_prices("QQQ", date(2025, 11, 6), date(2025, 11, 7))

    assert result.prices == []


@pytest.mark.parametrize("bad_price", ["NaN", "Infinity", -1, 0, "not a number"])
def test_invalid_closes_fail_instead_of_becoming_evidence(yahoo_response, chart_response, bad_price):
    response, _ = yahoo_response
    payload = chart_response()
    payload["chart"]["result"][0]["indicators"]["quote"][0]["close"] = [bad_price]
    response.json.return_value = payload

    with pytest.raises(yahoo.YahooFinanceError):
        yahoo.get_instrument_prices("QQQ", date(2025, 11, 6), date(2025, 11, 7))


def test_price_history_retains_metadata_for_detection(yahoo_response, chart_response):
    response, _ = yahoo_response
    response.json.return_value = chart_response()

    history = yahoo.get_instrument_prices("QQQ", date(2025, 11, 6), date(2025, 11, 7))
    result = detect_instrument(history.metadata)

    assert result.asset_type == "etf"
    assert result.detection_status == "detected"


def test_detection_keeps_unknown_type_unselected():
    result = detect_instrument(InstrumentMetadata(ticker="QQQ"))

    assert result.asset_type is None
    assert result.detection_status == "needs_selection"
