from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from backend.api.dependencies import feedback_service
from backend.schemas.feedback import FeedbackCreate, FeedbackReceipt
from backend.services.feedback import FeedbackService

feedback_router = APIRouter(prefix="/api/feedback", tags=["사용 의견"])
Service = Annotated[FeedbackService, Depends(feedback_service)]


@feedback_router.post(
    "",
    response_model=FeedbackReceipt,
    status_code=201,
    responses={200: {"model": FeedbackReceipt, "description": "이미 접수된 제출 ID"}},
)
def submit_feedback(
    input_data: FeedbackCreate, request: Request, response: Response, service: Service
) -> FeedbackReceipt:
    submission = service.submit(input_data)
    request.state.usage_event = submission.usage_event
    response.status_code = 201 if submission.created else 200
    return FeedbackReceipt(id=submission.id)
