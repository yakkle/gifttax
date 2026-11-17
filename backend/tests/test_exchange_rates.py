"""환율 조회, 단위, 공유 증빙 및 복수 통화 PDF 회귀 테스트."""

import io
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from curl_cffi.requests.exceptions import RequestException
from fastapi.testclient import TestClient

from backend.integrations.scraper import smbs
from backend.main import app
from backend.pdf.generator import exchange_rate_pdf, gift_calculation_pdf
from backend.pdf.generator.common import format_exchange_rate
from backend.schemas import GiftCalculationInput, PriceDataPoint, StockInput
from backend.services import calculator, exchange_rates

pytestmark = pytest.mark.usefixtures("legacy_stock_price_fixtures")


@pytest.fixture
def smbs_response():
    with patch.object(smbs.curl_requests, "Session") as session_factory:
        session = session_factory.return_value.__enter__.return_value
        response = Mock(status_code=200)
        session.get.return_value = response
        yield response, session


def xml_rate(value="1447", day="25.11.06"):
    return f"<chart><set label='{day}' value='{value}' /></chart>"


@pytest.mark.parametrize(
    "currency,raw,expected", [("USD", "1447", "1447"), ("JPY", "939.43", "9.3943")]
)
def test_observed_smbs_quotes_use_one_currency_unit(smbs_response, currency, raw, expected):
    # 2025-11-06 공개 XML API에서 확인한 원본 값: USD=1447, JPY(100)=939.43.
    response, session = smbs_response
    response.text = xml_rate(raw)

    result = smbs.get_exchange_rates(date(2025, 11, 6), date(2025, 11, 6), currency.lower())

    assert result == [(date(2025, 11, 6), Decimal(expected))]
    assert (
        session.get.call_args.kwargs["params"]["arr_value"] == f"{currency}_2025-11-06_2025-11-06"
    )


def test_xml_parser_accepts_attribute_order_and_double_quotes():
    xml = '<chart><set value="1,447.00" label="25.11.06"/></chart>'
    assert smbs.parse_xml_response(xml) == [(date(2025, 11, 6), Decimal("1447.00"))]


@pytest.mark.parametrize(
    "body",
    [
        "",
        "<html>maintenance</html>",
        "<chart>",
        xml_rate("oops"),
        xml_rate("NaN"),
        xml_rate("Infinity"),
        xml_rate("-1"),
        xml_rate("0"),
        xml_rate(day="25.13.01"),
        "<chart><set label='25.11.06'/></chart>",
    ],
)
def test_malformed_rate_response_is_an_error_not_a_holiday(body):
    with pytest.raises(smbs.SMBSError):
        smbs.parse_xml_response(body)


def test_empty_chart_means_no_rate():
    assert smbs.parse_xml_response("<chart></chart>") == []


def test_rate_lookup_starts_on_gift_date(smbs_response):
    response, session = smbs_response
    response.text = xml_rate()

    assert smbs.get_exchange_rate(date(2025, 11, 6)) == (Decimal(1447), date(2025, 11, 6))
    assert session.get.call_count == 1


def test_rate_lookup_skips_consecutive_holidays(smbs_response):
    _, session = smbs_response
    session.get.side_effect = [
        Mock(status_code=200, text="<chart/>"),
        Mock(status_code=200, text="<chart/>"),
        Mock(status_code=200, text=xml_rate(day="25.11.07")),
    ]

    value, actual_date = smbs.get_exchange_rate(date(2025, 11, 9))

    assert value == Decimal(1447)
    assert actual_date == date(2025, 11, 7)
    assert [call.kwargs["params"]["arr_value"] for call in session.get.call_args_list] == [
        "USD_2025-11-09_2025-11-09",
        "USD_2025-11-08_2025-11-08",
        "USD_2025-11-07_2025-11-07",
    ]


