# URL Parser

Инструмент для автоматической обработки списков URL: импорт, парсинг заголовков и LLM-классификация с помощью локальных Ollama-моделей. Данные хранятся в SQLite — прогресс сохраняется между запусками, повторная обработка уже готовых URL пропускается автоматически.

**Для чего:**
- Разобрать большую коллекцию закладок / ссылок по темам
- Классифицировать страницы без интернета и внешних API — всё локально
- Сравнить несколько LLM-моделей и выбрать лучшую для конкретного набора URL

---

## Логика проекта

Каждый URL в БД всегда находится в одном из трёх состояний:

```
pending → done → (category = NULL)  →  step3 классифицирует
                 (category = '...') →  уже готов, пропускается

pending → error                     →  --retry-failed повторяет
```

**Ключевые принципы:**
- Идемпотентность: повторный запуск без флагов не трогает уже обработанные URL
- Теги-подсказки (`tags`): модель видит уже накопленные теги → результаты становятся согласованнее по ходу классификации
- Сравнение моделей — изолировано: `--compare-models` никогда не меняет `urls.category`, только свою таблицу `model_results`

---

## Пайплайн

```
raw_links.txt
      │
      ▼
  [step1] Импорт
  Извлекает URL регулярным выражением, дедуплицирует,
  добавляет в БД со статусом pending.
      │
      ▼
  [step2] Парсинг заголовков
  Загружает страницу, достаёт <title>.
  Успех → status = done.  Ошибка → status = error.
      │
      ▼
  [step3] Классификация через Ollama
  Берёт done-URL без category, отправляет title в LLM,
  получает 1–3 тега, пишет в category + tagged_by.
      │
      ▼
   urls.db  ←  все результаты
```

Каждый шаг можно запускать отдельно. Полный прогон — `python main.py` без флагов.

---

## Установка

```bash
pip install -r requirements.txt
```

