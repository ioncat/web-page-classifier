"""JSON API роуты."""
import os
import pathlib
import re
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

import sys
from pathlib import Path
# Гарантируем, что web/ в sys.path (для запуска из папки web/)
_WEB_DIR = str(Path(__file__).resolve().parent.parent)
if _WEB_DIR not in sys.path:
    sys.path.insert(0, _WEB_DIR)

import database as db

router = APIRouter()

# ── Pipeline runner (in-memory state) ────────────────────────────────────────

_pipeline_state: dict = {
    "status": "idle",   # idle | running | done | error
    "step": None,       # "parse" | "classify" | None
    "progress": 0,      # 0–100 (общий)
    "step_done": 0,     # текущий счётчик в шаге
    "step_total": 0,    # сколько URL в шаге
    "last_line": "",    # последняя осмысленная строка вывода
    "error": None,
    "started_at": None,
    "finished_at": None,
}
_pipeline_lock = threading.Lock()

# step2/step3 с --no-progress печатают строки вида "[12/345] ..."
_PROGRESS_RE = re.compile(r"^\[(\d+)/(\d+)\]")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _do_run_pipeline(model: str | None = None) -> None:
    """Фоновый поток: step2 (parse) → step3 (classify).
    Потоково читает stdout, парсит "[N/M]" для прогресса.
    """
    python = _pipeline_python()
    main = str(_PROJECT_ROOT / "pipeline" / "main.py")
    env = {
        **os.environ,
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }

    classify_flags = ["--only-classify", "--no-progress"]
    if model:
        classify_flags += ["--model", model]

    steps = [
        ("parse",    ["--only-parse", "--no-progress"], 0,  50),
        ("classify", classify_flags,                    50, 100),
    ]

    for step_name, flags, base, cap in steps:
        with _pipeline_lock:
            _pipeline_state.update(
                step=step_name, progress=base,
                step_done=0, step_total=0, last_line="",
            )

        tail: deque[str] = deque(maxlen=40)
        try:
            proc = subprocess.Popen(
                [python, "-u", main] + flags,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # сливаем, чтобы не блокировать пайпы
                cwd=str(_PROJECT_ROOT / "pipeline"),
                env=env,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            with _pipeline_lock:
                _pipeline_state.update(
                    status="error", error=f"Не удалось запустить пайплайн: {exc}",
                    finished_at=_now(),
                )
            return

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\r\n")
            if not line:
                continue
            tail.append(line)
            m = _PROGRESS_RE.match(line)
            if m:
                done, total = int(m.group(1)), int(m.group(2))
                frac = done / total if total > 0 else 0.0
                overall = int(base + (cap - base) * frac)
                with _pipeline_lock:
                    _pipeline_state.update(
                        step_done=done, step_total=total,
                        progress=overall, last_line=line,
                    )
            else:
                with _pipeline_lock:
                    _pipeline_state["last_line"] = line

        rc = proc.wait()
        if rc != 0:
            with _pipeline_lock:
                _pipeline_state.update(
                    status="error",
                    error="\n".join(tail)[-1500:] or f"Exit code {rc}",
                    finished_at=_now(),
                )
            return

        with _pipeline_lock:
            _pipeline_state["progress"] = cap

    with _pipeline_lock:
        _pipeline_state.update(
            status="done", step=None, progress=100, finished_at=_now()
        )



# Корень проекта — директория, из которой запускается uvicorn
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _pipeline_python() -> str:
    """Абсолютный путь к Python-интерпретатору пайплайна."""
    env = os.getenv("PIPELINE_PYTHON")
    if env:
        return str(pathlib.Path(env).resolve())
    for candidate in (
        "pipeline/venv/Scripts/python.exe",
        "pipeline/venv/bin/python",
        "venv/Scripts/python.exe",
        "venv/bin/python",
    ):
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
        env = {
        **os.environ,
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }
        result = subprocess.run(
            [_pipeline_python(), "-c", script],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(_PROJECT_ROOT / "pipeline"),
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


# ── Управление таксономией ────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    section: str

class CategoryRename(BaseModel):
    old_name: str
    new_name: str

class CategoryMoveSection(BaseModel):
    name: str
    section: str

class CategoryDelete(BaseModel):
    name: str
    reassign_to: str | None = None


@router.post("/taxonomy/create")
def taxonomy_create(body: CategoryCreate):
    ok, error = db.create_category(body.name, body.section)
    if not ok:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True}


@router.post("/taxonomy/rename")
def taxonomy_rename(body: CategoryRename):
    ok, error, urls_updated = db.rename_category(body.old_name, body.new_name)
    if not ok:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True, "urls_updated": urls_updated}


@router.post("/taxonomy/move-section")
def taxonomy_move_section(body: CategoryMoveSection):
    if not db.change_category_section(body.name, body.section):
        raise HTTPException(status_code=404, detail="Категория не найдена")
    return {"ok": True}


@router.post("/taxonomy/delete")
def taxonomy_delete(body: CategoryDelete):
    ok, error, urls_affected = db.delete_category(body.name, body.reassign_to)
    if not ok:
        raise HTTPException(status_code=400, detail=error)
    return {"ok": True, "urls_affected": urls_affected}


# ── Добавление URL ────────────────────────────────────────────────────────────

class AddUrlsBody(BaseModel):
    text: str


@router.post("/add/urls")
def add_urls(body: AddUrlsBody):
    """Парсит сырой текст с URL, вставляет в БД как pending."""
    return db.insert_urls_bulk(body.text)


@router.post("/add/extract")
def add_extract(body: AddUrlsBody):
    """Извлекает URL из текста без записи в БД (предпросмотр)."""
    return {"urls": db.extract_urls(body.text)}


# ── Запуск пайплайна ──────────────────────────────────────────────────────────

class PipelineRunBody(BaseModel):
    model: str | None = None


@router.post("/pipeline/run")
def pipeline_run(body: PipelineRunBody | None = None):
    """Запускает step2+step3 в фоновом потоке."""
    model = (body.model if body else None) or None
    with _pipeline_lock:
        if _pipeline_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Pipeline already running")
        _pipeline_state.update(
            status="running", step="parse", progress=0,
            step_done=0, step_total=0, last_line="",
            error=None, started_at=_now(), finished_at=None,
        )
    threading.Thread(target=_do_run_pipeline, args=(model,), daemon=True).start()
    return {"ok": True}


OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


@router.get("/models")
def list_models():
    """Список моделей Ollama через REST (без зависимости от `ollama` пакета)."""
    import urllib.request
    import json as _json
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5) as r:
            data = _json.loads(r.read())
        names = [m.get("name") or m.get("model") for m in data.get("models", [])]
        return {"models": [n for n in names if n]}
    except Exception as exc:
        return {"models": [], "error": str(exc)}


@router.get("/pipeline/status")
def pipeline_status():
    """Возвращает текущее состояние пайплайна."""
    with _pipeline_lock:
        return dict(_pipeline_state)