@pytest.mark.parametrize("failure", ["http", "transport", "parse", "wrong_date"])
def test_lookup_failure_does_not_fall_back_to_older_rate(smbs_response, failure):
    response, session = smbs_response
    if failure == "http":
        response.status_code = 503
    elif failure == "transport":
        session.get.side_effect = RequestException("timeout")
    elif failure == "parse":
        response.text = "<html>error</html>"
    else:
        response.text = xml_rate(day="25.11.07")

    with pytest.raises(smbs.SMBSError):
        smbs.get_exchange_rate(date(2025, 11, 6))
    assert session.get.call_count == 1


def test_search_window_is_thirty_calendar_days_including_gift_date(smbs_response):
    response, session = smbs_response
    response.text = "<chart/>"

    with pytest.raises(smbs.SMBSError):
        smbs.get_exchange_rate(date(2025, 11, 30))
    assert session.get.call_count == 30
    assert session.get.call_args.kwargs["params"]["arr_value"] == "USD_2025-11-01_2025-11-01"


def test_evidence_window_is_based_on_actual_rate_date(monkeypatch):
    monkeypatch.setattr(smbs, "get_exchange_rate", lambda *args: (Decimal(1447), date(2025, 11, 7)))
    queried = Mock(return_value=[(date(2025, 11, 7), Decimal(1447))])
    monkeypatch.setattr(smbs, "get_exchange_rates", queried)

    result = exchange_rates.load_exchange_rate_evidence(date(2025, 11, 9), "USD")

    queried.assert_called_once_with(date(2025, 11, 6), date(2025, 11, 8), "USD")
    assert result.actual_rate_date == date(2025, 11, 7)
    assert result.period_start == date(2025, 11, 6)
    assert result.period_end == date(2025, 11, 8)
    assert "StrSch_sDay=06" in result.source_url
    assert "StrSch_eDay=08" in result.source_url


@pytest.mark.parametrize("rows", [[], [(date(2025, 11, 6), Decimal(1400))]])
def test_evidence_must_contain_the_rate_used_for_calculation(monkeypatch, rows):
    monkeypatch.setattr(smbs, "get_exchange_rate", lambda *args: (Decimal(1447), date(2025, 11, 6)))
    monkeypatch.setattr(smbs, "get_exchange_rates", lambda *args: rows)
    with pytest.raises(smbs.SMBSError, match="증빙"):
        exchange_rates.load_exchange_rate_evidence(date(2025, 11, 6), "USD")


@pytest.fixture
def calculation_rates(monkeypatch):
    applied = {
        "USD": (Decimal(1300), date(2025, 11, 6)),
        "EUR": (Decimal(1500), date(2025, 11, 5)),
        "JPY": (Decimal("9.3943"), date(2025, 11, 6)),
    }
    rate = Mock(side_effect=lambda day, currency: applied[currency])
    rows = Mock(
        side_effect=lambda start, end, currency: [(applied[currency][1], applied[currency][0])]
    )
    monkeypatch.setattr(smbs, "get_exchange_rate", rate)
    monkeypatch.setattr(smbs, "get_exchange_rates", rows)
    monkeypatch.setattr(
        calculator.scraper, "get_stock_prices", lambda *args: [(date(2025, 9, 8), Decimal(200))]
    )
    return rate, rows


def mixed_input():
    return GiftCalculationInput(
        gift_date=date(2025, 11, 6),
        stocks=[
            StockInput(ticker="AAPL", qty=10, currency="USD"),
            StockInput(ticker="MSFT", qty=5, currency="USD"),
            StockInput(ticker="SAP.DE", qty=10, currency="EUR"),
        ],
    )


def test_calculation_reuses_evidence_and_deduplicates_currency(calculation_rates):
    rate, rows = calculation_rates

    result = calculator.calculate_total_gift(mixed_input())

    assert result.total_gift_amount_krw == Decimal(6900000)
    assert rate.call_count == 2
    assert rows.call_count == 2
    assert [(e.currency, e.actual_rate_date) for e in result.exchange_rate_evidence] == [
        ("USD", date(2025, 11, 6)),
        ("EUR", date(2025, 11, 5)),
    ]
    assert result.stocks[0].exchange_rate_data == result.exchange_rate_evidence[0].rates
    assert result.stocks[1].exchange_rate_data == result.exchange_rate_evidence[0].rates


