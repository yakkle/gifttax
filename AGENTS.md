# AGENTS.md
해외 주식 증여금액 계산 및 증여세 신고용 PDF 생성 서비스

이 문서는 AI 개발 에이전트가 프로젝트를 이해하고 일관된 방식으로 코드를 작성하기 위한 규칙을 정의한다.

---

# 1. 프로젝트 목표

이 프로젝트는 해외 주식 증여 시 필요한 계산과 증빙 자료 생성을 자동화하는 서비스이다.

사용자는 다음 정보를 입력한다.

- 주식 종목 (Ticker)
- 증여 수량
- 증여일
- 증여자 / 수증자 정보

시스템은 다음을 수행한다.

1. 증여일 기준 주식 종가 조회
2. 해당 날짜 매매 기준 환율 조회
3. 증여금액 계산
4. 예상 증여세 계산
5. 계산 결과를 포함한 PDF 증빙자료 생성

사용자는 최종적으로 **증여세 신고용 계산 증빙 자료와 매매기준환율 정보**를 PDF 로 다운로드할 수 있어야 한다.

---

# 2. 핵심 계산 규칙

증여금액 계산

증여금액 = 주식가격 × 수량 × 환율

예시

주가: 200 USD
수량: 10
환율: 1300

증여금액 = 2,600,000 KRW

---

환율 데이터 조회 규칙

적용 환율

- 증여일 직전영업일 기준으로 조회한다
- 주말/공휴일을 고려하여 최대 30일 전까지 역방향으로 검색한다
- 실제 환율이 적용된 날짜를 actual_rate_date 로 기록한다

PDF용 환율 데이터 기간

- actual_rate_date 기준 전후 1일
- gift_date(증여일) 기준이 아님에 주의한다
- 이 기간 계산은 services 레이어(calculator.py)에서 수행한다

---

증여세 계산

TaxEngine 모듈에서 처리한다.

기본 흐름

1. 증여금액 계산
2. 공제금액 차감
3. 과세표준 계산
4. 누진세율 적용

세율과 공제 규칙은 TaxEngine 내부에 정의한다.

---

# 3. 시스템 구성

서비스는 다음 기능으로 구성된다.

Stock Price 조회
Exchange Rate 조회
Gift Calculation
Tax Engine
PDF Report 생성

---

# 4. 프로젝트 구조
 
gifttax/
├── frontend/
└── backend/
    ├── api
    ├── services
    ├── tax
    ├── integrations
    ├── pdf
    └── tests

---

레이어 역할

* api: HTTP endpoint 정의
* services: 비즈니스 로직 처리
* tax: 증여세 계산 로직
* integrations: 외부 API 연동
* pdf: PDF 문서 생성
* models: 데이터 계약 정의 (Pydantic 모델)

---

# 5. 주요 데이터 흐름

1. 사용자 입력 수신

ticker
quantity
gift_date

2. 주식 가격 조회

StockPriceProvider 사용

3. 환율 조회

ExchangeRateProvider 사용

4. 증여금액 계산

GiftCalculationService

5. 증여세 계산

TaxEngine

6. PDF 생성

PdfReportService

---

# 6. 주요 API

증여금액 계산

POST /calculate

request

{
  "ticker": "AAPL",
  "quantity": 10,
  "gift_date": "2024-05-01"
}

response

{
  "stock_price": 200,
  "exchange_rate": 1300,
  "gift_value": 2600000,
  "estimated_tax": 0
}

---

PDF 생성

POST /report

계산 결과를 기반으로 증빙 PDF 생성 후 다운로드

---

# 7. 외부 데이터 제공자

주식 가격

StockPriceProvider

예시 데이터 소스

Yahoo Finance

---

환율

ExchangeRateProvider

USD → KRW 환율 조회

---

# 8. AI 개발 규칙

항상 다음 규칙을 따른다.

- 비즈니스 로직은 services 레이어에 작성한다
- 세금 계산 로직은 tax 모듈에 작성한다
- 외부 API 호출은 integrations 레이어에서만 수행한다
- API 레이어는 요청/응답 처리만 담당한다
- 작은 함수 단위로 구현한다
- 테스트 가능한 구조로 작성한다

---

# 9. 금지 사항

다음 행동은 금지된다.

- API 레이어에 계산 로직 작성
- 컨트롤러에서 외부 API 직접 호출
- API 키를 코드에 하드코딩
- 테스트 코드 삭제
- 하나의 서비스에 과도한 책임 추가

---

# 10. 테스트 규칙

다음 로직은 반드시 테스트해야 한다.

증여금액 계산
환율 적용
증여세 계산

테스트 예시

주가: 200
수량: 10
환율: 1300

예상 결과

2,600,000 KRW

---

# 11. 확장 가능 기능

다음 기능은 향후 확장 가능하다.

증여 이력 저장
PDF 템플릿 확장
증여세 신고 가이드 제공
