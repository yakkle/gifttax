# StockTax - 해외주식 증여 금액 계산기

해외주식을 증여할 때 증여한 자산의 금액을 직접 계산하여 증빙 서류를 만들어주는 도구입니다.

## 기능

- **증여 금액 계산**: 증여일 전 2개월 + 1일부터 후 2개월 - 1일까지의 종가 평균 × 매매기준환율
- **주가 데이터**: finance.yahoo.com 에서 자동 수집
- **환율 데이터**: smbs.biz에서 자동 수집 (매매기준환율)
- **증빙 서류 생성(PDF)**:
  - 주가 데이터 + 종가 평균
  - 환율 증빙

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

# 린트
ruff check .

# 타입 체크
mypy backend/
```

## API 사용법

후기·관리자 기능용 저장소 설정 및 백업·보관 정책은
[운영 문서](docs/FEEDBACK_OPERATIONS.md)를 참고하세요.
현재 단계는 저장 기반만 제공하며 의견 제출과 관리 화면은 후속 단계에서 추가합니다.

### 계산하기

주의: 증여일 기준 후 2개월 기간이 모두 지난 뒤에만 계산할 수 있습니다. 예를 들어 `2025-11-06` 증여분은 `2026-01-06`부터 계산 가능합니다.

```bash
curl -X POST http://localhost:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "gift_date": "2025-11-06",
    "stocks": [
      {"ticker": "AAPL", "qty": 100, "currency": "USD"}
    ]
  }'
```

### 응답 예시

```json
{
  "gift_date": "2025-11-06",
  "stocks": [
    {
      "ticker": "AAPL",
      "qty": 100,
      "currency": "USD",
      "price_average": "150.00",
      "period_start": "2025-09-07",
      "period_end": "2026-01-05",
      "exchange_rate": "1350.00",
      "gift_amount_krw": "20250000.00"
    }
  ],
  "total_gift_amount_krw": "20250000.00",
  "exchange_rate_date": "2025-11-06"
}
```

계산 불가 예시:

```json
{
  "detail": {
    "code": "INSUFFICIENT_POST_GIFT_WINDOW",
    "message": "증여일 기준 후 2개월 기간이 아직 지나지 않아 현재는 계산할 수 없습니다. 2026-01-06부터 다시 시도해 주세요.",
    "available_from": "2026-01-06",
    "gift_date": "2025-11-06"
  }
}
```

## 프로젝트 구조

```
gifttax/
├── frontend/           # 프론트엔드
│   ├── index.html
│   ├── style.css
│   └── app.js
├── backend/            # 백엔드
│   ├── main.py            # FastAPI 앱
│   ├── api/
│   │   └── router.py          # API 라우터
│   ├── services/
│   │   └── calculator.py      # 계산 로직
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
