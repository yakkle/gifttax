"""Server-only administrator bootstrap and recovery commands."""

import argparse
import sys

from alembic.util.exc import CommandError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.services.admin_auth import AdminAuthService, reset_admin_auth
from backend.services.admin_sessions import AdminAuthError
from backend.settings import AdminSettings, Settings
from backend.storage.admin import AdminRepository
from backend.storage.database import Database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="GiftTax 관리자 인증 설정 및 복구")
    parser.add_argument(
        "command", choices=["issue-registration-code", "issue-login-token", "reset-auth"]
    )
    args = parser.parse_args(argv)
    database = None
    try:
        database = Database(Settings().database_path)
        database.initialize()
        repository = AdminRepository(database)
        if args.command == "reset-auth":
            reset_admin_auth(repository)
            print("관리자 패스키·세션·일회용 토큰·인증 요청을 모두 폐기했습니다.")
        else:
            service = AdminAuthService(repository, AdminSettings())
            if args.command == "issue-registration-code":
                code = service.issue_registration_code()
                print("최초 등록 코드 (10분 유효·1회 사용):")
            else:
                code = service.sessions.issue_login_token()
                print("관리자 로그인 토큰 (5분 유효·1회 사용):")
            print(code)
        return 0
    except ValidationError:
        print("DB 경로와 관리자 인증 환경변수 설정을 확인해 주세요.", file=sys.stderr)
    except AdminAuthError as error:
        print(str(error), file=sys.stderr)
    except (SQLAlchemyError, CommandError, OSError):
        print(
            "관리자 저장소에 접근할 수 없습니다. DB 경로와 마이그레이션 상태를 확인해 주세요.",
            file=sys.stderr,
        )
    finally:
        if database is not None:
            database.dispose()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
