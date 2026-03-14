import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable, Table, TableStyle

from models import GiftCalculationResult, StockGiftResult

# 폰트 경로 (이 파일 기준)
_FONTS_DIR = Path(__file__).parent.parent / "fonts"
_FONT_PATH = _FONTS_DIR / "NanumGothic.ttf"
_FONT_BOLD_PATH = _FONTS_DIR / "NanumGothic-Bold.ttf"

_KOREAN_FONT = "NanumGothic"
_KOREAN_FONT_BOLD = "NanumGothic-Bold"
_FALLBACK_FONT = "Helvetica"
_FALLBACK_FONT_BOLD = "Helvetica-Bold"

# 여백 및 레이아웃 상수
LEFT_MARGIN = 20 * mm
RIGHT_MARGIN = 20 * mm
COL1_X = LEFT_MARGIN
COL2_X = 70 * mm
COL3_X = 130 * mm
PAGE_WIDTH, PAGE_HEIGHT = A4
CONTENT_WIDTH = PAGE_WIDTH - LEFT_MARGIN - RIGHT_MARGIN
BOTTOM_MARGIN = 25 * mm

# 링크 색상 (파란색)
LINK_COLOR = (0, 0, 0.8)
NORMAL_COLOR = (0, 0, 0)

# 테이블 색상
TABLE_HEADER_BG = colors.HexColor("#2C3E50")  # 주가 테이블 헤더 배경 (남색)
TABLE_HEADER_FG = colors.white  # 주가 테이블 헤더 텍스트
TABLE_ROW_ALT_BG = colors.HexColor("#F5F5F5")  # 짝수 행 배경 (연회색)
TABLE_GRID_COLOR = colors.HexColor("#CCCCCC")  # 테두리 색상

# 키-값 정보 테이블 색상
INFO_KEY_BG = colors.HexColor("#EEEEEE")  # 키 컬럼 배경

# 계산식 박스 색상
FORMULA_BOX_BG = colors.HexColor("#EFF8FF")  # 연한 청색 배경
FORMULA_BOX_BORDER = colors.HexColor("#4A90D9")  # 테두리 색상


def _register_korean_font() -> bool:
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


