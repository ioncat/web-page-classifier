"""JSON API роуты."""
import os
import pathlib
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

import sys
from pathlib import Path
# Гарантируем, что web/ в sys.path (для запуска из папки web/)
_WEB_DIR = str(Path(__file__).resolve().parent.parent)
if _WEB_DIR not in sys.path:
    sys.path.insert(0, _WEB_DIR)

from auth import verify_auth
import database as db

router = APIRouter(dependencies=[Depends(verify_auth)])



# Корень проекта — директория, из которой запускается uvicorn
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _pipeline_python() -> str:
    """Абсолютный путь к Python-интерпретатору пайплайна."""
    env = os.getenv("PIPELINE_PYTHON")
    if env:
        return str(pathlib.Path(env).resolve())
    for candidate in ("venv/Scripts/python.exe", "venv/bin/python"):
        p = _PROJECT_ROOT / candidate
        if p.exists():
            return str(p)
    return "python"


def _run_refetch_for_url(url: str, timeout: int = 60) -> dict:
    """Сбрасывает URL в pending и перезагружает title + description через step2.

    Вызывает только существующие функции пайплайна:
      db.set_url_pending(url) → step2.main(urls=[url])
    Никакого импорта / step1 / raw_links.txt.
    """
    script = (
        "from db import init_db, set_url_pending; import step2; "
        "init_db(); "
        f"set_url_pending({url!r}); "
        f"step2.main(urls=[{url!r}], no_progress=True)"
    )
    try:
        env = {**os.environ, "TERM": "dumb", "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [_pipeline_python(), "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT),
            env=env,
        )
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout[-500:] if result.stdout else "",
            "stderr": result.stderr[-500:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "stdout": "", "stderr": "Timeout"}
    except Exception as exc:
        return {"ok": False, "stdout": "", "stderr": str(exc)}


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


class BulkDelete(BaseModel):
    ids: list[int]


@router.post("/bulk-delete")
def bulk_delete(body: BulkDelete):
    if not body.ids:
        raise HTTPException(status_code=422, detail="Список ids пустой")
    deleted = db.delete_urls_bulk(body.ids)
    return {"ok": True, "deleted": deleted}


class BulkIds(BaseModel):
    ids: list[int]


@router.post("/bulk-refetch")
def bulk_refetch(body: BulkIds):
    """Запуск пайплайна (step1+step2) для нескольких URL."""
    if not body.ids:
        raise HTTPException(status_code=422, detail="Список ids пустой")
    urls_map = db.get_urls_by_ids(body.ids)
    if not urls_map:
        raise HTTPException(status_code=404, detail="URL не найдены")
    ok_count = 0
    err_count = 0
    for url_id, url in urls_map.items():
        result = _run_refetch_for_url(url)
        if result["ok"]:
            ok_count += 1
        else:
            err_count += 1
    return {"ok": True, "processed": ok_count, "errors": err_count}


@router.post("/urls/{url_id}/refetch")
def refetch_url(url_id: int):
    """Запуск пайплайна (step1+step2) для одного URL."""
    url = db.get_url_by_id(url_id)
    if not url:
        raise HTTPException(status_code=404, detail="URL не найден")
    result = _run_refetch_for_url(url)
    if not result["ok"]:
        raise HTTPException(
            status_code=502,
            detail=f"Pipeline error: {result['stderr'][:200]}"
        )
    return {"ok": True, "url": url}


@router.delete("/urls/{url_id}")
def delete_url(url_id: int):
    if not db.delete_url(url_id):
        raise HTTPException(status_code=404, detail="URL не найден")
    return {"ok": True}


class CategoryUpdate(BaseModel):
    category: str


@router.patch("/urls/{url_id}/category")
def update_category(url_id: int, body: CategoryUpdate):
    if not body.category.strip():
        raise HTTPException(status_code=422, detail="Категория не может быть пустой")
    if not db.update_category(url_id, body.category.strip()):
        raise HTTPException(status_code=404, detail="URL не найден")
    return {"ok": True, "category": body.category.strip()}
