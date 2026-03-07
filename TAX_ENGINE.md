# TAX_ENGINE.md
해외 주식(미국) 증여 시 증여금액 산정 규칙

이 문서는 해외 주식 증여 시 **증여금액 계산 방식**을 정의한다.

현재 서비스의 목적은 **증여금액 계산과 증빙자료 생성**이며
증여세 계산 로직은 포함하지 않는다.

향후 필요 시 증여세 계산 기능을 확장할 수 있도록 구조만 정의한다.

---

# 1. 계산 목적

해외 주식을 증여할 때 다음 정보를 기반으로 **증여금액(KRW)** 을 계산한다.

필요 데이터

- 주식 종목 (Ticker)
- 증여 수량
- 증여일
- 해당 날짜 주식 종가
- 해당 날짜 환율 (USD → KRW)

계산 결과는 **증여세 신고 시 참고 가능한 증빙 자료**로 사용된다.

---

# 2. 증여금액 계산 규칙

증여금액 계산 공식

증여금액(KRW) = 주식종가(USD) × 수량 × 환율(KRW/USD)

---

예시

주식: AAPL

종가: 200 USD

수량: 10

환율: 1300 KRW/USD

---

증여금액 계산

200 × 10 × 1300

=

2,600,000 KRW

---

# 3. 주식 가격 기준

주식 가격은 **증여일 기준 종가(Closing Price)** 를 사용한다.

StockPriceProvider 모듈이 해당 데이터를 제공한다.

예

ticker: AAPL
date: 2024-05-01

result

closing_price: 200

---

# 4. 환율 기준

환율은 **증여일 기준 USD → KRW 환율**을 사용한다.

ExchangeRateProvider 모듈이 해당 데이터를 제공한다.

예

date: 2024-05-01

result

exchange_rate: 1300

---

# 5. 계산 흐름

전체 계산 흐름

사용자 입력

↓

주식 종가 조회

↓

환율 조회

↓

증여금액 계산

↓

PDF 증빙자료 생성

---

# 6. 입력 데이터 구조

GiftCalculationInput

ticker
quantity
gift_date

---

예시

{
  "ticker": "AAPL",
  "quantity": 10,
  "gift_date": "2024-05-01"
}

---

# 7. 출력 데이터 구조

GiftCalculationResult

ticker
quantity
stock_price_usd
exchange_rate
gift_value_krw

---

예시

{
  "ticker": "AAPL",
  "quantity": 10,
  "stock_price_usd": 200,
  "exchange_rate": 1300,
  "gift_value_krw": 2600000
}

---

# 8. 구현 규칙

GiftValueEngine 구현 시 다음 규칙을 따른다.

- 계산 로직은 순수 함수로 구현
- 외부 API 호출 금지
- 입력 데이터 검증 수행
- 계산 결과는 KRW 기준으로 반환

외부 데이터 조회는 다음 모듈이 담당한다.

StockPriceProvider
ExchangeRateProvider

---

# 9. 테스트 케이스

case 1

stock_price = 200
quantity = 10
exchange_rate = 1300

expected

gift_value = 2,600,000

---

case 2

stock_price = 150
quantity = 5
exchange_rate = 1200

expected

gift_value = 900,000

---

# 10. 향후 확장

향후 다음 기능을 추가할 수 있다.

증여세 계산
공제 규칙 적용
누진세율 적용
10년 합산 과세

확장 시 별도의 TaxEngine 모듈을 추가한다.
