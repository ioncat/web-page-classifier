# Web UI — web-page-classifier

Веб-интерфейс для просмотра и управления классифицированными URL.
Mobile-first, доступен из интернета.

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
| `DB_PATH` | `urls.db` | Путь к SQLite БД |
| `PIPELINE_PYTHON` | `venv/Scripts/python.exe` (авто) | Путь к Python-интерпретатору пайплайна для refetch |

Локально можно задать в `.env` или напрямую в терминале:

```bash
export WEB_USER=admin
export WEB_PASSWORD=secret
export DB_PATH=../urls.db
```

## Возможности

- Просмотр URL по категориям, поиск по title / description / URL
- **Удаление** URL из БД прямо из интерфейса (кнопка 🗑)
- **Перемещение** в другую категорию:
  - Десктоп: перетащи карточку на категорию в sidebar (подсветится зелёным)
  - Мобайл / десктоп: кнопка ↔ → модальное окно со списком категорий
- **Обработка (refetch)** — перезагрузка title и description через пайплайн:
  - Кнопка 🔄 на карточке — обработать один URL
  - Массовое: «Выбрать» → отметить → «Обработать выбранные»
  - Вызывает `set_url_pending()` + `step2.main()` через subprocess (пайплайн venv)
  - Без импорта (step1), без классификации (step3) — только fetch метаданных
- **Массовое удаление**: кнопка «Выбрать» → отметить нужные → «Удалить выбранные»
  - «Выбрать все» — отмечает все карточки на странице
  - Счётчики категорий в sidebar обновляются сразу, без перезагрузки

## Запуск локально

Запускать из **корня проекта** с активированным `web/venv`:

```bash
# Из корня проекта
.\web\venv\Scripts\Activate.ps1           # PowerShell
# или
.\web\venv\Scripts\activate.bat           # cmd

python -m uvicorn web.app:app --port 8000 --reload

# Открыть в браузере
http://localhost:8000
# Логин по умолчанию: admin / changeme

# После изменений — перезапустить сервер (Ctrl+C, затем снова):
# статика кэшируется браузером; cache-busting срабатывает при перезапуске
python -m uvicorn web.app:app --port 8000 --reload
```

> Запускать именно из корня (`web-page-classifier/`), иначе сломаются импорты `web.*` и путь к `urls.db`.

## Структура

```
web/
├── app.py              # точка входа FastAPI
├── auth.py             # HTTP Basic Auth
├── database.py         # запросы к SQLite (чтение + удаление/смена категории/получение URL по id)
├── models.py           # Pydantic схемы
├── routers/
│   ├── pages.py        # HTML-роуты
│   └── api.py          # JSON API
├── templates/
│   ├── base.html       # базовый layout
│   ├── index.html      # главная (категории)
│   ├── category.html   # страница категории
│   ├── search.html     # поиск
│   └── _url_card.html  # компонент карточки URL
├── static/
│   └── app.js          # бургер-меню, удаление, DnD, модальное окно, массовые операции, refetch
└── docs/
    └── backlog.md      # план разработки
```

## Деплой (Railway / Render)

```bash
uvicorn web.app:app --host 0.0.0.0 --port $PORT
```

Переменные `WEB_USER`, `WEB_PASSWORD`, `DB_PATH` задаются в настройках сервиса.

> Подробный план разработки: [`web/docs/backlog.md`](docs/backlog.md)
