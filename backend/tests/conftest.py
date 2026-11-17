from datetime import date
from typing import override

import pytest
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph

from backend.integrations.scraper import yahoo
from backend.schemas import StockPrice
from backend.schemas.instruments import InstrumentMetadata, InstrumentPriceHistory


@pytest.fixture
def legacy_stock_price_fixtures(monkeypatch):
    """기존 주식 회귀 테스트의 (날짜, 종가) fixture를 새 메타정보 계약에 연결한다.

    명시적으로 이 fixture를 선택한 기존 모듈에만 적용한다. 실제 네트워크 호출은 막고,
    새 상품 판별·평가 테스트는 어댑터 계약 자체를 독립적으로 검증한다.
    """
    original = yahoo.get_stock_prices

    def metadata(ticker):
        currency = {"SAP.DE": "EUR", "1306.T": "JPY", "ISF.L": "GBP"}.get(ticker, "USD")
        return InstrumentMetadata(
            ticker=ticker, instrument_type="EQUITY", currency=currency,
            quote_currency=currency, exchange_timezone="America/New_York",
        )

    def history(ticker: str, start: date, end: date):
        assert yahoo.get_stock_prices is not original, "시세 fixture를 지정해야 합니다."
        return InstrumentPriceHistory(
            metadata=metadata(ticker),
            prices=[StockPrice(date=day, close=close)
                    for day, close in yahoo.get_stock_prices(ticker, start, end)],
        )

    monkeypatch.setattr(yahoo, "get_instrument_metadata", metadata)
    monkeypatch.setattr(yahoo, "get_instrument_prices", history)


@pytest.fixture
def recorded_pdf(monkeypatch):
    """실제 PDF를 생성하면서 출력 텍스트·링크·페이지 수를 함께 관찰한다."""
    instances = []
    original_draw = Paragraph.drawOn

    def paragraph_draw(paragraph, target, *args, **kwargs):
        if hasattr(target, "texts"):
            target.texts.append(paragraph.getPlainText())
        return original_draw(paragraph, target, *args, **kwargs)

    monkeypatch.setattr(Paragraph, "drawOn", paragraph_draw)
    base = canvas.Canvas

    class RecordingCanvas(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.texts = []
            self.links = []
            self.page_count = 0
            instances.append(self)

        @override
        def drawString(self, x, y, text, *args, **kwargs):
            self.texts.append(text)
            return super().drawString(x, y, text, *args, **kwargs)

        @override
        def drawRightString(self, x, y, text, *args, **kwargs):
            self.texts.append(text)
            return super().drawRightString(x, y, text, *args, **kwargs)

        @override
        def drawCentredString(self, x, y, text, *args, **kwargs):
            self.texts.append(text)
            return super().drawCentredString(x, y, text, *args, **kwargs)

        @override
        def linkURL(self, url, *args, **kwargs):
            self.links.append(url)
            return super().linkURL(url, *args, **kwargs)

        @override
        def showPage(self):
            self.page_count += 1
            return super().showPage()

    monkeypatch.setattr(canvas, "Canvas", RecordingCanvas)
    return instances

