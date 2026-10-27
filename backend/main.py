import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.api.admin import auth_error_handler
from backend.api.errors import (
    feedback_error_handler,
    storage_error_handler,
    usage_error_handler,
    validation_error_handler,
)
from backend.api.routes import router
from backend.middleware.admin_security import AdminBoundaryMiddleware
from backend.middleware.feedback import FeedbackBoundaryMiddleware
from backend.middleware.rate_limit import RateLimiter
from backend.middleware.usage import UsageMiddleware
from backend.services.admin_sessions import AdminAuthError
from backend.services.feedback import FeedbackError
from backend.services.retention import maintain_storage
from backend.services.usage import UsageError, UsageService
from backend.settings import Settings
from backend.storage.database import Database
from backend.storage.usage import UsageRepository


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    database = Database(settings.database_path)
    app.state.database = database
    app.state.admin_limiter = RateLimiter()
    app.state.feedback_limiter = RateLimiter(per_client=5, total=60)
    app.state.usage_limiter = RateLimiter(per_client=30, total=300)
    app.state.usage_service = UsageService(UsageRepository(database))
    stop = asyncio.Event()
    ready = asyncio.Event()
    maintenance = asyncio.create_task(
        maintain_storage(
            database,
            stop,
            interval_seconds=settings.retention_interval_seconds,
            ready=ready,
        )
    )
    try:
        await ready.wait()
        yield
    finally:
        stop.set()
        await maintenance
        del app.state.usage_service
        database.dispose()


app = FastAPI(title="StockTax", description="해외주식 증여 금액 계산기", lifespan=lifespan)

app.add_middleware(UsageMiddleware)
app.add_middleware(FeedbackBoundaryMiddleware)
app.add_middleware(AdminBoundaryMiddleware)
app.add_exception_handler(AdminAuthError, auth_error_handler)
app.add_exception_handler(FeedbackError, feedback_error_handler)
app.add_exception_handler(UsageError, usage_error_handler)
app.add_exception_handler(SQLAlchemyError, storage_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(router)
