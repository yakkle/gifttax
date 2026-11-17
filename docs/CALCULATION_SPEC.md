# 증여금액 계산 명세

해외 상장 주식·ETF의 평가단가, 환율, 증여금액과 공유 증빙에 대한 현재 서비스 규칙을 정의한다.
계산 동작을 변경할 때는 이 명세와 관련 테스트를 함께 갱신한다.

- 입력·응답·오류·다운로드 API와 사용자 안내: [README](../README.md).
- PDF 구성과 표시 형식: [PDF 명세](../PDF_REPORT_SPEC.md).
- 증여세 엔진의 현재 상태와 향후 설계: [TAX_ENGINE.md](../TAX_ENGINE.md).
- 개발·검증·커밋 승인 절차: [AGENTS.md](../AGENTS.md).

## 1. 입력과 상품 유형

입력은 `GiftCalculationInput(gift_date, stocks)`이다. 각 종목은 `ticker`, 양의 정수 `qty`, `currency`와 `asset_type`을 갖는다.
`currency`는 생략 시 `USD`, `asset_type`은 생략 시 `auto`이다.

| 메타정보 | 적용 방식 |
| --- | --- |
| Yahoo `EQUITY` | 주식으로 자동 판별 |
| Yahoo `ETF` | ETF로 자동 판별 |
| 유형 누락·알 수 없는 유형·메타정보 조회 실패 | 사용자가 `stock`·`etf`를 선택해야 계산 가능 |
| 지수·뮤추얼펀드·선물·암호화폐·ETN 등 확인된 미지원 유형 | 수동 선택과 관계없이 거절 |
| 잘못된 티커 | `INVALID_TICKER` 오류 |

서버는 계산 요청에서도 상품 유형을 조회한다. 명시한 유형이 자동 판별 결과와 다르면 거절하고, 같으면 자동 판별로 기록한다. 수동 선택은 자동 판별이 불가능한 경우에만 적용한다. 시세 조회 응답의 메타정보도 다시 검사해 미지원 상품·유형 충돌·통화 불일치를 차단한다.

## 2. 주식 평가

주식의 평균 산정 기간은 다음과 같다.

- 시작: `gift_date - 2개월 + 1일`
- 종료(포함): `gift_date + 2개월 - 1일`
- 계산 가능일: `gift_date + 2개월`

조회한 종가의 단순 산술평균을 소수 둘째 자리로 반올림한 뒤 수량과 환율을 곱한다. 수정종가를 사용하지 않는다.
종가 날짜는 서버 시간대와 관계없이 거래소 시간대로 해석한다.
외부 API의 종료일이 미포함이면 조회 경계에만 종료일 다음 날을 전달하고, 결과·화면·PDF에는 원래 표시 기간을 유지한다.

예: `2025-11-10` 증여분의 표시 기간은 `2025-09-11`~`2026-01-09`, 계산 가능일은 `2026-01-10`이다.

## 3. 해외 상장 ETF 평가

ETF에는 주식의 전후 2개월 평균과 후 2개월 대기를 적용하지 않는다.

1. 증여일 전일부터 과거 30개 달력일을 검색한다. 정확한 구간은 `[gift_date - 30일, gift_date - 1일]`이다.
2. 구간 내 가장 최근 거래일의 Yahoo `quote.close`를 선택한다.
3. 증여일 당일·이후 가격, 30일 구간 밖 가격, `adjclose`는 사용하지 않는다.
4. 선택한 종가의 정밀도를 유지한 채 수량과 적용 환율을 곱한다.
5. 구간에 종가가 없으면 `PRICE_DATA_UNAVAILABLE`로 거절한다.

전일이 주말·거래소 휴장 등으로 종가가 없으면 그 이전 최근 거래일을 적용한다. 증여일 자체가 휴일이어도 증여일을 다른 날로 변경하지 않는다.
`price_date_note`는 전일 종가가 없어 이전 날짜를 선택했다는 설명이며, 거래소 휴장과 자료 누락을 구분해 확정하지 않는다.

예: 월요일 `2025-11-10` 증여분에 전일 종가가 없고 금요일 `2025-11-07` 종가가 가장 최근이면 이를 적용한다. 가격 적용일은 `2025-11-07`이지만 환율은 `2025-11-10`부터 별도로 조회한다.

## 4. 계산 가능일과 혼합 요청

- 현재 날짜는 한국 시간(`Asia/Seoul`)으로 판단한다. 미래 증여일은 상품 유형과 관계없이 거절한다.
- ETF만 있으면 후 2개월 대기 없이 계산한다. 필요한 종가·환율·증빙 데이터 조회는 성공해야 한다.
- 주식이 섞이면 모든 주식의 계산 가능일을 먼저 검사한다. 기간이 미충족인 종목이 있으면 해당 `ticker`와 `available_from`을 안내하고 전체 요청을 중단한다.
- 모든 종목 계산과 두 PDF 생성이 성공한 뒤 다운로드 파일 ID를 반환한다.

## 5. 통화와 환율

API는 USD·EUR·JPY·GBP·CNY·CHF·CAD·AUD를 받고, 현재 화면은 USD·EUR·JPY·GBP를 제공한다. 확인된 시세 통화와 입력 통화가 다르면 `CURRENCY_MISMATCH`로 거절한다.

| 원본 | 내부 가격·환율 단위 |
| --- | --- |
| Yahoo GBp·GBX 종가 | 원본 가격 × `0.01` → GBP 종가 |
| 서울외국환중개 JPY 고시값 | 원본 환율 ÷ `100` → KRW/JPY |
| 그 밖의 지원 통화 고시값 | 외화 1단위당 KRW |

