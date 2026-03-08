# Backlog реализованных фич — url-parser

**Даты:** 7–8 марта 2026 | **Коммитов:** 15 | **Файлов:** 9

---

## Сессия 1 — Инфраструктура пайплайна (07.03, утро)

| # | Фича | Файлы |
|---|------|-------|
| 1 | **SQLite-хранилище** вместо CSV — `urls` таблица со статусами `pending/done/error`, checkpointing | `db.py` |
| 2 | **Дедупликация URL** — `INSERT OR IGNORE`, повторный импорт безопасен | `db.py`, `step1.py` |
| 3 | **step1.py** — regex-извлечение URL из `raw_links.txt`, Rich-таблица с итогами (найдено / добавлено / дублей) | `step1.py` |
| 4 | **step2.py** — получение title через HTTP, Rich Progress bar, checkpointing (skip done URLs) | `step2.py` |
| 5 | **Polite crawling** — случайные задержки 2–5 с, ротация User-Agent (4 браузера), urllib3.Retry, exponential backoff | `step2.py` |
| 6 | **main.py** — единая точка входа, argparse CLI с флагами `--only-import`, `--only-parse`, `--limit`, `--domain`, `--force`, `--retry-failed`, `--url`, `--no-progress`, `-v` | `main.py` |
| 7 | **Verbose-режим** — детальный лог каждого URL в step2 | `step2.py` |

---

## Сессия 2 — Ollama-классификация (07.03, день)

| # | Фича | Файлы |
|---|------|-------|
| 8 | **step3 — LLM-классификация** через Ollama: присваивает 1–5 тегов каждому done-URL, сохраняет в `urls.category` | `step3.py` |
| 9 | **Система тегов-подсказок** — таблица `tags` как справочник для промпта, модель может изобретать свои теги | `db.py`, `step3.py` |
| 10 | **Флаги классификации**: `--only-classify`, `--model MODEL`, `--list-models`, `--add-tags TAG1 TAG2` | `main.py` |
| 11 | **Интерактивный выбор модели** — при запуске без `--model` выводится нумерованная таблица Ollama-моделей | `step3.py` |
| 12 | **`tagged_by` tracking** — в `urls` сохраняется имя модели, выставившей финальный тег | `db.py`, `step3.py` |
| 13 | **Улучшенная обработка ошибок Ollama** — retry, информативные сообщения, graceful degradation | `step3.py` |
| 14 | **Авто-синхронизация тегов** — после каждого `set_category()` новые теги сразу попадают в справочник и используются для следующих URL в том же прогоне | `step3.py`, `db.py` |
| 15 | **`--sync-tags`** — ручной запуск синхронизации тегов из существующих категорий | `main.py` |
| 16 | **`--re-tag`** — сбрасывает `category`/`tagged_by` у всех done-URL (справочник тегов сохраняется), запускает step3 заново | `main.py`, `db.py` |
| 17 | **`--clear-tags`** — очищает таблицу `tags` полностью | `main.py`, `db.py` |

---

## Сессия 3 — Сравнение моделей (07.03, вечер)

| # | Фича | Файлы |
|---|------|-------|
| 18 | **`model_results` таблица** — изолированное хранилище результатов нескольких моделей, `UNIQUE(url_id, model)` + upsert | `db.py` |
| 19 | **`--compare-models M1 M2 ...`** — прогоняет несколько Ollama-моделей по одним и тем же URL, пишет в `model_results` (не трогает `urls.category`) | `compare.py`, `main.py` |
| 20 | **`--compare`** — Rich-таблица side-by-side: колонка на модель, видны расхождения | `compare.py` |
| 21 | **`--compare --export FILE.csv`** — экспорт side-by-side в CSV | `compare.py` |
| 22 | **`--accept-model MODEL`** — копирует результаты выбранной модели из `model_results` в `urls.category` | `db.py`, `main.py` |
| 23 | **`--compare-clear`** — очищает таблицу `model_results` | `main.py` |
| 24 | **Изоляция экспериментов** — `--compare-models` и `--only-classify` не пересекаются; переход только через `--accept-model` | архитектура |
| 25 | **`--domain` фильтр для `--compare-models`** — www-нечувствительный фильтр по домену | `compare.py`, `main.py` |
| 26 | **`--workers N`** — параллельные запросы к Ollama через `ThreadPoolExecutor` + `as_completed` | `step3.py`, `compare.py` |
| 27 | **Thread-safety** — `Lock` для hints и счётчика ошибок, `threading.Event (_abort)` для остановки воркеров при N подряд conn-ошибках | `step3.py`, `compare.py` |
| 28 | **`--compare-models` с пробелами** — `nargs='+'` + обработка запятых внутри элементов (все 3 синтаксиса работают) | `main.py` |

