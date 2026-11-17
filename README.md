# GiftTax - 해외주식·ETF 증여 금액 계산기

해외 상장 주식과 ETF의 증여금액을 원화로 계산하고 평가 근거를 PDF로 만드는 도구입니다.

## 기능

- **상품 유형 확인**: 티커로 주식·ETF와 시세 통화를 자동 판별합니다. 유형 정보가 없거나 조회에 실패하면 직접 선택할 수 있습니다. 확인된 미지원 상품과 잘못된 티커는 계산하지 않습니다.
- **주식 평가**: 증여일 전 2개월 + 1일부터 후 2개월 - 1일까지의 종가 평균을 사용하며, 증여일 후 2개월부터 계산합니다.
- **ETF 평가**: 증여일 전일부터 과거 30개 달력일 안의 최근 거래일 종가를 사용합니다. 증여일 당일·이후 가격과 수정종가는 제외하며 후 2개월 대기는 적용하지 않습니다.
- **통화·단위 처리**: 화면에서 USD·EUR·JPY·GBP를 선택할 수 있습니다. Yahoo의 GBp·GBX 펜스 시세는 100으로 나누어 GBP로 계산합니다. 확인된 시세 통화와 입력 통화가 다르면 수정해야 합니다.
- **환율 조회**: 서울외국환중개(smbs.biz)의 증여일 당일 고시 환율을 먼저 조회하고, 데이터가 없을 때만 이전 고시일을 찾습니다. 내부 환율은 외화 1단위당 KRW이며 JPY 원본 고시값(KRW/100JPY)은 100으로 나눕니다.
- **두 종류의 PDF**: 주식 평균 산정 또는 ETF 적용 종가를 담은 계산 증빙 PDF와, 사용한 모든 통화·실제 고시일의 환율 증빙 PDF를 다운로드합니다. 계산과 PDF는 동일한 데이터를 사용합니다.

두 PDF는 법정 증여세 신고서 작성을 보조하는 **평가 증빙자료**입니다. 법정 신고서나 서울외국환중개가 발급한 공식 증명서를 대신하지 않습니다. 현재 `estimated_tax`는 증여세 엔진이 미구현인 상태의 `0`이므로 실제 세액을 의미하지 않습니다.

계산 방식은 [계산 명세](docs/CALCULATION_SPEC.md), 증여세 엔진의 구현 범위는 [증여세 엔진 안내](TAX_ENGINE.md), PDF 구성은 [PDF 명세](PDF_REPORT_SPEC.md), 커밋별 진행 상태는 [ETF 작업 계획](docs/ETF_IMPLEMENTATION_PLAN.md)을 참고하세요.

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI + Python 3.13 |
| DB | SQLite + SQLAlchemy ORM + Alembic |
| Frontend | Vanilla JS + HTML/CSS |
| PDF | reportlab |
| Scraping | requests + BeautifulSoup |
| Deploy | Docker + OCI |

## 시작하기

### 필수 조건

- Python 3.13+
- Docker (optional)

### 로컬 실행

```bash
# 설치
uv pip install .

# 실행
uvicorn backend.main:app --reload

# 브라우저에서 열기
open http://localhost:8000
```

### Docker로 실행

```bash
# 빌드 & 실행
docker-compose up -d

# 브라우저에서 열기
open http://localhost:8000

# 로그 확인
docker-compose logs -f
```

### 테스트 실행

```bash
# 개발 의존성 설치
uv pip install -e '.[dev]'

# 테스트
uv run --no-sync pytest backend/tests/ -v

# 프런트엔드 테스트 (Node.js 20 이상, CI는 24)
node --test frontend/tests/*.test.js

# 린트
ruff check .

# 타입 체크
mypy backend/
```

## API 사용법

