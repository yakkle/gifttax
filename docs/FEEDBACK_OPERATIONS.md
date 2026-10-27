# 후기·관리자 데이터 저장소

이 문서는 커밋별로 추가되는 후기 기능의 운영 설정을 설명한다.
현재 단계에서는 SQLAlchemy ORM·Alembic 기반 저장소·데이터 계약·자동 정리와
관리자 패스키 인증과 비공개 의견 제출 API를 제공한다. 통계 수집과 후기 작성·관리 화면은 후속 단계에서 추가한다.
관리자 인증 설정·최초 등록·JWT 대체 모드·복구 절차는 [관리자 인증 운영 안내](ADMIN_AUTH.md)를 참고한다.

## 저장 경로와 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `GIFTTAX_DATABASE_PATH` | `/tmp/gifttax/feedback.sqlite3` | SQLite 파일의 절대 경로 |
| `GIFTTAX_RETENTION_INTERVAL_SECONDS` | `86400` | 재정리 간격(초), 최소 60초 |

Docker Compose는 기존 `gifttax-data:/tmp/gifttax` 볼륨 안에 DB를 저장한다.
컨테이너를 재생성해도 데이터가 유지된다. 로컬 실행에서도 경로를 지정하지 않으면
`/tmp/gifttax`를 사용하므로 OS 임시 파일 정리의 영향을 받을 수 있다.
로컬 데이터를 보존하려면 다음처럼 별도의 절대 경로를 지정한다.

```bash
GIFTTAX_DATABASE_PATH="$PWD/.local/feedback.sqlite3" uvicorn backend.main:app --reload
```

`.env` 자동 로딩은 하지 않는다. 실행 환경에 변수를 전달해야 한다.
Docker 경로를 변경하려면 Compose 설정과 영속 볼륨 마운트를 함께 변경해야 한다.
DB와 `-wal`, `-shm` 파일은 Git에서 제외한다. 환경변수 외부에 인증 비밀을 기록하지 않는다.

## 초기화와 동시 접근

앱 시작 시 스키마를 초기화하고 만료 데이터를 정리한 뒤 요청을 받는다.
실패하면 오류를 기록하고 기존 계산·다운로드 서비스를 계속 제공하며,
설정된 간격으로 초기화와 정리를 재시도한다. 현재 단계에서 입력·계산 정보는 DB에 저장하지 않는다.

DB 모델은 `backend/storage/models.py`, 요청·응답용 Pydantic 계약은
`backend/schemas`에 따로 정의한다. 일반 데이터 처리는
`Database.session(write=True)`에서 ORM 객체를 추가·조회·변경하는 방식으로 수행한다.
정상 종료하면 커밋하고 예외가 발생하면 롤백한다. 세션을 요청·작업 간에 공유하지 않으며,
ORM 객체를 API에 직접 반환하지 않고 세션 안에서 응답 계약으로 변환한다.

DB 연결·세션과 Alembic 실행 설정은 `backend/storage/database.py`에서 관리한다.
테이블 생성·변경은 `backend/storage/alembic/versions`의 Alembic revision만 사용한다.

스키마 이력은 Alembic의 `alembic_version`으로 관리한다.
앱 시작 시 `upgrade head`를 실행하며 테이블 변경과 버전 변경을 한 트랜잭션으로
처리한다. 실패하면 함께 되돌린다. 알 수 없는 Alembic revision이나 테이블 이름 충돌이
있으면 자동으로 덮어쓰거나 downgrade하지 않고 저장소 오류를 기록한다.

운영에 배포되기 전이므로 초기 이력은 `0001_initial_storage.py` 하나로 유지한다.
빈 DB에서 테이블 9개, 인덱스와 제약조건을 생성하며 별도의 SQL 스냅샷이나 기존 DB 편입
기능은 제공하지 않는다. 최초 운영 배포 이후에는 적용된 revision을 수정·삭제하지 않고
새 revision을 추가한다.

이전 개발 과정에서 생성한 로컬 DB에 `0002` 등 제거된 이력이 남아 있으면 자동 변환하지
않는다. 필요한 데이터를 별도 보관한 뒤 새 빈 DB 경로를 지정해 초기화한다.
기존 파일을 유지하면서 새로 시작하는 예시는 다음과 같다.

```bash
GIFTTAX_DATABASE_PATH="$PWD/.local/feedback-fresh.sqlite3" uv run --no-sync uvicorn backend.main:app --reload
```

로컬에서는 프로젝트 루트에서 아래 명령을 사용한다. 앱과 같은
`GIFTTAX_DATABASE_PATH`를 지정해야 한다.

```bash
# 의존성 설치
uv pip install -e '.[dev]'

# 적용 상태 확인 및 최신 스키마 적용
uv run --no-sync alembic current
uv run --no-sync alembic upgrade head

# ORM 모델과 적용된 스키마 비교
uv run --no-sync alembic check

# 이후 모델 변경에 대한 마이그레이션 초안 생성
uv run --no-sync alembic revision --autogenerate -m 'describe schema change'
```

