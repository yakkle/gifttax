import sys
from pathlib import Path

from api.router import router
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

# Ensure backend directory is in sys.path so we can import modules directly
# This helps running the app without manually setting PYTHONPATH
root_dir = Path(__file__).parent.parent
backend_dir = Path(__file__).parent

if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))


app = FastAPI(title="StockTax", description="해외주식 증여 금액 계산기")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

FRONTEND_PATHS = [
    Path("/app/frontend"),
    Path("frontend"),
    Path("../frontend"),
]

frontend_path = None
for p in FRONTEND_PATHS:
    # Resolve relative paths against the project root (parent of backend)
    actual_path = p if p.is_absolute() else root_dir / p
    if actual_path.exists():
        frontend_path = actual_path
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
