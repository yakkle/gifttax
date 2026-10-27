# 관리자 인증 운영 안내

태스크 2는 `/admin`의 로그인·패스키 관리 화면과 `/api/admin/auth/*`를 제공한다.
후기 목록·처리 상태·이용 통계 화면은 후속 태스크에서 연결한다.
HTTP Basic 인증은 사용하지 않는다.

## 필수 설정

| 환경변수 | 기본값 | 설명 |
|---|---|---|
| `GIFTTAX_ADMIN_MODE` | `webauthn` | 기본 패스키 모드. 명시적 대체 모드는 `manual_jwt` |
| `GIFTTAX_ADMIN_ORIGIN` | 없음 | 실제 관리자 페이지의 HTTPS Origin. 예: `https://example.com` |
| `GIFTTAX_ADMIN_RP_ID` | 없음 | 패스키 모드에서 필수. Origin과 정확히 같은 호스트 이름, 포트 제외 |
| `GIFTTAX_ADMIN_JWT_SECRET` | 없음 | 최소 32바이트의 무작위 비밀. 패스키 모드의 세션 서명에도 필요 |
| `GIFTTAX_ADMIN_ALLOW_INSECURE_LOCALHOST` | `false` | 로컬 개발에서만 `http://localhost`, `127.0.0.1`, `::1` 허용 |

필수값이 없거나 유효하지 않으면 관리자 API는 `503 ADMIN_DISABLED`를 반환한다.
기존 계산·PDF 서비스는 계속 사용할 수 있다. `.env`는 자동으로 읽지 않는다.
관리자 페이지와 API를 같은 Origin에서 제공하고 운영에서는 기존 nginx의 TLS 종단을 사용한다.
운영 Compose는 HTTP 예외 변수를 전달하지 않는다.

비밀 생성 예시:

```bash
uv run --no-sync python -c 'import secrets; print(secrets.token_urlsafe(48))'
```

배포 환경 파일에 저장하고 파일 권한을 제한한다. 파일·환경변수·발급 코드를 Git이나 로그,
URL에 기록하지 않는다. `.env.deploy.example`에는 실제 비밀을 넣지 않는다.
서명 비밀이나 Origin·인증 모드를 변경하면 기존 JWT를 사용할 수 없다.
RP ID를 바꾸면 기존 패스키도 사용할 수 없으므로 인증 복구 후 재등록이 필요하다.

## 최초 패스키 등록

앱과 CLI는 반드시 같은 `GIFTTAX_DATABASE_PATH`와 관리자 환경변수를 사용해야 한다.
운영 Compose의 환경 파일 경로는 현재 프로젝트 배포 예시를 따른 것이다.

```bash
docker compose --env-file /etc/gifttax/gifttax.env exec gifttax python -m backend.admin issue-registration-code
```

1. 서버 터미널에서 위 명령으로 등록 코드를 발급한다.
2. 설정한 Origin의 `/admin`을 HTTPS로 연다.
3. 등록 코드와 패스키 이름을 입력하고 기기의 화면 잠금 또는 보안 키로 인증한다.
4. 등록이 완료되면 자동 로그인된다. 로그인한 상태에서 예비 패스키를 추가할 수 있다.

코드는 10분 동안 한 번 사용할 수 있으며 DB에는 SHA-256 해시만 저장한다.
다시 발급하면 이전 코드는 즉시 폐기된다. 패스키가 하나라도 등록되어 있으면 이 명령으로
새 코드를 발급할 수 없다. 추가 등록은 로그인 세션과 CSRF 토큰을 모두 요구한다.
개인키·생체정보는 서버로 전달하거나 저장하지 않는다.

WebAuthn은 Origin·RP ID·challenge와 로그인 서명을 검증하고 사용자 확인(UV)을 필수로 요구한다.
challenge는 브라우저의 HttpOnly 흐름 쿠키 및 등록 권한에 묶이며 5분 유효·1회 사용이다.
서명 검증이 실패해도 이미 제출된 challenge는 폐기하므로 화면에서 다시 시작해야 한다.
동기화 패스키의 0 카운터를 허용하며, 증가형 카운터의 역행은 거부한다.

## 세션과 패스키 관리

로그인 세션은 8시간 고정이며 자동 갱신하지 않는다. JWT는 `HS256`, issuer·audience·용도·모드와
만료 시각을 검증하고, DB에 유효한 세션이 있어야 사용할 수 있다.
JWT는 `__Host-` 접두사의 `HttpOnly; Secure; SameSite=Strict; Path=/` 쿠키에만 전달한다.
브라우저 스토리지에 토큰을 저장하지 않는다. 로그아웃하면 서버 세션도 폐기한다.

추가 등록이 완료되면 해당 브라우저의 기존 세션을 교체한다. 마지막 패스키는 삭제할 수 없다.
패스키 삭제 시 다른 기기를 포함한 모든 세션을 폐기하고 남은 패스키로 다시 로그인하게 한다.

