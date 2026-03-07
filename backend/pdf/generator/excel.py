import io
from datetime import date
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Font


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
