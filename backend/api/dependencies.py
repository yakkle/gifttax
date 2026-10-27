"""HTTP dependencies for validated settings and admin service construction."""

from fastapi import HTTPException, Request
from pydantic import ValidationError

from backend.services.admin_auth import AdminAuthService
from backend.settings import AdminSettings
from backend.storage.admin import AdminRepository


def admin_settings() -> AdminSettings:
    try:
        return AdminSettings()
    except ValidationError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "ADMIN_DISABLED", "message": "관리자 인증 설정이 완료되지 않았습니다."},
        ) from error


def admin_service(request: Request) -> AdminAuthService:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORAGE_UNAVAILABLE",
                "message": "관리자 저장소를 사용할 수 없습니다.",
            },
        )
    return AdminAuthService(AdminRepository(database), admin_settings())
