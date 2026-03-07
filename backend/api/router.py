import io
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse

from models import GiftCalculationInput, GiftCalculationResult
from services import calculator
from pdf.generator import pdf as pdf_generator
from pdf.generator import gift_calculation_pdf as gift_pdf_generator
from integrations.scraper import smbs
from integrations.scraper.yahoo import InvalidTickerError

router = APIRouter(prefix="/api")

STORAGE_DIR = "/tmp/gifttax"


@router.post("/calculate")
async def calculate_gift(input_data: GiftCalculationInput) -> GiftCalculationResult:
    try:
        result = calculator.calculate_total_gift(input_data)
        return result
    except InvalidTickerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-gift-pdf")
async def generate_gift_pdf(input_data: GiftCalculationInput):
    os.makedirs(STORAGE_DIR, exist_ok=True)

    file_id = str(uuid.uuid4())
    pdf_path = f"{STORAGE_DIR}/{file_id}.pdf"

    try:
        result = calculator.calculate_total_gift(input_data)

        output = io.BytesIO()
        gift_pdf_generator.generate_pdf_gift_calculation(result, output)

        with open(pdf_path, "wb") as f:
            f.write(output.getvalue())

        return JSONResponse({"file_id": file_id, "filename": f"gift_calculation_{file_id}.pdf"})

    except InvalidTickerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-pdf")
async def generate_pdf(input_data: GiftCalculationInput):
    os.makedirs(STORAGE_DIR, exist_ok=True)

    file_id = str(uuid.uuid4())
    pdf_path = f"{STORAGE_DIR}/{file_id}.pdf"

    try:
        result = calculator.calculate_total_gift(input_data)

        currency = result.stocks[0].currency if result.stocks else "USD"
        period_start, period_end = calculator.get_exchange_rate_pdf_period(
            result.exchange_rate_date
        )

        rates = smbs.get_exchange_rates(period_start, period_end, currency)

        output = io.BytesIO()
        pdf_generator.generate_pdf_exchange_rate(rates, currency, output)

        with open(pdf_path, "wb") as f:
            f.write(output.getvalue())

        return JSONResponse({"file_id": file_id, "filename": f"exchange_rate_{file_id}.pdf"})

    except InvalidTickerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/download/{file_id}")
async def download_file(file_id: str):
    file_path = Path(STORAGE_DIR) / f"{file_id}.pdf"
    if file_path.exists():
        return FileResponse(
            file_path,
            media_type="application/octet-stream",
            filename=f"gifttax_{file_id}.pdf",
        )

    raise HTTPException(status_code=404, detail="File not found")
