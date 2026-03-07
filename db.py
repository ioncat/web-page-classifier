import sqlite3
from datetime import datetime

DB_PATH = "urls.db"


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT UNIQUE NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                title        TEXT,
                error        TEXT,
                added_at     TEXT DEFAULT (datetime('now', 'localtime')),
                processed_at TEXT
            )
        """)


def insert_urls(urls: list[str]) -> tuple[int, int]:
    """Вставляет URL в БД, пропуская дубликаты.
    Возвращает (добавлено, пропущено).
    """
    added = 0
    skipped = 0
    with get_conn() as conn:
        for url in urls:
            try:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO urls (url) VALUES (?)", (url,)
                )
                if cur.rowcount:
                    added += 1
                else:
                    skipped += 1
            except sqlite3.Error:
                skipped += 1
    return added, skipped


def get_pending() -> list[str]:
    """Возвращает список URL со status='pending'."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM urls WHERE status = 'pending' ORDER BY id"
        ).fetchall()
    return [row["url"] for row in rows]


def update_url(
    url: str,
    status: str,
    title: str | None = None,
    error: str | None = None,
) -> None:
    """Обновляет запись: status, title или error, processed_at."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE urls
               SET status = ?,
                   title = ?,
                   error = ?,
                   processed_at = ?
             WHERE url = ?
            """,
            (status, title, error, now, url),
        )


def get_stats() -> dict[str, int]:
    """Возвращает словарь с количеством записей по каждому статусу."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM urls GROUP BY status"
        ).fetchall()
    stats = {"total": 0, "pending": 0, "done": 0, "error": 0}
    for row in rows:
        stats[row["status"]] = row["cnt"]
        stats["total"] += row["cnt"]
    return stats


def reset_all_to_pending() -> int:
    """Сбрасывает все записи в pending. Возвращает кол-во затронутых строк."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET status='pending', title=NULL, error=NULL, processed_at=NULL"
        )
        return cur.rowcount


def reset_errors_to_pending() -> int:
    """Сбрасывает записи с ошибками в pending. Возвращает кол-во затронутых строк."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET status='pending', error=NULL, processed_at=NULL WHERE status='error'"
        )
        return cur.rowcount


def set_url_pending(url: str) -> None:
    """Форсирует статус pending для конкретного URL (для режима --url)."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE urls SET status='pending', title=NULL, error=NULL, processed_at=NULL WHERE url=?",
            (url,),
        )


def get_pending_by_domain(domain: str) -> list[str]:
    """Возвращает pending URL только для указанного домена.
    Нечувствителен к www-префиксу и регистру.
    """
    from urllib.parse import urlparse

    domain_norm = domain.lower().removeprefix("www.")
    return [
        url for url in get_pending()
        if urlparse(url).netloc.lower().removeprefix("www.") == domain_norm
    ]


def get_errors() -> list[dict]:
    """Возвращает список записей с ошибками."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url, error FROM urls WHERE status = 'error' ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


# ── Теги и классификация ──────────────────────────────────────────────────────

def init_tags_schema() -> None:
    """Создаёт таблицу tags и добавляет колонки category / tagged_by в urls (идемпотентно)."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tags (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL
            )
        """)
        for col_def in (
            "ALTER TABLE urls ADD COLUMN category  TEXT",
            "ALTER TABLE urls ADD COLUMN tagged_by TEXT",
        ):
            try:
                conn.execute(col_def)
            except sqlite3.OperationalError:
                pass  # колонка уже существует


def get_tags() -> list[str]:
    """Возвращает список тегов из справочника."""
    with get_conn() as conn:
        rows = conn.execute("SELECT name FROM tags ORDER BY name").fetchall()
    return [row["name"] for row in rows]


def add_tags(names: list[str]) -> tuple[int, int]:
    """Добавляет теги в справочник, пропуская дубликаты.
    Возвращает (добавлено, пропущено).
    """
    added = 0
    skipped = 0
    with get_conn() as conn:
        for name in names:
            cur = conn.execute(
                "INSERT OR IGNORE INTO tags (name) VALUES (?)", (name.strip(),)
            )
            if cur.rowcount:
                added += 1
            else:
                skipped += 1
    return added, skipped


def get_done_unclassified() -> list[dict]:
    """Возвращает done-записи без присвоенной категории."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, url, title
                 FROM urls
                WHERE status = 'done'
                  AND (category IS NULL OR category = '')
                ORDER BY id"""
        ).fetchall()
    return [dict(row) for row in rows]


def set_category(url: str, category: str, model: str | None = None) -> None:
    """Сохраняет присвоенные теги и имя модели для URL."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE urls SET category = ?, tagged_by = ? WHERE url = ?",
            (category, model, url),
        )
