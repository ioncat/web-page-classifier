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

## Сессия 9 — Дозаполнение description (21.03)

| # | Фича | Файлы |
|---|------|-------|
| 55 | **Обнаружена проблема:** колонка `description` была добавлена в миграцию `init_db()`, но ни разу не применялась к боевой БД — все 6901 done-записей имели `NULL`. Фича `og:description` в step2 работала корректно, но данные некуда было писать | `db.py` |
| 56 | **`get_done_without_description()`** — выборка done-URL с пустым description | `db.py` |
| 57 | **`update_description()`** — точечный UPDATE только колонки `description`, не трогает `status`, `title`, `error` | `db.py` |
| 58 | **`refetch_descriptions()`** — дозаполняет description для done-записей без него: поддержка `--workers`, `--limit`, `--domain`, `--no-progress`, `--verbose`; при ошибке HTTP статус записи не меняется | `step2.py` |
| 59 | **`--refetch-description`** — флаг в `main.py` (mutually exclusive с `--only-*`); запускает `refetch_descriptions()` | `main.py` |
| 60 | **fix: счётчики в `refetch_descriptions()`** — было 2 счётчика (`done`/`error`), `done` считал любой успешный запрос включая `description=None`. Стало 3 счётчика: `got` (записано), `no_tag` (тег отсутствует), `error` (HTTP/таймаут); `None` больше не пишется в БД | `step2.py` |
| 61 | **JS anti-bot challenge bypass** — `_try_js_challenge()`: если ответ < 1500 байт и содержит `defaultHash="..."`, извлекает hash, ставит cookie `challenge_passed`, повторяет запрос. Прозрачно интегрировано в `fetch_page_meta()`. Решает проблему сайтов с JS-заглушкой (напр. `clubpuer.com.ua`), которые раньше возвращали `title=None` | `step2.py` |

### Результаты прогонов `--refetch-description` (21.03)

| Показатель | Прогон 1 | Прогон 2 | Итого |
|---|---|---|---|
| Без description на старте | **5237** (75.9%) | **3523** | — |
| Записано description | **1713** | **141** | **1854** |
| Страница OK, тег отсутствует | **2907** | **2959** | ~2959 (потолок) |
| Ошибка HTTP / таймаут | **617** | **423** | **423** (осталось) |
| Итого с description в БД | 3377 / 6901 (48.9%) | **3518 / 6901** (50.9%) | ← финал |

**Вывод:** ~3383 URL останутся без description навсегда — 2959 страниц без тега (GitHub-профили, одностраничники, страницы комментариев) + 423 стойкие ошибки (404, паywalls, таймауты).

### Ручная очистка БД (21.03)

Анализ ошибок по кодам и доменам → ручное удаление мусорных записей:

| Действие | Кол-во | Причина |
|---|---|---|
| Удалены `403` rozetka.com.ua + hard.rozetka.com.ua | 29 | антибот = страницы недоступны для нас |
| Удалены `403` habr.com | 60 | антибот = страницы недоступны для нас |
| Удалены `410` (все домены) | 12 | Gone — страница удалена навсегда |
| Удалены `404` (все домены) | 212 | Not Found — страница не существует |
| **Итого удалено** | **313** | |
| **Осталось в БД** | **7650** | |

Оставлены на ручную проверку: `429`, `401`, `500/502/503`, таймауты (`NULL`), habr.com `done`-страницы.
`visualcapitalist.com` (116 × 403) — оставлен, страницы открываются в браузере (антибот). Фича #61 (JS challenge bypass) может помочь с частью таких сайтов — стоит перепроверить через `--retry-transient`.

---

## Сессия 10 — Таксономия, очистка БД, manual override (25.03)

| # | Фича | Файлы |
|---|------|-------|
| 62 | **`config/taxonomy.py`** — 30 фиксированных категорий. Модель ОБЯЗАНА выбирать только из этого списка. Промпт включает полный список, `_normalize_category()` валидирует ответ | `config/taxonomy.py` (новый), `step3.py` |
| 63 | **Strict-режим по умолчанию** — step3 использует таксономию: `_TAXONOMY_SET` для быстрой валидации, `_TAXONOMY_STR` в промпте. Категории вне таксономии → ошибка | `step3.py`, `config/prompts.py` |
| 64 | **Очистка БД** — удалены мусорные категории: `(no title)` (531), мульти-категории с запятыми (12), `МЕНЮ` (19), `Агile` (3), англ./мусорные одиночные (32). Lowercase → Capitalized (132). Удалено 5 осиротевших тегов. Итого обработано 729 URL | ручная SQL-миграция |
| 65 | **`manual_override`** — новая колонка в `urls`. При ручной смене категории через UI ставится `1`. `get_done_unclassified()` пропускает такие URL | `db.py`, `web/database.py` |
| 66 | **Модалка с таксономией** — UI показывает 30 категорий из `config/taxonomy.py` (а не текущие из БД). Единый источник для LLM и UI | `web/database.py`, `web/templates/base.html`, `web/routers/pages.py` |
| 67 | **Иконка ✎ manual override** — на карточке отображается если категория назначена вручную | `web/templates/_url_card.html` |
| 68 | **Страница `/recent`** — лента всех URL, новые сверху, с пагинацией и сортировкой | `web/routers/pages.py`, `web/database.py`, `web/templates/recent.html` |
| 69 | **Страница `/uncategorized`** — URL без категории, с пагинацией и сортировкой | `web/routers/pages.py`, `web/database.py`, `web/templates/uncategorized.html` |
| 70 | **Сортировка** — новые сверху / старые сверху / по алфавиту. Доступна на category, recent, uncategorized, search | `web/database.py`, `web/templates/_sort_bar.html` |
| 71 | **`OLLAMA_NUM_CTX = 2048`** — уменьшение контекстного окна для лучшей утилизации GPU (35%→34% CPU) | `config/settings.py`, `step3.py` |
| 72 | **`config/domain_rules.py`** — правила классификации по домену: `{"category": "..."}` пропускает LLM, `{"section": "..."}` сужает промпт до категорий секции. Валидация при импорте. 9 доменов (habr, github, youtube, flibusta, rozetka, amazon и др.) | `config/domain_rules.py` (новый), `step3.py` |
| 73 | **Section-narrowed prompts** — `_taxonomy_str_for(section)` генерирует сокращённый список категорий для промпта. Для habr.com LLM видит 11 категорий вместо 30 | `step3.py` |

