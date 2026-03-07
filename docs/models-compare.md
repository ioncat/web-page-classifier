# Сравнение моделей — схема и диаграммы

Документ описывает архитектуру запуска нескольких Ollama-моделей
на одном наборе URL и сравнения результатов их классификации.

---

## Схема базы данных (полная)

### Таблицы и связи

```mermaid
erDiagram
    urls {
        INTEGER id PK
        TEXT    url        "UNIQUE"
        TEXT    status     "pending | done | error"
        TEXT    title
        TEXT    error
        TEXT    added_at
        TEXT    processed_at
        TEXT    category   "финальный выбор (step3 / --accept-model)"
        TEXT    tagged_by  "модель, выставившая финальный тег"
    }

    tags {
        INTEGER id   PK
        TEXT    name "UNIQUE — подсказки для LLM-промпта"
    }

    model_results {
        INTEGER id        PK
        INTEGER url_id    FK
        TEXT    model     "имя модели Ollama"
        TEXT    category  "теги от этой модели"
        TEXT    tagged_at
    }

    urls      ||--o{ model_results : "url_id"
```

> **Ключевой constraint:** `UNIQUE(url_id, model)` в `model_results` —
> повторный запуск той же модели перезаписывает результат (upsert).

---

## Жизненный цикл данных

```mermaid
flowchart TD
    A([raw_links.txt]) --> S1

    subgraph step1["Step 1 — Импорт"]
        S1[Regex-извлечение URL\nДедупликация]
        S1 --> DB1[(urls\nstatus=pending)]
    end

    subgraph step2["Step 2 — Парсинг"]
        DB1 --> S2[HTTP запрос\npolite crawling\nretry + backoff]
        S2 --> DB2[(urls\nstatus=done\ntitle=...)]
        S2 --> DB2e[(urls\nstatus=error)]
    end

    subgraph step3["Step 3 — Классификация"]
        DB2 --> S3{Режим?}

        S3 -->|"--only-classify\n--re-tag"| NORM[Один запуск\nодна модель]
        NORM --> DBcat[(urls\ncategory=...\ntagged_by=...)]
        NORM --> DBtags[(tags\nсправочник\nобновляется)]

        S3 -->|"--compare-models"| CM[Несколько моделей\nпо очереди]
        CM --> DBmr[(model_results\nurl_id + model\n+ category)]
    end

    subgraph compare["Сравнение и выбор"]
        DBmr --> CMP["--compare\nside-by-side таблица"]
        DBmr --> EXP["--compare --export\nCSV файл"]
        CMP --> ACC["--accept-model mistral\nкопирует в urls.category"]
        ACC --> DBcat
    end
```

---

## Процесс сравнения моделей

```mermaid
sequenceDiagram
    actor User
    participant CLI as main.py
    participant S3  as step3.py
    participant OL  as Ollama
    participant DB  as urls.db

    User->>CLI: --compare-models llama3,mistral,gemma2

    loop для каждой модели
        CLI->>S3: main(model=X, compare_mode=True)
        S3->>DB: get_done_urls() → N строк

        loop для каждого URL
            S3->>OL: chat(model=X, prompt+title)
            OL-->>S3: "tag1, tag2"
            S3->>DB: save_model_result(url_id, model=X, category)
        end

        S3-->>CLI: готово (N/err статистика)
    end

    CLI-->>User: все модели отработали

    User->>CLI: --compare
    CLI->>DB: get_model_results()
    DB-->>CLI: [{url, title, llama3, mistral, gemma2}, ...]
    CLI-->>User: Rich-таблица side-by-side

    User->>CLI: --accept-model mistral
    CLI->>DB: copy model_results(model=mistral) → urls.category
    CLI-->>User: N записей обновлено
```

---

## Схема таблицы `model_results`

```sql
CREATE TABLE model_results (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    url_id    INTEGER NOT NULL REFERENCES urls(id) ON DELETE CASCADE,
    model     TEXT    NOT NULL,
    category  TEXT,
    tagged_at TEXT    DEFAULT (datetime('now')),
    UNIQUE(url_id, model)
);

CREATE INDEX idx_model_results_model ON model_results(model);
```

### Логика записи (upsert)

```sql
INSERT INTO model_results (url_id, model, category, tagged_at)
VALUES (?, ?, ?, datetime('now'))
ON CONFLICT(url_id, model)
DO UPDATE SET
    category  = excluded.category,
    tagged_at = excluded.tagged_at;
```

---

## SQL-запросы для анализа

```sql
-- Side-by-side для первых 20 URL (pivot через GROUP BY + MAX CASE)
SELECT
    u.title,
    u.url,
    MAX(CASE WHEN mr.model LIKE '%llama3%'  THEN mr.category END) AS llama3,
    MAX(CASE WHEN mr.model LIKE '%mistral%' THEN mr.category END) AS mistral,
    MAX(CASE WHEN mr.model LIKE '%gemma%'   THEN mr.category END) AS gemma2
FROM urls u
JOIN model_results mr ON mr.url_id = u.id
GROUP BY u.id
LIMIT 20;

-- Сколько URL каждая модель обработала
SELECT model, COUNT(*) AS cnt FROM model_results GROUP BY model;

-- URL где модели дали наиболее разные теги
SELECT u.url, u.title, COUNT(DISTINCT mr.category) AS unique_results
FROM urls u
JOIN model_results mr ON mr.url_id = u.id
GROUP BY u.id
HAVING unique_results > 1
ORDER BY unique_results DESC;

-- Самые частые теги от конкретной модели
SELECT mr.model, tag.value AS tag, COUNT(*) AS freq
FROM model_results mr,
     json_each('["' || REPLACE(mr.category, ', ', '","') || '"]') AS tag
GROUP BY mr.model, tag.value
ORDER BY mr.model, freq DESC;
```

---

## Новые флаги CLI (планируемые)

| Флаг | Описание |
|---|---|
| `--compare-models M1,M2,...` | запустить несколько моделей, сохранить в `model_results` |
| `--compare` | показать side-by-side Rich-таблицу результатов |
| `--compare --export FILE.csv` | экспортировать сравнение в CSV |
| `--accept-model MODEL` | скопировать результаты модели в `urls.category` |
| `--compare-clear` | очистить таблицу `model_results` |

---

## Изоляция: эксперименты vs финальный выбор

```mermaid
flowchart LR
    MR[(model_results\nрезультаты сравнения)]
    UC[(urls.category\nфинальный выбор)]

    MR -->|"--accept-model"| UC
    UC -.->|"НЕ влияет"| MR

    style MR fill:#2d4a6e,color:#fff
    style UC fill:#2d6e4a,color:#fff
```

`model_results` и `urls.category` **полностью изолированы**:
- `--compare-models` пишет только в `model_results`, не трогает `urls.category`
- `--only-classify` пишет только в `urls.category`, не трогает `model_results`
- Переход между ними — только явный `--accept-model`
