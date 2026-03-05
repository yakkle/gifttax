from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from stocktax.main import app
from stocktax.models import GiftCalculationInput, StockInput

client = TestClient(app)


class TestModels:
    def test_stock_input_valid(self):
        stock = StockInput(ticker="AAPL", qty=100, currency="USD")
        assert stock.ticker == "AAPL"
        assert stock.qty == 100
        assert stock.currency == "USD"

    def test_stock_input_qty_must_be_positive(self):
        with pytest.raises(Exception):
            StockInput(ticker="AAPL", qty=0, currency="USD")

    def test_gift_calculation_input_valid(self):
        input_data = GiftCalculationInput(
            gift_date=date(2025, 11, 6),
            stocks=[StockInput(ticker="AAPL", qty=100, currency="USD")],
        )
        assert input_data.gift_date == date(2025, 11, 6)
        assert len(input_data.stocks) == 1


class TestAPI:
    def test_calculate_endpoint_valid_input(self):
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "AAPL", "qty": 100, "currency": "USD"},
            ],
        }

        with (
            patch("stocktax.services.scraper.yahoo.get_stock_prices") as mock_prices,
            patch("stocktax.services.scraper.smbs.get_exchange_rate") as mock_rate,
        ):
            mock_prices.return_value = [
                (date(2025, 9, 7), Decimal("150.00")),
                (date(2025, 9, 8), Decimal("152.00")),
            ]
            mock_rate.return_value = (Decimal("1350.00"), date(2025, 11, 6))

            response = client.post("/api/calculate", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["gift_date"] == "2025-11-06"
            assert len(data["stocks"]) == 1

    def test_calculate_endpoint_missing_fields(self):
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [],
        }

        response = client.post("/api/calculate", json=payload)
        assert response.status_code == 422

    def test_download_endpoint_not_found(self):
        response = client.get("/api/download/nonexistent-file")
        assert response.status_code == 404


class TestCalculator:
    def test_calculate_gift_amount(self):
        from stocktax.services.calculator import calculate_gift_amount

        with (
            patch("stocktax.services.scraper.yahoo.get_stock_prices") as mock_prices,
            patch("stocktax.services.scraper.smbs.get_exchange_rate") as mock_rate,
        ):
            mock_prices.return_value = [
                (date(2025, 9, 7), Decimal("100.00")),
                (date(2025, 9, 8), Decimal("200.00")),
            ]
            mock_rate.return_value = (Decimal("1000.00"), date(2025, 11, 6))

            result = calculate_gift_amount(
                gift_date=date(2025, 11, 6),
                ticker="AAPL",
                qty=10,
                currency="USD",
            )

            assert result.ticker == "AAPL"
            assert result.qty == 10
            assert result.currency == "USD"
            assert result.price_average == Decimal("150.00")
            assert result.exchange_rate == Decimal("1000.00")
            assert result.gift_amount_krw == Decimal("1500000.00")


class TestScraper:
    def test_parse_investing_date(self):
        from stocktax.services.scraper.investing import parse_investing_date

        result = parse_investing_date("Nov 6, 2025")
        assert result == date(2025, 11, 6)

    def test_datetime_str_to_date(self):
        from stocktax.services.scraper.smbs import datetime_str_to_date

        result = datetime_str_to_date("2025.11.06")
        assert result == date(2025, 11, 6)


class TestInvalidTicker:
    """잘못된 종목 코드 예외 처리 테스트"""

    def test_invalid_ticker_returns_400(self):
        """존재하지 않는 종목 코드 입력 시 400 에러 반환"""
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "INVALID123", "qty": 100, "currency": "USD"},
            ],
        }

        response = client.post("/api/calculate", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]

    def test_invalid_ticker_appl_returns_400(self):
        """APPL (잘못된 티커) 입력 시 400 에러 반환"""
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "APPL", "qty": 100, "currency": "USD"},
            ],
        }

        response = client.post("/api/calculate", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]

    def test_invalid_ticker_generate_excel(self):
        """엑셀 생성 시 존재하지 않는 종목 코드 입력 시 400 에러 반환"""
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "NOTEXIST", "qty": 100, "currency": "USD"},
            ],
        }

        response = client.post("/api/generate-excel", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]

    def test_invalid_ticker_generate_pdf(self):
        """PDF 생성 시 존재하지 않는 종목 코드 입력 시 400 에러 반환"""
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "FAKETICKER", "qty": 100, "currency": "USD"},
            ],
        }

        response = client.post("/api/generate-pdf", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]
