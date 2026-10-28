from typing import Annotated

from fastapi import APIRouter, Depends, Request

from backend.api.dependencies import admin_service, usage_service
from backend.schemas.usage import ClientUsageEvent, UsageSummary
from backend.services.admin_auth import AdminAuthService
from backend.services.usage import UsageService

usage_router = APIRouter(tags=["이용 통계"])
Service = Annotated[UsageService, Depends(usage_service)]
Admin = Annotated[AdminAuthService, Depends(admin_service)]


@usage_router.post("/api/events", status_code=204)
def record_event(input_data: ClientUsageEvent, request: Request, service: Service) -> None:
    service.record_client(input_data, request.state.usage_visitor_id)


@usage_router.get("/api/admin/usage", response_model=UsageSummary)
def summary(request: Request, service: Service, admin: Admin, days: int = 30) -> UsageSummary:
    admin.sessions.authenticate(request.cookies.get(admin.settings.session_cookie_name))
    return service.summary(days)