생성된 마이그레이션은 검토한 뒤 커밋한다. 자동 생성이 모든 제약조건 변경이나
컬럼 이름 변경을 정확히 판단하지는 않으므로 생성 결과와 데이터 보존을 테스트한다.
운영에서는 앱 초기화가 마이그레이션을 실행하므로 `alembic.ini` 없이도 동작한다.
컨테이너에는 CLI 설정도 포함하므로
`docker compose exec gifttax alembic current`로 상태를 확인할 수 있다.
`downgrade base`는 후기·인증 테이블과 데이터를 삭제하므로 빈 테스트 DB에서만 사용한다.

SQLite WAL 모드와 SQLAlchemy 동기 세션을 사용하고 작업별로 독립된 연결을 연다.
쓰기 트랜잭션은 `BEGIN IMMEDIATE`로 직렬화하며 잠금 대기는 최대 5초다.
외래 키를 모든 연결에서 활성화한다. 단일 서버의 로컬 영속 볼륨을 기준으로 하며,
여러 서버가 공유하는 네트워크 파일시스템에서 사용하지 않는다.

## 데이터 구분과 보관

- `feedback`: 만족도, 분류, 본문, 진입 위치, 처리 상태, 접수 시각.
  접수 후 1년(달력 기준)이 지나면 삭제한다. 제출 식별자가 기본 키이므로 중복 저장을 막을 수 있다.
- `feedback_contacts`: 이메일, 동의 시각, 만료 시각. 동의 시각에서 90일 뒤 만료한다.
  의견과 별도로 삭제하며, 의견을 삭제하면 연락처도 함께 삭제한다.
- `usage_events`: 무작위 이벤트·브라우저 식별자, 허용된 이벤트 종류, 진입 위치·후원 대상,
  발생 시각. 90일 뒤 삭제한다. 금융 입력값·이메일·원본 IP를 저장할 필드는 없다.
- `daily_usage_counts`: 한국 시간 기준 날짜·이벤트별 합계. 원본 기록을 정리해도 보존한다.
  90일이 지난 구간의 브라우저별 고유 이용자는 재계산할 수 없다.
- `admin_account`, `admin_credentials`: 관리자 하나의 공개 식별자와 패스키 공개키 정보.
  기간 정리로 삭제하지 않는다. 개인키나 생체정보는 저장하지 않는다.
- `admin_sessions`, `admin_one_time_tokens`, `admin_challenges`: 인증용 상태.
  만료된 행을 정리한다. 일회용 토큰과 challenge 바인딩 값은 해시로 저장할 구조다.

시각은 UTC Unix 초로 저장하고, 통계 날짜는 서비스에서 한국 시간으로 계산한다.
정리는 시작 시 및 기본 24시간 간격으로 수행한다. 기간이 끝났다고 즉시 정리가
실행되는 것은 아니므로 삭제는 다음 정리 시점에 완료된다. 후속 조회 API는 정리 실행 여부와
관계없이 만료된 연락처·인증 상태를 사용하거나 반환하지 않아야 한다.
본문 안에 사용자가 직접 적은 이메일 등은 연락처 컬럼처럼 자동 분리되지 않으므로,
후속 입력 화면에서 민감한 정보를 적지 않도록 안내한다.

입력 계약의 형식·길이·열거형은 `backend/schemas/feedback.py`에 정의한다.
의견의 필수 조건·이메일 수집 동의는 의견 서비스에서 검증한다.
통계 이벤트 수집과 이벤트 조합 검증은 후속 단계에서 구현한다.

## 비공개 의견 제출 API

`POST /api/feedback`은 로그인 없이 JSON으로 의견을 접수한다.
관리자 인증 설정이 없어도 사용할 수 있다. 공개 조회 API는 제공하지 않는다.

```json
{
  "submission_id": "c5c9cd84-96c7-43c9-8458-b535315b9680",
  "satisfaction": "satisfied",
  "category": "suggestion",
  "message": "계산 결과를 다시 확인할 수 있으면 좋겠습니다.",
  "source": "result",
  "email": "reply@example.com",
  "email_consent": true,
  "website": ""
}
```

- `submission_id`: 클라이언트에서 새 의견마다 생성하는 UUID. 통신 실패 후 재시도할 때는 같은 값을 사용한다.
- `satisfaction`: `satisfied`, `neutral`, `dissatisfied` 중 하나. 생략할 수 있다.
- `message`: 앞뒤 공백을 제거한 최대 2,000자 본문. 만족도와 본문 중 하나는 있어야 한다.
- `category`: `review`(기본값), `problem`, `suggestion` 중 하나.
- `source`: `general`(기본값), `result`, `error` 중 하나.
- `email`: 선택 항목. 비어 있지 않으면 `email_consent: true`가 필요하다.
  형식 검사와 주소 정규화만 수행하며 DNS 조회·메일 발송·실제 수신 가능 여부 확인은 하지 않는다.
