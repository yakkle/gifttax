"""계산 증빙 PDF 생성 모듈 테스트

테스트 범위:
- URL 빌더 함수 (_build_yahoo_url, _build_smbs_url)
- 숫자 포맷 함수 (_round2, _format_krw)
- generate_pdf_gift_calculation 출력 (바이트 유무, PDF 헤더)
- API 엔드포인트 /generate-gift-pdf
"""

import io
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest

from pdf.generator.gift_calculation_pdf import (
    _build_smbs_url,
    _build_yahoo_url,
    _format_krw,
    _round2,
    generate_pdf_gift_calculation,
)
from models import GiftCalculationResult, StockGiftResult, PriceDataPoint


# ---------------------------------------------------------------------------
# 픽스처
# ---------------------------------------------------------------------------


def _make_stock_result(
    ticker: str = "AAPL",
    currency: str = "USD",
    qty: int = 10,
    price_average: str = "200.00",
    exchange_rate: str = "1300.00",
    gift_amount_krw: str = "2600000",
    period_start: date = date(2024, 3, 2),
    period_end: date = date(2024, 6, 30),
    exchange_rate_date: date = date(2024, 4, 30),
    price_data: list | None = None,
) -> StockGiftResult:
    if price_data is None:
        price_data = [
            PriceDataPoint(date="2024-03-02", close="195.301"),
            PriceDataPoint(date="2024-03-03", close="200.004"),
            PriceDataPoint(date="2024-03-04", close="204.695"),
        ]
    return StockGiftResult(
        ticker=ticker,
        currency=currency,
        qty=qty,
        price_average=Decimal(price_average),
        price_data=price_data,
        period_start=period_start,
        period_end=period_end,
        exchange_rate=Decimal(exchange_rate),
        exchange_rate_date=exchange_rate_date,
        exchange_rate_data=[],
        gift_amount_krw=Decimal(gift_amount_krw),
    )


def _make_result(stocks: list[StockGiftResult] | None = None) -> GiftCalculationResult:
    if stocks is None:
        stocks = [_make_stock_result()]
    total = sum(s.gift_amount_krw for s in stocks)
    return GiftCalculationResult(
        gift_date=date(2024, 5, 1),
        stocks=stocks,
        total_gift_amount_krw=total,
        estimated_tax=Decimal("0"),
        exchange_rate_date=stocks[0].exchange_rate_date,
    )


# ---------------------------------------------------------------------------
# 숫자 포맷 함수
# ---------------------------------------------------------------------------


class TestRound2:
    def test_rounds_to_two_decimal_places(self):
        assert _round2(Decimal("195.301")) == "195.30"

    def test_rounds_up(self):
        assert _round2(Decimal("195.305")) == "195.31"

    def test_rounds_down(self):
        assert _round2(Decimal("195.304")) == "195.30"

    def test_already_two_decimals(self):
        assert _round2(Decimal("200.00")) == "200.00"

    def test_integer_value(self):
        assert _round2(Decimal("200")) == "200.00"

    def test_adds_thousands_separator(self):
        assert _round2(Decimal("1300.00")) == "1,300.00"

    def test_large_value(self):
        assert _round2(Decimal("12345.678")) == "12,345.68"


class TestFormatKrw:
    def test_formats_with_comma(self):
        assert _format_krw(Decimal("2600000")) == "2,600,000"

    def test_small_amount(self):
        assert _format_krw(Decimal("0")) == "0"

    def test_large_amount(self):
        assert _format_krw(Decimal("1000000000")) == "1,000,000,000"

    def test_truncates_decimal(self):
        # gift_amount_krw 는 원 단위 정수이지만 Decimal 타입일 수 있음
        assert _format_krw(Decimal("2600000.00")) == "2,600,000"


# ---------------------------------------------------------------------------
# URL 빌더 함수
# ---------------------------------------------------------------------------


class TestBuildYahooUrl:
    def test_contains_ticker(self):
        url = _build_yahoo_url("AAPL", date(2024, 3, 2), date(2024, 6, 30))
        assert "AAPL" in url

    def test_contains_history_path(self):
        url = _build_yahoo_url("AAPL", date(2024, 3, 2), date(2024, 6, 30))
        assert "finance.yahoo.com/quote/AAPL/history" in url

    def test_contains_period1_and_period2(self):
        url = _build_yahoo_url("AAPL", date(2024, 3, 2), date(2024, 6, 30))
        assert "period1=" in url
        assert "period2=" in url

    def test_period1_is_unix_timestamp(self):
        url = _build_yahoo_url("AAPL", date(2024, 3, 2), date(2024, 6, 30))
        # period1 값이 숫자인지 확인
        import re

        match = re.search(r"period1=(\d+)", url)
        assert match is not None
        assert int(match.group(1)) > 0

    def test_period1_less_than_period2(self):
        import re

        url = _build_yahoo_url("AAPL", date(2024, 3, 2), date(2024, 6, 30))
        p1 = int(re.search(r"period1=(\d+)", url).group(1))
        p2 = int(re.search(r"period2=(\d+)", url).group(1))
        assert p1 < p2

    def test_ticker_uppercase_in_url(self):
        url = _build_yahoo_url("aapl", date(2024, 3, 2), date(2024, 6, 30))
        assert "aapl" in url  # 빌더는 ticker 그대로 사용 (대문자 변환은 호출부 책임)


