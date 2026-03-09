import sqlite3
from datetime import datetime

from config.settings import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# HTTP-коды, которые считаются временными (retry имеет смысл).
# None (сетевая ошибка / таймаут) тоже считается временной.
TRANSIENT_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# HTTP-коды, которые считаются постоянными (retry бессмысленен).
PERMANENT_CODES: frozenset[int] = frozenset({400, 401, 403, 404, 405, 410, 451})


def init_db() -> None:
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS urls (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT UNIQUE NOT NULL,
                status       TEXT NOT NULL DEFAULT 'pending',
                title        TEXT,
                error        TEXT,
                error_code   INTEGER,
                added_at     TEXT DEFAULT (datetime('now', 'localtime')),
                processed_at TEXT
            )
        """)
        # Миграция: добавляем error_code если колонки ещё нет (старые БД)
        try:
            conn.execute("ALTER TABLE urls ADD COLUMN error_code INTEGER")
        except sqlite3.OperationalError:
            pass  # колонка уже существует


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
    error_code: int | None = None,
) -> None:
    """Обновляет запись: status, title или error, error_code, processed_at."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE urls
               SET status = ?,
                   title = ?,
                   error = ?,
                   error_code = ?,
                   processed_at = ?
             WHERE url = ?
            """,
            (status, title, error, error_code, now, url),
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


def get_full_stats() -> dict:
    """Расширенная статистика: статусы + классификация + теги + сравнение."""
    stats = get_stats()
    with get_conn() as conn:
        # Классифицировано среди done
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM urls"
            " WHERE status = 'done' AND category IS NOT NULL AND category != ''"
        ).fetchone()
        stats["classified"] = row["cnt"]
        stats["unclassified"] = stats["done"] - stats["classified"]

        # Тегов в справочнике
        try:
            row = conn.execute("SELECT COUNT(*) as cnt FROM tags").fetchone()
            stats["tags"] = row["cnt"]
        except sqlite3.OperationalError:
            stats["tags"] = 0

        # URL, участвовавших в сравнении моделей
        try:
            row = conn.execute(
                "SELECT COUNT(DISTINCT url_id) as cnt FROM model_results"
            ).fetchone()
            stats["compared"] = row["cnt"]
        except sqlite3.OperationalError:
            stats["compared"] = 0

    return stats


def reset_all_to_pending() -> int:
    """Сбрасывает все записи в pending. Возвращает кол-во затронутых строк."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET status='pending', title=NULL, error=NULL, processed_at=NULL"
        )
        return cur.rowcount


def reset_errors_to_pending() -> int:
    """Сбрасывает ВСЕ записи с ошибками в pending. Возвращает кол-во затронутых строк."""
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET status='pending', error=NULL, error_code=NULL,"
            " processed_at=NULL WHERE status='error'"
        )
        return cur.rowcount