관리자 로그인·패스키 등록·JWT 대체 모드·인증 복구는
[관리자 인증 운영 안내](docs/ADMIN_AUTH.md)를 참고한다.
후기·관리자 기능용 저장소 설정 및 백업·보관 정책은
[운영 문서](docs/FEEDBACK_OPERATIONS.md)를 참고하세요.
배포 전 설정, 배포 후 확인과 실제 기기 검증 항목은
[배포 점검표](docs/RELEASE_CHECKLIST.md)를 참고하세요.
비공개 의견 제출(`POST /api/feedback`), 익명 이벤트 수집(`POST /api/events`),
관리자 이용 통계(`GET /api/admin/usage?days=30`, 7·30·90일)를 제공합니다.
상단의 **의견 남기기** 또는 계산 결과 아래에서 비공개 후기를 작성할 수 있습니다.
만족도나 의견 중 하나만 입력해도 제출할 수 있으며, 만족한 후기 접수 후에는 후원 링크를 안내합니다.
`/admin`에 로그인하면 이용 통계와 비공개 의견을 조회할 수 있습니다.
날짜·분류·만족도·처리 상태 필터, 상태 변경·삭제, 답변용 이메일 복사를 제공합니다.

### 종목 유형 조회

```bash
curl http://localhost:8000/api/instruments/QQQ
```

응답 예시(메타정보 값은 조회 시점에 따라 달라질 수 있음):

```json
{
  "ticker": "QQQ",
  "instrument_type": "ETF",
  "currency": "USD",
  "quote_currency": "USD",
  "price_multiplier": "1",
  "exchange_name": "NGM",
  "exchange_timezone": "America/New_York",
  "asset_type": "etf",
  "detection_status": "detected",
  "reason": null,
  "message": null
}
```

| `detection_status` | 화면·요청 처리 |
| --- | --- |
| `detected` | `EQUITY`는 주식, `ETF`는 ETF로 자동 판별. 확인된 시세 통화로 입력 |
| `needs_selection` | 유형 누락·알 수 없는 유형·메타정보 조회 실패. `asset_type`을 `stock` 또는 `etf`로 선택 |
| `unsupported` | 지수·뮤추얼펀드·선물·암호화폐·ETN 등 확인된 미지원 유형. 수동 선택으로 우회 불가 |

잘못된 티커는 HTTP 400 `INVALID_TICKER` 오류로 반환합니다. 계산 서버에서도 유형·통화를 다시 검사하며, 실제 시세 응답에서 확인된 미지원 유형이나 선택과 충돌하는 유형도 거절합니다.

### 계산 요청

`POST /api/calculate`의 `stocks` 배열에는 주식과 ETF를 함께 넣을 수 있습니다.

| 입력 | 의미 |
| --- | --- |
| `gift_date` | 증여일(`YYYY-MM-DD`). 한국 날짜 기준 미래 증여일은 거절 |
| `stocks[].ticker` | 종목 티커. 앞뒤 공백을 제거하고 대문자로 처리 |
| `stocks[].qty` | 1 이상의 정수 수량 |
| `stocks[].currency` | 기본 `USD`. API는 USD·EUR·JPY·GBP·CNY·CHF·CAD·AUD, 화면은 USD·EUR·JPY·GBP 지원 |
| `stocks[].asset_type` | 생략 시 `auto`. `auto`·`stock`·`etf` 중 선택 |

자동 판별이 가능하면 서버의 판별 결과를 사용합니다. 명시한 유형이 판별 결과와 같아도 결과의 `detection_method`는 `auto`입니다. 판별 결과와 다른 유형은 거절하고, 자동 판별이 불가능할 때만 명시한 유형을 `manual`로 적용합니다.

ETF 단독 요청:

```bash
curl -X POST http://localhost:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "gift_date": "2025-11-10",
    "stocks": [
      {"ticker": "QQQ", "qty": 10, "currency": "USD", "asset_type": "auto"}
    ]
  }'
```

주식·ETF·복수 통화 혼합 요청:

```json
{
  "gift_date": "2025-11-10",
  "stocks": [
    {"ticker": "AAPL", "qty": 10, "currency": "USD"},
    {"ticker": "QQQ", "qty": 10, "currency": "USD"},
    {"ticker": "ISF.L", "qty": 10, "currency": "GBP"},
    {"ticker": "1306.T", "qty": 10, "currency": "JPY"}
  ]
}
```

주식이 포함되면 증여일 후 2개월이 지나야 **요청 전체**를 계산합니다. 위 혼합 요청의 계산 가능일은 `2026-01-10`입니다. ETF만 있는 같은 증여일 요청은 후 2개월을 기다리지 않습니다. 유형을 직접 고르는 경우에는 자동 판별이 불가능한 해당 행에 `"asset_type": "stock"` 또는 `"asset_type": "etf"`를 지정합니다.

