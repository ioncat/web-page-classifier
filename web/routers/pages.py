"""HTML роуты (Jinja2 шаблоны)."""
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from web.auth import verify_auth
from web import database as db

router = APIRouter(dependencies=[Depends(verify_auth)])
templates = Jinja2Templates(directory="web/templates")


def _all_categories() -> list[dict]:
    return db.get_categories_with_counts()


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    categories = _all_categories()
    stats = db.get_stats()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "categories": categories,
        "all_categories": categories,
        "stats": stats,
        "active_category": None,
    })


@router.get("/category/{category_name}", response_class=HTMLResponse)
def category(request: Request, category_name: str, page: int = Query(default=1, ge=1)):
    data = db.get_urls_by_category(category_name, page=page)
    all_categories = _all_categories()
    return templates.TemplateResponse("category.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": category_name,
        **data,
    })


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = Query(default=""),
    category: str = Query(default=""),
    page: int = Query(default=1, ge=1),
):
    data = db.search_urls(query=q, category=category, page=page)
    all_categories = _all_categories()
    return templates.TemplateResponse("search.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": category or None,
        "q": q,
        **data,
    })
