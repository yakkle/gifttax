import io
from datetime import date
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


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

    y -= 8 * mm

    c.setFont("Helvetica", 9)
    for rate_date, rate_value in rates:
        if y < 30 * mm:
            c.showPage()
            y = height - 40 * mm

        c.drawString(40 * mm, y, rate_date.isoformat())
        c.drawString(90 * mm, y, f"{rate_value:.2f}")
        y -= 6 * mm

    c.save()
