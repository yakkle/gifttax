"""Safe HTTP errors for private admin APIs and public feedback submission."""

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from backend.services.feedback import FeedbackError


async def feedback_error_handler(request: Request, error: FeedbackError) -> JSONResponse:
    return JSONResponse({"detail": {"code": error.code, "message": str(error)}}, status_code=422)


async def storage_error_handler(request: Request, error: SQLAlchemyError) -> JSONResponse:
    if request.url.path.startswith("/api/admin"):
        message = "관리자 저장소를 사용할 수 없습니다. DB 상태를 확인해 주세요."
    elif request.url.path == "/api/feedback":
        message = "의견을 저장하지 못했습니다. 잠시 후 다시 시도해 주세요."
    else:
        raise error
    return JSONResponse(
        {"detail": {"code": "STORAGE_UNAVAILABLE", "message": message}}, status_code=503
    )


async def validation_error_handler(request: Request, error: RequestValidationError) -> JSONResponse:
    if not request.url.path.startswith("/api/admin") and request.url.path != "/api/feedback":
        return await request_validation_exception_handler(request, error)
    # Pydantic errors include input values; never echo contact details or admin secrets.
    return JSONResponse(
        {"detail": {"code": "INVALID_REQUEST", "message": "입력 내용을 확인해 주세요."}},
        status_code=422,
    )
