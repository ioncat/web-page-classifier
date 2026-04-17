"""Слой доступа к SQLite для Web UI.
Read-операции — просмотр данных.
Write-операции — только удаление и смена категории через UI.
"""
import os
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(_PROJECT_ROOT / "data" / "urls.db"))

def _ensure_categories_table(conn: sqlite3.Connection) -> None:
    """Создаёт таблицу categories и засевает из taxonomy.py если пустая."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL UNIQUE,
            section    TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0
        )
    """)
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] > 0:
        return
    import importlib.util
    _tax_path = _PROJECT_ROOT / "pipeline" / "config" / "taxonomy.py"
    _spec = importlib.util.spec_from_file_location("_tax_seed", str(_tax_path))
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    rows, order = [], 0
    for section_name, cats in _mod.TAXONOMY_SECTIONS:
        for cat in cats:
            rows.append((cat, section_name, order))
            order += 1
    conn.executemany(
        "INSERT OR IGNORE INTO categories (name, section, sort_order) VALUES (?, ?, ?)",
        rows,
    )


def get_taxonomy() -> list[str]:
    """Плоский список категорий из БД."""
    with _get_conn() as conn:
        _ensure_categories_table(conn)
        rows = conn.execute(
            "SELECT name FROM categories ORDER BY sort_order, id"
        ).fetchall()
    return [r["name"] for r in rows]


def get_taxonomy_sections() -> list[tuple[str, list[str]]]:
    """Список (раздел, [категории]) из БД."""
    with _get_conn() as conn:
        _ensure_categories_table(conn)
        rows = conn.execute(
            "SELECT section, name FROM categories ORDER BY sort_order, id"
        ).fetchall()
    sections: dict[str, list[str]] = {}
    for row in rows:
        sections.setdefault(row["section"], []).append(row["name"])
    return list(sections.items())


def get_sections() -> list[str]:
    """Список уникальных разделов в порядке появления."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT section FROM categories GROUP BY section ORDER BY MIN(sort_order), MIN(id)"
        ).fetchall()
    return [r["section"] for r in rows]


# ── Управление категориями (CRUD) ─────────────────────────────────────────────

def get_categories_managed() -> list[dict]:
    """Все категории с кол-вом URLs — для страницы управления."""
    with _get_conn() as conn:
        _ensure_categories_table(conn)
        rows = conn.execute("""
            SELECT c.id, c.name, c.section, c.sort_order,
                   COUNT(u.id) AS url_count
              FROM categories c
              LEFT JOIN urls u ON u.category = c.name AND u.status = 'done'
             GROUP BY c.id
             ORDER BY c.sort_order, c.id
        """).fetchall()
    return [dict(r) for r in rows]


def create_category(name: str, section: str) -> tuple[bool, str]:
    """Создаёт новую категорию. Возвращает (ok, error)."""
    name = name.strip()
    if not name:
        return False, "Название не может быть пустым"
    try:
        with _get_conn() as conn:
            max_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) FROM categories WHERE section = ?",
                (section,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO categories (name, section, sort_order) VALUES (?, ?, ?)",
                (name, section, max_order + 1),
            )
        return True, ""
    except sqlite3.IntegrityError:
        return False, f"Категория «{name}» уже существует"


def rename_category(old_name: str, new_name: str) -> tuple[bool, str, int]:
    """Переименовывает категорию + мигрирует URLs. Возвращает (ok, error, urls_updated)."""
    new_name = new_name.strip()
    if not new_name:
        return False, "Новое название не может быть пустым", 0
    if old_name == new_name:
        return False, "Название не изменилось", 0
    with _get_conn() as conn:
        if conn.execute("SELECT 1 FROM categories WHERE name = ?", (new_name,)).fetchone():
            return False, f"Категория «{new_name}» уже существует", 0
        cur = conn.execute(
            "UPDATE urls SET category = ? WHERE category = ?", (new_name, old_name)
        )
        urls_updated = cur.rowcount
        conn.execute(
            "UPDATE categories SET name = ? WHERE name = ?", (new_name, old_name)
        )
    return True, "", urls_updated


def change_category_section(name: str, new_section: str) -> bool:
    """Перемещает категорию в другой раздел."""
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE categories SET section = ? WHERE name = ?", (new_section, name)
        )
    return cur.rowcount > 0


def delete_category(name: str, reassign_to: str | None = None) -> tuple[bool, str, int]:
    """Удаляет категорию. reassign_to=None → URLs сбрасываются в NULL."""
    with _get_conn() as conn:
        url_count = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE category = ? AND status = 'done'", (name,)
        ).fetchone()[0]
        if reassign_to:
            conn.execute(
                "UPDATE urls SET category = ? WHERE category = ?", (reassign_to, name)
            )
        else:
            conn.execute(
                "UPDATE urls SET category = NULL, manual_override = 0 WHERE category = ?",
                (name,),
            )
        conn.execute("DELETE FROM categories WHERE name = ?", (name,))
    return True, "", url_count

def get_pending_count() -> int:
    """Количество URL со статусом pending."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status = 'pending'"
        ).fetchone()[0]


