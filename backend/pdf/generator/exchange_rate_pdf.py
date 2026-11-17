"""환율증명서 PDF 생성 모듈."""

import io
from datetime import date
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable

from backend.pdf.generator.common import (
    CONTENT_WIDTH,
    LEFT_MARGIN,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    RIGHT_MARGIN,
    build_longtable_style,
    draw_longtable,
    font,
    format_exchange_rate,
)
from backend.schemas import ExchangeRateEvidence


def generate_pdf_exchange_rate(
    rates: list[tuple[date, Decimal]],
    currency: str,
    output: io.BytesIO,
) -> None:
    """환율 증명서 PDF를 생성하여 output 버퍼에 쓴다.

    Args:
        rates: [(날짜, 환율), ...] 리스트 (오름차순 정렬)
        currency: 통화 코드 (예: "USD")
        output: 쓸 BytesIO 버퍼
    """
    c = canvas.Canvas(output, pagesize=A4)

    # 테이블 컬럼 너비: 날짜 45%, 환율 55%
    col_widths = [CONTENT_WIDTH * 0.45, CONTENT_WIDTH * 0.55]

    # 헤더 + 데이터 행 구성
    header_row = ["날짜", f"매매기준환율 (KRW/{currency})"]
    rows = [header_row]
    for rate_date, rate_value in rates:
        rows.append([rate_date.isoformat(), format_exchange_rate(rate_value)])

    table = LongTable(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(build_longtable_style(num_data_rows=len(rates)))

    # 첫 페이지: 제목 + 부제목 출력 후 테이블 시작 y 결정
    y = PAGE_HEIGHT - 25 * mm

    c.setFont(font(bold=True), 16)
    c.drawString(LEFT_MARGIN, y, f"{currency}/KRW 환율증명서")
    y -= 9 * mm

    period_text = f"기간: {rates[0][0].isoformat()} ~ {rates[-1][0].isoformat()}"
    c.setFont(font(), 10)
    c.drawString(LEFT_MARGIN, y, period_text)
    y -= 6 * mm

    # 구분선
    c.setLineWidth(0.5)
    c.line(LEFT_MARGIN, y, PAGE_WIDTH - RIGHT_MARGIN, y)
    y -= 6 * mm

    draw_longtable(c, table, LEFT_MARGIN, y, CONTENT_WIDTH)

    c.save()


def generate_pdf_exchange_rate_report(
    evidence: list[ExchangeRateEvidence], gift_date: date, output: io.BytesIO
) -> None:
    """통화·고시일별로 계산과 동일한 환율 증빙을 한 PDF에 출력한다."""
    if not evidence or any(not item.rates for item in evidence):
        raise ValueError("출력할 환율 증빙 데이터가 없습니다.")
    c = canvas.Canvas(output, pagesize=A4)
    for index, item in enumerate(evidence):
        if index:
            c.showPage()
        y = PAGE_HEIGHT - 25 * mm
        c.setFont(font(bold=True), 16)
        c.drawString(LEFT_MARGIN, y, f"{item.currency}/KRW 매매기준환율 증빙")
        y -= 10 * mm
        basis = "증여일 고시" if item.actual_rate_date == gift_date else "증여일 이전 고시일 대체"
        lines = [
            f"증여일: {gift_date.isoformat()}",
            f"환율 적용일: {item.actual_rate_date.isoformat()} ({basis})",
            f"적용 환율: {format_exchange_rate(item.rate)} KRW/{item.currency}",
            f"조회 기간: {item.period_start.isoformat()} ~ {item.period_end.isoformat()}",
        ]
        if item.source_unit != 1:
            lines.append(
                f"원본 고시: {format_exchange_rate(item.rate * item.source_unit)} KRW/"
                f"{item.source_unit}{item.currency} (계산·표는 1{item.currency} 기준)"
            )
        c.setFont(font(), 10)
        for line in lines:
            c.drawString(LEFT_MARGIN, y, line)
            y -= 6 * mm
        source_label = "데이터 출처: 서울외국환중개 기간별 매매기준율 (원문 조회)"
        c.setFont(font(), 9)
        c.setFillColorRGB(0, 0, 0.8)
        c.drawString(LEFT_MARGIN, y, source_label)
        width = c.stringWidth(source_label, font(), 9)
        c.linkURL(item.source_url, (LEFT_MARGIN, y - 2, LEFT_MARGIN + width, y + 9))
        c.setFillColorRGB(0, 0, 0)
        y -= 8 * mm
        rows = [["날짜", f"매매기준환율 (KRW/{item.currency})"]]
        rows.extend([[point.date, format_exchange_rate(Decimal(point.close))] for point in item.rates])
        table = LongTable(rows, colWidths=[CONTENT_WIDTH * 0.45, CONTENT_WIDTH * 0.55], repeatRows=1)
        style = build_longtable_style(len(item.rates))
        for row, point in enumerate(item.rates, start=1):
            if point.date == item.actual_rate_date.isoformat():
                style.add("BACKGROUND", (0, row), (-1, row), "#DFF0FF")
                style.add("FONTNAME", (0, row), (-1, row), font(bold=True))
        table.setStyle(style)
        draw_longtable(c, table, LEFT_MARGIN, y, CONTENT_WIDTH)
    c.save()
