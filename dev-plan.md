# План: Переход на SQLite + Rich

## Контекст
Текущий пайплайн (step1 → step2 → step3) использует CSV-файлы как хранилище между шагами. Проблемы: нет checkpointing в step2 (при сбое теряется прогресс), нет дедупликации URL, двойное логирование, баги. Переходим на SQLite как единое хранилище для всех шагов. step3 — на потом.

## Схема БД (единый файл `urls.db`)

```sql
CREATE TABLE IF NOT EXISTS urls (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT UNIQUE NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending / done / error
    title       TEXT,
    error       TEXT,
    added_at    TEXT DEFAULT (datetime('now', 'localtime')),
    processed_at TEXT
);
```

## Файлы

### Новые / изменённые
| Файл | Действие | Описание |
|---|---|---|
| `db.py` | создать | Общий модуль: init_db(), insert_urls(), get_pending(), update_url() |
| `step1.py` | переписать | Читает raw_links.txt → вставляет URL в БД, rich-вывод итогов |
| `step2.py` | переписать | Читает pending из БД → парсит title → обновляет БД, rich progress |
| `requirements.txt` | создать | requests, beautifulsoup4, rich |

### Без изменений
- `step3.py` — отложен
- `input.csv`, `output.csv` — больше не нужны (данные в БД)

---

## db.py — детали

Функции:
- `init_db()` — создаёт таблицу если нет
- `insert_urls(urls)` — INSERT OR IGNORE, возвращает (добавлено, дублей)
- `get_pending()` — возвращает список URL со status='pending'
- `update_url(url, status, title, error)` — обновляет запись
- `get_stats()` — возвращает {'total', 'pending', 'done', 'error'}

---

## step1.py — детали

**Вход:** `raw_links.txt`
**Выход:** записи в `urls.db` (status=pending)

1. `init_db()` — создаёт БД если нет
2. Читает файл, regex с очисткой trailing `.,;!?)`
3. `insert_urls()` — дедупликация через UNIQUE
4. Rich: `Panel` + `Table` (найдено / добавлено / дублей)

---

## step2.py — детали

**Вход:** pending URL из `urls.db`
**Выход:** обновляет status=done/error, заполняет title/error

1. `init_db()` + `get_stats()` → rich `Panel` с состоянием БД
2. `get_pending()` — список для обработки
3. Rich `Progress`: spinner, текущий URL, счётчик done/error, время
4. Для каждого URL: GET с timeout=10, извлечь title, update_url()
5. Финальный `Table` — итоги + таблица ошибок если есть

---

## requirements.txt

```
requests
beautifulsoup4
rich
```

---

## Проверка

1. `pip install -r requirements.txt`
2. Положить `raw_links.txt` → `python step1.py` → проверить `urls.db`
3. `python step2.py` → rich progress → проверить результат
4. Повторный запуск step2 — обработанные URL пропускаются
5. Переобработка ошибок: `UPDATE urls SET status='pending' WHERE status='error'`