- `website`: 스팸 방지용 숨김 필드로 항상 빈 문자열을 보낸다.
  값이 있으면 일반 접수 응답을 반환하지만 DB에는 아무것도 저장하지 않는다.

최초 접수는 `201`, 이미 저장된 제출 ID의 재시도는 `200`으로 응답한다.
응답에는 `id`와 감사 메시지만 포함하며 입력 본문·이메일을 반환하지 않는다.
같은 ID로 다른 내용을 보내도 최초 의견과 연락처를 수정하지 않는다.
연락처가 만료·삭제된 뒤 재시도해도 연락처를 다시 만들거나 보관 기간을 연장하지 않는다.
의견 자체가 보관 기간 이후 삭제되면 해당 ID의 중복 여부도 더는 확인할 수 없다.

이메일과 의견은 한 트랜잭션으로 저장한다. 일부 저장에 실패하면 모두 롤백한다.
이메일 동의·접수 시각은 서버에서 정하며 연락처는 접수 후 90일간 보관한다.
사용자가 연락처를 남겨도 자동 답변 메일은 발송하지 않는다.

오류 응답은 `detail.code`, `detail.message` 형식을 사용하며 입력값을 다시 노출하지 않는다.

| HTTP 상태 | 의미 |
|---|---|
| `413` | 요청 본문이 32 KiB를 초과함 |
| `415` | `Content-Type`이 `application/json`이 아님 |
| `422` | 필수 조건·형식·길이 오류 또는 이메일 수집 동의 누락 |
| `429` | 요청 빈도 초과. `Retry-After: 60` 이후 재시도 |
| `503` | 저장소 준비 또는 저장 실패. 같은 제출 ID로 재시도 |

접수와 오류 응답 모두 `Cache-Control: no-store`를 설정한다.

## 접수 빈도 제한과 프록시

한 프로세스에서 IP별 최근 60초간 5회, 전체 최근 60초간 60회까지 접수 요청을 허용한다.
잘못된 입력과 스팸 방지 필드가 채워진 요청도 횟수에 포함한다.
IP는 메모리에서만 최대 2,048개까지 관리하며 DB에 저장하지 않는다.
제한 기록은 서버 재시작 시 초기화되고 여러 프로세스·서버 사이에 공유되지 않는다.
현재 단일 프로세스 배포를 기준으로 하며, 공유 IP를 쓰는 사용자는 같은 제한을 적용받는다.

운영 Compose에서는 백엔드 포트를 외부에 공개하지 않고 Nginx를 통해서만 접근한다.
Nginx가 `X-Forwarded-For`를 실제 접속 IP로 덮어쓰고,
백엔드는 `FORWARDED_ALLOW_IPS=*`로 이 프록시 정보를 사용한다.
따라서 운영 설정에서 백엔드 포트를 직접 노출하거나 신뢰할 수 없는 컨테이너를 같은 네트워크에
추가하지 않는다. 앞단에 CDN이나 다른 프록시를 추가한다면 실제 클라이언트 IP 전달 설정도 함께 조정한다.
직접 접근하는 개발 환경에는 이 전체 신뢰 설정을 추가하지 않는다.

## 백업과 복원

실행 중인 DB 파일만 복사하면 WAL에 있는 데이터를 놓칠 수 있다.
Python 표준 SQLite 백업 API로 일관된 스냅샷을 만든다. 아래 경로는 컨테이너 안의 예시다.

```bash
docker compose exec -T gifttax python - <<'PY'
import sqlite3

with sqlite3.connect('/tmp/gifttax/feedback.sqlite3') as source:
    with sqlite3.connect('/tmp/gifttax/feedback-backup.sqlite3') as destination:
        source.backup(destination)
PY
```

백업은 별도의 안전한 저장소로 옮긴다. 이메일과 관리자 인증 정보가 포함되므로
접근을 제한하고 보관 기간을 적용한다. 자동 정리는 백업 파일까지 정리하지 않는다.

복원 시 앱을 정지하고 현재 DB와 sidecar를 별도 보관한 뒤,
백업을 설정된 DB 경로로 배치하고 앱 실행 사용자의 읽기·쓰기 권한을 확인한다.
이전 `-wal`, `-shm` 파일을 복원한 DB와 섞지 않는다. 재시작 시 정합성·스키마 버전과
만료 데이터 정리가 수행되는지 확인한다. 앱은 기존 DB에 `PRAGMA integrity_check`를
자동 실행하지 않으므로 복원 전 SQLite 도구로 `PRAGMA integrity_check` 결과가 `ok`인지 확인한다.
백업 시점의 세션·토큰이 복구될 수 있으므로 복원 후 `python -m backend.admin reset-auth`로
인증 상태를 폐기하고 패스키를 다시 등록한다. 자세한 명령은 관리자 인증 운영 안내를 참고한다.
