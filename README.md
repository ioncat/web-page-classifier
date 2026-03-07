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
# Добавить подсказки один раз
python main.py --add-tags "python, machine learning, devops, frontend, security, tutorial"
```

### Промпт

```
Classify the following web page by assigning 1 to 3 short topic tags.
Rules:
- Tags must be in the same language as the title (Russian or English).
- You may use the suggested tags OR invent your own — pick whatever fits best.
- Respond with ONLY a comma-separated list of tags, nothing else.

Tag suggestions: python, tutorial, ...

URL: https://...
Title: ...
```

### Переклассификация

```bash
# Сбросить категории и запустить заново
python -c "import sqlite3; conn = sqlite3.connect('urls.db'); conn.execute('UPDATE urls SET category = NULL'); conn.commit()"
python main.py --only-classify
```

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
