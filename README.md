# URL Parser

Инструмент для сбора и парсинга заголовков веб-страниц по списку URL.
Данные хранятся в SQLite, прогресс сохраняется между запусками.

## Структура проекта

```
url-parser/
├── main.py          # точка входа, CLI
├── step1.py         # импорт URL из файла в БД
├── step2.py         # парсинг <title> для каждого URL
├── step3.py         # анализ через LLM (в разработке)
├── db.py            # работа с SQLite
├── requirements.txt
├── raw_links.txt    # входной файл со ссылками
└── urls.db          # база данных (создаётся автоматически)
```

## Установка

```bash
pip install -r requirements.txt
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

### Полный пайплайн

```bash
python main.py
```

Запускает step1 (импорт) → step2 (парсинг) последовательно.

### Только импорт URL в БД

```bash
python main.py --only-import
```

### Только парсинг заголовков

```bash
python main.py --only-parse
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
| `--no-progress` | отключить progress bar, plain вывод в консоль |
| `-v, --verbose` | показывать заголовок / ошибку по каждому URL |

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
```

## Поведение при повторном запуске

- URL со статусом `done` **пропускаются** — повторно не запрашиваются
- URL со статусом `pending` или `error` обрабатываются
- При добавлении дублирующихся URL через `--url` или `--input` — они игнорируются (`INSERT OR IGNORE`)

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
