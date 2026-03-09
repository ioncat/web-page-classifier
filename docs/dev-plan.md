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

---

## Постфактум: анализ ошибок парсинга (март 2026)

После двух прогонов `--only-parse --workers 5` на ~7 400 URL в БД осталось **1 908 ошибок**.

### Проблема 1 — `error_code` не заполнен у старых записей

Колонка `error_code` была добавлена (#54) уже после первых прогонов step2.
Все 1 908 строк имели `error_code = NULL`, из-за чего `--retry-transient`
не мог различать временные и постоянные ошибки.

**Решение:** однократный бэкфилл из текста ошибки с помощью регулярного выражения:

```python
# Ищем паттерн requests: '403 Client Error: Forbidden for url: ...'
m = re.search(r'(\d{3})\s+(Client|Server)\s+Error', error_text)
if m:
    UPDATE urls SET error_code = int(m.group(1)) WHERE url = ?
```

Скрипт заполнил `error_code` для 1 595 из 1 908 записей.
Оставшиеся 313 (таймауты, SSL, сетевые ошибки) остались с `NULL` — это корректно,
`--retry-transient` захватывает их через `error_code IS NULL`.

### Проблема 2 — Windows cp1252 при анализе в PowerShell

При запуске `python -c "..."` с русскими строками в `print()` на Windows:

```
UnicodeEncodeError: 'charmap' codec can't encode characters in position N
```

PowerShell использует cp1252 по умолчанию. **Решение:** в разовых аналитических
скриптах использовать только ASCII-вывод (латинские ключи, цифры).

### Распределение ошибок (после бэкфилла)

| Код / тип | Кол-во | % | Тип | Действие |
|---|---:|---:|---|---|
| 403 Forbidden | 757 | 39.7% | ❌ Постоянная | пропустить |
| **429 Too Many Requests** | **548** | **28.7%** | **♻️ Временная** | **повторить** |
| 404 Not Found | 214 | 11.2% | ❌ Постоянная | пропустить |
| Таймаут / сетевая | 173 | 9.1% | ♻️ Временная | повторить |
| Прочие NULL | 113 | 5.9% | ♻️ Временная | повторить |
| 401 Unauthorized | 45 | 2.4% | ❌ Постоянная | пропустить |
| SSL / TLS | 27 | 1.4% | ♻️ Временная | повторить |
| 410 Gone | 12 | 0.6% | ❌ Постоянная | пропустить |
| 400/402/500/502/503/… | 19 | 1.0% | смешанные | — |
| **Итого** | **1 908** | | | |
| **♻️ Retriable** | **~869** | **~45.5%** | | `--retry-transient` |
| **❌ Permanent** | **~1 035** | **~54.2%** | | оставить как есть |

### Вывод

После бэкфилла `--retry-transient` корректно сбрасывает в `pending` только 869 записей
(429 + таймауты + SSL + NULL), не трогая 403/404/401/410.

**40% всех ошибок — 403 (Forbidden):** сайты блокируют парсер.
Для них `title` без proxy или headless browser не получить — в рамках текущего
проекта оставляем как есть.
