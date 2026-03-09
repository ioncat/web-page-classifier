# Backlog реализованных фич — url-parser

**Даты:** 7–9 марта 2026 | **Коммитов:** 30+ | **Файлов:** 11

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

## Сессия 6 — Качество классификации и ML-план (08.03, вечер)

| # | Фича | Файлы |
|---|------|-------|
| 40 | **`--stats`** — показывает статистику БД и выходит: total / pending / done / error / классифицировано (% от done) / тегов в справочнике / URL в model_results | `main.py`, `db.py` |
| 41 | **`get_full_stats()`** — расширенная статистика в db.py: classification coverage + теги + model_results | `db.py` |
| 42 | **Промпт: 1 категория** — изменён с «1–3 тегов» на «ровно 1 категория, 1–3 слова»; парсер ответа упрощён (вся первая строка = категория, без split по запятой) | `step3.py` |
| 43 | **`--re-tag --domain` bug fix** — `reset_categories_by_domain()`: раньше `--re-tag --domain X` сбрасывал категории у ВСЕХ URL; теперь сбрасывает только домен X | `db.py`, `main.py` |
| 44 | **`--dry-run`** — запускает step3 без записи в БД: выводит в консоль URL, категорию и уверенность, но не вызывает `set_category()`; полезно для тестирования промпта и модели перед полным прогоном | `step3.py`, `main.py` |

---

## Сессия 7 — Конфигурация и качество промпта (09.03)

| # | Фича | Файлы |
|---|------|-------|
| 45 | **`config/settings.py`** — все пользовательские константы вынесены из `db.py`, `step1–3.py`, `compare.py` в одно место: задержки краулера, таймауты Ollama, токены, фильтры тегов, параметры compare | `config/settings.py` (новый) |
| 46 | **`config/prompts.py`** — шаблоны промптов вынесены из `step3.py`; плейсхолдеры `{url}`, `{title}`, `{hints_line}` — редактируй без касания кода | `config/prompts.py` (новый) |
| 47 | **Переработка промпта** — новый формат «данные → инструкция-продолжение»: `URL/Title` идут первыми, последняя строка `Category (...): ` побуждает модель продолжить строку категорией без предисловий | `config/prompts.py` |
| 48 | **`_is_valid_tag()`** — фильтр мусора в справочнике тегов: отклоняет теги длиннее 40 символов, начинающиеся с `url:` / `http` / `the web` и т.д., содержащие запрещённые слова, или длиннее 4 слов; константы фильтра — в `config/settings.py` | `step3.py`, `config/settings.py` |

---

## Сессия 8 — XLSX-экспорт, логирование и детерминизм (09.03, продолжение)

| # | Фича | Файлы |
|---|------|-------|
| 49 | **`--compare --export-xlsx FILE.xlsx`** — экспорт side-by-side сравнения в Excel: синяя шапка, жёлтые строки = расхождения между моделями, чередующийся серый/белый, заморозка строки 1, авто-ширина колонок | `compare.py`, `main.py`, `requirements.txt` |
| 50 | **Dry-run таймер и авто-лог** — `_print_summary()` показывает elapsed time и URL/с; каждый `--dry-run` прогон автоматически дописывается в `benchmark/dryrun_log.csv` (date, model, batch, workers, url/s, classified) | `step3.py` |
| 51 | **`temperature=0.0`** — все Ollama-запросы (step3 + compare) теперь детерминированы; константа `OLLAMA_TEMPERATURE` вынесена в `config/settings.py` | `step3.py`, `config/settings.py` |
| 54 | **Структурированные коды ошибок** — новая колонка `error_code INTEGER` в `urls`; `_fetch_one` ловит `HTTPError` отдельно и сохраняет HTTP-статус (404, 503 и т.п.), сетевые ошибки → `NULL`; флаг `--retry-transient` сбрасывает только временные (5xx, 429, NULL), пропускает постоянные (404, 403, 410, 451); автомиграция старых БД в `init_db()` | `db.py`, `step2.py`, `main.py` |

---

## Запланировано

| # | Фича | Приоритет | Описание |
|---|------|-----------|----------|
| P0 | **`--strict` режим (L1 taxonomy)** | критический | Пререквизит для ML-плана. Флаг меняет промпт с «вот подсказки» на «выбери ОДНУ категорию строго из списка taxonomy.json». Детали — см. `docs/ml-plan.md`. |
| P0 | **`taxonomy.json`** | критический | Файл с 15 L1-категориями, описаниями и примерами. Используется в `--strict` и при обучении ML-модели. |
| P0 | **`export_dataset.py`** | критический | Экспорт БД в JSONL для обучения: `{"text": "title [SEP] domain", "label": "category"}`. |
| P1 | **`--fix-category`** | высокий | Ручная правка категории одного URL через CLI. Нужен для валидации датасета. |
| P1 | **`train_classifier.py`** | высокий | Fine-tune `xlm-roberta-base` на датасете. Обучение ~3 мин на RTX A4000. |
| P1 | **`step4.py` — ML-классификатор** | высокий | Инференс обученной модели: ~2мс/URL, confidence score, fallback на LLM при низкой уверенности. |
| P1 | **`--only-ml-classify`, `--ml-confidence`** | высокий | Флаги для step4 в `main.py`. |
| P2 | **Active learning UI** | средний | Показывает примеры с низкой ML-confidence для ручной проверки. |
| P2 | **#52 Per-model prompt templates** | средний | Поддержка отдельных промптов для каждой модели: `config/prompts/mistral.txt`, `config/prompts/default.txt`. `--compare-models` выбирает промпт по имени модели. Цель: максимизировать качество под специфику каждой модели (структурированный `###`-формат для Mistral, явные правила `lowercase only`, `no underscores`, `same language as title`). |
| P2 | **#53 Прогон 3 — батчинг vs качество** | средний | Эксперимент: запустить лучшую модель (mistral-small3.2) с `--batch 1`, `--batch 5`, `--batch 10`, `--batch 20` на одинаковом наборе URL. Сравнить agreement rate и с/URL. Задокументировать drift качества и найти оптимальный размер батча. |

> Полный план ML-разработки: **`docs/ml-plan.md`**

---

## Итог

| Показатель | Значение |
|---|---|
| Всего фич | **52** (+10 запланировано) |
| Файлов в проекте | 11 (`main.py`, `step1–3.py`, `compare.py`, `benchmark/benchmark.py`, `db.py`, `config/settings.py`, `config/prompts.py`, `README.md`, `docs/`) |
| GPU утилизация: старт → финал | 5–10% → **80–90%** |
| Сессий | 8 (3 дня) |
| Коммитов | 30+ |
