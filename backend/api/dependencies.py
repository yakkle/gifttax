"""HTTP dependencies for validated settings and service construction."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from pydantic import ValidationError

from backend.services.admin_auth import AdminAuthService
from backend.services.admin_feedback import AdminFeedbackService
from backend.services.admin_sessions import SessionInfo
from backend.services.feedback import FeedbackService
from backend.services.usage import UsageService
from backend.settings import AdminSettings
from backend.storage.admin import AdminRepository
from backend.storage.feedback import AdminFeedbackRepository, FeedbackRepository


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


def feedback_service(request: Request) -> FeedbackService:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "의견 저장소를 사용할 수 없습니다."},
        )
    return FeedbackService(FeedbackRepository(database))


def require_admin_session(
    request: Request, service: Annotated[AdminAuthService, Depends(admin_service)]
) -> SessionInfo:
    session = service.sessions.authenticate(
        request.cookies.get(service.settings.session_cookie_name)
    )
    if request.method not in {"GET", "HEAD"}:
        service.sessions.verify_csrf(session, request.headers.get("x-csrf-token"))
    return session


def admin_feedback_service(request: Request) -> AdminFeedbackService:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "STORAGE_UNAVAILABLE", "message": "의견 저장소를 사용할 수 없습니다."},
        )
    return AdminFeedbackService(AdminFeedbackRepository(database))


def usage_service(request: Request) -> UsageService:
    service = getattr(request.app.state, "usage_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "STORAGE_UNAVAILABLE",
                "message": "통계 저장소를 사용할 수 없습니다.",
            },
        )
    return service
