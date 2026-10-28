# 후기·관리자 기능 배포 점검표

## 배포 전

- [ ] PR CI와 배포 CI의 Ruff, Python 테스트, Node 테스트가 모두 통과했다.
  두 workflow는 `ruff check .`, `uv run --no-sync pytest backend/tests/`,
  `node --test frontend/tests/*.test.js`를 실행한다. CI는 Python 3.13과 Node.js 24를 사용한다.
- [ ] 운영 환경 파일에 [관리자 필수 설정](ADMIN_AUTH.md#필수-설정)을 반영했다.
  `GIFTTAX_ADMIN_ORIGIN`은 실제 HTTPS 주소, `GIFTTAX_ADMIN_RP_ID`는 그 호스트다.
  `CERT_DOMAIN`은 인증서 디렉토리 이름이므로 RP ID와 다를 수 있다.
  기본 모드는 `webauthn`이며, `manual_jwt`는 운영자가 명시적으로 선택한다.
- [ ] 32바이트 이상의 무작위 JWT 서명 비밀을 설정하고 환경 파일 읽기 권한을 제한했다.
  기존 파일을 인증서 설정 예시로 덮어쓰지 않았다. `docker compose config`는 비밀을 출력하므로
  CI 로그나 공유 터미널에서 실행하지 않는다.
- [ ] `gifttax-data` 볼륨과 `/tmp/gifttax/feedback.sqlite3` 경로를 확인했다.
  첫 배포는 빈 DB에 Alembic `0001`을 적용한다. 레거시 변환은 제공하지 않는다.
  기존 데이터가 있다면 [SQLite 백업](FEEDBACK_OPERATIONS.md#백업과-복원)을 먼저 만들었다.
- [ ] 백엔드의 8000 포트가 외부에 열려 있지 않고 nginx만 접근한다.
  nginx가 전달 주소·프로토콜을 덮어쓰며 운영 환경에는 로컬 HTTP 인증 예외가 없다.

## 배포와 서버 확인

`main`에 반영하면 배포 workflow가 테스트 후 이미지를 빌드하고 서비스를 재시작한다.
수동 실행이 필요한 경우 프로젝트 루트에서 실행한다.

```bash
docker compose --env-file /etc/gifttax/gifttax.env build
docker compose --env-file /etc/gifttax/gifttax.env up -d --remove-orphans
docker compose --env-file /etc/gifttax/gifttax.env ps
docker compose --env-file /etc/gifttax/gifttax.env exec -T gifttax \
  python -c 'import json, urllib.request; response = urllib.request.urlopen("http://127.0.0.1:8000/api/health", timeout=5); assert response.status == 200; assert json.load(response)["status"] == "ok"'
docker compose --env-file /etc/gifttax/gifttax.env exec -T gifttax alembic current
```

- [ ] `alembic current`가 `0001 (head)`이며 시작 로그에 저장소·만료 정리 실패가 없다.
- [ ] 실제 도메인의 HTTPS `/api/health`가 `200 {"status":"ok"}`이고 인증서가 유효하다.
  HTTP는 HTTPS로 리다이렉트된다. CI의 내부 API 검사는 외부 TLS 정상 여부를 보장하지 않는다.
- [ ] `/`, `/admin`과 관리자 JS·CSS가 정상 제공된다.
  관리자 설정 누락 시 API는 `503 ADMIN_DISABLED`, 비로그인 시 비공개 조회는 `401`이다.
  `/api/health`는 DB 장애 시에도 정상일 수 있으므로 DB·관리자 확인을 생략하지 않는다.
- [ ] [최초 등록](ADMIN_AUTH.md#최초-패스키-등록)을 완료하고 예비 패스키를 등록했다.

## 브라우저·실제 기기 인수 확인

아래 항목은 자동 테스트 통과와 별도로 실제 대상 브라우저·기기에서 확인한다.
확인한 날짜, OS, 브라우저 버전과 결과를 배포 기록에 남기며 토큰·이메일·의견 원문은 기록하지 않는다.

| 흐름 | 확인할 결과 |
| --- | --- |
| 의견 작성 | 상단·계산 결과·오류 화면에서 열기, 만족도만/의견만 제출, 선택 연락처 동의, 중복 제출 방지 |
| 후원 안내 | 만족한 의견의 접수 후 링크 표시, 실제 클릭 시 통계 증가 |
| 화면과 키보드 | 좁은 모바일 화면, Tab 이동, 의견 폼 펼치기·접기, 후원 메뉴 Escape 닫기·초점 복귀, 오류 안내 |
| 계산·PDF | 정상 계산과 두 PDF 다운로드, 계산 가능일 이전 안내 |
| 패스키 등록·로그인 | 서버 등록 코드 → 기기 사용자 확인 → 로그아웃 → 패스키 로그인 |
| 패스키 관리·복구 | 예비 키 추가, 키 삭제 후 모든 세션 폐기, 마지막 키 삭제 차단, 서버 reset-auth 후 재등록 |
| JWT 대체 모드 | 명시적 모드 변경 후 토큰 교환, 일회 사용·재사용 거부, 로그아웃 |
| 관리자 조회 | 7·30·90일 통계, 의견 필터·페이지 이동·상태 변경·삭제·이메일 복사 |
| 세션 만료 | 다른 기기의 키 삭제/서버 reset-auth 후 다음 조회에서 로그아웃되고 화면의 비공개 정보 제거 |
| 재시작·복원 | 재시작 후 데이터 유지, 복원 시 공개 전 reset-auth, 과거 세션 거부, 사용자 데이터 보존 |

자동 Python 테스트는 실제 P-256 서명을 포함한 WebAuthn 검증과 API 정책을 확인한다.
Node 테스트는 DOM 모형으로 화면 로직을 확인한다. 실제 생체인증·보안 키 및 OS 패스키 UI는
지원 기기에서 직접 확인해야 한다. 미확인 항목은 완료 처리하지 않는다.

### 태스크 7 개발 검증 기록 (2026-10-27)

- Ruff와 Python 전체 269개 테스트 통과. 외부 환율 사이트를 호출하던 계산 테스트도 모킹했다.
- 프론트엔드 32개 테스트를 로컬 Node.js 20 및 CI와 같은 Node.js 24에서 통과했다.
- 로컬 Docker 이미지 빌드와 앱·정적 파일·Alembic·관리자 API 실행을 확인했다.
  위 백업·복원 문서의 Python 명령을 임시 DB에서 직접 실행했고,
  복원 후 의견 유지와 이전 세션 거부를 확인했다.
- 로컬 앱 브라우저에서 의견만/만족도만 접수, 만족 후기 후원 안내, JWT 로그인,
  통계·의견 조회, 상태 저장, 로그아웃을 확인했다.
- 실제 모바일 기기 화면과 기기의 패스키 등록·생체인증·보안 키 흐름, 운영 HTTPS 배포는 미확인이다.
  위 기록은 실제 기기 인수 확인을 대신하지 않는다.

## 장애 대응

- 관리자 설정 오류는 환경 파일을 수정해 컨테이너를 재생성한다. 공개 계산·PDF 제공은 유지된다.
- 패스키 분실·비밀 유출은 [인증 복구](ADMIN_AUTH.md#분실침해백업-복원-후-복구)를 따른다.
  DB 복원은 반드시 앱 정지 → 백업 검증·복원 → 인증 초기화 → 앱 시작 순서다.
- 코드 롤백 전 DB revision 호환성을 확인한다. 이전 코드와 현재 DB가 호환되지 않으면
  앱을 정지하고 해당 버전의 백업을 복원한다. `docker compose down -v`로 볼륨을 지우지 않는다.
- 통계는 익명 브라우저 기준이며 쿠키 삭제·차단·여러 기기 및 저장 실패로 실제 사람 수와 다를 수 있다.
  의견 저장과 통계 저장은 별도 작업이므로 일부 집계 누락은 접수 실패를 의미하지 않는다.