class TestBuildSmbsUrl:
    def test_contains_smbs_domain(self):
        url = _build_smbs_url(date(2024, 4, 29), date(2024, 5, 1), "USD")
        assert "smbs.biz" in url

    def test_contains_currency(self):
        url = _build_smbs_url(date(2024, 4, 29), date(2024, 5, 1), "USD")
        assert "tongwha_code=USD" in url

    def test_contains_start_date_parts(self):
        url = _build_smbs_url(date(2024, 4, 29), date(2024, 5, 1), "USD")
        assert "StrSch_sYear=2024" in url
        assert "StrSch_sMonth=04" in url
        assert "StrSch_sDay=29" in url

    def test_contains_end_date_parts(self):
        url = _build_smbs_url(date(2024, 4, 29), date(2024, 5, 1), "USD")
        assert "StrSch_eYear=2024" in url
        assert "StrSch_eMonth=05" in url
        assert "StrSch_eDay=01" in url

    def test_month_zero_padded(self):
        url = _build_smbs_url(date(2024, 1, 5), date(2024, 1, 7), "EUR")
        assert "StrSch_sMonth=01" in url
        assert "StrSch_sDay=05" in url

    def test_different_currencies(self):
        for currency in ["USD", "EUR", "JPY", "GBP"]:
            url = _build_smbs_url(date(2024, 4, 29), date(2024, 5, 1), currency)
            assert f"tongwha_code={currency}" in url


# ---------------------------------------------------------------------------
# PDF 생성 함수
# ---------------------------------------------------------------------------


class TestGeneratePdfGiftCalculation:
    def test_returns_non_empty_bytes(self):
        result = _make_result()
        buf = io.BytesIO()
        generate_pdf_gift_calculation(result, buf)
        assert buf.tell() > 0

    def test_output_starts_with_pdf_header(self):
        result = _make_result()
        buf = io.BytesIO()
        generate_pdf_gift_calculation(result, buf)
        buf.seek(0)
        assert buf.read(4) == b"%PDF"

    def test_single_stock_generates_pdf(self):
        stock = _make_stock_result(ticker="TSLA", currency="USD", qty=5)
        result = _make_result(stocks=[stock])
        buf = io.BytesIO()
        generate_pdf_gift_calculation(result, buf)
        assert buf.tell() > 0

    def test_multiple_stocks_generates_pdf(self):
        stocks = [
            _make_stock_result(ticker="AAPL", qty=10, gift_amount_krw="2600000"),
            _make_stock_result(
                ticker="TSLA",
                qty=5,
                price_average="800.00",
                gift_amount_krw="5200000",
                period_start=date(2024, 3, 2),
                period_end=date(2024, 6, 30),
                exchange_rate_date=date(2024, 4, 30),
            ),
        ]
        result = _make_result(stocks=stocks)
        buf = io.BytesIO()
        generate_pdf_gift_calculation(result, buf)
        assert buf.tell() > 0

    def test_many_price_rows_triggers_page_break(self):
        """데이터가 많으면 페이지 넘김이 발생해도 정상 생성된다."""
        price_data = [
            PriceDataPoint(date=f"2024-03-{i:02d}", close="200.00")
            for i in range(1, 90)  # 89개 행 — 한 페이지를 초과
        ]
        stock = _make_stock_result(price_data=price_data)
        result = _make_result(stocks=[stock])
        buf = io.BytesIO()
        generate_pdf_gift_calculation(result, buf)
        buf.seek(0)
        assert buf.read(4) == b"%PDF"

    def test_price_rounding_does_not_raise(self):
        """소수 자릿수가 많은 값도 오류 없이 처리된다."""
        price_data = [
            PriceDataPoint(date="2024-03-01", close="195.30123456789"),
            PriceDataPoint(date="2024-03-02", close="200.99999999"),
        ]
        stock = _make_stock_result(price_data=price_data)
        result = _make_result(stocks=[stock])
        buf = io.BytesIO()
        generate_pdf_gift_calculation(result, buf)
        assert buf.tell() > 0


# ---------------------------------------------------------------------------
# API 엔드포인트 /generate-gift-pdf
# ---------------------------------------------------------------------------


class TestGenerateGiftPdfEndpoint:
    def test_generate_gift_pdf_returns_file_id(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        payload = {
            "gift_date": "2024-05-01",
            "stocks": [{"ticker": "AAPL", "qty": 10, "currency": "USD"}],
        }

        with (
            patch("services.calculator.scraper.get_stock_prices") as mock_prices,
            patch("services.calculator.smbs.get_exchange_rate") as mock_rate,
            patch("services.calculator.smbs.get_exchange_rates") as mock_rates,
        ):
            mock_prices.return_value = [
                (date(2024, 3, 2), Decimal("195.30")),
                (date(2024, 3, 3), Decimal("204.70")),
            ]
            mock_rate.return_value = (Decimal("1300.00"), date(2024, 4, 30))
            mock_rates.return_value = [
                (date(2024, 4, 29), Decimal("1298.00")),
                (date(2024, 4, 30), Decimal("1300.00")),
            ]

            response = client.post("/api/generate-gift-pdf", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "file_id" in data
        assert "filename" in data
        assert data["filename"].startswith("gift_calculation_")
        assert data["filename"].endswith(".pdf")

    def test_generate_gift_pdf_invalid_ticker_returns_400(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        from integrations.scraper.yahoo import InvalidTickerError

        client = TestClient(app)
        payload = {
            "gift_date": "2024-05-01",
            "stocks": [{"ticker": "NOTEXIST", "qty": 10, "currency": "USD"}],
        }

        with patch("services.calculator.scraper.get_stock_prices") as mock_prices:
            mock_prices.side_effect = InvalidTickerError("종목 코드를 찾을 수 없습니다: NOTEXIST")
            response = client.post("/api/generate-gift-pdf", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]

    def test_generate_gift_pdf_missing_stocks_returns_422(self):
        from fastapi.testclient import TestClient
        from backend.main import app

        client = TestClient(app)
        payload = {"gift_date": "2024-05-01", "stocks": []}
        response = client.post("/api/generate-gift-pdf", json=payload)
        assert response.status_code == 422