### 계산 결과

아래는 종가 `200 USD`, 환율 `1,300 KRW/USD`, 수량 `10`을 가정한 **설명용 응답**입니다. 실제 QQQ의 과거 시세나 고시 환율을 나타내지 않으며 파일 ID도 예시입니다.

```json
{
  "gift_date": "2025-11-10",
  "stocks": [
    {
      "ticker": "QQQ",
      "qty": 10,
      "currency": "USD",
      "asset_type": "etf",
      "detection_method": "auto",
      "valuation_method": "previous_close",
      "valuation_price": "200",
      "price_average": "200",
      "price_date": "2025-11-07",
      "price_date_note": "증여일 전일 종가가 없어 이전 최근 거래일의 종가를 적용했습니다.",
      "price_source_url": "https://finance.yahoo.com/quote/QQQ/history/?period1=1762473600&period2=1762560000",
      "quote_currency": "USD",
      "price_multiplier": "1",
      "period_start": "2025-11-07",
      "period_end": "2025-11-07",
      "price_data": [{"date": "2025-11-07", "close": "200"}],
      "exchange_rate": "1300",
      "exchange_rate_date": "2025-11-10",
      "exchange_rate_data": [{"date": "2025-11-10", "close": "1300"}],
      "gift_amount_krw": "2600000"
    }
  ],
  "total_gift_amount_krw": "2600000",
  "estimated_tax": "0",
  "exchange_rate_date": "2025-11-10",
  "exchange_rate_evidence": [
    {
      "currency": "USD",
      "rate": "1300",
      "actual_rate_date": "2025-11-10",
      "period_start": "2025-11-09",
      "period_end": "2025-11-11",
      "source_unit": 1,
      "source_url": "http://www.smbs.biz/ExRate/StdExRatePop.jsp?StrSch_sYear=2025&StrSch_sMonth=11&StrSch_sDay=09&StrSch_eYear=2025&StrSch_eMonth=11&StrSch_eDay=11&tongwha_code=USD",
      "rates": [{"date": "2025-11-10", "close": "1300"}]
    }
  ],
  "gift_pdf_file_id": "gift-<uuid>",
  "rate_pdf_file_id": "rate-<uuid>"
}
```

| 결과 | 주식 | ETF |
| --- | --- | --- |
| `valuation_method` | `average_close` | `previous_close` |
| `valuation_price` / 호환용 `price_average` | 소수 둘째 자리로 반올림한 평균 종가 | 선택한 종가의 정밀도 유지 |
| `price_date` | `null` | 실제 종가 적용일 |
| `period_start` / `period_end` | 전후 2개월 평균 산정 기간 | 둘 다 실제 종가 적용일 |
| `price_data` | 평균 산정에 사용한 종가 목록 | 선택한 종가 1건 |

`price_date_note`는 증여일 전일의 종가가 없어 이전 최근 거래일을 선택한 경우에 반환합니다. 주말·거래소 휴장·자료 누락을 구분해 확정하는 필드는 아닙니다. `price_source_url`은 가격 출처이며, 환율 증빙별 `source_url`은 smbs.biz 원문 조회 링크입니다.

종가 날짜는 거래소 시간대로 해석합니다. 주식은 평균 단가를 소수 둘째 자리로 반올림한 후, ETF는 종가 정밀도를 유지한 채 계산합니다. 최종 원화 금액은 종목별로 기존 원 단위 반올림을 적용한 뒤 합산합니다. ETF 가격 적용일과 환율 적용일은 서로 다를 수 있습니다.

복수 통화에서는 종목별 `exchange_rate_date`와 `exchange_rate_evidence`의 통화·실제 고시일을 사용하세요. 최상위 `exchange_rate_date`는 첫 종목의 날짜를 담는 호환용 필드입니다. 증빙 조회 구간은 **각 실제 환율 적용일 전후 1일**이며 해당 구간에 고시 데이터가 있는 날짜만 포함합니다.

### 계산 오류

계산할 수 없는 주식이 섞인 경우의 예시:

