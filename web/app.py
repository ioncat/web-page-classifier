"""FastAPI точка входа Web UI."""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web.routers import pages, api

app = FastAPI(title="Web Page Classifier", docs_url=None, redoc_url=None)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

templates = Jinja2Templates(directory="web/templates")

app.include_router(pages.router)
app.include_router(api.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok"}
