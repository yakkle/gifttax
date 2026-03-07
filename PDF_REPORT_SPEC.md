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
    증여일:    YYYY-MM-DD
    종목코드:  {TICKER}
    수량:      {QTY}주

  ■ 주가 평균 계산 근거                          (Bold 11pt)
    평균 산정 기간: YYYY-MM-DD ~ YYYY-MM-DD
    [종가 데이터 표]
      날짜          | 종가 ({CURRENCY})
      YYYY-MM-DD   | 000.00           ← 소수 둘째 자리 반올림
      ...
    데이터 건수: N일
    평균 종가:  000.00 {CURRENCY}
    출처: https://finance.yahoo.com/quote/{TICKER}/history/?period1={P1}&period2={P2}
          (클릭 가능 하이퍼링크, 증여일 기준 전후 2개월 기간)

  ■ 환율 정보                                    (Bold 11pt)
    환율 적용일:  YYYY-MM-DD (증여일 직전 영업일)
    매매기준환율: 0,000.00 KRW/{CURRENCY}
    출처: http://www.smbs.biz/ExRate/StdExRatePop.jsp?...
          (클릭 가능 하이퍼링크, actual_rate_date 전후 1일 기간)

  ■ 증여금액 계산                                (Bold 11pt)
    {평균종가} × {수량}주 × {환율} = {증여금액} 원
    (소수점 이하 반올림, 원 단위)

[합계 섹션 — 2종목 이상인 경우만 표시]
  ■ 합계                                         (Bold 12pt)
    종목           | 증여금액
    {TICKER1}     | {금액1} 원
    {TICKER2}     | {금액2} 원
    총 증여금액:  {합계} 원
```

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

- 종가 데이터 테이블 행이 많아 하단 여백(30mm 미만)에 도달하면 자동으로 다음 페이지 시작
- 새 페이지 시작 시 섹션 제목 없이 테이블 이어서 출력

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

[환율 데이터 표]
  날짜          | 매매기준환율
  YYYY-MM-DD   | 0,000.00
  ...
```

### 데이터 기간

- `actual_rate_date - 1일` ~ `actual_rate_date + 1일`
- `actual_rate_date`: 증여일 직전 실제 영업일
- 데이터 출처: smbs.biz XML API (`StdExRate_xml.jsp`)

### 페이지 넘김 규칙

- 하단 여백 30mm 미만 도달 시 자동 페이지 넘김
- 새 페이지에서 열 헤더 없이 데이터 이어서 출력

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
| 테이블 본문 | NanumGothic | 9pt |
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
