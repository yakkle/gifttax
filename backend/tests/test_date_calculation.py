from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from dateutil.relativedelta import relativedelta

from services.calculator import calculate_gift_amount
from integrations.scraper.yahoo import get_stock_prices
from integrations.scraper.smbs import get_exchange_rate, get_exchange_rates


class TestDateCalculation:
    """증여일 기준 전후 2개월 계산 테스트"""

    def test_period_start_is_gift_date_minus_2_months_plus_1_day(self):
        """전: gift_date - 2개월 + 1일"""
        gift_date = date(2025, 11, 6)

        period_start = gift_date - relativedelta(months=2) + timedelta(days=1)

        assert period_start == date(2025, 9, 7)

    def test_period_end_is_gift_date_plus_2_months_minus_1_day(self):
        """후: gift_date + 2개월 - 1일 + 1일 (Yahoo Finance 호환)"""
        gift_date = date(2025, 11, 6)

        period_end = gift_date + relativedelta(months=2) - timedelta(days=1) + timedelta(days=1)

        assert period_end == date(2026, 1, 6)

    def test_period_calculation_with_different_dates(self):
        """다른 날짜로 테스트"""
        gift_date = date(2025, 1, 15)

        period_start = gift_date - relativedelta(months=2) + timedelta(days=1)
        period_end = gift_date + relativedelta(months=2) - timedelta(days=1) + timedelta(days=1)

        assert period_start == date(2024, 11, 16)
        assert period_end == date(2025, 3, 15)

    def test_period_calculation_leap_year(self):
        """윤년 테스트"""
        gift_date = date(2024, 2, 29)  # 윤년

        period_start = gift_date - relativedelta(months=2) + timedelta(days=1)
        period_end = gift_date + relativedelta(months=2) - timedelta(days=1) + timedelta(days=1)

        assert period_start == date(2023, 12, 30)
        assert period_end == date(2024, 4, 29)


class TestCalculatorWithMock:
    """계산기 mock 테스트"""

    def test_calculate_gift_amount_with_mock(self):
        """Mock을 사용한 계산 테스트"""
        with (
            patch("services.calculator.scraper.get_stock_prices") as mock_prices,
            patch("services.calculator.smbs.get_exchange_rate") as mock_rate,
        ):
            mock_prices.return_value = [
                (date(2025, 9, 8), Decimal("100.00")),
                (date(2025, 9, 9), Decimal("200.00")),
            ]
            mock_rate.return_value = (Decimal("1350.00"), date(2025, 11, 6))

            result = calculate_gift_amount(
                gift_date=date(2025, 11, 6),
                ticker="AAPL",
                qty=10,
                currency="USD",
            )

            assert result.ticker == "AAPL"
            assert result.period_start == date(2025, 9, 7)
            assert result.period_end == date(2026, 1, 6)
            assert result.price_average == Decimal("150.00")
            assert result.gift_amount_krw == Decimal("2025000.00")


class TestScraperFunctions:
    """Scraper 함수 테스트"""

    def test_get_exchange_rate_parses_xml(self):
        """환율 XML 파싱 테스트"""
        xml_data = """<?xml version="1.0" encoding="EUC-KR"?>
        <chart>
        <set label='25.11.06' value='1447.5' />
        <set label='25.11.07' value='1448.0' />
        </chart>"""

        from integrations.scraper.smbs import parse_xml_response

        result = parse_xml_response(xml_data)

        assert len(result) == 2
        assert result[0][0] == date(2025, 11, 6)
        assert result[0][1] == Decimal("1447.5")
