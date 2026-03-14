# PDF Report Specification

해외주식 증여세 서비스에서 생성하는 두 종류의 PDF 문서 포맷 명세.

---

## 1. 계산 증빙 PDF (해외주식 증여금액 계산 증빙자료)

### 개요

- 파일명: `gift_calculation_{uuid}.pdf`
- 엔드포인트: `POST /api/generate-gift-pdf`
- 용도: 증여세 신고 시 증여금액 계산 근거를 증빙하는 문서
- 페이지 크기: A4
- 폰트: NanumGothic (한글 지원), 폴백: Helvetica

### 문서 구성

```
[문서 헤더]
  제목:   해외주식 증여금액 계산 증빙자료        (Bold 16pt)
  생성일: YYYY-MM-DD                             (10pt)

[종목 섹션 — 종목 수만큼 반복]
  섹션 제목: {TICKER} ({CURRENCY}) — {N}/{TOTAL}  (Bold 12pt, 하단 구분선)

  ■ 증여 기본 정보                               (Bold 11pt)
  ┌──────────────┬────────────────────────────┐
  │ 증여일       │ YYYY-MM-DD                 │
  │ 종목코드     │ {TICKER}                   │
  │ 수량         │ {QTY}주                    │
  └──────────────┴────────────────────────────┘

  ■ 주가 평균 계산 근거                          (Bold 11pt)
  ┌──────────────┬────────────────────────────┐
  │ 평균 산정 기간│ YYYY-MM-DD ~ YYYY-MM-DD   │
  └──────────────┴────────────────────────────┘

  [종가 데이터 테이블]
  ┌─────────────────┬─────────────────────────┐  ← 헤더: 남색 배경 + 흰색 텍스트
  │ 날짜            │ 종가 ({CURRENCY})        │
  ├─────────────────┼─────────────────────────┤
  │ YYYY-MM-DD      │                  000.00  │  ← 흰색 행
  │ YYYY-MM-DD      │                  000.00  │  ← 연회색 행 (zebra)
  │ ...             │                   ...    │
  └─────────────────┴─────────────────────────┘

  ┌──────────────┬────────────────────────────┐
  │ 데이터 건수  │ N일                        │
  │ 평균 종가    │ 000.00 {CURRENCY}          │
  └──────────────┴────────────────────────────┘
  출처: https://finance.yahoo.com/...  (클릭 가능 하이퍼링크)

  ■ 환율 정보                                    (Bold 11pt)
  ┌──────────────┬────────────────────────────┐
  │ 환율 적용일  │ YYYY-MM-DD (증여일 직전 영업일) │
  │ 매매기준환율 │ 0,000.00 KRW/{CURRENCY}    │
  └──────────────┴────────────────────────────┘
  출처: http://www.smbs.biz/...  (클릭 가능 하이퍼링크)

  ■ 증여금액 계산                                (Bold 11pt)
  ╔═══════════════════════════════════════════════╗
  ║  {평균종가} {CURRENCY} × {수량}주             ║
  ║              × {환율} KRW/{CURRENCY}          ║
  ║                      = {증여금액} 원           ║  ← Bold
  ╚═══════════════════════════════════════════════╝
  (연한 청색 배경 박스, 결과값 Bold 11pt)

[합계 섹션 — 2종목 이상인 경우만 표시]
  ■ 합계                                         (Bold 11pt)
  ┌─────────────────────────┬────────────────────┐  ← 헤더: 남색 배경 + 흰색 텍스트
  │ 종목                    │ 증여금액            │
  ├─────────────────────────┼────────────────────┤
  │ {TICKER1} ({CUR1})      │        {금액1} 원   │  ← 흰색 행
  │ {TICKER2} ({CUR2})      │        {금액2} 원   │  ← 연회색 행 (zebra)
  ├─────────────────────────┼────────────────────┤  ← 상단 강조선 (남색)
  │ 총 증여금액             │      {합계금액} 원  │  ← 연파란 배경 + Bold 11pt
  └─────────────────────────┴────────────────────┘
```

### 시각 디자인 규칙

#### 주가 데이터 테이블 (`_draw_price_table`)

| 요소 | 규칙 |
|---|---|
| 구현 방식 | `reportlab.platypus.LongTable` + `TableStyle` |
| 헤더 배경 | `#2C3E50` (남색) |
| 헤더 텍스트 | 흰색 (`colors.white`), Bold 10pt |
| 짝수 데이터 행 배경 | `#F5F5F5` (연회색) — zebra striping |
| 홀수 데이터 행 배경 | 흰색 |
| 전체 테두리 | `GRID`, 0.4pt, `#CCCCCC` |
| 헤더 하단 강조선 | `LINEBELOW`, 1.0pt, `#2C3E50` |
| 날짜 열 정렬 | LEFT |
| 종가 열 정렬 | RIGHT |
| 셀 패딩 | 상하 3pt, 좌우 6pt |
| 헤더 반복 | `repeatRows=1` (페이지 넘김 시 자동 반복) |
| 컬럼 너비 | 날짜 45%, 종가 55% (콘텐츠 영역 기준) |
| 페이지 분할 | `LongTable.split(width, avail_height)`로 페이지별 분할 출력, 전체 데이터 잘림 없음 |

