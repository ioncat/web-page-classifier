"""JSON API роуты."""
from fastapi import APIRouter, Depends, HTTPException, Query

from web.auth import verify_auth
from web import database as db

router = APIRouter(dependencies=[Depends(verify_auth)])


@router.get("/categories")
def categories():
    return db.get_categories_with_counts()


@router.get("/urls")
def urls(
    q: str = Query(default=""),
    category: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
):
    return db.search_urls(query=q, category=category, page=page, per_page=per_page)


@router.get("/stats")
def stats():
    return db.get_stats()


@router.delete("/urls/{url_id}")
def delete_url(url_id: int):
    if not db.delete_url(url_id):
        raise HTTPException(status_code=404, detail="URL не найден")
    return {"ok": True}
