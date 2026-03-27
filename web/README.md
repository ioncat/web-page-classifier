# Web UI — web-page-classifier

Веб-интерфейс для просмотра и управления классифицированными URL.
Mobile-first.

## Стек

- **Backend:** FastAPI + Jinja2
- **Frontend:** Tailwind CSS (CDN) + vanilla JS
- **БД:** SQLite локально → PostgreSQL в облаке

## Установка

Web UI — отдельный проект со своим virtualenv:

```bash
cd web/
python -m venv venv

# Активация (PowerShell)
.\venv\Scripts\Activate.ps1

# Активация (cmd)
.\venv\Scripts\activate.bat

pip install -r requirements.txt
```

> Пайплайн и Web UI — разные проекты с разными окружениями. `venv/` в корне проекта для веб UI не нужен.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|---------|
| `WEB_USER` | — | Логин для Basic Auth |
| `WEB_PASSWORD` | — | Пароль для Basic Auth |
| `DB_PATH` | `../urls.db` | Путь к SQLite БД (относительно `web/`) |
| `PIPELINE_PYTHON` | `../venv/Scripts/python.exe` (авто) | Путь к Python-интерпретатору пайплайна для refetch |

Локально можно задать в `.env` или напрямую в терминале:

```bash
export WEB_USER=admin
export WEB_PASSWORD=secret
```

## Возможности

- **Просмотр** URL по категориям, поиск по title / description / URL
- **Лента новых** (`/recent`) — все URL, новые сверху, с сортировкой
- **Без категории** (`/uncategorized`) — URL ожидающие классификации
- **Сортировка** — новые сверху / старые сверху / по алфавиту (на всех страницах)
- **Удаление** URL из БД (кнопка на карточке)
- **Перемещение в категорию** — из фиксированной таксономии (30 категорий):
  - Десктоп: перетащи карточку на категорию в sidebar (подсветится зелёным)
  - Мобайл / десктоп: кнопка ↔ → модальное окно со списком категорий таксономии
  - Ставит `manual_override=1` — LLM не перезапишет ручной выбор при `--only-classify`
  - Иконка ✎ на карточке показывает, что категория назначена вручную
- **Обработка (refetch)** — перезагрузка title и description через пайплайн:
  - Кнопка на карточке — обработать один URL
  - Массовое: «Выбрать» → отметить → «Обработать выбранные»
  - Вызывает `set_url_pending()` + `step2.main()` через subprocess (пайплайн venv)
  - Без импорта (step1), без классификации (step3) — только fetch метаданных
- **Массовые операции**: кнопка «Выбрать» → отметить нужные → удалить / обработать
  - «Выбрать все» — отмечает все карточки на странице
  - Счётчики категорий в sidebar обновляются сразу, без перезагрузки

## Запуск локально

Запускать из папки `web/` с активированным venv:

```bash
cd web/
.\venv\Scripts\Activate.ps1           # PowerShell
# или
.\venv\Scripts\activate.bat           # cmd

python -m uvicorn app:app --port 8000 --reload

# Открыть в браузере
http://localhost:8000
# Логин по умолчанию: admin / changeme

# После изменений — перезапустить сервер (Ctrl+C, затем снова):
# статика кэшируется браузером; cache-busting срабатывает при перезапуске
```

## Структура

```
web/
├── app.py              # точка входа FastAPI
├── auth.py             # HTTP Basic Auth
├── database.py         # запросы к SQLite (чтение + управление + таксономия)
├── routers/
│   ├── pages.py        # HTML-роуты (/, /category, /recent, /uncategorized, /search)
│   └── api.py          # JSON API (CRUD + refetch + bulk)
├── templates/
│   ├── base.html       # базовый layout + модалка смены категории (таксономия)
│   ├── index.html      # главная (категории)
│   ├── category.html   # страница категории
│   ├── recent.html     # лента новых URL
│   ├── uncategorized.html # URL без категории
│   ├── search.html     # поиск
│   ├── _url_card.html  # компонент карточки URL
│   └── _sort_bar.html  # компонент выбора сортировки
├── static/
│   └── app.js          # бургер-меню, удаление, DnD, модальное окно, массовые операции, refetch
├── requirements.txt    # зависимости только для UI
└── docs/
    └── backlog.md      # план разработки
```

## Таксономия

Модалка смены категории показывает 30 категорий из `config/taxonomy.py` (единый справочник для LLM и UI). При ручной смене категории ставится `manual_override=1` — LLM пропускает такие URL при `--only-classify`.

## Деплой (Railway / Render)

```bash
uvicorn app:app --host 0.0.0.0 --port $PORT
```

Переменные `WEB_USER`, `WEB_PASSWORD`, `DB_PATH` задаются в настройках сервиса.

> Подробный план разработки: [`docs/backlog.md`](docs/backlog.md)