# ── Backup БД ─────────────────────────────────────────────────────────────────

_BACKUP_DIR = _PROJECT_ROOT / "data" / "backups"
_BACKUP_KEEP = 3


def backup_db(reason: str = "manual") -> Path:
    """Копирует urls.db в data/backups/urls-YYYYMMDD-HHMMSS-REASON.db.
    Ротирует, оставляя последние `_BACKUP_KEEP` файлов. Использует SQLite
    backup API для консистентности при параллельной записи.
    Возвращает путь к созданному файлу.
    """
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_reason = re.sub(r"[^a-zA-Z0-9_-]", "", reason)[:20] or "backup"
    target = _BACKUP_DIR / f"urls-{ts}-{safe_reason}.db"
    src = sqlite3.connect(DB_PATH)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    # Ротация
    backups = sorted(_BACKUP_DIR.glob("urls-*.db"), key=lambda p: p.stat().st_mtime)
    for old in backups[:-_BACKUP_KEEP]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def list_backups() -> list[dict]:
    """Возвращает список бэкапов (новые сверху) с метаданными."""
    if not _BACKUP_DIR.exists():
        return []
    out = []
    for p in sorted(_BACKUP_DIR.glob("urls-*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({
            "name": p.name,
            "size": st.st_size,
            "mtime": st.st_mtime,
        })
    return out


# ── Benchmark snapshot/restore ────────────────────────────────────────────────

