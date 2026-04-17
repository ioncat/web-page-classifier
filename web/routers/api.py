"""JSON API роуты."""
import os
import pathlib
import re
import subprocess
import threading
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
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


def _do_run_pipeline(
    model: str | None = None,
    batch: int | None = None,
    workers: int | None = None,
    retry_failed: bool = False,
    retry_transient: bool = False,
) -> None:
    """Фоновый поток: step2 (parse) → step3 (classify).
    Потоково читает stdout, парсит "[N/M]" для прогресса.
    retry_failed — сбрасывает все error → pending.
    retry_transient — сбрасывает только 5xx/429/сетевые → pending.
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

    parse_flags = ["--only-parse", "--no-progress"]
    if retry_transient:
        parse_flags += ["--retry-transient"]
    elif retry_failed:
        parse_flags += ["--retry-failed"]
    if workers and workers > 1:
        parse_flags += ["--workers", str(workers)]

    classify_flags = ["--only-classify", "--no-progress"]
    if model:
        classify_flags += ["--model", model]
    if batch and batch > 1:
        classify_flags += ["--batch", str(batch)]
    if workers and workers > 1:
        classify_flags += ["--workers", str(workers)]

    steps = [
        ("parse",    parse_flags,    0,  50),
        ("classify", classify_flags, 50, 100),
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
    batch: int | None = None
    workers: int | None = None
    retry_failed: bool = False
    retry_transient: bool = False


def _do_refetch_missing(workers: int | None = None) -> None:
    """Фоновый поток: запускает main.py --refetch-description.
    Дозаполняет title/description у done-URL где они пустые.
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

    flags = ["--refetch-description", "--no-progress"]
    if workers and workers > 1:
        flags += ["--workers", str(workers)]

    with _pipeline_lock:
        _pipeline_state.update(
            step="refetch", progress=0,
            step_done=0, step_total=0, last_line="",
        )

    tail: deque[str] = deque(maxlen=40)
    try:
        proc = subprocess.Popen(
            [python, "-u", main] + flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT / "pipeline"),
            env=env,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as exc:
        with _pipeline_lock:
            _pipeline_state.update(
                status="error", error=f"Не удалось запустить: {exc}",
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
            with _pipeline_lock:
                _pipeline_state.update(
                    step_done=done, step_total=total,
                    progress=int(100 * frac), last_line=line,
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
        _pipeline_state.update(
            status="done", step=None, progress=100, finished_at=_now()
        )


@router.post("/pipeline/refetch-missing")
def pipeline_refetch_missing(workers: int | None = None):
    """Дозаполняет title/description у done-URL где они пустые."""
    if workers is not None and not (1 <= workers <= 16):
        raise HTTPException(status_code=400, detail="workers must be in 1..16")
    with _pipeline_lock:
        if _pipeline_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Pipeline already running")
        _pipeline_state.update(
            status="running", step="refetch", progress=0,
            step_done=0, step_total=0, last_line="",
            error=None, started_at=_now(), finished_at=None,
        )
    threading.Thread(
        target=_do_refetch_missing,
        kwargs={"workers": workers},
        daemon=True,
    ).start()
    return {"ok": True}


@router.post("/pipeline/run")
def pipeline_run(body: PipelineRunBody | None = None):
    """Запускает step2+step3 в фоновом потоке."""
    model = body.model if body else None
    batch = body.batch if body else None
    workers = body.workers if body else None
    retry_failed = body.retry_failed if body else False
    retry_transient = body.retry_transient if body else False
    # Санитизация
    if batch is not None and not (1 <= batch <= 100):
        raise HTTPException(status_code=400, detail="batch must be in 1..100")
    if workers is not None and not (1 <= workers <= 16):
        raise HTTPException(status_code=400, detail="workers must be in 1..16")
    with _pipeline_lock:
        if _pipeline_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Pipeline already running")
        _pipeline_state.update(
            status="running", step="parse", progress=0,
            step_done=0, step_total=0, last_line="",
            error=None, started_at=_now(), finished_at=None,
        )
    threading.Thread(
        target=_do_run_pipeline,
        kwargs={"model": model, "batch": batch, "workers": workers,
                "retry_failed": retry_failed,
                "retry_transient": retry_transient},
        daemon=True,
    ).start()
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


# ── Backup БД ─────────────────────────────────────────────────────────────────

@router.post("/db/backup")
def db_backup_create(reason: str = Query("manual", max_length=20)):
    """Создаёт бэкап БД и возвращает метаданные созданного файла."""
    try:
        path = db.backup_db(reason=reason)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Не удалось создать бэкап: {exc}")
    st = path.stat()
    return {"name": path.name, "size": st.st_size, "mtime": st.st_mtime}


@router.get("/db/backups")
def db_backup_list():
    return {"backups": db.list_backups()}


@router.get("/db/backup/download")
def db_backup_download(name: str | None = None):
    """Скачивает бэкап. Без `name` — создаёт свежий и отдаёт его."""
    if name:
        safe = re.sub(r"[^a-zA-Z0-9._-]", "", name)
        path = pathlib.Path(db._BACKUP_DIR) / safe
        if not path.exists() or path.parent != pathlib.Path(db._BACKUP_DIR):
            raise HTTPException(status_code=404, detail="Бэкап не найден")
    else:
        path = db.backup_db(reason="download")
    return FileResponse(
        path=str(path),
        filename=path.name,
        media_type="application/octet-stream",
    )


# ── Benchmark runner ──────────────────────────────────────────────────────────

# Must mirror CONFIGS in pipeline/benchmark/benchmark.py
BENCHMARK_CONFIGS: list[dict] = [
    {"batch": 1,  "workers": 1, "label": "baseline"},
    {"batch": 1,  "workers": 2, "label": "parallel ×2"},
    {"batch": 1,  "workers": 4, "label": "parallel ×4"},
    {"batch": 5,  "workers": 1, "label": "batch=5"},
    {"batch": 10, "workers": 1, "label": "batch=10"},
    {"batch": 5,  "workers": 4, "label": "batch=5 ×4"},
    {"batch": 10, "workers": 4, "label": "batch=10 ×4"},
    {"batch": 20, "workers": 4, "label": "batch=20 ×4"},
    {"batch": 10, "workers": 8, "label": "batch=10 ×8"},
    {"batch": 20, "workers": 8, "label": "batch=20 ×8"},
]

_bench_state: dict = {
    "status": "idle",        # idle | running | done | error
    "current_idx": -1,       # индекс текущей конфигурации в selected_configs
    "current_done": 0,
    "current_total": 0,
    "last_line": "",
    "results": [],           # list[{batch, workers, label, done, elapsed, rps}]
    "winner": None,          # {batch, workers, rps}
    "error": None,
    "started_at": None,
    "finished_at": None,
    "has_snapshot": False,   # обновляется на /status
}
_bench_lock = threading.Lock()

_BENCH_CFG_RE    = re.compile(r"batch=(\d+)\s+workers=(\d+)")
_BENCH_RESULT_RE = re.compile(r"→\s*(\d+)/(\d+)\s+URL\s+за\s+([\d.]+)\s*с\s*=\s*([\d.]+)\s*URL/с")
_BENCH_PROG_RE   = re.compile(r"\[(\d+)/(\d+)\]")


def _do_benchmark(
    model: str | None,
    limit: int,
    selected_idx: list[int],
    no_warmup: bool,
) -> None:
    """Фоновый поток: snapshot → benchmark.py subprocess → restore в finally."""
    python = _pipeline_python()
    bench = str(_PROJECT_ROOT / "pipeline" / "benchmark" / "benchmark.py")
    env = {
        **os.environ,
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }

    selected_configs = [BENCHMARK_CONFIGS[i] for i in selected_idx]

    # Страховка: бэкап БД перед snapshot.
    try:
        db.backup_db(reason="benchmark")
    except Exception as exc:
        with _bench_lock:
            _bench_state.update(
                status="error",
                error=f"Не удалось создать бэкап БД: {exc}",
                finished_at=_now(),
            )
        return

    # Snapshot.
    try:
        db.benchmark_snapshot(limit)
    except ValueError as exc:
        with _bench_lock:
            _bench_state.update(
                status="error", error=str(exc), finished_at=_now(),
            )
        return
    except Exception as exc:
        with _bench_lock:
            _bench_state.update(
                status="error",
                error=f"Snapshot failed: {exc}",
                finished_at=_now(),
            )
        return

    flags = ["--limit", str(limit)]
    if model:
        flags += ["--model", model]
    if no_warmup:
        flags += ["--no-warmup"]
    flags += ["--only"] + [str(i) for i in selected_idx]

    tail: deque[str] = deque(maxlen=80)
    rc = -1
    try:
        try:
            proc = subprocess.Popen(
                [python, "-u", bench] + flags,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(_PROJECT_ROOT / "pipeline"),
                env=env,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except Exception as exc:
            with _bench_lock:
                _bench_state.update(
                    status="error",
                    error=f"Не удалось запустить benchmark.py: {exc}",
                    finished_at=_now(),
                )
            return

        assert proc.stdout is not None
        current_cfg: dict | None = None

        for line in proc.stdout:
            line = line.rstrip("\r\n").strip()
            if not line:
                continue
            tail.append(line)

            # Начало новой конфигурации: "batch=X workers=Y"
            m_cfg = _BENCH_CFG_RE.search(line)
            if m_cfg:
                b, w = int(m_cfg.group(1)), int(m_cfg.group(2))
                idx = next(
                    (i for i, c in enumerate(selected_configs)
                     if c["batch"] == b and c["workers"] == w),
                    -1,
                )
                if idx >= 0:
                    current_cfg = selected_configs[idx]
                    with _bench_lock:
                        _bench_state.update(
                            current_idx=idx,
                            current_done=0, current_total=0,
                            last_line=line,
                        )
                    continue

            # Финал конфигурации: "→ done/total URL  за T с  =  R URL/с"
            m_res = _BENCH_RESULT_RE.search(line)
            if m_res and current_cfg is not None:
                done  = int(m_res.group(1))
                total = int(m_res.group(2))
                elap  = float(m_res.group(3))
                rps   = float(m_res.group(4))
                with _bench_lock:
                    _bench_state["results"].append({
                        "batch":   current_cfg["batch"],
                        "workers": current_cfg["workers"],
                        "label":   current_cfg["label"],
                        "done":    done,
                        "total":   total,
                        "elapsed": elap,
                        "rps":     rps,
                    })
                    _bench_state["last_line"] = line
                current_cfg = None
                continue

            # Прогресс step3: "[N/M] ..."
            m_prog = _BENCH_PROG_RE.match(line)
            if m_prog:
                done, total = int(m_prog.group(1)), int(m_prog.group(2))
                with _bench_lock:
                    _bench_state.update(
                        current_done=done, current_total=total, last_line=line,
                    )
                continue

            with _bench_lock:
                _bench_state["last_line"] = line

        rc = proc.wait()
    finally:
        # Restore всегда.
        try:
            db.benchmark_restore()
        except Exception as exc:
            with _bench_lock:
                _bench_state.update(
                    status="error",
                    error=f"Restore failed: {exc}",
                    finished_at=_now(),
                )
            return

    if rc != 0:
        with _bench_lock:
            _bench_state.update(
                status="error",
                error="\n".join(tail)[-1500:] or f"Exit code {rc}",
                finished_at=_now(),
            )
        return

    with _bench_lock:
        winner = max(
            _bench_state["results"],
            key=lambda r: r["rps"],
            default=None,
        )
        _bench_state.update(
            status="done",
            winner=({"batch": winner["batch"], "workers": winner["workers"], "rps": winner["rps"]}
                    if winner else None),
            finished_at=_now(),
        )


class BenchmarkRunBody(BaseModel):
    model: str | None = None
    limit: int = 30
    configs: list[int] = []
    no_warmup: bool = False


@router.post("/benchmark/run")
def benchmark_run(body: BenchmarkRunBody):
    if not body.configs:
        raise HTTPException(status_code=422, detail="Выберите хотя бы одну конфигурацию")
    if any(i < 0 or i >= len(BENCHMARK_CONFIGS) for i in body.configs):
        raise HTTPException(status_code=422, detail="Неверный индекс конфигурации")
    if not (10 <= body.limit <= 500):
        raise HTTPException(status_code=422, detail="limit must be in 10..500")

    eligible = db.benchmark_eligible_count()
    if eligible < body.limit:
        raise HTTPException(
            status_code=400,
            detail=f"В БД только {eligible} подходящих URL (нужно {body.limit}). "
                   f"Требуется status=done + title + category.",
        )

    with _bench_lock:
        if _bench_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Бенчмарк уже запущен")
        if db.benchmark_has_snapshot():
            raise HTTPException(
                status_code=409,
                detail="Остался snapshot с прошлого прогона. Сначала /api/benchmark/restore.",
            )
        _bench_state.update(
            status="running", current_idx=-1,
            current_done=0, current_total=0, last_line="",
            results=[], winner=None, error=None,
            started_at=_now(), finished_at=None,
        )

    threading.Thread(
        target=_do_benchmark,
        kwargs={
            "model":        body.model,
            "limit":        body.limit,
            "selected_idx": body.configs,
            "no_warmup":    body.no_warmup,
        },
        daemon=True,
    ).start()
    return {"ok": True}


@router.get("/benchmark/status")
def benchmark_status():
    with _bench_lock:
        state = dict(_bench_state)
    state["has_snapshot"] = db.benchmark_has_snapshot()
    state["configs"] = BENCHMARK_CONFIGS
    return state


@router.post("/benchmark/restore")
def benchmark_restore_manual():
    """Ручной откат snapshot (если subprocess упал и finally не сработал)."""
    with _bench_lock:
        if _bench_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Бенчмарк ещё работает")
    if not db.benchmark_has_snapshot():
        return {"ok": True, "restored": 0}
    n = db.benchmark_restore()
    return {"ok": True, "restored": n}


# ── Сравнение моделей ────────────────────────────────────────────────────────

_compare_state: dict = {
    "status": "idle",       # idle | running | done | error
    "current_model": None,  # имя текущей модели
    "model_idx": 0,         # индекс текущей модели (0-based)
    "models_total": 0,      # всего моделей
    "step_done": 0,         # URL обработано в текущей модели
    "step_total": 0,        # URL всего
    "last_line": "",
    "error": None,
    "started_at": None,
    "finished_at": None,
}
_compare_lock = threading.Lock()

_COMPARE_MODEL_RE = re.compile(r"^─+\s*(\S+)")  # Rule line "── model_name ──"


def _do_compare_models(
    models: list[str],
    limit: int,
    workers: int,
) -> None:
    """Фоновый поток: запускает main.py --compare-models m1 m2 --limit N --no-progress."""
    python = _pipeline_python()
    main = str(_PROJECT_ROOT / "pipeline" / "main.py")
    env = {
        **os.environ,
        "TERM": "dumb",
        "NO_COLOR": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
    }

    flags = [
        "--compare-models", *models,
        "--limit", str(limit),
        "--no-progress",
    ]
    if workers > 1:
        flags += ["--workers", str(workers)]

    tail: deque[str] = deque(maxlen=80)
    model_idx = -1

    try:
        proc = subprocess.Popen(
            [python, "-u", main] + flags,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=str(_PROJECT_ROOT / "pipeline"),
            env=env,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except Exception as exc:
        with _compare_lock:
            _compare_state.update(
                status="error",
                error=f"Не удалось запустить: {exc}",
                finished_at=_now(),
            )
        return

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\r\n")
        if not line:
            continue
        tail.append(line)

        # Прогресс "[N/M] ..."
        m = _PROGRESS_RE.match(line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            with _compare_lock:
                _compare_state.update(
                    step_done=done, step_total=total, last_line=line,
                )
            continue

        # Новая модель — строка содержит имя из нашего списка
        for i, model_name in enumerate(models):
            short = model_name.split(":")[0]
            if short in line and ("─" in line or "OK" not in line):
                # Проверяем что это Rule-линия с именем модели
                if "─" in line:
                    model_idx = i
                    with _compare_lock:
                        _compare_state.update(
                            current_model=model_name,
                            model_idx=i,
                            step_done=0, step_total=0,
                            last_line=line,
                        )
                    break

        # Итоговая строка модели "N OK  M ERR"
        if "OK" in line and "ERR" in line and model_idx >= 0:
            with _compare_lock:
                _compare_state["last_line"] = line
            continue

        with _compare_lock:
            _compare_state["last_line"] = line

    rc = proc.wait()
    if rc != 0:
        with _compare_lock:
            _compare_state.update(
                status="error",
                error="\n".join(tail)[-1500:] or f"Exit code {rc}",
                finished_at=_now(),
            )
        return

    with _compare_lock:
        _compare_state.update(
            status="done", current_model=None, finished_at=_now(),
        )


class CompareRunBody(BaseModel):
    models: list[str]
    limit: int = 30
    workers: int = 1


@router.post("/compare/run")
def compare_run(body: CompareRunBody):
    """Запускает сравнение нескольких моделей."""
    if len(body.models) < 2:
        raise HTTPException(status_code=422, detail="Выберите минимум 2 модели")
    if not (10 <= body.limit <= 500):
        raise HTTPException(status_code=422, detail="limit must be in 10..500")
    if body.workers < 1 or body.workers > 16:
        raise HTTPException(status_code=422, detail="workers must be in 1..16")

    with _compare_lock:
        if _compare_state["status"] == "running":
            raise HTTPException(status_code=409, detail="Сравнение уже запущено")
        _compare_state.update(
            status="running",
            current_model=body.models[0],
            model_idx=0,
            models_total=len(body.models),
            step_done=0, step_total=0,
            last_line="",
            error=None,
            started_at=_now(),
            finished_at=None,
        )

    threading.Thread(
        target=_do_compare_models,
        kwargs={
            "models": body.models,
            "limit": body.limit,
            "workers": body.workers,
        },
        daemon=True,
    ).start()
    return {"ok": True}


@router.get("/compare/status")
def compare_status():
    with _compare_lock:
        return dict(_compare_state)


@router.get("/compare/results")
def compare_results():
    """Возвращает pivot-таблицу результатов сравнения моделей."""
    return db.get_compare_results()


class AcceptModelBody(BaseModel):
    model: str


@router.post("/compare/accept")
def compare_accept(body: AcceptModelBody):
    """Принимает результаты выбранной модели как финальные."""
    n = db.accept_model_results(body.model)
    if n == 0:
        raise HTTPException(status_code=404, detail=f"Нет результатов для модели {body.model}")
    return {"ok": True, "updated": n}


@router.post("/compare/clear")
def compare_clear():
    """Очищает таблицу model_results."""
    n = db.clear_compare_results()
    return {"ok": True, "deleted": n}
