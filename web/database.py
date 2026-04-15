"""Слой доступа к SQLite для Web UI.
Read-операции — просмотр данных.
Write-операции — только удаление и смена категории через UI.
"""
import os
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

PER_PAGE_DEFAULT = 20
PER_PAGE_MAX = 100

# Допустимые варианты сортировки: ключ → SQL ORDER BY
SORT_OPTIONS = {
    "newest": ("added_at DESC, id DESC", "Новые сверху"),
    "oldest": ("added_at ASC, id ASC", "Старые сверху"),
    "title":  ("COALESCE(title, url) ASC", "По алфавиту"),
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

    if query:
        like = f"%{query}%"
        conditions.append("(title LIKE ? OR description LIKE ? OR url LIKE ?)")
        params.extend([like, like, like])

    if category:
        conditions.append("category=?")
        params.append(category)

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
    return {"total_urls": total, "total_categories": cats}


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
