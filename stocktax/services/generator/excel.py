import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


def generate_excel_stock_prices(
    ticker: str,
    prices: list[tuple[date, Decimal]],
    output: io.BytesIO,
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "주가데이터"

    headers = ["날짜", "종가"]
    ws.append(headers)

    header_font = Font(bold=True)
    for cell in ws[1]:
        cell.font = header_font

    for price_date, price_value in prices:
        ws.append([price_date.isoformat(), float(price_value)])

    ws.append([])
    ws.append(["평균", f"=AVERAGE(B2:B{len(prices) + 1})"])

    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except Exception:
                pass
        adjusted_width = min(max_length + 2, 20)
        ws.column_dimensions[column_letter].width = adjusted_width

    wb.save(output)


def generate_pdf_exchange_rate(
    rates: list[tuple[date, Decimal]],
    currency: str,
    output: io.BytesIO,
) -> None:
    c = canvas.Canvas(output, pagesize=A4)
    width, height = A4

    y = height - 40 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40 * mm, y, f"{currency}/KRW 환율증")

    y -= 15 * mm

    c.setFont("Helvetica", 10)
    c.drawString(40 * mm, y, f"기간: {rates[0][0].isoformat()} ~ {rates[-1][0].isoformat()}")

    y -= 10 * mm

    headers = ["날짜", "매매기준환율"]
    x_positions = [40 * mm, 90 * mm]

    c.setFont("Helvetica-Bold", 10)
    for i, header in enumerate(headers):
        c.drawString(x_positions[i], y, header)

    y -= 5 * mm

    c.setFont("Helvetica", 9)
    for rate_date, rate_value in rates:
        if y < 30 * mm:
            c.showPage()
            y = height - 40 * mm

        c.drawString(40 * mm, y, rate_date.isoformat())
        c.drawString(90 * mm, y, f"{rate_value:.2f}")
        y -= 6 * mm

    c.save()