```json
{
  "detail": {
    "code": "INSUFFICIENT_POST_GIFT_WINDOW",
    "message": "AAPL: 증여일 기준 후 2개월 기간이 아직 지나지 않아 현재는 계산할 수 없습니다. 2026-01-10부터 다시 시도해 주세요.",
    "ticker": "AAPL",
    "available_from": "2026-01-10",
    "gift_date": "2025-11-10"
  }
}
```

| HTTP / 코드 | 의미 |
| --- | --- |
| 400 `INVALID_TICKER` | 잘못되었거나 조회되지 않는 티커 |
| 422 `ASSET_TYPE_REQUIRED` | 자동 판별 불가. 주식·ETF 선택 필요 |
| 422 `ASSET_TYPE_MISMATCH` | 선택한 유형과 확인된 상품 유형이 다름 |
| 422 `UNSUPPORTED_INSTRUMENT` | 확인된 미지원 상품 |
| 422 `CURRENCY_MISMATCH` | 시세 통화와 입력 통화가 다름 |
| 422 `FUTURE_GIFT_DATE` | 미래 증여일 |
| 422 `INSUFFICIENT_POST_GIFT_WINDOW` | 주식 평균 산정 기간 미충족. `ticker`와 `available_from` 안내 |
| 422 `PRICE_DATA_UNAVAILABLE` | 평가 구간에 종가 없음. ETF는 전일부터 과거 30개 달력일 이내에서만 검색 |
| 503 `PRICE_LOOKUP_FAILED` / `EXCHANGE_RATE_LOOKUP_FAILED` | 시세 또는 환율·증빙 조회 실패 |

종목별 계산 오류에는 `ticker`를 포함합니다. 통신·응답 해석 오류를 휴일이나 데이터가 없는 날로 처리하지 않습니다. 한 종목이라도 계산에 실패하면 PDF 다운로드 ID를 발급하지 않습니다.

### PDF 다운로드

`POST /api/calculate`가 모든 종목 계산과 두 PDF 생성을 마치면 `gift_pdf_file_id`와 `rate_pdf_file_id`를 반환합니다. ETF도 주식과 동일하게 두 파일을 제공합니다.

```bash
curl -OJ "http://localhost:8000/api/download/<gift_pdf_file_id>"
curl -OJ "http://localhost:8000/api/download/<rate_pdf_file_id>"
```

파일명은 `gifttax_<file_id>.pdf`입니다. 파일은 다운로드 응답 처리 후 삭제되므로 다시 받으려면 재계산해야 합니다. 미다운로드 파일은 `DELETE /api/download/{file_id}`로 정리할 수 있습니다.

화면의 환율 원문 출력 링크는 통화·실제 적용일별로 제공하며, 같은 조합은 중복 표시하지 않습니다. 다운로드 ID 대신 원문을 확인하려는 경우에 사용할 수 있습니다.

## 프로젝트 구조

```
gifttax/
├── frontend/           # 프론트엔드
│   ├── index.html
│   ├── style.css
│   ├── instruments.js   # 종목 판별·수동 선택 상태
│   └── app.js
├── backend/            # 백엔드
│   ├── main.py            # FastAPI 앱
│   ├── api/
│   │   └── routes.py          # API 라우터
│   ├── services/
│   │   ├── calculator.py      # 계산 흐름
│   │   ├── instruments.py     # 상품 유형·통화 검증
│   │   ├── price_valuation.py # 주식·ETF 평가
│   │   └── exchange_rates.py  # 공유 환율 증빙
│   ├── tax/                   # 세금 계산 (예정)
│   ├── integrations/
│   │   └── scraper/           # 웹 크롤러
│   │       ├── investing.py
│   │       ├── smbs.py
│   │       └── yahoo.py
│   ├── pdf/
│   │   └── generator/         # 파일 생성기
│   │       ├── exchange_rate_pdf.py
│   │       └── gift_calculation_pdf.py
│   ├── schemas/       # Pydantic 요청/응답 및 계산 데이터 계약
│   ├── storage/       # DB 연결, ORM 모델 및 마이그레이션
│   │   ├── models.py             # SQLAlchemy DB 테이블 및 관계
│   │   ├── database.py           # DB 연결, 세션 및 Alembic 실행
│   │   └── alembic/              # DB 변경 이력
│   └── tests/         # 테스트
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## 라이선스

MIT