GBp·GBX의 가격 단위 환산과 JPY 고시 환율의 단위 환산은 별개이며 각각 한 번만 수행한다.

환율은 증여일 **당일** 고시 데이터를 우선 조회한다. 당일 데이터가 없을 때만 이전 날짜로 이동하며 증여일을 포함해 최대 30개 달력일을 검색한다. 정확한 검색 구간은 `[gift_date - 29일, gift_date]`이며 당일부터 역순으로 조회한다.
통신·응답 해석 오류는 휴일이나 데이터 없음으로 간주하지 않는다. 검색 구간에 고시 데이터가 없거나 조회가 실패하면 오류로 중단한다.

실제 적용일은 종목별 `exchange_rate_date`, 공유 증빙의 `actual_rate_date`에 기록한다.
`exchange_rate_evidence`는 통화·실제 적용일 조합별로 중복 없이 제공한다. 최상위 `exchange_rate_date`는 첫 종목의 날짜를 담는 호환용 필드다.

환율 PDF용 구간은 **실제 환율 적용일 전후 1일**이다. `services/exchange_rates.py`에서 이 구간의 증빙을 준비하고 계산·PDF가 공유한다. 증빙에서 계산에 사용한 날짜와 환율을 확인할 수 없으면 계산을 중단한다.

## 6. 금액과 정밀도

```text
종목별 증여금액(KRW) = 평가단가 × 수량 × 적용 환율(KRW/외화 1단위)
총 증여금액 = 원 단위로 반올림한 종목별 증여금액의 합
```

| 단계 | 현재 처리 |
| --- | --- |
| 주식 평균 단가 | Decimal 평균에 `round(value, 2)` 적용 |
| ETF 적용 종가 | 추가 반올림 없이 정밀도 유지 |
| 환율 | 외화 1단위당 KRW로 환산한 정밀도 유지 |
| 종목별 최종 원화 | `round(value)`로 원 단위 반올림 |

현재 계산은 Python의 Decimal 반올림을 사용한다. 기본 컨텍스트에서 정확한 중간값은 짝수 쪽으로 반올림한다(`ROUND_HALF_EVEN`). ETF 지원 과정에서 기존 주식 단가·원화 반올림 방식을 변경하지 않았다.

설명용 예시(실제 특정 종목 시세·고시값이 아님):

| 평가단가 | 수량 | 환율 | 종목별 증여금액 |
| --- | --- | --- | --- |
| 200 USD | 10 | 1,300 KRW/USD | 2,600,000 KRW |
| 150 USD | 5 | 1,200 KRW/USD | 900,000 KRW |
| ETF 200.12345 USD | 10 | 1,300 KRW/USD | 2,601,605 KRW |
| ETF 10.1723 GBP | 10 | 1,887.35 KRW/GBP | 191,987 KRW |

## 7. 결과와 증빙

`valuation_method`는 주식 `average_close`, ETF `previous_close`이다.
`valuation_price`와 호환용 `price_average`는 둘 다 실제 계산에 쓴 평가단가다.
ETF는 `price_date`에 선택한 종가 날짜를 기록하고 `period_start`·`period_end`도 이 날짜로 반환한다.
주식의 `price_date`는 `null`이고 기간 필드는 평균 산정 구간을 유지한다.

계산 PDF에는 상품 유형별 평가 근거와 실제 환율 적용일을, 환율 PDF에는 사용한 모든 통화·실제 적용일별 증빙을 출력한다. 두 PDF는 법정 신고서 작성을 보조하는 평가 자료다.

## 8. 구현 및 검증 참조

| 담당 | 구현 | 관련 검증 |
| --- | --- | --- |
| 상품 유형·통화 검사 | [instruments.py](../backend/services/instruments.py) | [종목 판별](../backend/tests/test_instruments.py), [ETF 계산](../backend/tests/test_etf_calculation.py) |
| 주식 평균·ETF 종가 선택 | [price_valuation.py](../backend/services/price_valuation.py) | [날짜 계산](../backend/tests/test_date_calculation.py), [ETF 계산](../backend/tests/test_etf_calculation.py) |
| 계산 가능일·혼합 요청·원화 합산 | [calculator.py](../backend/services/calculator.py) | [증여금액 계산](../backend/tests/test_gifttax.py), [ETF 계산](../backend/tests/test_etf_calculation.py) |
| 공유 환율·실제 적용일·증빙 구간 | [exchange_rates.py](../backend/services/exchange_rates.py) | [환율·증빙](../backend/tests/test_exchange_rates.py) |
| 시세 단위·거래소 날짜 변환 | [yahoo.py](../backend/integrations/scraper/yahoo.py) | [종목 판별·시세 계약](../backend/tests/test_instruments.py) |
| 환율 고시 조회·JPY 단위 변환 | [smbs.py](../backend/integrations/scraper/smbs.py) | [환율·증빙](../backend/tests/test_exchange_rates.py) |
| 판별부터 두 PDF 다운로드까지 | [API](../backend/api/backend.py), [결과 스키마](../backend/schemas/__init__.py) | [전체 흐름](../backend/tests/test_etf_release_flow.py) |

외부 데이터 조회는 integrations에서 수행하고, 평가·계산·증빙 데이터 준비는 services가 담당한다.
PDF 레이어는 준비된 결과를 출력하며 외부 데이터를 다시 조회하지 않는다. 출력 형식은 PDF 명세에서 관리한다.