관리 API는 공개 API의 wildcard CORS에서 제외한다. 다른 Origin과 외부 preflight는 거부하며,
모든 변경 요청에는 정확한 Origin과 JSON Content-Type이 필요하다.
세션을 변경하는 작업은 세션에 묶인 CSRF 토큰도 검증한다.
관리자 HTML·JS·CSS 및 API 응답은 캐시하지 않으며 외부 프레임 삽입을 차단한다.

인증 변경 요청은 프로세스별로 클라이언트 주소당 분당 30회, 전체 분당 120회로 제한한다.
제한 초과 시 `429`와 `Retry-After: 60`을 반환하며 요청 본문은 최대 64 KiB다.
원본 주소를 DB에 저장하지 않는다. 임의의 `X-Forwarded-For` 헤더를 직접 신뢰하지 않는다.
기존 nginx 구성에서는 여러 사용자가 프록시 주소 하나로 합산될 수 있다.
워커별 메모리 제한이므로 여러 워커·서버에서는 공통 제한 저장소나 프록시 제한을 별도로 구성한다.

## 수동 JWT 대체 모드

패스키를 사용할 수 없는 운영 환경에서 운영자가 `GIFTTAX_ADMIN_MODE=manual_jwt`로 설정하고
서비스를 재시작한다. 브라우저 오류나 패스키 취소만으로 자동 전환하지 않는다.
Origin과 서명 비밀은 이 모드에서도 필수다. RP ID는 필요하지 않다.

```bash
docker compose --env-file /etc/gifttax/gifttax.env exec gifttax python -m backend.admin issue-login-token
```

서버에서 발급한 JWT를 `/admin`에 입력하면 5분 유효·1회 사용 토큰을 8시간 세션 쿠키로
교환한다. 재발급하면 이전 미사용 토큰은 폐기된다. 동시 교환 요청 중 하나만 성공한다.
JWT 문자열을 쿠키나 Authorization 헤더에 직접 넣어 로그인할 수 없다.
서버 터미널에 접근할 수 있어야 새 토큰을 발급할 수 있으며, 공개 토큰 발급 API는 없다.
패스키 모드에서는 토큰 발급과 교환을 거부하고, 대체 모드에서는 패스키 등록·로그인을 거부한다.

## 분실·침해·백업 복원 후 복구

```bash
docker compose --env-file /etc/gifttax/gifttax.env exec gifttax python -m backend.admin reset-auth
```

이 명령은 관리자 계정·패스키·모든 세션·등록 코드·로그인 토큰·challenge를 삭제한다.
후기·연락처·이용 통계는 보존한다. 관리자 설정이 누락되어도 서버에서 복구 명령을 사용할 수 있다.
DB 초기화와 Alembic 상태가 정상이어야 하며, 다른 버전 DB를 자동 변환하지 않는다.
분실 시 패스키 모드에서 새 등록 코드를 발급하고 재등록한다.
비밀 유출이 의심되면 서명 비밀도 교체하고 서비스를 재시작한 뒤 재등록한다.

## 로컬 개발과 검증

기존 개발 DB에 제거된 Alembic revision이 있으면 [저장소 안내](FEEDBACK_OPERATIONS.md)에 따라
새 빈 DB 경로를 사용한다. 기존 DB를 자동으로 삭제하거나 초기화하지 않는다.
프로젝트 루트에서 다음 환경을 앱과 CLI 양쪽에 전달한다.

```bash
export GIFTTAX_DATABASE_PATH="$PWD/.local/admin-dev.sqlite3"
export GIFTTAX_ADMIN_ORIGIN=http://localhost:8000
export GIFTTAX_ADMIN_RP_ID=localhost
export GIFTTAX_ADMIN_JWT_SECRET="$(uv run --no-sync python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export GIFTTAX_ADMIN_ALLOW_INSECURE_LOCALHOST=true
uv run --no-sync python -m backend.admin issue-registration-code
uv run --no-sync uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

`http://localhost:8000/admin`에서 접속한다. 명시적 로컬 HTTP 예외에서만 `Secure`와
`__Host-` 접두사를 사용하지 않으며, 이 설정은 운영에 적용하지 않는다.

자동 테스트는 실제 P-256 키·CBOR 등록 응답·서명된 인증 응답으로 검증한다.
실제 기기에서는 최초 등록 → 로그아웃 → 패스키 로그인 → 예비 키 추가 → 키 삭제 후
재로그인 → 서버 복구 후 재등록을 확인한다. 생체인증·보안 키 동작은 실제 지원 기기가 필요하다.

참조: [py_webauthn 등록](https://duo-labs.github.io/py_webauthn/registration.html),
[인증](https://duo-labs.github.io/py_webauthn/authentication.html),
[PyJWT 사용법](https://pyjwt.readthedocs.io/en/stable/usage.html).
