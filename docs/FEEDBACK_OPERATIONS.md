# 후기·관리자 데이터 저장소

이 문서는 커밋별로 추가되는 후기 기능의 운영 설정을 설명한다.
현재 단계에서는 SQLAlchemy ORM·Alembic 기반 저장소·데이터 계약·자동 정리를 제공한다.
의견 제출 API, 통계 수집, 관리자 로그인과 관리 화면은 후속 단계에서 추가한다.

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

DB 연결·세션은 `backend/storage/database.py`, Alembic 실행 설정과 기존 SQLite DB
호환성 검사는 `backend/storage/migration_support.py`에 모아 저장 계층에서 관리한다.

스키마 이력은 Alembic의 `alembic_version`으로 관리한다.
앱 시작 시 `upgrade head`를 실행하며 테이블 변경과 버전 변경을 한 트랜잭션으로
처리한다. 실패하면 함께 되돌린다. 알 수 없는 Alembic revision이나 기존 스키마를
발견하면 자동으로 덮어쓰거나 downgrade하지 않고 저장소 오류를 기록한다.

태스크 1에서 생성한 DB(`PRAGMA user_version = 1`)는 원본 테이블·인덱스 정의가
보존된 스냅샷과 일치하고 추가 트리거·뷰 등이 없을 때만 편입한다. `0001`은 기존 테이블을 유지하고,
`0002`는 SQLAlchemy가 인라인 외래 키의 `ON DELETE CASCADE`를 제대로 읽도록
연락처 테이블 하나를 데이터·CHECK·외래 키·인덱스·STRICT 속성을 보존하며 재작성한다.
나머지 테이블은 재생성하지 않는다. 새 DB는 같은 Alembic 이력으로 초기화한다.
편입 후 `user_version` 값은 과거 버전 표시로만 남으며, 이후 스키마 변경은 Alembic으로 관리한다.
`backend/storage/migrations.py`는 기존 DB 검증용 불변 스냅샷이므로 수정하지 않는다.

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
이메일 형식·수집 동의, 만족도 또는 본문 필요 조건, 요청 빈도 제한과
이벤트 조합 검증은 후속 의견·통계 서비스 단계에서 구현한다.
현재 모델을 공개 API로 직접 연결하지 않는다.

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
백업 시점의 세션·토큰이 복구될 수 있으므로 인증 기능이 추가된 뒤에는 복원 후
인증 상태를 폐기하는 복구 명령을 반드시 실행한다.