---

## Сессия 11 — Очистка, аналитика, парсер LLM-ответов (27.03)

| # | Фича | Файлы |
|---|------|-------|
| 74 | **Статус `deferred`** — новый статус URL для отложенных ошибок (антибот, JS-страницы). `--defer-errors` переводит error → deferred, `--undefer` — обратно. Не мешают обычным прогонам | `db.py`, `main.py` |
| 75 | **`--analytics`** — подробная аналитика БД: разбивка по title/description/category, топ проблемных доменов, deferred по кодам. Читаемый русский вывод | `db.py`, `main.py` |
| 76 | **Улучшен парсер LLM-ответов** — `_normalize_category()` теперь извлекает категорию из `**жирного текста**`, после `Категория:`, `Катерия:` и др. паттернов. 57 ранее ошибочных URL успешно классифицированы | `step3.py` |
| 77 | **Экспорт и очистка БД** — google.com (526 URL), 404/410 ошибки, habr/rozetka 403 выгружены в `exports/`. Одноразовые скрипты перенесены в `archive/` | `exports/` (новое), `archive/` (новое) |
| 78 | **Удалён legacy-функционал tags** — таблица `tags`, флаги `--add-tags`/`--sync-tags`/`--clear-tags`, функции `init_tags_schema`/`get_tags`/`add_tags`/`sync_tags_from_categories`/`clear_tags`. Таксономия теперь единственный источник подсказок для LLM | `db.py`, `main.py`, `step3.py`, `benchmark.py` |
| 79 | **Исправления README.md** — 30→31 категория, `title+domain`→`title+description+domain`, убран `--strict`, убран `--batch` из быстрого старта, удалены разделы tags, обновлена схема БД | `README.md`, `web/README.md` |

---

## Запланировано

| # | Фича | Приоритет | Описание |
|---|------|-----------|----------|
| P0 | ~~**`--strict` режим**~~ | ✅ готово | Реализовано: таксономия в `config/taxonomy.py`, валидация в `_normalize_category()` |
| P0 | ~~**`taxonomy.json`**~~ | ✅ готово | Реализовано как `config/taxonomy.py` — 31 категория |
| P0 | **`export_dataset.py`** | критический | Экспорт БД в JSONL для обучения: `{"text": "title [SEP] domain", "label": "category"}` |
| P1 | ~~**`--fix-category`**~~ | ✅ готово | Реализовано через Web UI: модалка + drag&drop + `manual_override` |
| P1 | **`train_classifier.py`** | высокий | Fine-tune `xlm-roberta-base` на датасете. Обучение ~3 мин на RTX A4000 |
| P1 | **`step4.py` — ML-классификатор** | высокий | Инференс обученной модели: ~2мс/URL, confidence score, fallback на LLM |
| P1 | **`--only-ml-classify`, `--ml-confidence`** | высокий | Флаги для step4 в `main.py` |
| P2 | **Active learning UI** | средний | Показывает примеры с низкой ML-confidence для ручной проверки |
| P2 | **Публичный репозиторий (EN) + приватный (RU)** | средний | Проект ведётся на русском — комментарии, доки, бэклог. Для публичного GitHub нужна английская версия. **Решение:** два git remote: `origin` → приватный репо (RU, текущий), `public` → публичный репо (EN). Отдельная ветка `public` с переведёнными доками и английскими комментариями в коде. Код синхронизируется, тексты — разные. Русская версия не теряется, хранится в приватном репо. Реализация: `git remote add public <url>`, ветка `public`, `git push public public:master` |
| P1 | **Удобный интерфейс управления** | высокий | Проблема: слишком много флагов, каждый с параметрами (workers, batch, model...) — невозможно запомнить. **Варианты решения:** (1) Интерактивный CLI — меню со стрелками, wizard-стиль, подсказки по параметрам; (2) Расширить Web UI — добавить страницу управления пайплайном (запуск задач, выбор параметров, просмотр логов); (3) Гибрид — CLI для быстрых операций + Web UI для сложных. Покрыть 100% функциональности, включая все комбинации параметров |

> Полный план ML-разработки: **`docs/ml-plan.md`**

---

## Итог

| Показатель | Значение |
|---|---|
| Всего фич | **79** (+5 запланировано) |
| Файлов в проекте | 13 (`main.py`, `step1–3.py`, `compare.py`, `benchmark/benchmark.py`, `db.py`, `config/settings.py`, `config/prompts.py`, `config/taxonomy.py`, `config/domain_rules.py`, `README.md`, `docs/`) |
| GPU утилизация: старт → финал | 5–10% → **30–50%** (65% GPU, 35% CPU split) |
| Сессий | 11 (6 дней) |
| Коммитов | 30+ |
