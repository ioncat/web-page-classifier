# URL Parser

Инструмент для сбора, парсинга заголовков и LLM-классификации веб-страниц по списку URL.
Данные хранятся в SQLite, прогресс сохраняется между запусками.

## Структура проекта

```
url-parser/
├── main.py          # точка входа, CLI
├── step1.py         # импорт URL из файла в БД
├── step2.py         # парсинг <title> для каждого URL
├── step3.py         # классификация через локальный Ollama LLM
├── compare.py       # сравнение нескольких моделей side-by-side
├── benchmark.py     # поиск оптимального batch/workers
├── db.py            # работа с SQLite
├── requirements.txt
├── raw_links.txt    # входной файл со ссылками
└── urls.db          # база данных (создаётся автоматически)
```

## Установка

```bash
pip install -r requirements.txt
```

Для step3 также нужна локальная [Ollama](https://ollama.com):
```bash
# Установить и запустить Ollama
ollama serve

# Загрузить модель (один раз)
ollama pull llama3
```

## Входной файл

`raw_links.txt` — текстовый файл со ссылками в любом формате:

```
https://habr.com/ru/articles/805105/
https://example.com | Example Site
какой-то текст https://site.com/page и ещё текст
```

Скрипт сам извлечёт URL регулярным выражением, очистит и дедуплицирует.

## Запуск

### Полный пайплайн (step1 + step2)

```bash
python main.py
```

### Только импорт URL в БД

```bash
python main.py --only-import
```

### Только парсинг заголовков

```bash
python main.py --only-parse
```

### Только классификация через Ollama

```bash
python main.py --only-classify
```

## Все флаги

| Флаг | Описание |
|---|---|
| `--input FILE` | входной файл для step1 (по умолчанию: `raw_links.txt`) |
| `--limit N` | обработать не более N URL за один запуск |
| `--force` | сбросить все записи в `pending` и начать заново |
| `--retry-failed` | повторить только URL с ошибками |
| `--url URL` | добавить и обработать один конкретный URL |
| `--domain DOMAIN` | обработать только URL указанного домена |
| `--only-import` | запустить только step1 |
| `--only-parse` | запустить только step2 |
| `--only-classify` | запустить только step3 (Ollama) |
| `--model MODEL` | модель Ollama для step3 (по умолчанию: первая доступная) |
| `--list-models` | показать список доступных моделей и выйти |
| `--add-tags TAGS` | добавить теги-подсказки в справочник (через запятую) |
| `--sync-tags` | импортировать накопленные теги из `category` в справочник и выйти |
| `--re-tag` | сбросить `category`/`tagged_by` у всех done-URL и запустить step3 заново |
| `--clear-tags` | очистить таблицу `tags` (справочник) и выйти |
| `--compare-models M1 M2 ...` | запустить несколько моделей, сохранить результаты в `model_results` (модели через пробел или запятую) |
| `--compare` | показать side-by-side Rich-таблицу результатов сравнения |
| `--compare --export FILE.csv` | то же + экспорт в CSV |
| `--accept-model MODEL` | скопировать результаты модели в `urls.category` (финальный выбор) |
| `--compare-clear` | очистить таблицу `model_results` |
| `--workers N` | кол-во параллельных потоков к Ollama (по умолчанию: 1) |
| `--batch N` | кол-во URL в одном запросе к модели — батчинг (по умолчанию: 1, рекомендуется 5–20) |
| `--no-progress` | отключить progress bar, plain вывод в консоль |
| `-v, --verbose` | показывать заголовок / теги / ошибку по каждому URL |

## Примеры

```bash
# Полный пайплайн
python main.py

# Только парсинг, первые 50 URL
python main.py --only-parse --limit 50

# Повторить URL с ошибками
python main.py --retry-failed

# Сбросить всё и начать заново
python main.py --force

# Обработать один URL
python main.py --url https://habr.com/ru/articles/805105/

# Другой входной файл
python main.py --input links.txt

# Только URL с habr.com
python main.py --domain habr.com

# Повторить ошибки для конкретного домена
python main.py --domain habr.com --retry-failed

# Plain вывод с деталями (для логов)
python main.py --no-progress -v

# Записать вывод в файл
python main.py --no-progress > run.log

# Классификация — посмотреть доступные модели
python main.py --list-models

# Классифицировать с конкретной моделью
python main.py --only-classify --model mistral

# Добавить подсказки для классификации
python main.py --add-tags "python,ai,tutorial,data science,devops"

# Классифицировать первые 20 URL с деталями
python main.py --only-classify --limit 20 -v
```

## Схема БД

Таблица `urls` в файле `urls.db`:

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER | первичный ключ |
| `url` | TEXT | адрес страницы (уникальный) |
| `status` | TEXT | `pending` / `done` / `error` |
| `title` | TEXT | содержимое тега `<title>` |
| `error` | TEXT | текст ошибки если статус `error` |
| `added_at` | TEXT | дата добавления |
| `processed_at` | TEXT | дата обработки |
| `category` | TEXT | теги, присвоенные моделью (step3) |
| `tagged_by` | TEXT | имя модели Ollama, которая классифицировала URL |

Таблица `tags` — справочник тегов-подсказок для LLM:

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER | первичный ключ |
| `name` | TEXT | название тега (уникальное) |

### Полезные SQL-запросы

```sql
-- Статистика по статусам
SELECT status, COUNT(*) FROM urls GROUP BY status;

-- Все ошибки
SELECT url, error FROM urls WHERE status = 'error';

-- Переобработать ошибки вручную
UPDATE urls SET status = 'pending', error = NULL WHERE status = 'error';

-- Посмотреть результаты по домену
SELECT url, title FROM urls WHERE url LIKE '%habr.com%' AND status = 'done';

-- URL с присвоенными тегами и моделью-классификатором
SELECT url, title, category, tagged_by FROM urls WHERE category IS NOT NULL;

-- Статистика по моделям
SELECT tagged_by, COUNT(*) as cnt FROM urls WHERE tagged_by IS NOT NULL GROUP BY tagged_by;

-- Сбросить категории (для переклассификации)
UPDATE urls SET category = NULL, tagged_by = NULL WHERE status = 'done';
```

## Поведение при повторном запуске

- URL со статусом `done` **пропускаются** в step2 — повторно не запрашиваются
- URL без `category` обрабатываются в step3 — классифицируются заново только при сбросе
- При добавлении дублирующихся URL через `--url` или `--input` — они игнорируются (`INSERT OR IGNORE`)

## Step 3 — Классификация через Ollama

Step3 берёт все URL со статусом `done` и без присвоенной категории, передаёт в локальную LLM заголовок страницы и просит назначить 1–3 тега.

При запуске без `--model` скрипт показывает список доступных моделей и предлагает выбрать одну интерактивно.
Имя выбранной модели сохраняется в колонку `tagged_by` для каждого классифицированного URL.

### Теги-подсказки

Теги из таблицы `tags` передаются в промпт как подсказки. Модель **может использовать их или создавать собственные** — ограничений нет, сохраняется всё, что вернула модель.

```bash
# Добавить начальные подсказки вручную
python main.py --add-tags "python, machine learning, devops, frontend, security, tutorial"
```

### Повторная классификация (ре-тэггинг)

```bash
# Перетэггировать всё заново (справочник сохраняется как подсказки)
python main.py --re-tag

# Перетэггировать другой моделью
python main.py --re-tag --model mistral

# Полный сброс — очистить справочник И перетэггировать с чистого листа
python main.py --clear-tags && python main.py --re-tag
```

Поведение `--re-tag`:

| Что сбрасывается | Что сохраняется |
|---|---|
| `category = NULL` для всех `done` URL | таблица `tags` (подсказки) |
| `tagged_by = NULL` для всех `done` URL | сами URL и их `title` |

Справочник намеренно **не очищается**: накопленные теги помогают новой модели давать согласованные результаты. Если нужен полный сброс — сначала `--clear-tags`.

### Автоматическое обновление справочника

Во время классификации справочник обновляется **автоматически**: каждый новый тег от модели сразу добавляется в таблицу `tags`. Это работает в обе стороны:

- Чем дальше идёт классификация, тем богаче становятся подсказки для следующих URL
- Модель видит уже использованные теги и тяготеет к более согласованной терминологии

Если уже есть классифицированные URL и нужно наполнить справочник из них:

```bash
python main.py --sync-tags
```

### Промпты

**Одиночный запрос** (`--batch 1`, по умолчанию):
```
Classify the following web page by assigning 1 to 3 short topic tags.
Rules: ...

URL: https://...
Title: ...
```

**Пакетный запрос** (`--batch N`):
```
Classify each web page below with 1–3 short topic tags.
Rules: ...
Format exactly: 1. tag1, tag2, tag3

1. URL: https://...
   Title: ...
2. URL: https://...
   Title: ...
```

Ответ модели ограничен `num_predict` (80 токенов для одиночного, 30×N для пакетного) — защита от бесконечной генерации. Если модель не смогла разобрать ответ для отдельного URL в батче, делается автоматический fallback на одиночный запрос для этого URL.

### Переклассификация

```bash
# Сбросить категории и запустить заново
python -c "import sqlite3; conn = sqlite3.connect('urls.db'); conn.execute('UPDATE urls SET category = NULL'); conn.commit()"
python main.py --only-classify
```

## Сравнение моделей

Режим позволяет прогнать несколько Ollama-моделей на одном наборе URL и сравнить их результаты side-by-side — без влияния на основные данные (`urls.category`).

### Полный цикл сравнения

```bash
# 1. Запустить несколько моделей (результаты пишутся в model_results, не в urls.category)
#    Модели можно перечислять через пробел или запятую — оба варианта равнозначны
python main.py --compare-models llama3 mistral gemma2
python main.py --compare-models llama3,mistral,gemma2  # то же самое

# 1а. Только для конкретного домена + параллельные запросы
python main.py --compare-models llama3 mistral --domain habr.com --workers 4

# 1б. Ограничить кол-во URL (для быстрого теста)
python main.py --compare-models llama3 mistral --domain habr.com --limit 20

# 2. Посмотреть результаты в терминале
python main.py --compare

# 3. Экспортировать в CSV для детального анализа
python main.py --compare --export compare_results.csv

# 4. Выбрать лучшую модель и применить её результаты как финальные
python main.py --accept-model mistral

# 5. Очистить таблицу сравнения (если нужно начать заново)
python main.py --compare-clear
```

### Производительность: батчинг и параллельность

По умолчанию step3 отправляет по одному URL за запрос последовательно. Два флага позволяют существенно ускорить классификацию и повысить утилизацию GPU.

**`--batch N`** — отправляет N URL в одном запросе к модели. Вместо N коротких запросов модель получает один нумерованный список и возвращает ответ для каждого URL. Снижает накладные расходы и позволяет модели дольше работать с GPU без простоев.

**`--workers N`** — запускает N параллельных потоков, каждый со своим запросом к Ollama.

```bash
# Батчинг: 10 URL за запрос, последовательно
python main.py --only-classify --batch 10

# Батчинг + параллельность: 4 потока × 10 URL = 40 URL "в воздухе"
python main.py --only-classify --batch 10 --workers 4

# Сравнение моделей с теми же параметрами
python main.py --compare-models llama3 mistral --workers 4
```

Для **настоящего GPU-параллелизма** дополнительно установите переменную окружения перед запуском Ollama:

```bash
# Windows
set OLLAMA_NUM_PARALLEL=4
ollama serve

# Linux / macOS
OLLAMA_NUM_PARALLEL=4 ollama serve
```

| `--batch` | `--workers` | `OLLAMA_NUM_PARALLEL` | Утилизация GPU |
|---|---|---|---|
| 1 | 1 | 1 | ~5–10% (по умолчанию) |
| 1 | 4 | 4 | ~30–50% |
| 10 | 4 | 4 | ~80–90% ✓ |
| 20 | 4 | 4 | ~85–95% |

> **Рекомендация:** начните с `--batch 10 --workers 4`. Для подбора оптимума используйте `benchmark.py`.

### Поиск оптимальных параметров

`benchmark.py` автоматически прогоняет несколько конфигураций на одном наборе URL и выводит сравнительную таблицу URL/с:

```bash
python benchmark.py                     # 50 URL × 10 конфигов
python benchmark.py --limit 30          # быстрее, меньше URL
python benchmark.py --no-warmup         # модель уже в VRAM
python benchmark.py --only 0 4 6 7     # только конкретные конфиги
```

Пример вывода:
```
★ batch=10 ×4    10    4    18.3    54.6    ×12.3
  batch=20 ×4    20    4    21.1    47.4    ×10.7
  ...
  baseline        1    1   192.0     4.4    ×1.0

Запустить победителя: python main.py --only-classify --batch 10 --workers 4
```

### Фильтрация по домену

`--domain` работает совместно с `--compare-models` — прогоняет модели только по URL указанного домена.
Фильтрация нечувствительна к `www.` и регистру: `habr.com` и `www.habr.com` эквивалентны.

```bash
python main.py --compare-models llama3 mistral --domain habr.com
# Вывод: URL: 42  |  Модели: llama3, mistral  |  Домен: habr.com
```

### Изоляция

`--compare-models` **не трогает** `urls.category` и таблицу `tags` — это чистый эксперимент.
Переход результатов в основные данные происходит **только явным** `--accept-model`.

| Таблица | Кто пишет | Изоляция |
|---|---|---|
| `model_results` | `--compare-models` | только для сравнения |
| `urls.category` | `--only-classify`, `--accept-model` | финальный результат |

Подробная схема и диаграммы: [`docs/models-compare.md`](docs/models-compare.md)

## Polite crawling

Скрипт не перегружает серверы — для этого реализованы три механизма.

### Случайные задержки

Перед каждым запросом делается пауза `random.uniform(2, 5)` секунд.
Это имитирует поведение человека и снижает риск rate-limit.

### Ротация User-Agent

Каждый запрос уходит со случайным User-Agent из пула:
- Chrome 124 / Windows
- Safari 17 / macOS
- Firefox 125 / Linux
- Edge 123 / Windows

### Retry с exponential back-off

Два слоя защиты от ошибок:

| Слой | Что обрабатывает | Как |
|---|---|---|
| `urllib3.Retry` | HTTP 429, 500, 502, 503, 504 | автоматически, прозрачно |
| ручной retry-loop | ReadTimeout, ConnectionError | вручную, с логом в консоль |

Расписание backoff при сетевых ошибках:
```
Попытка 1 → ждём 2s → retry
Попытка 2 → ждём 4s → retry
Попытка 3 → ждём 8s → raise → статус error в БД
```

Сервер вернул `Retry-After`? Скрипт подождёт ровно столько, сколько указано.

### Таймауты

```python
timeout = (10, 30)  # connect: 10s, read: 30s
```

## Обработка ошибок

Ошибки при парсинге (таймаут, 404, нет `<title>`) не прерывают выполнение.
URL получает статус `error`, сообщение сохраняется в колонку `error`.
После завершения выводится таблица с ошибками и подсказка для повтора.
