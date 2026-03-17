"""환율증명서 PDF 생성 모듈."""

import io
from datetime import date
from decimal import Decimal

from pdf.generator.common import (
    CONTENT_WIDTH,
    LEFT_MARGIN,
    PAGE_HEIGHT,
    PAGE_WIDTH,
    RIGHT_MARGIN,
    build_longtable_style,
    draw_longtable,
    font,
)
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable


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
        rows.append([rate_date.isoformat(), f"{rate_value:.2f}"])

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