---

## Сессия 4 — Производительность и надёжность (08.03)

| # | Фича | Файлы |
|---|------|-------|
| 29 | **`--batch N`** — отправляет N URL в одном запросе к Ollama (нумерованный список), разбирает ответ regex-ом | `step3.py` |
| 30 | **`classify_batch()`** — fallback на `classify_url()` для неразобранных строк; при падении всего батча — переход на одиночные запросы | `step3.py` |
| 31 | **4 режима обработки** — sequential/parallel × single/batch (все комбинации `--workers`/`--batch`) | `step3.py` |
| 32 | **`num_predict` лимит** — `80` токенов для одиночного URL, `30×N` для батча из N — защита от бесконечной генерации | `step3.py` |
| 33 | **HTTP timeout** — `OLLAMA_REQUEST_TIMEOUT = 120s` на клиенте — защита от зависшего запроса | `step3.py` |
| 34 | **Ctrl+C в параллельном режиме** — `try/except KeyboardInterrupt` внутри `as_completed`, `f.cancel()` для очереди, корректный выход | `step3.py`, `compare.py` |
| 35 | **`_check_conflicts()`** — останавливает программу с объяснением при несовместимых флагах (`--compare-models` + pipeline, `--batch/--workers` без step3) | `main.py` |
| 36 | **`benchmark/benchmark.py`** — автоматический поиск оптимального `batch×workers`: 10 конфигов, фиксированный набор URL, измерение URL/с, Rich-таблица с победителем, лог в `benchmark_log.csv` | `benchmark/benchmark.py` |

---

## Сессия 5 — Надёжность и документация (08.03, продолжение)

| # | Фича | Файлы |
|---|------|-------|
| 37 | **`--no-think`** — отключает thinking-режим для qwen3/deepseek-r1/minimax-m2 (`think: false` в Ollama options); без флага эти модели тратят все `num_predict` токены на рассуждения и возвращают пустой `content` | `step3.py`, `compare.py`, `main.py`, `benchmark/benchmark.py` |
| 38 | **`--workers N` для step2** — параллельный парсинг через `ThreadPoolExecutor`; URL перемешиваются round-robin по доменам (`_interleave_by_domain`) — одновременно идут только разные домены, снижая риск бана | `step2.py`, `main.py` |
| 39 | **Реструктуризация README** — новая структура: логика проекта, ASCII-диаграмма пайплайна, флаги разбиты на 6 тематических таблиц, примеры сгруппированы по сценариям | `README.md` |

---

## Запланировано

| # | Фича | Приоритет | Описание |
|---|------|-----------|----------|
| P1 | **`--strict` режим (L1 taxonomy)** | высокий | Флаг меняет промпт с «вот подсказки» на «выбери ОДНУ категорию строго из списка». Первый шаг к иерархической классификации. Workflow: `--add-tags` наполняет L1-категории → `--strict --only-classify` классифицирует строго по ним. Схема БД не меняется. |

---

## Итог

| Показатель | Значение |
|---|---|
| Всего фич | **39** (+3 запланировано) |
| Файлов в проекте | 9 (`main.py`, `step1–3.py`, `compare.py`, `benchmark/benchmark.py`, `db.py`, `README.md`, `docs/`) |
| GPU утилизация: старт → финал | 5–10% → **80–90%** |
| Сессий | 5 (2 дня) |
| Коммитов | 20+ |
