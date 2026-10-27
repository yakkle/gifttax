import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError

from backend.api.admin import auth_error_handler, storage_error_handler, validation_error_handler
from backend.api.routes import router
from backend.middleware.admin_security import AdminBoundaryMiddleware, AdminRateLimiter
from backend.services.admin_sessions import AdminAuthError
from backend.services.retention import maintain_storage
from backend.settings import Settings
from backend.storage.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    database = Database(settings.database_path)
    app.state.database = database
    app.state.admin_limiter = AdminRateLimiter()
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
        database.dispose()


app = FastAPI(title="StockTax", description="해외주식 증여 금액 계산기", lifespan=lifespan)

app.add_middleware(AdminBoundaryMiddleware)
app.add_exception_handler(AdminAuthError, auth_error_handler)
app.add_exception_handler(SQLAlchemyError, storage_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.include_router(router)
