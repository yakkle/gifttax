# StockTax - 해외주식 증여 금액 계산기

해외주식을 증여할 때 증여한 자산의 금액을 직접 계산하여 증빙 서류를 만들어주는 도구입니다.

## 기능

- **증여 금액 계산**: 증여일 전후 2개월간의 종가 평균 × 매매기준환율
- **주가 데이터**: investing.com에서 자동 수집
- **환율 데이터**: smbs.biz에서 자동 수집 (매매기준환율)
- **증빙 서류 생성**:
  - Excel: 주가 데이터 + 종가 평균
  - PDF: 환율 증빙

## 기술 스택

| 구분 | 기술 |
|------|------|
| Backend | FastAPI + Python 3.11 |
| Frontend | Vanilla JS + HTML/CSS |
| Excel | openpyxl |
| PDF | reportlab |
| Scraping | requests + BeautifulSoup |
| Deploy | Docker + OCI |

## 시작하기

### 필수 조건

- Python 3.11+
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
# 테스트
pytest backend/tests/ -v

# 린트
ruff check .

# 타입 체크
mypy backend/
```

## API 사용법

### 계산하기

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
│   │       ├── excel.py
│   │       └── pdf.py
│   ├── models/        # Pydantic 모델
│   └── tests/         # 테스트
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## OCI 배포 (선택)

```bash
# 1. OCI VM 생성 (Always Free)

# 2. Docker 설치
sudo yum install -y docker
sudo systemctl start docker

# 3. 코드 클론
git clone <your-repo>
cd stocktax

# 4. 빌드 & 실행
docker-compose up -d

# 5. 방화벽 설정
sudo firewall-cmd --permanent --add-port=8000/tcp
sudo firewall-cmd --reload
```

## 라이선스

MIT
