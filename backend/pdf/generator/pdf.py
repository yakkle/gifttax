import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

# 이 파일 기준으로 폰트 경로 계산 (로컬/Docker 공통)
_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_PATH = _FONTS_DIR / "NanumGothic.ttf"
_FONT_BOLD_PATH = _FONTS_DIR / "NanumGothic-Bold.ttf"

_KOREAN_FONT = "NanumGothic"
_KOREAN_FONT_BOLD = "NanumGothic-Bold"
_FALLBACK_FONT = "Helvetica"
_FALLBACK_FONT_BOLD = "Helvetica-Bold"


def _register_korean_font() -> bool:
    """한글 폰트를 ReportLab에 등록한다.

    폰트 파일이 없으면 False를 반환하고 Helvetica로 폴백한다.
    """
    if not _FONT_PATH.exists():
        return False
    try:
        pdfmetrics.registerFont(TTFont(_KOREAN_FONT, str(_FONT_PATH)))
        bold_path = _FONT_BOLD_PATH if _FONT_BOLD_PATH.exists() else _FONT_PATH
        pdfmetrics.registerFont(TTFont(_KOREAN_FONT_BOLD, str(bold_path)))
        return True
    except Exception:
        return False


_KOREAN_FONT_AVAILABLE = _register_korean_font()


def _font(bold: bool = False) -> str:
    if _KOREAN_FONT_AVAILABLE:
        return _KOREAN_FONT_BOLD if bold else _KOREAN_FONT
    return _FALLBACK_FONT_BOLD if bold else _FALLBACK_FONT


def generate_pdf_exchange_rate(
    rates: list[tuple[date, Decimal]],
    currency: str,
    output: io.BytesIO,
) -> None:
    c = canvas.Canvas(output, pagesize=A4)
    width, height = A4

    y = height - 40 * mm

    c.setFont(_font(bold=True), 16)
    c.drawString(40 * mm, y, f"{currency}/KRW 환율증명서")

    y -= 15 * mm

    c.setFont(_font(), 10)
    c.drawString(40 * mm, y, f"기간: {rates[0][0].isoformat()} ~ {rates[-1][0].isoformat()}")

    y -= 10 * mm

    headers = ["날짜", "매매기준환율"]
    x_positions = [40 * mm, 90 * mm]

    c.setFont(_font(bold=True), 10)
    for i, header in enumerate(headers):
        c.drawString(x_positions[i], y, header)

    y -= 8 * mm

    c.setFont(_font(), 9)
    for rate_date, rate_value in rates:
        if y < 30 * mm:
            c.showPage()
            y = height - 40 * mm

        c.drawString(40 * mm, y, rate_date.isoformat())
        c.drawString(90 * mm, y, f"{rate_value:.2f}")
        y -= 6 * mm

    c.save()