def reset_transient_errors_to_pending() -> int:
    """Сбрасывает только временные ошибки (5xx, 429, сетевые) в pending.
    Постоянные ошибки (404, 403, 410 и т.п.) остаются нетронутыми.
    Возвращает кол-во затронутых строк.
    """
    placeholders = ",".join("?" * len(TRANSIENT_CODES))
    with get_conn() as conn:
        cur = conn.execute(
            f"UPDATE urls SET status='pending', error=NULL, error_code=NULL,"
            f" processed_at=NULL"
            f" WHERE status='error'"
            f"   AND (error_code IS NULL OR error_code IN ({placeholders}))",
            list(TRANSIENT_CODES),
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
    """Возвращает список записей с ошибками (url, error, error_code)."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url, error, error_code FROM urls WHERE status = 'error' ORDER BY id"
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


def sync_tags_from_categories() -> tuple[int, int]:
    """Читает все category из urls и добавляет уникальные теги в справочник.
    Возвращает (добавлено, уже было).
    """
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT category FROM urls WHERE category IS NOT NULL AND category != ''"
        ).fetchall()

    # Собираем все теги из всех строк
    all_tags: set[str] = set()
    for row in rows:
        for tag in row["category"].split(","):
            tag = tag.strip()
            if tag:
                all_tags.add(tag)

    if not all_tags:
        return 0, 0

    return add_tags(sorted(all_tags))


def reset_categories() -> int:
    """Сбрасывает category и tagged_by для всех done-записей (подготовка к ре-тэггингу).
    Справочник tags НЕ затрагивается — накопленные теги остаются как подсказки.
    Возвращает кол-во затронутых строк.
    """
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE urls SET category = NULL, tagged_by = NULL WHERE status = 'done'"
        )
        return cur.rowcount


def reset_categories_by_domain(domain: str) -> int:
    """Сбрасывает category и tagged_by только для done-записей указанного домена.
    Нечувствителен к www-префиксу и регистру.
    Возвращает кол-во затронутых строк.
    """
    from urllib.parse import urlparse

    domain_norm = domain.lower().removeprefix("www.")
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT url FROM urls WHERE status = 'done'"
        ).fetchall()
        urls_in_domain = [
            row["url"] for row in rows
            if urlparse(row["url"]).netloc.lower().removeprefix("www.") == domain_norm
        ]
        if not urls_in_domain:
            return 0
        placeholders = ",".join("?" * len(urls_in_domain))
        cur = conn.execute(
            f"UPDATE urls SET category = NULL, tagged_by = NULL WHERE url IN ({placeholders})",
            urls_in_domain,
        )
        return cur.rowcount


def clear_tags() -> int:
    """Полностью очищает справочник тегов (таблицу tags).
    Возвращает кол-во удалённых строк.
    """
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tags")
        return cur.rowcount


# ── Сравнение моделей ─────────────────────────────────────────────────────────

def init_compare_schema() -> None:
    """Создаёт таблицу model_results (идемпотентно)."""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS model_results (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                url_id    INTEGER NOT NULL REFERENCES urls(id) ON DELETE CASCADE,
                model     TEXT    NOT NULL,
                category  TEXT,
                tagged_at TEXT    DEFAULT (datetime('now')),
                UNIQUE(url_id, model)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_mr_model ON model_results(model)"
        )


def save_model_result(url_id: int, model: str, category: str) -> None:
    """Upsert результата для пары (url_id, model).
    Повторный вызов той же модели перезаписывает предыдущий результат.
    """
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO model_results (url_id, model, category, tagged_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(url_id, model) DO UPDATE SET
                category  = excluded.category,
                tagged_at = excluded.tagged_at
        """, (url_id, model, category))


def get_done_urls() -> list[dict]:
    """Возвращает все done-записи (id, url, title) для запуска сравнения моделей."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, url, title FROM urls WHERE status = 'done' ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


def get_compared_models() -> list[str]:
    """Возвращает отсортированный список моделей, участвовавших в сравнении."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT DISTINCT model FROM model_results ORDER BY model"
        ).fetchall()
    return [row["model"] for row in rows]


def get_model_results_raw() -> list[dict]:
    """Возвращает все строки model_results, объединённые с urls."""
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT u.id, u.url, u.title, mr.model, mr.category, mr.tagged_at
              FROM model_results mr
              JOIN urls u ON u.id = mr.url_id
             ORDER BY u.id, mr.model
        """).fetchall()
    return [dict(row) for row in rows]


def accept_model(model: str) -> int:
    """Копирует результаты выбранной модели из model_results в urls.category + tagged_by.
    Возвращает кол-во обновлённых строк.
    """
    with get_conn() as conn:
        cur = conn.execute("""
            UPDATE urls
               SET category  = (SELECT mr.category  FROM model_results mr
                                 WHERE mr.url_id = urls.id AND mr.model = ?),
                   tagged_by = ?
             WHERE id IN (SELECT url_id FROM model_results WHERE model = ?)
        """, (model, model, model))
        return cur.rowcount


def clear_model_results() -> int:
    """Очищает таблицу model_results. Возвращает кол-во удалённых строк."""
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM model_results")
        return cur.rowcount
