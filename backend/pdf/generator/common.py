"""PDF 생성 공통 모듈.

폰트, 레이아웃 상수, 페이지 상태 관리, LongTable 유틸을 제공한다.
exchange_rate_pdf.py 와 gift_calculation_pdf.py 에서 공통으로 사용한다.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Flowable, LongTable, TableStyle

# ---------------------------------------------------------------------------
# 폰트
# ---------------------------------------------------------------------------

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


def font(bold: bool = False) -> str:
    """사용 가능한 폰트 이름을 반환한다. 한글 폰트가 없으면 Helvetica로 폴백한다."""
    if _KOREAN_FONT_AVAILABLE:
        return _KOREAN_FONT_BOLD if bold else _KOREAN_FONT
    return _FALLBACK_FONT_BOLD if bold else _FALLBACK_FONT


# ---------------------------------------------------------------------------
# 레이아웃 / 색상 상수
# ---------------------------------------------------------------------------

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT_MARGIN = 20 * mm
RIGHT_MARGIN = 20 * mm
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
BOTTOM_MARGIN = 25 * mm

TABLE_HEADER_BG = colors.HexColor("#2C3E50")
TABLE_HEADER_FG = colors.white
TABLE_ROW_ALT_BG = colors.HexColor("#F5F5F5")
TABLE_GRID_COLOR = colors.HexColor("#CCCCCC")


# ---------------------------------------------------------------------------
# 페이지 상태 관리
# ---------------------------------------------------------------------------


class PageState:
    """페이지 상태를 추적하며 자동 페이지 넘김을 처리하는 헬퍼 클래스."""

    def __init__(self, c: canvas.Canvas) -> None:
        self.c = c
        self.y: float = PAGE_HEIGHT - 25 * mm

    def need_new_page(self, required_height: float = 10 * mm) -> bool:
        return self.y < BOTTOM_MARGIN + required_height

    def new_page(self) -> None:
        self.c.showPage()
        self.y = PAGE_HEIGHT - 25 * mm

    def ensure_space(self, required_height: float = 10 * mm) -> None:
        if self.need_new_page(required_height):
            self.new_page()

    def move(self, delta: float) -> None:
        self.y -= delta


# ---------------------------------------------------------------------------
# LongTable 유틸
# ---------------------------------------------------------------------------


def build_longtable_style(num_data_rows: int) -> TableStyle:
    """LongTable 공통 TableStyle을 생성한다.

    헤더 스타일, zebra striping, 그리드, 패딩을 포함한다.
    날짜 컬럼(0)은 LEFT, 값 컬럼(1)은 RIGHT 정렬로 설정한다.

    Args:
        num_data_rows: 헤더를 제외한 데이터 행 수 (zebra striping 계산에 사용)
    """
    total_rows = num_data_rows + 1  # 헤더 포함

    style_cmds: list = [
        # 헤더 행
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TABLE_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), font(bold=True)),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, TABLE_HEADER_BG),
        # 데이터 행 공통
        ("FONTNAME", (0, 1), (-1, -1), font()),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
        # 정렬: 날짜(0열) LEFT, 값(1열) RIGHT
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

    # 짝수 데이터 행 zebra striping (헤더 다음 행부터 2, 4, 6...)
    for i in range(2, total_rows, 2):
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ALT_BG))

    return TableStyle(style_cmds)


def draw_longtable(
    c: canvas.Canvas,
    table: LongTable,
    x: float,
    y: float,
    table_width: float,
) -> float:
    """LongTable을 페이지 분할하며 캔버스에 그린다.

    split() 루프로 현재 페이지에 맞는 만큼 출력하고, 넘치면 새 페이지를 시작한다.

    Args:
        c: ReportLab 캔버스
        table: 그릴 LongTable (wrap 이전 상태여도 무방)
        x: 테이블 왼쪽 x 좌표
        y: 테이블 상단 y 좌표 (시작 위치)
        table_width: 테이블 너비

    Returns:
        마지막으로 그린 후의 y 좌표 (테이블 하단)
    """
    table.wrap(table_width, 9999 * mm)

    remaining = table  # type: ignore[assignment]
    while remaining is not None:
        avail_height = y - BOTTOM_MARGIN

        if avail_height < 10 * mm:
            c.showPage()
            y = PAGE_HEIGHT - 25 * mm
            avail_height = y - BOTTOM_MARGIN

        parts = remaining.split(table_width, avail_height)

        if not parts:
            c.showPage()
            y = PAGE_HEIGHT - 25 * mm
            avail_height = y - BOTTOM_MARGIN
            parts = remaining.split(table_width, avail_height)
            if not parts:
                break

        part = parts[0]
        _, part_height = part.wrap(table_width, 9999 * mm)
        part.drawOn(c, x, y - part_height)
        y -= part_height

        remaining = parts[1] if len(parts) > 1 else None
        if remaining is not None:
            c.showPage()
            y = PAGE_HEIGHT - 25 * mm

    return y
