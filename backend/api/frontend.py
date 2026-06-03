from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

r = frontend_router = APIRouter()


root_dir = Path(__file__).parent.parent

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


@r.get("/")
@r.get("/index")
async def root():
    if frontend_path:
        index_file = frontend_path / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text())
    return HTMLResponse(
        content="<h1>StockTax API</h1><p>Go to <a href='/docs'>/docs</a> for API docs</p>"
    )


@r.get("/app.js")
async def app_js():
    if frontend_path:
        js_file = frontend_path / "app.js"
        if js_file.exists():
            return HTMLResponse(content=js_file.read_text(), media_type="application/javascript")
    return HTMLResponse(content="Not Found", status_code=404)


@r.get("/style.css")
async def style_css():
    if frontend_path:
        css_file = frontend_path / "style.css"
        if css_file.exists():
            return HTMLResponse(content=css_file.read_text(), media_type="text/css")
    return HTMLResponse(content="Not Found", status_code=404)