def benchmark_eligible_count() -> int:
    """Сколько done+classified URL с title пригодны для бенчмарка."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM urls "
            "WHERE status='done' AND category IS NOT NULL "
            "AND title IS NOT NULL AND title != ''"
        ).fetchone()[0]


def benchmark_has_snapshot() -> bool:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_bench_backup'"
        ).fetchone()
        return row is not None


def benchmark_snapshot(limit: int) -> list[int]:
    """Берёт первые `limit` done+classified URL с title, сохраняет (id, category,
    tagged_by) в _bench_backup. Возвращает список id. Идемпотентно для того же набора —
    если _bench_backup уже есть, ValueError.
    """
    if benchmark_has_snapshot():
        raise ValueError("_bench_backup уже существует — предыдущий прогон не восстановлен")
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE _bench_backup (
                id         INTEGER PRIMARY KEY,
                category   TEXT,
                tagged_by  TEXT
            )
        """)
        rows = conn.execute(
            "SELECT id, category, tagged_by FROM urls "
            "WHERE status='done' AND category IS NOT NULL "
            "AND title IS NOT NULL AND title != '' "
            "ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
        if not rows:
            conn.execute("DROP TABLE _bench_backup")
            raise ValueError("Нет URL, пригодных для бенчмарка")
        conn.executemany(
            "INSERT INTO _bench_backup (id, category, tagged_by) VALUES (?, ?, ?)",
            rows,
        )
        return [r[0] for r in rows]


def benchmark_restore() -> int:
    """Восстанавливает category/tagged_by из _bench_backup. Возвращает число
    восстановленных строк. Если snapshot нет — 0.
    """
    if not benchmark_has_snapshot():
        return 0
    with _get_conn() as conn:
        # SQLite не поддерживает UPDATE ... FROM во всех версиях — используем подзапрос.
        n = conn.execute(
            "UPDATE urls SET "
            "  category  = (SELECT category  FROM _bench_backup WHERE _bench_backup.id = urls.id), "
            "  tagged_by = (SELECT tagged_by FROM _bench_backup WHERE _bench_backup.id = urls.id) "
            "WHERE id IN (SELECT id FROM _bench_backup)"
        ).rowcount
        conn.execute("DROP TABLE _bench_backup")
        return n


_URL_RE = re.compile(r"https?://[^\s|<>\"'`]+")
_URL_TRAILING_JUNK = re.compile(r"[.,;!?)]+$")


def extract_urls(text: str) -> list[str]:
    """Извлекает все http(s) URL из произвольного текста — как step1.py.

    Дедупликация с сохранением порядка. Отсекает типичный мусор
    в конце URL (.,;!?)).
    """
    raw = _URL_RE.findall(text)
    urls: list[str] = []
    seen: set[str] = set()
    for u in raw:
        u = _URL_TRAILING_JUNK.sub("", u)
        if u and u not in seen:
            seen.add(u)
            urls.append(u)
    return urls


def insert_urls_bulk(text: str) -> dict:
    """Парсит произвольный текст, вставляет найденные URL как pending.

    Возвращает {added, duplicates}.
    """
    urls = extract_urls(text)
    added: list[str] = []
    duplicates: list[str] = []
    with _get_conn() as conn:
        for url in urls:
            existing = conn.execute(
                "SELECT id FROM urls WHERE url = ?", (url,)
            ).fetchone()
            if existing:
                duplicates.append(url)
            else:
                conn.execute(
                    "INSERT INTO urls (url, status, added_at) VALUES (?, 'pending', datetime('now'))",
                    (url,),
                )
                added.append(url)
    return {"added": added, "duplicates": duplicates}


PER_PAGE_DEFAULT = 20
PER_PAGE_MAX = 100

# Допустимые варианты сортировки: ключ → SQL ORDER BY
SORT_OPTIONS = {
    "newest": ("added_at DESC, id DESC", "Новые сверху"),
    "oldest": ("added_at ASC, id ASC", "Старые сверху"),
    "title":  ("COALESCE(title, url) ASC", "По алфавиту"),
    "id_desc": ("id DESC", "По ID ↓"),
    "id_asc":  ("id ASC",  "По ID ↑"),
}
SORT_DEFAULT = "newest"


def _order_clause(sort: str) -> str:
    """Возвращает SQL ORDER BY для заданного ключа сортировки."""
    return SORT_OPTIONS.get(sort, SORT_OPTIONS[SORT_DEFAULT])[0]


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_categories_with_counts() -> list[dict]:
    """Все категории с количеством URL, отсортированные по убыванию."""
    with _get_conn() as conn:
        rows = conn.execute("""
            SELECT category, COUNT(*) as count
              FROM urls
             WHERE status = 'done'
               AND category IS NOT NULL AND category != ''
             GROUP BY category
             ORDER BY count DESC
        """).fetchall()
    return [dict(r) for r in rows]


def get_urls_by_category(
    category: str,
    page: int = 1,
    per_page: int = PER_PAGE_DEFAULT,
    sort: str = SORT_DEFAULT,
) -> dict:
    """URL заданной категории с пагинацией."""
    per_page = min(per_page, PER_PAGE_MAX)
    offset = (page - 1) * per_page

    with _get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='done' AND category=?",
            (category,),
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT id, url, title, description, category, processed_at, added_at,
                       COALESCE(manual_override, 0) as manual_override
                 FROM urls
                WHERE status='done' AND category=?
                ORDER BY {_order_clause(sort)}
                LIMIT ? OFFSET ?""",
            (category, per_page, offset),
        ).fetchall()

    items = [_enrich(dict(r)) for r in rows]
    return {
        "category": category,
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),  # ceiling division
    }


def search_urls(
    query: str = "",
    category: str = "",
    page: int = 1,
    per_page: int = PER_PAGE_DEFAULT,
    sort: str = SORT_DEFAULT,
) -> dict:
    """Полнотекстовый поиск по title, description, url."""
    per_page = min(per_page, PER_PAGE_MAX)
    offset = (page - 1) * per_page

    conditions = ["status='done'"]
    params: list = []

    if category == "uncategorized":
        conditions.append("(category IS NULL OR category = '')")
    elif category and category != "recent":
        conditions.append("category=?")
        params.append(category)

    if query:
        like = f"%{query}%"
        conditions.append("(title LIKE ? OR description LIKE ? OR url LIKE ?)")
        params.extend([like, like, like])

    where = " AND ".join(conditions)

    with _get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM urls WHERE {where}", params
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT id, url, title, description, category, processed_at, added_at,
                       COALESCE(manual_override, 0) as manual_override
                  FROM urls
                 WHERE {where}
                 ORDER BY {_order_clause(sort)}
                 LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()

    items = [_enrich(dict(r)) for r in rows]
    return {
        "query": query,
        "category": category,
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
    }


def get_recent_urls(
    page: int = 1,
    per_page: int = PER_PAGE_DEFAULT,
    sort: str = SORT_DEFAULT,
) -> dict:
    """Все URL отсортированные по дате добавления, с пагинацией."""
    per_page = min(per_page, PER_PAGE_MAX)
    offset = (page - 1) * per_page

    with _get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='done'"
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT id, url, title, description, category, processed_at, added_at,
                       COALESCE(manual_override, 0) as manual_override
                 FROM urls
                WHERE status='done'
                ORDER BY {_order_clause(sort)}
                LIMIT ? OFFSET ?""",
            (per_page, offset),
        ).fetchall()

    items = [_enrich(dict(r)) for r in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
    }


