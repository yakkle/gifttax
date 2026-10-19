import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routes import router
from backend.services.retention import maintain_storage
from backend.settings import Settings
from backend.storage.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    database = Database(settings.database_path)
    app.state.database = database
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


app = FastAPI(title="StockTax", description="해외주식 증여 금액 계산기", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
