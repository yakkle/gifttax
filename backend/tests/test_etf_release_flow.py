"""외부 HTTP 경계만 대체해 자동 판별부터 복수 통화 PDF 다운로드까지 검증한다."""

from datetime import date, datetime
from decimal import Decimal
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from backend.api import backend
from backend.integrations.scraper import smbs, yahoo
from backend.main import app
from backend.services import calculator

GIFT_DATE = date(2025, 11, 10)
INSTRUMENTS = {
    "AAPL": ("EQUITY", "USD", "America/New_York", "200"),
    "QQQ": ("ETF", "USD", "America/New_York", "200.12345"),
    "EUNL.DE": ("ETF", "EUR", "Europe/Berlin", "100.5"),
    "1306.T": ("ETF", "JPY", "Asia/Tokyo", "3210.125"),
    "ISF.L": ("ETF", "GBp", "Europe/London", "1017.23"),
}
# 검증용 합성 고시값. 실제 해당 날짜의 고시·휴일을 나타내지 않는다.
RAW_RATES = {
    "USD": {"2025-11-07": "1300", "2025-11-10": "1300", "2025-11-11": "1301"},
    "EUR": {"2025-11-06": "1499", "2025-11-07": "1500"},
    "JPY": {"2025-11-05": "938.43", "2025-11-06": "939.43"},
    "GBP": {"2025-11-10": "1887.35", "2025-11-11": "1888.35"},
}


@pytest.fixture
def transport_market(monkeypatch):
    calls = []

    class Response:
        status_code = 200

        def __init__(self, *, data=None, text=""):
            self.data = data
            self.text = text

        def json(self):
            return self.data

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, *, params, timeout):
            calls.append((url, params.copy()))
            if "finance.yahoo.com" in url:
                ticker = unquote(url.rsplit("/", 1)[-1])
                kind, currency, timezone, price = INSTRUMENTS[ticker]
                days = [date(2025, 9, 12), date(2025, 11, 7), date(2026, 1, 9)] if kind == "EQUITY" else [date(2025, 10, 10), date(2025, 11, 7), GIFT_DATE, date(2025, 11, 11)]
                closes = [195, 200, 205] if kind == "EQUITY" else [1, float(price), 9999, 99999]
                return Response(data={"chart": {"error": None, "result": [{
                    "meta": {"symbol": ticker, "instrumentType": kind, "currency": currency,
                             "exchangeTimezoneName": timezone, "exchangeName": "TEST"},
                    "timestamp": [int(datetime(d.year, d.month, d.day, 16, tzinfo=ZoneInfo(timezone)).timestamp()) for d in days],
                    "indicators": {"quote": [{"close": closes}], "adjclose": [{"adjclose": [1] * len(days)}]},
                }]}})
            assert url == "http://www.smbs.biz/ExRate/StdExRate_xml.jsp"
            currency, start, end = params["arr_value"].split("_")
            rows = [f"<set label='{day[2:].replace('-', '.')}' value='{rate}'/>"
                    for day, rate in RAW_RATES[currency].items() if start <= day <= end]
            return Response(text="<chart>" + "".join(rows) + "</chart>")

    monkeypatch.setattr(yahoo.requests, "Session", lambda **kwargs: Session())
    monkeypatch.setattr(smbs.curl_requests, "Session", lambda **kwargs: Session())
    monkeypatch.setattr(calculator, "get_current_date", lambda: date(2026, 1, 10))
    return calls


@pytest.mark.parametrize(
    "tickers,total,currencies",
    [(["QQQ"], "2601605", ["USD"]),
     (["AAPL", "QQQ"], "5201605", ["USD"]),
     (["QQQ", "EUNL.DE", "1306.T", "ISF.L"], "4602661", ["USD", "EUR", "JPY", "GBP"])],
)
def test_detection_calculation_and_both_pdf_downloads(
    transport_market, recorded_pdf, tmp_path, monkeypatch, tickers, total, currencies
):
    monkeypatch.setattr(backend, "STORAGE_DIR", str(tmp_path))
    if tickers == ["QQQ"]:
        # 최근 ETF 증여는 일반 주식의 후 2개월 조건을 통과할 필요가 없다.
        monkeypatch.setattr(calculator, "get_current_date", lambda: GIFT_DATE)
    client = TestClient(app)
    stocks = []
    for ticker in tickers:
        lookup = client.get(f"/api/instruments/{ticker}")
        assert lookup.status_code == 200
        info = lookup.json()
        assert info["detection_status"] == "detected"
        assert info["asset_type"] == ("stock" if ticker == "AAPL" else "etf")
        stocks.append({"ticker": ticker, "qty": 10, "currency": info["currency"]})
    response = client.post("/api/calculate", json={"gift_date": GIFT_DATE.isoformat(), "stocks": stocks})
    assert response.status_code == 200, response.text
    data = response.json()
    assert Decimal(data["total_gift_amount_krw"]) == Decimal(total)
    assert [item["currency"] for item in data["exchange_rate_evidence"]] == currencies
    for stock in data["stocks"]:
        assert stock["detection_method"] == "auto"
        if stock["ticker"] == "AAPL":
            assert stock["valuation_method"] == "average_close"
            assert Decimal(stock["valuation_price"]) == Decimal(200)
            assert (stock["period_start"], stock["period_end"]) == ("2025-09-11", "2026-01-09")
        else:
            assert stock["valuation_method"] == "previous_close"
            assert stock["price_date"] == stock["period_start"] == stock["period_end"] == "2025-11-07"
            assert len(stock["price_data"]) == 1
        if stock["ticker"] == "ISF.L":
            assert Decimal(stock["valuation_price"]) == Decimal("10.1723")
            assert stock["quote_currency"] == "GBp"
        if stock["ticker"] == "1306.T":
            assert Decimal(stock["exchange_rate"]) == Decimal("9.3943")
            assert stock["exchange_rate_date"] == "2025-11-06"
    for item in data["exchange_rate_evidence"]:
        actual = date.fromisoformat(item["actual_rate_date"])
        assert (actual - date.fromisoformat(item["period_start"])).days == 1
        assert (date.fromisoformat(item["period_end"]) - actual).days == 1
    gift_text = "\n".join(recorded_pdf[0].texts)
    assert f"{int(total):,} 원" in gift_text
    assert recorded_pdf[1].page_count == len(currencies)
    for stock in data["stocks"]:
        assert stock["price_source_url"] in recorded_pdf[0].links
    if "JPY" in currencies:
        rate_text = "\n".join(recorded_pdf[1].texts)
        assert "939.43 KRW/100JPY" in rate_text
        assert "9.3943 KRW/JPY" in gift_text
    # 같은 USD 환율은 주식과 ETF가 공유하고 계산용 단일 날짜 조회는 한 번만 한다.
    usd_queries = [params["arr_value"] for url, params in transport_market if "smbs.biz" in url]
    assert usd_queries.count("USD_2025-11-10_2025-11-10") == 1
    for key in ["gift_pdf_file_id", "rate_pdf_file_id"]:
        file_id = data[key]
        download = client.get(f"/api/download/{file_id}")
        assert download.status_code == 200
        assert download.content.startswith(b"%PDF-")
        assert f"gifttax_{file_id}.pdf" in download.headers["content-disposition"]
        assert client.get(f"/api/download/{file_id}").status_code == 404
    assert list(tmp_path.iterdir()) == []