def test_jpy_gift_uses_normalized_rate(calculation_rates):
    result = calculator.calculate_gift_amount(date(2025, 11, 6), "1306.T", 10, "JPY")

    assert result.exchange_rate == Decimal("9.3943")
    assert result.gift_amount_krw == Decimal(18789)



def test_endpoint_generates_both_currencies_without_refetching(
    calculation_rates, recorded_pdf, tmp_path, monkeypatch
):
    monkeypatch.setattr("backend.api.backend.STORAGE_DIR", str(tmp_path))
    rate, rows = calculation_rates

    result = TestClient(app).post("/api/calculate", json=mixed_input().model_dump(mode="json"))

    assert result.status_code == 200
    assert rate.call_count == rows.call_count == 2
    evidence = result.json()["exchange_rate_evidence"]
    assert [item["currency"] for item in evidence] == ["USD", "EUR"]
    assert len(recorded_pdf) == 2
    report = recorded_pdf[1]
    assert report.page_count == 2
    assert sum("USD/KRW 매매기준환율 증빙" == text for text in report.texts) == 1
    assert sum("EUR/KRW 매매기준환율 증빙" == text for text in report.texts) == 1
    assert "환율 적용일: 2025-11-05 (증여일 이전 고시일 대체)" in report.texts
    assert len(report.links) == 2
    for kind in ["gift", "rate"]:
        file_id = result.json()[f"{kind}_pdf_file_id"]
        assert TestClient(app).get(f"/api/download/{file_id}").content.startswith(b"%PDF-")


def test_gift_pdf_labels_actual_rate_date(calculation_rates, recorded_pdf):
    result = calculator.calculate_total_gift(mixed_input())
    gift_calculation_pdf.generate_pdf_gift_calculation(result, io.BytesIO())

    text = "\n".join(recorded_pdf[0].texts)
    assert "2025-11-06 (증여일 고시)" in text
    assert "2025-11-05 (증여일 이전 고시일 대체)" in text
    assert "증여일 직전 영업일" not in text


def test_jpy_pdf_retains_calculation_precision_and_source_unit(calculation_rates, recorded_pdf):
    result = calculator.calculate_total_gift(
        GiftCalculationInput(
            gift_date=date(2025, 11, 6),
            stocks=[StockInput(ticker="1306.T", qty=10, currency="JPY")],
        )
    )
    gift_calculation_pdf.generate_pdf_gift_calculation(result, io.BytesIO())
    exchange_rate_pdf.generate_pdf_exchange_rate_report(
        result.exchange_rate_evidence, result.gift_date, io.BytesIO()
    )

    assert "9.3943 KRW/JPY" in "\n".join(recorded_pdf[0].texts)
    text = "\n".join(recorded_pdf[1].texts)
    assert "적용 환율: 9.3943 KRW/JPY" in text
    assert "939.43 KRW/100JPY" in text
    assert "9.3943" in recorded_pdf[1].texts


def test_same_currency_distinct_rate_dates_get_separate_sections(recorded_pdf):
    evidence = [
        exchange_rates.build_exchange_rate_evidence(
            "USD", Decimal(1300), day, [PriceDataPoint(date=day.isoformat(), close="1300")]
        )
        for day in [date(2025, 11, 5), date(2025, 11, 6)]
    ]
    output = io.BytesIO()

    exchange_rate_pdf.generate_pdf_exchange_rate_report(evidence, date(2025, 11, 6), output)

    assert output.getvalue().startswith(b"%PDF-")
    assert recorded_pdf[0].page_count == 2


@pytest.mark.parametrize(
    "rate,expected", [("1300", "1,300.00"), ("9.3943", "9.3943"), ("9.3900", "9.39")]
)
def test_exchange_rate_display_matches_used_precision(rate, expected):
    assert format_exchange_rate(Decimal(rate)) == expected
