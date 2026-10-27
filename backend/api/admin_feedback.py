from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from backend.api.dependencies import admin_feedback_service, require_admin_session
from backend.schemas.feedback import (
    FeedbackFilters,
    FeedbackPage,
    FeedbackStatusReceipt,
    FeedbackStatusUpdate,
)
from backend.services.admin_feedback import AdminFeedbackService

admin_feedback_router = APIRouter(
    prefix="/api/admin/feedback",
    tags=["의견 관리"],
    dependencies=[Depends(require_admin_session)],
)
Service = Annotated[AdminFeedbackService, Depends(admin_feedback_service)]


@admin_feedback_router.get("", response_model=FeedbackPage)
def list_feedback(filters: Annotated[FeedbackFilters, Depends()], service: Service) -> FeedbackPage:
    return service.list(filters)


@admin_feedback_router.patch("/{identifier}", response_model=FeedbackStatusReceipt)
def change_status(
    identifier: UUID, input_data: FeedbackStatusUpdate, service: Service
) -> FeedbackStatusReceipt:
    return service.change_status(identifier, input_data.status)


@admin_feedback_router.delete("/{identifier}", status_code=204)
def delete_feedback(identifier: UUID, service: Service) -> None:
    service.delete(identifier)