def _round2(value: Decimal) -> str:
    """소수 둘째 자리까지 반올림하여 문자열로 반환."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f}"


def _format_krw(value: Decimal) -> str:
    """원화 금액을 정수 + 천 단위 구분자 형식으로 반환."""
    return f"{int(value):,}"


def _date_to_unix(d: date) -> int:
    """date 를 UTC 기준 Unix timestamp (초) 로 변환."""
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(dt.timestamp())


def _build_yahoo_url(ticker: str, period_start: date, period_end: date) -> str:
    p1 = _date_to_unix(period_start)
    p2 = _date_to_unix(period_end)
    return f"https://finance.yahoo.com/quote/{ticker}/history/?period1={p1}&period2={p2}"


def _build_smbs_url(start: date, end: date, currency: str) -> str:
    return (
        f"http://www.smbs.biz/ExRate/StdExRatePop.jsp"
        f"?StrSch_sYear={start.year}&StrSch_sMonth={start.month:02d}&StrSch_sDay={start.day:02d}"
        f"&StrSch_eYear={end.year}&StrSch_eMonth={end.month:02d}&StrSch_eDay={end.day:02d}"
        f"&tongwha_code={currency}"
    )


class _PageState:
    """페이지 상태를 추적하며 자동 페이지 넘김을 처리하는 헬퍼 클래스."""

    def __init__(self, c: canvas.Canvas) -> None:
        self.c = c
        self.y = PAGE_HEIGHT - 25 * mm

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


def _draw_header(ps: _PageState, gift_date: date) -> None:
    """문서 제목과 생성일 출력."""
    c = ps.c
    c.setFont(_font(bold=True), 16)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN, ps.y, "해외주식 증여금액 계산 증빙자료")
    ps.move(9 * mm)

    c.setFont(_font(), 10)
    today = date.today().isoformat()
    c.drawString(LEFT_MARGIN, ps.y, f"증여일: {gift_date.isoformat()}    생성일: {today}")
    ps.move(6 * mm)

    # 구분선
    c.setLineWidth(0.5)
    c.line(LEFT_MARGIN, ps.y, PAGE_WIDTH - RIGHT_MARGIN, ps.y)
    ps.move(6 * mm)


def _draw_section_title(ps: _PageState, ticker: str, currency: str, idx: int, total: int) -> None:
    """종목 섹션 제목 출력."""
    ps.ensure_space(20 * mm)
    c = ps.c
    c.setFont(_font(bold=True), 12)
    c.setFillColorRGB(*NORMAL_COLOR)
    label = f"[{ticker} ({currency})"
    if total > 1:
        label += f"  —  {idx}/{total}"
    label += "]"
    c.drawString(LEFT_MARGIN, ps.y, label)
    ps.move(5 * mm)
    c.setLineWidth(0.3)
    c.line(LEFT_MARGIN, ps.y, PAGE_WIDTH - RIGHT_MARGIN, ps.y)
    ps.move(6 * mm)


def _draw_sub_heading(ps: _PageState, text: str) -> None:
    """■ 소제목 출력."""
    ps.ensure_space(12 * mm)
    c = ps.c
    c.setFont(_font(bold=True), 11)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN, ps.y, f"■ {text}")
    ps.move(6 * mm)


def _draw_price_table(ps: _PageState, stock: StockGiftResult) -> None:
    """종가 데이터 테이블 출력 — LongTable + split()으로 페이지 분할 처리."""
    c = ps.c
    indent = 5 * mm
    table_width = CONTENT_WIDTH - indent
    x = LEFT_MARGIN + indent

    # 컬럼 너비: 날짜 45%, 종가 55%
    col_widths = [table_width * 0.45, table_width * 0.55]

    # 데이터 구성: 헤더 + 데이터 행
    header = ["날짜", f"종가 ({stock.currency})"]
    rows = [header]
    for point in stock.price_data:
        rows.append([point.date, _round2(Decimal(point.close))])

    # 스타일 기본 설정
    style_cmds = [
        # 헤더 행
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TABLE_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), _font(bold=True)),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # 데이터 행 공통
        ("FONTNAME", (0, 1), (-1, -1), _font()),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), colors.black),
        # 정렬: 날짜 LEFT, 종가 RIGHT
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        # 패딩
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # 전체 그리드 테두리
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_GRID_COLOR),
        # 헤더 하단 강조선
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, TABLE_HEADER_BG),
    ]

    # 짝수 데이터 행 zebra striping (인덱스 1부터 시작, 짝수 행 = 2, 4, 6...)
    for i in range(2, len(rows), 2):
        style_cmds.append(("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ALT_BG))

    # LongTable: split()으로 페이지 분할 지원
    table = LongTable(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle(style_cmds))

    # 전체 높이를 제한 없이 계산 (잘림 방지)
    table.wrap(table_width, 9999 * mm)

    # 현재 페이지 가용 높이로 분할 후 페이지별 출력
    # split()은 avail_height에 맞게 parts[0]을 자르므로
    # parts[0]은 언제나 현재 페이지에 바로 출력하고,
    # parts[1]이 있을 때만 새 페이지로 넘긴다.
    remaining = table
    while remaining is not None:
        avail_height = ps.y - BOTTOM_MARGIN

        # 가용 공간이 너무 적으면 새 페이지에서 시작
        if avail_height < 10 * mm:
            ps.new_page()
            avail_height = ps.y - BOTTOM_MARGIN

        parts = remaining.split(table_width, avail_height)

        # split() 결과가 없으면 새 페이지 재시도 (안전장치)
        if not parts:
            ps.new_page()
            avail_height = ps.y - BOTTOM_MARGIN
            parts = remaining.split(table_width, avail_height)
            if not parts:
                break

        part = parts[0]
        _, part_height = part.wrap(table_width, 9999 * mm)

        # parts[0]은 avail_height에 맞게 분할됐으므로 현재 페이지에 바로 출력
        part.drawOn(c, x, ps.y - part_height)
        ps.move(part_height)

        # 다음 파트가 있으면 새 페이지 후 계속
        remaining = parts[1] if len(parts) > 1 else None
        if remaining is not None:
            ps.new_page()

    ps.move(2 * mm)


def _draw_info_table(ps: _PageState, rows: list[tuple[str, str]], indent: float = 5 * mm) -> None:
    """키-값 쌍을 2컬럼 테이블 형태로 출력.

    Args:
        ps: 페이지 상태
        rows: [(키, 값), ...] 리스트
        indent: 왼쪽 들여쓰기
    """
    table_width = CONTENT_WIDTH - indent
    col_widths = [table_width * 0.35, table_width * 0.65]

    table_data = [[key, value] for key, value in rows]

    style_cmds = [
        # 키 컬럼: 연회색 배경 + Bold
        ("BACKGROUND", (0, 0), (0, -1), INFO_KEY_BG),
        ("FONTNAME", (0, 0), (0, -1), _font(bold=True)),
        # 값 컬럼: 흰색 배경 + 일반
        ("BACKGROUND", (1, 0), (1, -1), colors.white),
        ("FONTNAME", (1, 0), (1, -1), _font()),
        # 공통 폰트 크기 / 색상
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.black),
        # 정렬
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "LEFT"),
        # 패딩
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # 외곽선 + 행 구분선
        ("BOX", (0, 0), (-1, -1), 0.5, TABLE_GRID_COLOR),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, TABLE_GRID_COLOR),
    ]

    table = Table(table_data, colWidths=col_widths)
    table.setStyle(TableStyle(style_cmds))

    tbl_width, tbl_height = table.wrap(table_width, ps.y - BOTTOM_MARGIN)
    ps.ensure_space(tbl_height + 2 * mm)
    table.drawOn(ps.c, LEFT_MARGIN + indent, ps.y - tbl_height)
    ps.move(tbl_height + 3 * mm)


def _draw_link(ps: _PageState, label: str, url: str, indent: float = 5 * mm) -> None:
    """클릭 가능한 하이퍼링크 출력."""
    ps.ensure_space(8 * mm)
    c = ps.c

    c.setFont(_font(), 10)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN + indent, ps.y, label)

    c.setFont(_font(), 8)
    c.setFillColorRGB(*LINK_COLOR)
    link_x = LEFT_MARGIN + indent + 38 * mm
    link_y = ps.y
    c.drawString(link_x, link_y, url)

    # 클릭 가능 영역 설정
    link_width = min(len(url) * 4.5, CONTENT_WIDTH - 38 * mm)
    c.linkURL(url, (link_x, link_y - 2, link_x + link_width, link_y + 8), relative=0)

    c.setFillColorRGB(*NORMAL_COLOR)
    ps.move(5.5 * mm)


def _draw_formula_box(ps: _PageState, stock: StockGiftResult) -> None:
    """증여금액 계산식을 강조 박스 안에 출력."""
    avg_disp = _round2(stock.price_average)
    rate_disp = _round2(stock.exchange_rate)
    krw_disp = _format_krw(stock.gift_amount_krw)

    line1 = f"{avg_disp} {stock.currency}  ×  {stock.qty:,}주  ×  {rate_disp} KRW/{stock.currency}"
    line2 = f"= {krw_disp} 원"

    box_height = 18 * mm
    box_width = CONTENT_WIDTH - 5 * mm
    box_x = LEFT_MARGIN + 5 * mm

    ps.ensure_space(box_height + 4 * mm)
    box_y = ps.y - box_height

    c = ps.c
    # 배경 + 테두리
    c.setFillColor(FORMULA_BOX_BG)
    c.setStrokeColor(FORMULA_BOX_BORDER)
    c.setLineWidth(0.8)
    c.roundRect(box_x, box_y, box_width, box_height, 2 * mm, fill=1, stroke=1)

    # 텍스트 (중앙 정렬)
    c.setFillColorRGB(*NORMAL_COLOR)
    text_center_x = box_x + box_width / 2

    c.setFont(_font(), 10)
    c.drawCentredString(text_center_x, box_y + box_height * 0.60, line1)

    c.setFont(_font(bold=True), 11)
    c.drawCentredString(text_center_x, box_y + box_height * 0.22, line2)

    ps.move(box_height + 4 * mm)


def _draw_stock_section(
    ps: _PageState,
    stock: StockGiftResult,
    gift_date: date,
    idx: int,
    total: int,
    rate_period_start: date,
    rate_period_end: date,
) -> None:
    """종목 한 개의 섹션 전체 출력."""
    _draw_section_title(ps, stock.ticker, stock.currency, idx, total)

    # ■ 증여 기본 정보
    _draw_sub_heading(ps, "증여 기본 정보")
    _draw_info_table(
        ps,
        [
            ("증여일", gift_date.isoformat()),
            ("종목코드", stock.ticker),
            ("수량", f"{stock.qty:,}주"),
        ],
    )
    ps.move(2 * mm)

    # ■ 주가 평균 계산 근거
    _draw_sub_heading(ps, "주가 평균 계산 근거")
    period_str = f"{stock.period_start.isoformat()} ~ {stock.period_end.isoformat()}"

    # 평균 산정 기간 테이블과 종가 테이블 첫 몇 행을 같은 페이지에 이어서 배치.
    # info_table 높이 + 종가 테이블 헤더 1행 분(약 10mm)을 합산해 공간 확보 후 넘김 판단.
    INFO_ROW_H = 8 * mm  # info_table 1행 대략 높이
    PRICE_HDR_H = 10 * mm  # 종가 테이블 헤더 + 1행 최소 높이
    ps.ensure_space(INFO_ROW_H + PRICE_HDR_H)

    _draw_info_table(ps, [("평균 산정 기간", period_str)])
    ps.move(1 * mm)

    _draw_price_table(ps, stock)
    ps.move(1 * mm)

    _draw_info_table(
        ps,
        [
            ("데이터 건수", f"{len(stock.price_data)}일"),
            ("평균 종가", f"{_round2(stock.price_average)} {stock.currency}"),
        ],
    )

    yahoo_url = _build_yahoo_url(stock.ticker, stock.period_start, stock.period_end)
    _draw_link(ps, "데이터 출처", yahoo_url)
    ps.move(2 * mm)

    # ■ 환율 정보
    _draw_sub_heading(ps, "환율 정보")
    rate_date_str = f"{stock.exchange_rate_date.isoformat()} (증여일 직전 영업일)"
    rate_str = f"{_round2(stock.exchange_rate)} KRW/{stock.currency}"
    _draw_info_table(
        ps,
        [
            ("환율 적용일", rate_date_str),
            ("매매기준환율", rate_str),
        ],
    )

    smbs_url = _build_smbs_url(rate_period_start, rate_period_end, stock.currency)
    _draw_link(ps, "데이터 출처", smbs_url)
    ps.move(2 * mm)

    # ■ 증여금액 계산
    _draw_sub_heading(ps, "증여금액 계산")
    _draw_formula_box(ps, stock)


def _draw_total_section(ps: _PageState, result: GiftCalculationResult) -> None:
    """합계 섹션 출력 (2종목 이상인 경우만) — Platypus Table 사용."""
    indent = 5 * mm
    table_width = CONTENT_WIDTH - indent

    # 구분선
    ps.ensure_space(10 * mm)
    c = ps.c
    c.setLineWidth(0.5)
    c.line(LEFT_MARGIN, ps.y, PAGE_WIDTH - RIGHT_MARGIN, ps.y)
    ps.move(6 * mm)

    _draw_sub_heading(ps, "합계")

    # 종목별 소계 행 + 합계 행
    col_widths = [table_width * 0.55, table_width * 0.45]

    header = ["종목", "증여금액"]
    rows = [header]
    for stock in result.stocks:
        rows.append(
            [
                f"{stock.ticker} ({stock.currency})",
                f"{_format_krw(stock.gift_amount_krw)} 원",
            ]
        )
    # 합계 행
    rows.append(["총 증여금액", f"{_format_krw(result.total_gift_amount_krw)} 원"])

    total_row_idx = len(rows) - 1

    style_cmds = [
        # 헤더 행
        ("BACKGROUND", (0, 0), (-1, 0), TABLE_HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), TABLE_HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), _font(bold=True)),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # 데이터 행 공통
        ("FONTNAME", (0, 1), (-1, total_row_idx - 1), _font()),
        ("FONTSIZE", (0, 1), (-1, total_row_idx - 1), 10),
        ("TEXTCOLOR", (0, 1), (-1, total_row_idx - 1), colors.black),
        # 짝수 데이터 행 zebra striping
        *[("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ALT_BG) for i in range(2, total_row_idx, 2)],
        # 합계 행: 강조
        ("BACKGROUND", (0, total_row_idx), (-1, total_row_idx), colors.HexColor("#DFF0FF")),
        ("FONTNAME", (0, total_row_idx), (-1, total_row_idx), _font(bold=True)),
        ("FONTSIZE", (0, total_row_idx), (-1, total_row_idx), 11),
        ("TEXTCOLOR", (0, total_row_idx), (-1, total_row_idx), colors.black),
        ("LINEABOVE", (0, total_row_idx), (-1, total_row_idx), 1.0, TABLE_HEADER_BG),
        # 정렬: 종목 LEFT, 금액 RIGHT
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        # 패딩
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # 전체 그리드 테두리
        ("GRID", (0, 0), (-1, -1), 0.4, TABLE_GRID_COLOR),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, TABLE_HEADER_BG),
    ]

    table = Table(rows, colWidths=col_widths)
    table.setStyle(TableStyle(style_cmds))

    tbl_width, tbl_height = table.wrap(table_width, ps.y - BOTTOM_MARGIN)
    ps.ensure_space(tbl_height + 2 * mm)
    table.drawOn(c, LEFT_MARGIN + indent, ps.y - tbl_height)
    ps.move(tbl_height + 4 * mm)


def generate_pdf_gift_calculation(
    result: GiftCalculationResult,
    output: io.BytesIO,
) -> None:
    """계산 증빙 PDF를 생성하여 output 버퍼에 쓴다.

    Args:
        result: 증여금액 계산 결과
        output: 쓸 BytesIO 버퍼
    """
    c = canvas.Canvas(output, pagesize=A4)
    ps = _PageState(c)

    _draw_header(ps, result.gift_date)

    total = len(result.stocks)
    for idx, stock in enumerate(result.stocks, start=1):
        # 환율 출처 기간: actual_rate_date ±1일
        rate_period_start = stock.exchange_rate_date - timedelta(days=1)
        rate_period_end = stock.exchange_rate_date + timedelta(days=1)

        _draw_stock_section(
            ps,
            stock,
            result.gift_date,
            idx,
            total,
            rate_period_start,
            rate_period_end,
        )

        # 종목 간 구분 여백 (마지막 종목 제외)
        if idx < total:
            ps.move(4 * mm)

    if total > 1:
        _draw_total_section(ps, result)

    c.save()
