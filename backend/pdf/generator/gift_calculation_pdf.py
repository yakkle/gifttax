"""계산 증빙자료 PDF 생성 모듈."""

import io
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import LongTable, Table, TableStyle

from backend.models import GiftCalculationResult, StockGiftResult
from backend.pdf.generator.common import (
    BOTTOM_MARGIN,
    CONTENT_WIDTH,
    LEFT_MARGIN,
    PAGE_WIDTH,
    RIGHT_MARGIN,
    TABLE_GRID_COLOR,
    TABLE_HEADER_BG,
    TABLE_HEADER_FG,
    TABLE_ROW_ALT_BG,
    PageState,
    build_longtable_style,
    draw_longtable,
    font,
)

# 컬럼 x 좌표
COL1_X = LEFT_MARGIN
COL2_X = 70 * mm
COL3_X = 130 * mm

# 링크 색상
LINK_COLOR = (0, 0, 0.8)
NORMAL_COLOR = (0, 0, 0)

# 키-값 정보 테이블 색상
INFO_KEY_BG = colors.HexColor("#EEEEEE")

# 계산식 박스 색상
FORMULA_BOX_BG = colors.HexColor("#EFF8FF")
FORMULA_BOX_BORDER = colors.HexColor("#4A90D9")


# ---------------------------------------------------------------------------
# 숫자 포매터
# ---------------------------------------------------------------------------


def _round2(value: Decimal) -> str:
    """소수 둘째 자리까지 반올림하여 문자열로 반환."""
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{rounded:,.2f}"


def _format_krw(value: Decimal) -> str:
    """원화 금액을 정수 + 천 단위 구분자 형식으로 반환."""
    return f"{int(value):,}"


# ---------------------------------------------------------------------------
# URL 빌더
# ---------------------------------------------------------------------------


def _date_to_unix(d: date) -> int:
    """date 를 UTC 기준 Unix timestamp (초) 로 변환."""
    dt = datetime(d.year, d.month, d.day, tzinfo=UTC)
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


# ---------------------------------------------------------------------------
# 드로우 헬퍼
# ---------------------------------------------------------------------------


def _draw_header(ps: PageState, gift_date: date) -> None:
    """문서 제목과 생성일 출력."""
    c = ps.c
    c.setFont(font(bold=True), 16)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN, ps.y, "해외주식 증여금액 계산 증빙자료")
    ps.move(9 * mm)

    c.setFont(font(), 10)
    today = date.today().isoformat()
    c.drawString(LEFT_MARGIN, ps.y, f"증여일: {gift_date.isoformat()}    생성일: {today}")
    ps.move(6 * mm)

    # 구분선
    c.setLineWidth(0.5)
    c.line(LEFT_MARGIN, ps.y, PAGE_WIDTH - RIGHT_MARGIN, ps.y)
    ps.move(6 * mm)


def _draw_section_title(ps: PageState, ticker: str, currency: str, idx: int, total: int) -> None:
    """종목 섹션 제목 출력."""
    ps.ensure_space(20 * mm)
    c = ps.c
    c.setFont(font(bold=True), 12)
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


def _draw_sub_heading(ps: PageState, text: str) -> None:
    """■ 소제목 출력."""
    ps.ensure_space(12 * mm)
    c = ps.c
    c.setFont(font(bold=True), 11)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN, ps.y, f"■ {text}")
    ps.move(6 * mm)


def _draw_price_table(ps: PageState, stock: StockGiftResult) -> None:
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

    table = LongTable(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(build_longtable_style(num_data_rows=len(stock.price_data)))

    ps.y = draw_longtable(c, table, x, ps.y, table_width)
    ps.move(2 * mm)


def _draw_info_table(ps: PageState, rows: list[tuple[str, str]], indent: float = 5 * mm) -> None:
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
        ("FONTNAME", (0, 0), (0, -1), font(bold=True)),
        # 값 컬럼: 흰색 배경 + 일반
        ("BACKGROUND", (1, 0), (1, -1), colors.white),
        ("FONTNAME", (1, 0), (1, -1), font()),
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


def _draw_link(ps: PageState, label: str, url: str, indent: float = 5 * mm) -> None:
    """클릭 가능한 하이퍼링크 출력."""
    ps.ensure_space(8 * mm)
    c = ps.c

    c.setFont(font(), 10)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN + indent, ps.y, label)

    c.setFont(font(), 8)
    c.setFillColorRGB(*LINK_COLOR)
    link_x = LEFT_MARGIN + indent + 38 * mm
    link_y = ps.y
    c.drawString(link_x, link_y, url)

    # 클릭 가능 영역 설정
    link_width = min(len(url) * 4.5, CONTENT_WIDTH - 38 * mm)
    c.linkURL(url, (link_x, link_y - 2, link_x + link_width, link_y + 8), relative=0)

    c.setFillColorRGB(*NORMAL_COLOR)
    ps.move(5.5 * mm)


def _draw_formula_box(ps: PageState, stock: StockGiftResult) -> None:
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

    c.setFont(font(), 10)
    c.drawCentredString(text_center_x, box_y + box_height * 0.60, line1)

    c.setFont(font(bold=True), 11)
    c.drawCentredString(text_center_x, box_y + box_height * 0.22, line2)

    ps.move(box_height + 4 * mm)


def _draw_stock_section(
    ps: PageState,
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
    info_row_h = 8 * mm  # info_table 1행 대략 높이
    price_hdr_h = 10 * mm  # 종가 테이블 헤더 + 1행 최소 높이
    ps.ensure_space(info_row_h + price_hdr_h)

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


def _draw_total_section(ps: PageState, result: GiftCalculationResult) -> None:
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
        ("FONTNAME", (0, 0), (-1, 0), font(bold=True)),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        # 데이터 행 공통
        ("FONTNAME", (0, 1), (-1, total_row_idx - 1), font()),
        ("FONTSIZE", (0, 1), (-1, total_row_idx - 1), 10),
        ("TEXTCOLOR", (0, 1), (-1, total_row_idx - 1), colors.black),
        # 짝수 데이터 행 zebra striping
        *[("BACKGROUND", (0, i), (-1, i), TABLE_ROW_ALT_BG) for i in range(2, total_row_idx, 2)],
        # 합계 행: 강조
        ("BACKGROUND", (0, total_row_idx), (-1, total_row_idx), colors.HexColor("#DFF0FF")),
        ("FONTNAME", (0, total_row_idx), (-1, total_row_idx), font(bold=True)),
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


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


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
    ps = PageState(c)

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
