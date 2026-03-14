import io
from datetime import date
from decimal import Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable, TableStyle

# 이 파일 기준으로 폰트 경로 계산 (로컬/Docker 공통)
_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_PATH = _FONTS_DIR / "NanumGothic.ttf"
_FONT_BOLD_PATH = _FONTS_DIR / "NanumGothic-Bold.ttf"

_KOREAN_FONT = "NanumGothic"
_KOREAN_FONT_BOLD = "NanumGothic-Bold"
_FALLBACK_FONT = "Helvetica"
_FALLBACK_FONT_BOLD = "Helvetica-Bold"

# 레이아웃 상수
PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 20 * mm
RIGHT_MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
BOTTOM_MARGIN = 25 * mm

# 테이블 색상
TABLE_HEADER_BG = colors.HexColor("#2C3E50")
TABLE_HEADER_FG = colors.white
TABLE_ROW_ALT_BG = colors.HexColor("#F5F5F5")
TABLE_GRID_COLOR = colors.HexColor("#CCCCCC")


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

    # 스타일
    style_cmds = [
        # 헤더 행
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TABLE_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), _font(bold=True)),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, TABLE_HEADER_BG),
        # 데이터 행 공통
        ("FONTNAME", (0, 1), (-1, -1), _font()),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
        # 정렬: 날짜 LEFT, 환율 RIGHT
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        # 패딩
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # 전체 그리드 테두리
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_GRID_COLOR),
    ]

    # 짝수 데이터 행 zebra striping (인덱스 2, 4, 6…)
    for i in range(2, len(rows), 2):
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ALT_BG))

    table = LongTable(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(style_cmds))

    # 전체 높이를 제한 없이 계산
    table.wrap(CONTENT_WIDTH, 9999 * mm)

    # 첫 페이지: 제목 + 부제목 출력 후 테이블 시작 y 결정
    y = PAGE_HEIGHT - 25 * mm

    c.setFont(_font(bold=True), 16)
    c.drawString(LEFT_MARGIN, y, f"{currency}/KRW 환율증명서")
    y -= 9 * mm

    period_text = f"기간: {rates[0][0].isoformat()} ~ {rates[-1][0].isoformat()}"
    c.setFont(_font(), 10)
    c.drawString(LEFT_MARGIN, y, period_text)
    y -= 6 * mm

    # 구분선
    c.setLineWidth(0.5)
    c.line(LEFT_MARGIN, y, PAGE_WIDTH - RIGHT_MARGIN, y)
    y -= 6 * mm

    # LongTable.split() 루프로 페이지 분할 출력
    remaining = table
    while remaining is not None:
        avail_height = y - BOTTOM_MARGIN

        if avail_height < 10 * mm:
            c.showPage()
            y = PAGE_HEIGHT - 25 * mm
            avail_height = y - BOTTOM_MARGIN

        parts = remaining.split(CONTENT_WIDTH, avail_height)

        if not parts:
            c.showPage()
            y = PAGE_HEIGHT - 25 * mm
            avail_height = y - BOTTOM_MARGIN
            parts = remaining.split(CONTENT_WIDTH, avail_height)
            if not parts:
                break

        part = parts[0]
        _, part_height = part.wrap(CONTENT_WIDTH, 9999 * mm)
        part.drawOn(c, LEFT_MARGIN, y - part_height)
        y -= part_height

        remaining = parts[1] if len(parts) > 1 else None
        if remaining is not None:
            c.showPage()
            y = PAGE_HEIGHT - 25 * mm

    c.save()