Для step3 нужна локальная [Ollama](https://ollama.com):

```bash
ollama serve
ollama pull llama3   # загрузить модель один раз
```

### Входной файл

`raw_links.txt` — текстовый файл со ссылками в любом формате:
```
https://habr.com/ru/articles/805105/
https://example.com | Example Site
какой-то текст https://site.com/page и ещё текст
```
Скрипт сам извлечёт URL, очистит и дедуплицирует.

---

## Запуск

```bash
python main.py                        # полный пайплайн: step1 + step2 + step3
python main.py --only-import          # только step1 — загрузить URL в БД
python main.py --only-parse           # только step2 — спарсить заголовки
python main.py --only-classify        # только step3 — классифицировать

python benchmark/benchmark.py         # найти оптимальный batch/workers
```

---

## Флаги

### Управление пайплайном

| Флаг | Что делает |
|---|---|
| `--only-import` | запустить только step1 (импорт URL) |
| `--only-parse` | запустить только step2 (парсинг заголовков) |
| `--only-classify` | запустить только step3 (классификация через Ollama) |
| `--re-tag` | сбросить `category`/`tagged_by` у всех done-URL и запустить step3 заново |

### Фильтрация и входные данные

| Флаг | Что делает |
|---|---|
| `--input FILE` | входной файл для step1 (по умолчанию: `raw_links.txt`) |
| `--url URL` | добавить один URL и обработать его |
| `--domain DOMAIN` | обрабатывать только URL этого домена (нечувствительно к `www.` и регистру) |
| `--limit N` | обработать не более N URL за один запуск |
| `--force` | сбросить все записи в `pending` и начать заново |
| `--retry-failed` | повторить только URL со статусом `error` |

### Параллельность

| Флаг | Что делает | По умолчанию |
|---|---|---|
| `--workers N` | кол-во параллельных потоков | 1 |

- **Step2:** воркеры распределяются по доменам round-robin — одновременно идут только разные домены, снижая риск бана
- **Step3:** параллельные запросы к Ollama (для GPU-параллелизма также нужен `OLLAMA_NUM_PARALLEL=N`)

### Классификация (step3 / Ollama)

| Флаг | Что делает | По умолчанию |
|---|---|---|
| `--model MODEL` | модель Ollama | первая доступная |
| `--list-models` | показать список доступных моделей и выйти | — |
| `--batch N` | кол-во URL в одном запросе к модели (батчинг) | 1 |
| `--no-think` | отключить thinking-режим модели (`think: false`) | выкл. |

> `--no-think` нужен для thinking-моделей: `qwen3`, `deepseek-r1`, `minimax-m2` и др.
> Для обычных моделей флаг не нужен и не влияет на результат.

### Управление тегами-подсказками

| Флаг | Что делает |
|---|---|
| `--add-tags TAGS` | добавить теги в справочник вручную (через запятую) |
| `--sync-tags` | импортировать теги из `category` в справочник и выйти |
| `--clear-tags` | очистить таблицу `tags` и выйти |

### Сравнение моделей

| Флаг | Что делает |
|---|---|
| `--compare-models M1 M2 …` | прогнать несколько моделей, результаты → `model_results` (не трогает `urls.category`) |
| `--compare` | показать side-by-side таблицу результатов в терминале |
| `--compare --export FILE.csv` | то же + экспорт в CSV |
| `--accept-model MODEL` | скопировать результаты модели в `urls.category` (финальный выбор) |
| `--compare-clear` | очистить таблицу `model_results` |

### Вывод

| Флаг | Что делает |
|---|---|
| `--no-progress` | отключить progress bar, plain вывод (удобно для логов) |
| `-v, --verbose` | показывать заголовок / теги / ошибку по каждому URL |

---

## Примеры

### Основной пайплайн

```bash
# Полный прогон
python main.py

# Другой входной файл, первые 100 URL
python main.py --input links.txt --limit 100

# Добавить и сразу обработать один URL
python main.py --url https://habr.com/ru/articles/805105/

# Только habr.com
python main.py --domain habr.com

# Повторить ошибки
python main.py --retry-failed

# Сбросить всё и начать заново
python main.py --force

# Параллельный парсинг — 4 потока, разные домены одновременно
python main.py --only-parse --workers 4
```

### Классификация

```bash
# Посмотреть доступные модели
python main.py --list-models

# Классифицировать конкретной моделью
python main.py --only-classify --model mistral

# Thinking-модели (qwen3, deepseek-r1, minimax-m2) — обязательно с --no-think
python main.py --only-classify --model qwen3:8b --no-think
python main.py --only-classify --model minimax-m2:cloud --no-think

# Батчинг + параллельность (быстрее на больших объёмах)
python main.py --only-classify --batch 10 --workers 4

# Перетэггировать всё другой моделью
python main.py --re-tag --model mistral
```

### Теги-подсказки

```bash
# Добавить начальные подсказки
python main.py --add-tags "python, machine learning, devops, frontend, security"

# Наполнить справочник из уже классифицированных URL
python main.py --sync-tags

# Полный сброс: очистить справочник + перетэггировать с нуля
python main.py --clear-tags && python main.py --re-tag
```

### Сравнение моделей

```bash
# Прогнать три модели
python main.py --compare-models llama3 mistral gemma2

# Только первые 20 URL конкретного домена
python main.py --compare-models llama3 mistral --domain habr.com --limit 20

# Посмотреть результаты
python main.py --compare

# Экспортировать в CSV
python main.py --compare --export compare_results.csv

# Применить лучшую модель
python main.py --accept-model mistral
```

### Вывод и логи

```bash
# Plain вывод с деталями по каждому URL
python main.py --no-progress -v

# Записать в лог-файл
python main.py --no-progress > run.log
```

---

## Производительность

`--workers N` ускоряет оба шага:
- **Step2** (парсинг): 4 воркера ≈ 4× быстрее, разные домены параллельно
- **Step3** (классификация): параллельные запросы к Ollama + батчинг

По умолчанию оба шага работают последовательно (`workers=1`).
`--batch` и `--workers` позволяют существенно ускорить классификацию.

| `--batch` | `--workers` | `OLLAMA_NUM_PARALLEL` | Утилизация GPU |
|:---------:|:-----------:|:---------------------:|:----------:|
| 1 | 1 | 1 | ~5–10% (по умолчанию) |
| 1 | 4 | 4 | ~30–50% |
| 10 | 4 | 4 | ~80–90% ✓ |
| 20 | 4 | 4 | ~85–95% |

Для GPU-параллелизма запустить Ollama с переменной окружения:

```bash
# Windows (в текущей сессии PowerShell)
$env:OLLAMA_NUM_PARALLEL = 4
ollama serve

# Linux / macOS
OLLAMA_NUM_PARALLEL=4 ollama serve
```

> **Рекомендация:** начните с `--batch 10 --workers 4`.
> Для точного подбора используйте `benchmark/benchmark.py`.

### Бенчмарк

```bash
python benchmark/benchmark.py                              # 50 URL × 10 конфигов
python benchmark/benchmark.py --limit 30                  # быстрее
python benchmark/benchmark.py --model mistral --limit 30  # конкретная модель
python benchmark/benchmark.py --no-warmup                 # модель уже в VRAM
python benchmark/benchmark.py --only 0 4 6               # только нужные конфиги
```

Результат каждого полного прогона дописывается в `benchmark/benchmark_log.csv`.

---

## Схема БД

### Таблица `urls`

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER | первичный ключ |
| `url` | TEXT | адрес страницы (уникальный) |
| `status` | TEXT | `pending` / `done` / `error` |
| `title` | TEXT | содержимое тега `<title>` |
| `error` | TEXT | текст ошибки при статусе `error` |
| `added_at` | TEXT | дата добавления |
| `processed_at` | TEXT | дата обработки |
| `category` | TEXT | теги, присвоенные моделью |
| `tagged_by` | TEXT | имя модели Ollama |

### Таблица `tags` — справочник подсказок

| Колонка | Тип | Описание |
|---|---|---|
| `id` | INTEGER | первичный ключ |
| `name` | TEXT | название тега (уникальное) |

### Таблица `model_results` — изолированные результаты сравнения

| Колонка | Тип | Описание |
|---|---|---|
| `url_id` | INTEGER | ссылка на `urls.id` |
| `model` | TEXT | имя модели |
| `category` | TEXT | теги от этой модели |

### Полезные SQL-запросы

```sql
-- Статистика по статусам
SELECT status, COUNT(*) FROM urls GROUP BY status;

-- Все ошибки
SELECT url, error FROM urls WHERE status = 'error';

-- URL с присвоенными тегами
SELECT url, title, category, tagged_by FROM urls WHERE category IS NOT NULL;

-- Статистика по моделям
SELECT tagged_by, COUNT(*) FROM urls WHERE tagged_by IS NOT NULL GROUP BY tagged_by;

-- Посмотреть результаты по домену
SELECT url, title FROM urls WHERE url LIKE '%habr.com%' AND status = 'done';
```

---

## Структура проекта

```
url-parser/
├── main.py          # точка входа, CLI
├── step1.py         # импорт URL из файла в БД
├── step2.py         # парсинг <title> для каждого URL
├── step3.py         # классификация через Ollama
├── compare.py       # сравнение моделей side-by-side
├── db.py            # работа с SQLite
├── benchmark/
│   ├── benchmark.py      # поиск оптимального batch/workers
│   └── benchmark_log.csv # лог результатов (создаётся автоматически)
├── docs/
│   ├── models-compare.md # детали режима сравнения
│   └── backlog.md        # история реализованных фич
├── requirements.txt
├── raw_links.txt    # входной файл со ссылками
└── urls.db          # база данных (создаётся автоматически)
```