#### 키-값 정보 테이블 (`_draw_info_table`)

증여 기본 정보, 주가 요약, 환율 정보 섹션에서 키-값 쌍을 2컬럼 테이블로 출력한다.

| 요소 | 규칙 |
|---|---|
| 구현 방식 | `reportlab.platypus.Table` + `TableStyle` |
| 키 컬럼 배경 | `#EEEEEE` (연회색), Bold |
| 값 컬럼 배경 | 흰색 |
| 외곽선 | `BOX`, 0.5pt, `#CCCCCC` |
| 행 구분선 | `INNERGRID`, 0.3pt, `#CCCCCC` |
| 폰트 크기 | 10pt |
| 컬럼 너비 | 키 35%, 값 65% (콘텐츠 영역 기준) |

#### 계산식 강조 박스 (`_draw_formula_box`)

| 요소 | 규칙 |
|---|---|
| 배경 | `#EFF8FF` (연한 청색) |
| 테두리 | 0.8pt, `#4A90D9` (파란색), 모서리 둥글게 (`roundRect`) |
| 계산 수식 줄 | 10pt, 가운데 정렬 |
| 결과 금액 줄 | Bold 11pt, 가운데 정렬 |
| 박스 높이 | 18mm |

#### 합계 테이블 (`_draw_total_section`)

| 요소 | 규칙 |
|---|---|
| 구현 방식 | `reportlab.platypus.Table` + `TableStyle` |
| 헤더 배경 | `#2C3E50` (남색) |
| 헤더 텍스트 | 흰색 (`colors.white`), Bold 10pt |
| 짝수 데이터 행 배경 | `#F5F5F5` (연회색) — zebra striping |
| 홀수 데이터 행 배경 | 흰색 |
| 합계 행 배경 | `#DFF0FF` (연파란색) |
| 합계 행 텍스트 | Bold 11pt |
| 합계 행 상단 강조선 | 1.0pt, `#2C3E50` (남색) |
| 전체 테두리 | `GRID`, 0.4pt, `#CCCCCC` |
| 종목 열 정렬 | LEFT |
| 금액 열 정렬 | RIGHT |
| 셀 패딩 | 상하 4pt, 좌우 6pt |
| 컬럼 너비 | 종목 55%, 금액 45% (콘텐츠 영역 기준) |

### URL 파라미터 상세

#### Yahoo Finance 히스토리 URL

```
https://finance.yahoo.com/quote/{TICKER}/history/?period1={P1}&period2={P2}
```

- `P1`: `period_start` Unix timestamp (초 단위, UTC 기준)
- `P2`: `period_end` Unix timestamp (초 단위, UTC 기준)
- `period_start` = 증여일 - 2개월 + 1일
- `period_end` = 증여일 + 2개월 - 1일

#### smbs.biz 환율 URL

```
http://www.smbs.biz/ExRate/StdExRatePop.jsp
  ?StrSch_sYear={YYYY}&StrSch_sMonth={MM}&StrSch_sDay={DD}
  &StrSch_eYear={YYYY}&StrSch_eMonth={MM}&StrSch_eDay={DD}
  &tongwha_code={CURRENCY}
```

- 기간: `actual_rate_date - 1일` ~ `actual_rate_date + 1일`
- `actual_rate_date`: 증여일 직전 실제 영업일 (smbs.biz에서 환율 데이터가 존재하는 날)

### 페이지 넘김 규칙

- 종가 데이터 테이블은 `LongTable.split(width, avail_height)`로 현재 페이지 가용 높이에 맞게 분할한다. 각 파트를 페이지별로 순서대로 출력하므로 전체 기간 데이터가 잘리지 않는다
- 페이지 분할 시 `repeatRows=1` 옵션으로 헤더 행이 각 페이지 상단에 자동 반복된다
- 평균 산정 기간 테이블과 종가 데이터 테이블은 `ensure_space()`로 두 테이블을 함께 시작할 최소 공간을 확보한 뒤 같은 페이지에 이어서 출력한다. 종가 테이블이 길어지면 이후 페이지로 자동 분할된다
- 키-값 정보 테이블과 계산식 박스는 배치 전 `ensure_space()`로 공간을 확인하고 부족하면 새 페이지에서 시작한다
- 하단 여백 기준: `BOTTOM_MARGIN = 25mm`

---

## 2. 매매기준환율 증명서 (환율증명서 PDF)

