"""티커 자동 판별을 위한 읽기 전용 API."""

from fastapi import APIRouter, HTTPException

from backend.schemas.instruments import InstrumentDetection
from backend.services.instruments import InstrumentError, lookup_instrument

instruments_router = APIRouter(prefix="/api/instruments", tags=["종목 조회"])


@instruments_router.get("/{ticker}", response_model=InstrumentDetection)
def get_instrument(ticker: str) -> InstrumentDetection:
    try:
        return lookup_instrument(ticker)
    except InstrumentError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": str(error), "ticker": error.ticker},
        ) from error
