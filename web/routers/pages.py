"""HTML роуты (Jinja2 шаблоны)."""
from pathlib import Path
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import sys
_WEB_DIR = str(Path(__file__).resolve().parent.parent)
if _WEB_DIR not in sys.path:
    sys.path.insert(0, _WEB_DIR)

import database as db

_BASE = Path(__file__).resolve().parent.parent

router = APIRouter()
templates = Jinja2Templates(directory=str(_BASE / "templates"))


def _all_categories() -> list[dict]:
    return db.get_categories_with_counts()


def _common_ctx() -> dict:
    """Общий контекст для всех шаблонов."""
    return {
        "taxonomy": db.get_taxonomy(),
        "taxonomy_sections": db.get_taxonomy_sections(),
    }


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
        **_common_ctx(),
    })


@router.get("/category/{category_name}", response_class=HTMLResponse)
def category(
    request: Request,
    category_name: str,
    page: int = Query(default=1, ge=1),
    sort: str = Query(default=db.SORT_DEFAULT),
):
    data = db.get_urls_by_category(category_name, page=page, sort=sort)
    all_categories = _all_categories()
    return templates.TemplateResponse("category.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": category_name,
        "sort": sort,
        "sort_options": db.SORT_OPTIONS,
        **data,
        **_common_ctx(),
    })


@router.get("/recent", response_class=HTMLResponse)
def recent(
    request: Request,
    page: int = Query(default=1, ge=1),
    sort: str = Query(default=db.SORT_DEFAULT),
):
    data = db.get_recent_urls(page=page, sort=sort)
    all_categories = _all_categories()
    return templates.TemplateResponse("recent.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": None,
        "sort": sort,
        "sort_options": db.SORT_OPTIONS,
        **data,
        **_common_ctx(),
    })


@router.get("/uncategorized", response_class=HTMLResponse)
def uncategorized(
    request: Request,
    page: int = Query(default=1, ge=1),
    sort: str = Query(default=db.SORT_DEFAULT),
):
    data = db.get_uncategorized_urls(page=page, sort=sort)
    all_categories = _all_categories()
    return templates.TemplateResponse("uncategorized.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": None,
        "sort": sort,
        "sort_options": db.SORT_OPTIONS,
        **data,
        **_common_ctx(),
    })


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    q: str = Query(default=""),
    category: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    sort: str = Query(default=db.SORT_DEFAULT),
):
    data = db.search_urls(query=q, category=category, page=page, sort=sort)
    all_categories = _all_categories()
    return templates.TemplateResponse("search.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": category or None,
        "q": q,
        "sort": sort,
        "sort_options": db.SORT_OPTIONS,
        **data,
        **_common_ctx(),
    })


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    all_categories = _all_categories()
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": None,
        **_common_ctx(),
    })


@router.get("/categories", response_class=HTMLResponse)
def categories_manage(request: Request):
    """Страница управления таксономией."""
    all_categories = _all_categories()
    managed = db.get_categories_managed()
    sections = db.get_sections()

    # Группируем по разделам в Python — не в шаблоне
    grouped: list[dict] = []
    idx: dict[str, int] = {}
    for cat in managed:
        s = cat["section"]
        if s not in idx:
            idx[s] = len(grouped)
            grouped.append({"section": s, "cats": []})
        grouped[idx[s]]["cats"].append(cat)

    return templates.TemplateResponse("categories.html", {
        "request": request,
        "all_categories": all_categories,
        "active_category": None,
        "grouped": grouped,
        "sections": sections,
        "all_managed": managed,
        **_common_ctx(),
    })
