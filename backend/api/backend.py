import io
import os
import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.integrations.scraper.yahoo import InvalidTickerError
from backend.pdf.generator import exchange_rate_pdf as pdf_generator
from backend.pdf.generator import gift_calculation_pdf as gift_pdf_generator
from backend.schemas import GiftCalculationInput, GiftCalculationResult
from backend.services import calculator
from backend.services.instruments import InstrumentError

r = backend_router = APIRouter(prefix="/api")

STORAGE_DIR = "/tmp/gifttax"


@r.get("/health")
async def health_check():
    return {"status": "ok"}


def _save_pdf(output: io.BytesIO, kind: Literal["gift", "rate"]) -> str:
    """BytesIO PDF를 스토리지에 저장하고 file_id를 반환한다."""
    os.makedirs(STORAGE_DIR, exist_ok=True)
    file_id = f"{kind}-{uuid.uuid4()}"
    pdf_path = Path(STORAGE_DIR) / f"{file_id}.pdf"
    pdf_path.write_bytes(output.getvalue())
    return file_id


def _delete_pdf(file_id: str) -> None:
    """스토리지에서 PDF 파일을 삭제한다."""
    Path(STORAGE_DIR, f"{file_id}.pdf").unlink(missing_ok=True)


@r.post("/calculate")
async def calculate_gift(input_data: GiftCalculationInput) -> GiftCalculationResult:
    # 프론트엔드에서 이전 계산의 file_id를 전달하면 해당 파일을 먼저 정리한다
    try:
        result = calculator.calculate_total_gift(input_data)

        # 계산 증빙 PDF 생성
        gift_output = io.BytesIO()
        gift_pdf_generator.generate_pdf_gift_calculation(result, gift_output)

        # 매매기준환율 PDF 생성
        rate_output = io.BytesIO()
        pdf_generator.generate_pdf_exchange_rate_report(
            result.exchange_rate_evidence, result.gift_date, rate_output
        )
        # 모든 종목 계산과 두 PDF 생성이 성공한 후에만 다운로드 파일을 저장한다.
        gift_pdf_file_id = _save_pdf(gift_output, "gift")
        try:
            rate_pdf_file_id = _save_pdf(rate_output, "rate")
        except Exception:
            _delete_pdf(gift_pdf_file_id)
            raise

        result.gift_pdf_file_id = gift_pdf_file_id
        result.rate_pdf_file_id = rate_pdf_file_id

        return result

    except InvalidTickerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InstrumentError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"code": e.code, "message": str(e), "ticker": e.ticker},
        ) from e
    except calculator.CalculationUnavailableError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INSUFFICIENT_POST_GIFT_WINDOW",
                "message": str(e),
                "available_from": e.available_from.isoformat(),
                "gift_date": e.gift_date.isoformat(),
                "ticker": e.ticker,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@r.get("/download/{file_id}")
async def download_file(file_id: str):
    file_path = Path(STORAGE_DIR) / f"{file_id}.pdf"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        file_path,
        media_type="application/octet-stream",
        filename=f"gifttax_{file_id}.pdf",
        background=BackgroundTask(lambda p: p.unlink(missing_ok=True), file_path),
    )


@r.delete("/download/{file_id}", status_code=204)
async def delete_file(file_id: str):
    """미다운로드 PDF 파일을 삭제한다. 파일이 없어도 성공으로 처리한다."""
    _delete_pdf(file_id)
