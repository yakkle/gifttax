import io
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, FileResponse

from models import GiftCalculationInput, GiftCalculationResult
from services import calculator
from pdf.generator import excel as excel_generator
from pdf.generator import pdf as pdf_generator
from integrations.scraper import smbs
from integrations.scraper import yahoo as scraper
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


@router.post("/generate-excel")
async def generate_excel(input_data: GiftCalculationInput):
    os.makedirs(STORAGE_DIR, exist_ok=True)

    file_id = str(uuid.uuid4())
    excel_path = f"{STORAGE_DIR}/{file_id}.xlsx"

    try:
        result = calculator.calculate_total_gift(input_data)

        for stock_result in result.stocks:
            period_start = stock_result.period_start
            period_end = stock_result.period_end

            prices = scraper.get_stock_prices(
                stock_result.ticker,
                period_start,
                period_end,
            )

            output = io.BytesIO()
            excel_generator.generate_excel_stock_prices(
                stock_result.ticker,
                prices,
                output,
            )

            with open(excel_path, "wb") as f:
                f.write(output.getvalue())

        return JSONResponse({"file_id": file_id, "filename": f"stock_prices_{file_id}.xlsx"})

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
    for ext in [".xlsx", ".pdf"]:
        file_path = Path(STORAGE_DIR) / f"{file_id}{ext}"
        if file_path.exists():
            return FileResponse(
                file_path,
                media_type="application/octet-stream",
                filename=f"gifttax_{file_id}{ext}",
            )

    raise HTTPException(status_code=404, detail="File not found")
