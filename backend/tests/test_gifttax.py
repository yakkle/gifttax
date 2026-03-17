import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from integrations.scraper.yahoo import InvalidTickerError
from models import GiftCalculationInput, StockInput

from backend.main import app

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
            patch("services.calculator.scraper.get_stock_prices") as mock_prices,
            patch("services.calculator.smbs.get_exchange_rate") as mock_rate,
            patch("services.calculator.smbs.get_exchange_rates") as mock_rates,
        ):
            mock_prices.return_value = [
                (date(2025, 9, 7), Decimal("150.00")),
                (date(2025, 9, 8), Decimal("152.00")),
            ]
            mock_rate.return_value = (Decimal("1350.00"), date(2025, 11, 6))
            mock_rates.return_value = [
                (date(2025, 11, 5), Decimal("1348.00")),
                (date(2025, 11, 6), Decimal("1350.00")),
            ]

            response = client.post("/api/calculate", json=payload)

            assert response.status_code == 200
            data = response.json()
            assert data["gift_date"] == "2025-11-06"
            assert len(data["stocks"]) == 1
            assert data["gift_pdf_file_id"] is not None
            assert data["rate_pdf_file_id"] is not None

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

    def test_download_deletes_file_after_download(self):
        """다운로드 완료 후 서버에 저장된 PDF 파일이 삭제된다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_id = "test-file-id"
            pdf_path = Path(tmpdir) / f"{file_id}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test content")

            with patch("api.router.STORAGE_DIR", tmpdir):
                response = client.get(f"/api/download/{file_id}")

            assert response.status_code == 200
            assert not pdf_path.exists()

    def test_download_already_deleted_returns_404(self):
        """이미 다운로드(삭제)된 파일을 재요청하면 404를 반환한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_id = "test-file-id"
            pdf_path = Path(tmpdir) / f"{file_id}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test content")

            with patch("api.router.STORAGE_DIR", tmpdir):
                first = client.get(f"/api/download/{file_id}")
                second = client.get(f"/api/download/{file_id}")

            assert first.status_code == 200
            assert second.status_code == 404

    def test_delete_file_removes_pdf(self):
        """DELETE 요청으로 미다운로드 PDF 파일이 삭제된다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_id = "test-file-id"
            pdf_path = Path(tmpdir) / f"{file_id}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4 test content")

            with patch("api.router.STORAGE_DIR", tmpdir):
                response = client.delete(f"/api/download/{file_id}")

            assert response.status_code == 204
            assert not pdf_path.exists()

    def test_delete_nonexistent_file_returns_204(self):
        """이미 없는 파일을 DELETE 해도 204를 반환한다 (멱등성)."""
        response = client.delete("/api/download/nonexistent-file")
        assert response.status_code == 204

    def test_recalculate_deletes_previous_files(self):
        """재계산 시 이전 계산의 미다운로드 파일이 DELETE 요청으로 삭제된다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gift_file_id = "prev-gift-pdf"
            rate_file_id = "prev-rate-pdf"
            (Path(tmpdir) / f"{gift_file_id}.pdf").write_bytes(b"%PDF-1.4 gift")
            (Path(tmpdir) / f"{rate_file_id}.pdf").write_bytes(b"%PDF-1.4 rate")

            with patch("api.router.STORAGE_DIR", tmpdir):
                # 프론트엔드가 재계산 전 이전 file_id를 DELETE로 정리
                r1 = client.delete(f"/api/download/{gift_file_id}")
                r2 = client.delete(f"/api/download/{rate_file_id}")

            assert r1.status_code == 204
            assert r2.status_code == 204
            assert not (Path(tmpdir) / f"{gift_file_id}.pdf").exists()
            assert not (Path(tmpdir) / f"{rate_file_id}.pdf").exists()


class TestCalculator:
    def test_calculate_gift_amount(self):
        from services.calculator import calculate_gift_amount

        with (
            patch("services.calculator.scraper.get_stock_prices") as mock_prices,
            patch("services.calculator.smbs.get_exchange_rate") as mock_rate,
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
        from integrations.scraper.investing import parse_investing_date

        result = parse_investing_date("Nov 6, 2025")
        assert result == date(2025, 11, 6)

    def test_datetime_str_to_date(self):
        from integrations.scraper.smbs import datetime_str_to_date

        result = datetime_str_to_date("2025.11.06")
        assert result == date(2025, 11, 6)


class TestTaxEngine:
    def test_calculate_gift_tax_returns_zero(self):
        """현재 TaxEngine은 stub으로 0을 반환한다."""
        from tax.engine import calculate_gift_tax

        result = calculate_gift_tax(Decimal("2600000"))
        assert result == Decimal("0")

    def test_calculate_gift_tax_zero_amount(self):
        """증여금액이 0이어도 0을 반환한다."""
        from tax.engine import calculate_gift_tax

        result = calculate_gift_tax(Decimal("0"))
        assert result == Decimal("0")

    def test_calculate_gift_tax_large_amount(self):
        """큰 금액에도 현재는 0을 반환한다."""
        from tax.engine import calculate_gift_tax

        result = calculate_gift_tax(Decimal("1000000000"))
        assert result == Decimal("0")


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

        with patch("services.calculator.scraper.get_stock_prices") as mock_prices:
            mock_prices.side_effect = InvalidTickerError("종목 코드를 찾을 수 없습니다: INVALID123")
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

        with patch("services.calculator.scraper.get_stock_prices") as mock_prices:
            mock_prices.side_effect = InvalidTickerError("종목 코드를 찾을 수 없습니다: APPL")
            response = client.post("/api/calculate", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]

    def test_invalid_ticker_generate_gift_pdf(self):
        """잘못된 종목 코드 입력 시 /api/calculate 에서 400 에러 반환"""
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "NOTEXIST", "qty": 100, "currency": "USD"},
            ],
        }

        with patch("services.calculator.scraper.get_stock_prices") as mock_prices:
            mock_prices.side_effect = InvalidTickerError("종목 코드를 찾을 수 없습니다: NOTEXIST")
            response = client.post("/api/calculate", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]

    def test_invalid_ticker_generate_pdf(self):
        """잘못된 종목 코드 입력 시 /api/calculate 에서 400 에러 반환"""
        payload = {
            "gift_date": "2025-11-06",
            "stocks": [
                {"ticker": "FAKETICKER", "qty": 100, "currency": "USD"},
            ],
        }

        with patch("services.calculator.scraper.get_stock_prices") as mock_prices:
            mock_prices.side_effect = InvalidTickerError("종목 코드를 찾을 수 없습니다: FAKETICKER")
            response = client.post("/api/calculate", json=payload)

        assert response.status_code == 400
        assert "종목 코드를 찾을 수 없습니다" in response.json()["detail"]