def get_uncategorized_urls(
    page: int = 1,
    per_page: int = PER_PAGE_DEFAULT,
    sort: str = SORT_DEFAULT,
) -> dict:
    """URL без категории (done), с пагинацией."""
    per_page = min(per_page, PER_PAGE_MAX)
    offset = (page - 1) * per_page

    with _get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='done' AND (category IS NULL OR category = '')"
        ).fetchone()[0]

        rows = conn.execute(
            f"""SELECT id, url, title, description, category, processed_at, added_at,
                       COALESCE(manual_override, 0) as manual_override
                 FROM urls
                WHERE status='done' AND (category IS NULL OR category = '')
                ORDER BY {_order_clause(sort)}
                LIMIT ? OFFSET ?""",
            (per_page, offset),
        ).fetchall()

    items = [_enrich(dict(r)) for r in rows]
    return {
        "items": items,
        "total": total,
        "page": page,
        "pages": max(1, -(-total // per_page)),
    }


def get_stats() -> dict:
    """Общая статистика для главной страницы."""
    with _get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='done'"
        ).fetchone()[0]
        cats = conn.execute(
            "SELECT COUNT(DISTINCT category) FROM urls"
            " WHERE status='done' AND category IS NOT NULL AND category != ''"
        ).fetchone()[0]
        errors = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='error'"
        ).fetchone()[0]
        incomplete = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='done' "
            "AND (title IS NULL OR title = '' OR description IS NULL OR description = '')"
        ).fetchone()[0]
        pending = conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='pending'"
        ).fetchone()[0]
        placeholders = ",".join("?" * len(_TRANSIENT_CODES))
        transient = conn.execute(
            f"SELECT COUNT(*) FROM urls WHERE status='error'"
            f" AND (error_code IS NULL OR error_code IN ({placeholders}))",
            list(_TRANSIENT_CODES),
        ).fetchone()[0]
    return {
        "total_urls": total,
        "total_categories": cats,
        "error_count": errors,
        "transient_error_count": transient,
        "incomplete_count": incomplete,
        "pending_count": pending,
    }


def get_error_count() -> int:
    """Количество URL со статусом error."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='error'"
        ).fetchone()[0]


# Временные HTTP-коды (retry имеет смысл) — зеркалит pipeline/db.py
_TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})


def get_transient_error_count() -> int:
    """Количество URL с временными ошибками (5xx, 429, сетевые/таймаут)."""
    placeholders = ",".join("?" * len(_TRANSIENT_CODES))
    with _get_conn() as conn:
        return conn.execute(
            f"SELECT COUNT(*) FROM urls WHERE status='error'"
            f" AND (error_code IS NULL OR error_code IN ({placeholders}))",
            list(_TRANSIENT_CODES),
        ).fetchone()[0]


def get_incomplete_count() -> int:
    """Количество URL со status=done, но без title или без description."""
    with _get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM urls WHERE status='done' "
            "AND (title IS NULL OR title = '' OR description IS NULL OR description = '')"
        ).fetchone()[0]


def update_category(url_id: int, new_category: str, manual: bool = True) -> bool:
    """Меняет категорию URL. manual=True ставит manual_override=1 (защита от перезаписи LLM)."""
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET category = ?, manual_override = ? WHERE id = ?",
            (new_category, 1 if manual else 0, url_id),
        )
    return cur.rowcount > 0


def get_url_by_id(url_id: int) -> str | None:
    """Возвращает URL-строку по id или None."""
    with _get_conn() as conn:
        row = conn.execute("SELECT url FROM urls WHERE id = ?", (url_id,)).fetchone()
    return row["url"] if row else None


def get_urls_by_ids(ids: list[int]) -> dict[int, str]:
    """Возвращает {id: url} для списка id."""
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, url FROM urls WHERE id IN ({placeholders})", ids
        ).fetchall()
    return {row["id"]: row["url"] for row in rows}


def delete_urls_bulk(ids: list[int]) -> int:
    """Удаляет несколько URL по списку id. Возвращает кол-во удалённых."""
    if not ids:
        return 0
    placeholders = ",".join("?" * len(ids))
    with _get_conn() as conn:
        cur = conn.execute(f"DELETE FROM urls WHERE id IN ({placeholders})", ids)
    return cur.rowcount


def delete_url(url_id: int) -> bool:
    """Удаляет запись по id. Возвращает True если строка была удалена."""
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM urls WHERE id = ?", (url_id,))
    return cur.rowcount > 0


def _enrich(row: dict) -> dict:
    """Добавляет вычисляемые поля: domain, categories_list."""
    row["domain"] = urlparse(row["url"]).netloc.removeprefix("www.")
    raw_cat = row.get("category") or ""
    row["categories_list"] = [c.strip() for c in raw_cat.split(",") if c.strip()]
    return row
