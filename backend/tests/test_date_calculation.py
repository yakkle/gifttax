from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from dateutil.relativedelta import relativedelta

from backend.services.calculator import (
    CalculationUnavailableError,
    calculate_gift_amount,
    get_calculation_available_from,
    get_stock_price_display_period,
    get_stock_price_fetch_period,
    validate_calculation_availability,
)


class TestDateCalculation:
    """증여일 기준 전후 2개월 계산 테스트"""

    def test_period_start_is_gift_date_minus_2_months_plus_1_day(self):
        """전: gift_date - 2개월 + 1일"""
        gift_date = date(2025, 11, 6)

        period_start, _ = get_stock_price_display_period(gift_date)

        assert period_start == date(2025, 9, 7)

    def test_period_end_is_gift_date_plus_2_months_minus_1_day(self):
        """후: gift_date + 2개월 - 1일"""
        gift_date = date(2025, 11, 6)

        _, period_end = get_stock_price_display_period(gift_date)

        assert period_end == date(2026, 1, 5)

    def test_fetch_period_end_adds_one_day_for_yahoo(self):
        gift_date = date(2025, 11, 6)

        _, fetch_period_end = get_stock_price_fetch_period(gift_date)

        assert fetch_period_end == date(2026, 1, 6)

    def test_period_calculation_with_different_dates(self):
        """다른 날짜로 테스트"""
        gift_date = date(2025, 1, 15)

        period_start, period_end = get_stock_price_display_period(gift_date)

        assert period_start == date(2024, 11, 16)
        assert period_end == date(2025, 3, 14)

    def test_period_calculation_leap_year(self):
        """윤년 테스트"""
        gift_date = date(2024, 2, 29)  # 윤년

        period_start, period_end = get_stock_price_display_period(gift_date)

        assert period_start == date(2023, 12, 30)
        assert period_end == date(2024, 4, 28)


class TestCalculationAvailability:
    def test_available_from_is_gift_date_plus_two_months(self):
        gift_date = date(2025, 11, 6)

        available_from = get_calculation_available_from(gift_date)

        assert available_from == date(2026, 1, 6)

    def test_validation_raises_before_two_month_window_completes(self):
        gift_date = date(2025, 11, 6)

        with pytest.raises(CalculationUnavailableError) as exc_info:
            validate_calculation_availability(gift_date, today=date(2026, 1, 5))

        assert exc_info.value.available_from == date(2026, 1, 6)

    def test_validation_allows_on_available_date(self):
        gift_date = date(2025, 11, 6)

        validate_calculation_availability(gift_date, today=date(2026, 1, 6))


class TestCalculatorWithMock:
    """계산기 mock 테스트"""

    def test_calculate_gift_amount_with_mock(self):
        """Mock을 사용한 계산 테스트"""
        with (
            patch("backend.services.calculator.scraper.get_stock_prices") as mock_prices,
            patch("backend.services.calculator.smbs.get_exchange_rate") as mock_rate,
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
            assert result.period_end == date(2026, 1, 5)
            assert result.price_average == Decimal("150.00")
            assert result.gift_amount_krw == Decimal("2025000.00")
            mock_prices.assert_called_once_with(
                "AAPL",
                date(2025, 9, 7),
                date(2026, 1, 6),
            )

    def test_calculate_gift_amount_raises_when_two_month_window_incomplete(self):
        gift_date = date.today() - relativedelta(months=1)

        with pytest.raises(CalculationUnavailableError):
            calculate_gift_amount(
                gift_date=gift_date,
                ticker="AAPL",
                qty=10,
                currency="USD",
            )


class TestScraperFunctions:
    """Scraper 함수 테스트"""

    def test_get_exchange_rate_parses_xml(self):
        """환율 XML 파싱 테스트"""
        xml_data = """<?xml version="1.0" encoding="EUC-KR"?>
        <chart>
        <set label='25.11.06' value='1447.5' />
        <set label='25.11.07' value='1448.0' />
        </chart>"""

        from backend.integrations.scraper.smbs import parse_xml_response

        result = parse_xml_response(xml_data)

        assert len(result) == 2
        assert result[0][0] == date(2025, 11, 6)
        assert result[0][1] == Decimal("1447.5")
