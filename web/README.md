# Web UI — web-page-classifier

Веб-интерфейс для просмотра классифицированных URL по категориям.
Mobile-first, доступен из интернета.

## Стек

- **Backend:** FastAPI + Jinja2
- **Frontend:** Tailwind CSS (CDN) + vanilla JS
- **БД:** SQLite локально → PostgreSQL в облаке

## Установка

```bash
# Только веб-зависимости (отдельно от пайплайна)
pip install -r web/requirements.txt
```

> Зависимости пайплайна (`requests`, `ollama`, `rich` и др.) находятся в корневом `requirements.txt` и для веб UI не нужны.

## Переменные окружения

| Переменная | По умолчанию | Описание |
|------------|-------------|---------|
| `WEB_USER` | — | Логин для Basic Auth |
| `WEB_PASSWORD` | — | Пароль для Basic Auth |
| `DB_PATH` | `urls.db` | Путь к SQLite БД |

Локально можно задать в `.env` или напрямую в терминале:

```bash
export WEB_USER=admin
export WEB_PASSWORD=secret
export DB_PATH=../urls.db
```

## Запуск локально

```bash
# Из корня проекта
uvicorn web.app:app --reload

# Открыть в браузере
http://localhost:8000
```

## Структура

```
web/
├── app.py              # точка входа FastAPI
├── auth.py             # HTTP Basic Auth
├── database.py         # read-only запросы к SQLite
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
│   └── app.js          # бургер-меню
└── docs/
    └── backlog.md      # план разработки
```

## Деплой (Railway / Render)

```bash
uvicorn web.app:app --host 0.0.0.0 --port $PORT
```

Переменные `WEB_USER`, `WEB_PASSWORD`, `DB_PATH` задаются в настройках сервиса.

> Подробный план разработки: [`web/docs/backlog.md`](docs/backlog.md)
