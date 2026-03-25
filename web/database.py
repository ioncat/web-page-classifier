"""Слой доступа к SQLite для Web UI.
Read-операции — просмотр данных.
Write-операции — только удаление и смена категории через UI.
"""
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = os.getenv("DB_PATH", str(_PROJECT_ROOT / "urls.db"))

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
            f"""SELECT id, url, title, description, category, processed_at, added_at
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
            f"""SELECT id, url, title, description, category, processed_at, added_at
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
            f"""SELECT id, url, title, description, category, processed_at, added_at
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
            f"""SELECT id, url, title, description, category, processed_at, added_at
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


def update_category(url_id: int, new_category: str) -> bool:
    """Меняет категорию URL. Возвращает True если строка обновлена."""
    with _get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET category = ? WHERE id = ?",
            (new_category, url_id),
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