### 개요

- 파일명: `exchange_rate_{uuid}.pdf`
- 엔드포인트: `POST /api/generate-pdf`
- 용도: 매매기준환율 출처 증빙 문서
- 페이지 크기: A4
- 폰트: NanumGothic (한글 지원), 폴백: Helvetica

### 문서 구성

```
[문서 헤더]
  제목:  {CURRENCY}/KRW 환율증명서               (Bold 16pt)
  기간:  YYYY-MM-DD ~ YYYY-MM-DD                (10pt)
  ─────────────────────────────────────────────  (구분선 0.5pt)

[환율 데이터 테이블]
  ┌─────────────────────────┬─────────────────────────────────┐  ← 헤더: 남색 배경 + 흰색 텍스트
  │ 날짜                    │ 매매기준환율 (KRW/{CURRENCY})   │
  ├─────────────────────────┼─────────────────────────────────┤
  │ YYYY-MM-DD              │                       0,000.00  │  ← 흰색 행
  │ YYYY-MM-DD              │                       0,000.00  │  ← 연회색 행 (zebra)
  │ ...                     │                            ...  │
  └─────────────────────────┴─────────────────────────────────┘
```

### 시각 디자인 규칙

#### 환율 데이터 테이블 (`generate_pdf_exchange_rate`)

| 요소 | 규칙 |
|---|---|
| 구현 방식 | `reportlab.platypus.LongTable` + `TableStyle` |
| 헤더 배경 | `#2C3E50` (남색) |
| 헤더 텍스트 | 흰색 (`colors.white`), Bold 10pt |
| 짝수 데이터 행 배경 | `#F5F5F5` (연회색) — zebra striping |
| 홀수 데이터 행 배경 | 흰색 |
| 전체 테두리 | `GRID`, 0.4pt, `#CCCCCC` |
| 헤더 하단 강조선 | `LINEBELOW`, 1.0pt, `#2C3E50` |
| 날짜 열 정렬 | LEFT |
| 환율 열 정렬 | RIGHT |
| 셀 패딩 | 상하 3pt, 좌우 6pt |
| 헤더 반복 | `repeatRows=1` (페이지 넘김 시 자동 반복) |
| 컬럼 너비 | 날짜 45%, 환율 55% (콘텐츠 영역 기준) |
| 페이지 분할 | `LongTable.split(width, avail_height)`로 페이지별 분할 출력 |

### 데이터 기간

- `actual_rate_date - 1일` ~ `actual_rate_date + 1일`
- `actual_rate_date`: 증여일 직전 실제 영업일
- 데이터 출처: smbs.biz XML API (`StdExRate_xml.jsp`)

### 페이지 넘김 규칙

- 환율 데이터 테이블은 `LongTable.split(width, avail_height)`로 현재 페이지 가용 높이에 맞게 분할한다
- 페이지 분할 시 `repeatRows=1` 옵션으로 헤더 행이 각 페이지 상단에 자동 반복된다
- 하단 여백 기준: `BOTTOM_MARGIN = 25mm`

---

## 공통 규칙

### 폰트

| 용도 | 폰트 | 크기 |
|---|---|---|
| 문서 제목 | NanumGothic-Bold | 16pt |
| 섹션 제목 | NanumGothic-Bold | 12pt |
| 소제목 (■) | NanumGothic-Bold | 11pt |
| 본문 | NanumGothic | 10pt |
| 테이블 헤더 | NanumGothic-Bold | 10pt |
| 테이블 본문 | NanumGothic | 9pt (주가 테이블), 10pt (정보 테이블) |
| 계산식 결과 | NanumGothic-Bold | 11pt |
| 출처 URL | NanumGothic | 8pt (파란색) |

### 숫자 표기

| 항목 | 형식 | 예시 |
|---|---|---|
| 종가 (외화) | 소수 둘째 자리 반올림 | `195.30` |
| 평균 종가 | 소수 둘째 자리 반올림 | `200.00` |
| 환율 | 소수 둘째 자리 | `1,300.00` |
| 증여금액 | 정수 (원 단위) | `2,600,000` |

### 하이퍼링크

- 색상: RGB(0, 0, 0.8) — 파란색
- 밑줄 없음 (ReportLab 기본)
- `canvas.linkURL()` 로 클릭 영역 지정

### PDF 생성 라이브러리

| 용도 | 방식 |
|---|---|
| 페이지 드로잉 | `reportlab.pdfgen.canvas.Canvas` |
| 테이블 렌더링 | `reportlab.platypus.Table` + `TableStyle` |
| 테이블 배치 | `table.drawOn(canvas, x, y)` |
| 페이지 상태 관리 | `_PageState` 헬퍼 클래스 (계산 증빙 PDF) / y 변수 직접 추적 (환율 PDF) |
