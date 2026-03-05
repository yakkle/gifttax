import io
import os
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from stocktax.models import GiftCalculationInput, GiftCalculationResult
from stocktax.services import calculator
from stocktax.services.generator import excel as excel_generator
from stocktax.services.generator import pdf as pdf_generator
from stocktax.services.scraper import smbs
from stocktax.services.scraper import yahoo as scraper
from stocktax.services.scraper.yahoo import InvalidTickerError

app = FastAPI(title="StockTax", description="해외주식 증여 금액 계산기")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE_DIR = "/tmp/stocktax"

FRONTEND_PATHS = [
    Path("/app/frontend"),
    Path("frontend"),
    Path("../frontend"),
]

frontend_path = None
for p in FRONTEND_PATHS:
    if p.exists():
        frontend_path = p
        break


@app.get("/")
@app.get("/index")
async def root():
    if frontend_path:
        index_file = frontend_path / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text())
    return HTMLResponse(
        content="<h1>StockTax API</h1><p>Go to <a href='/docs'>/docs</a> for API docs</p>"
    )


@app.get("/app.js")
async def app_js():
    if frontend_path:
        js_file = frontend_path / "app.js"
        if js_file.exists():
            return HTMLResponse(content=js_file.read_text(), media_type="application/javascript")
    return HTMLResponse(content="Not Found", status_code=404)


@app.get("/style.css")
async def style_css():
    if frontend_path:
        css_file = frontend_path / "style.css"
        if css_file.exists():
            return HTMLResponse(content=css_file.read_text(), media_type="text/css")
    return HTMLResponse(content="Not Found", status_code=404)


@app.post("/api/calculate")
async def calculate_gift(input_data: GiftCalculationInput) -> GiftCalculationResult:
    try:
        result = calculator.calculate_total_gift(input_data)
        return result
    except InvalidTickerError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-excel")
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


@app.post("/api/generate-pdf")
async def generate_pdf(input_data: GiftCalculationInput):
    os.makedirs(STORAGE_DIR, exist_ok=True)

    file_id = str(uuid.uuid4())
    pdf_path = f"{STORAGE_DIR}/{file_id}.pdf"

    try:
        result = calculator.calculate_total_gift(input_data)

        currency = result.stocks[0].currency if result.stocks else "USD"
        gift_date = result.gift_date
        period_start = gift_date - timedelta(days=60)
        period_end = gift_date + timedelta(days=60)

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


@app.get("/api/download/{file_id}")
async def download_file(file_id: str):
    for ext in [".xlsx", ".pdf"]:
        file_path = Path(STORAGE_DIR) / f"{file_id}{ext}"
        if file_path.exists():
            return FileResponse(
                file_path,
                media_type="application/octet-stream",
                filename=f"stocktax_{file_id}{ext}",
            )

    raise HTTPException(status_code=404, detail="File not found")
