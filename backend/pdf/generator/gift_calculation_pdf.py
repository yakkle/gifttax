import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

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

# 테이블 열 위치
TABLE_DATE_X = LEFT_MARGIN
TABLE_PRICE_X = LEFT_MARGIN + 55 * mm

# 링크 색상 (파란색)
LINK_COLOR = (0, 0, 0.8)
NORMAL_COLOR = (0, 0, 0)


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


def _draw_key_value(ps: _PageState, key: str, value: str, indent: float = 5 * mm) -> None:
    """들여쓰기된 키-값 행 출력."""
    ps.ensure_space(6 * mm)
    c = ps.c
    c.setFont(_font(), 10)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN + indent, ps.y, key)
    c.drawString(LEFT_MARGIN + indent + 38 * mm, ps.y, value)
    ps.move(5.5 * mm)


def _draw_price_table(ps: _PageState, stock: StockGiftResult) -> None:
    """종가 데이터 테이블 출력 (소수 둘째 자리 반올림)."""
    c = ps.c
    indent = 5 * mm

    # 테이블 헤더
    ps.ensure_space(10 * mm)
    c.setFont(_font(bold=True), 10)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(TABLE_DATE_X + indent, ps.y, "날짜")
    c.drawString(TABLE_PRICE_X + indent, ps.y, f"종가 ({stock.currency})")
    ps.move(5 * mm)

    c.setLineWidth(0.3)
    c.line(LEFT_MARGIN + indent, ps.y + 1 * mm, TABLE_PRICE_X + indent + 30 * mm, ps.y + 1 * mm)
    ps.move(1 * mm)

    # 데이터 행
    c.setFont(_font(), 9)
    for point in stock.price_data:
        if ps.need_new_page(6 * mm):
            ps.new_page()
            # 새 페이지에서 헤더 재출력
            c.setFont(_font(bold=True), 10)
            c.setFillColorRGB(*NORMAL_COLOR)
            c.drawString(TABLE_DATE_X + indent, ps.y, "날짜")
            c.drawString(TABLE_PRICE_X + indent, ps.y, f"종가 ({stock.currency})")
            ps.move(5 * mm)
            c.setLineWidth(0.3)
            c.line(
                LEFT_MARGIN + indent, ps.y + 1 * mm, TABLE_PRICE_X + indent + 30 * mm, ps.y + 1 * mm
            )
            ps.move(1 * mm)
            c.setFont(_font(), 9)

        c.setFillColorRGB(*NORMAL_COLOR)
        c.drawString(TABLE_DATE_X + indent, ps.y, point.date)
        price_str = _round2(Decimal(point.close))
        c.drawString(TABLE_PRICE_X + indent, ps.y, price_str)
        ps.move(5 * mm)


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
    _draw_key_value(ps, "증여일", gift_date.isoformat())
    _draw_key_value(ps, "종목코드", stock.ticker)
    _draw_key_value(ps, "수량", f"{stock.qty:,}주")
    ps.move(2 * mm)

    # ■ 주가 평균 계산 근거
    _draw_sub_heading(ps, "주가 평균 계산 근거")
    period_str = f"{stock.period_start.isoformat()} ~ {stock.period_end.isoformat()}"
    _draw_key_value(ps, "평균 산정 기간", period_str)
    ps.move(1 * mm)

    _draw_price_table(ps, stock)
    ps.move(1 * mm)

    _draw_key_value(ps, "데이터 건수", f"{len(stock.price_data)}일")
    avg_str = f"{_round2(stock.price_average)} {stock.currency}"
    _draw_key_value(ps, "평균 종가", avg_str)

    yahoo_url = _build_yahoo_url(stock.ticker, stock.period_start, stock.period_end)
    _draw_link(ps, "데이터 출처", yahoo_url)
    ps.move(2 * mm)

    # ■ 환율 정보
    _draw_sub_heading(ps, "환율 정보")
    rate_date_str = f"{stock.exchange_rate_date.isoformat()} (증여일 직전 영업일)"
    _draw_key_value(ps, "환율 적용일", rate_date_str)
    rate_str = f"{_round2(stock.exchange_rate)} KRW/{stock.currency}"
    _draw_key_value(ps, "매매기준환율", rate_str)

    smbs_url = _build_smbs_url(rate_period_start, rate_period_end, stock.currency)
    _draw_link(ps, "데이터 출처", smbs_url)
    ps.move(2 * mm)

    # ■ 증여금액 계산
    _draw_sub_heading(ps, "증여금액 계산")
    ps.ensure_space(8 * mm)
    avg_disp = _round2(stock.price_average)
    rate_disp = _round2(stock.exchange_rate)
    krw_disp = _format_krw(stock.gift_amount_krw)
    formula = (
        f"{avg_disp} {stock.currency}  ×  {stock.qty:,}주  ×  {rate_disp} KRW/{stock.currency}"
        f"  =  {krw_disp} 원"
    )
    c = ps.c
    c.setFont(_font(), 10)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN + 5 * mm, ps.y, formula)
    ps.move(8 * mm)


def _draw_total_section(ps: _PageState, result: GiftCalculationResult) -> None:
    """합계 섹션 출력 (2종목 이상인 경우만)."""
    ps.ensure_space(30 * mm)
    c = ps.c

    # 구분선
    c.setLineWidth(0.5)
    c.line(LEFT_MARGIN, ps.y, PAGE_WIDTH - RIGHT_MARGIN, ps.y)
    ps.move(6 * mm)

    c.setFont(_font(bold=True), 12)
    c.setFillColorRGB(*NORMAL_COLOR)
    c.drawString(LEFT_MARGIN, ps.y, "■ 합계")
    ps.move(7 * mm)

    # 종목별 소계 표
    c.setFont(_font(bold=True), 10)
    c.drawString(LEFT_MARGIN + 5 * mm, ps.y, "종목")
    c.drawString(LEFT_MARGIN + 60 * mm, ps.y, "증여금액")
    ps.move(5 * mm)

    c.setLineWidth(0.3)
    c.line(LEFT_MARGIN + 5 * mm, ps.y + 1 * mm, LEFT_MARGIN + 110 * mm, ps.y + 1 * mm)
    ps.move(1 * mm)

    c.setFont(_font(), 10)
    for stock in result.stocks:
        ps.ensure_space(6 * mm)
        c.drawString(LEFT_MARGIN + 5 * mm, ps.y, f"{stock.ticker} ({stock.currency})")
        c.drawString(LEFT_MARGIN + 60 * mm, ps.y, f"{_format_krw(stock.gift_amount_krw)} 원")
        ps.move(5.5 * mm)

    ps.move(2 * mm)

    # 총합계
    ps.ensure_space(8 * mm)
    c.setFont(_font(bold=True), 11)
    c.drawString(LEFT_MARGIN + 5 * mm, ps.y, "총 증여금액")
    c.drawString(LEFT_MARGIN + 60 * mm, ps.y, f"{_format_krw(result.total_gift_amount_krw)} 원")
    ps.move(6 * mm)


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
