# Web UI — web-page-classifier

Веб-интерфейс для просмотра и управления классифицированными URL.
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

## Возможности

- Просмотр URL по категориям, поиск по title / description / URL
- **Удаление** URL из БД прямо из интерфейса (кнопка 🗑)
- **Перемещение** в другую категорию:
  - Десктоп: перетащи карточку на категорию в sidebar (подсветится зелёным)
  - Мобайл / десктоп: кнопка ↔ → модальное окно со списком категорий

## Запуск локально

```bash
# Из корня проекта
python -m uvicorn web.app:app --port 8000 --reload

# Открыть в браузере
http://localhost:8000
# Логин по умолчанию: admin / changeme

# После изменений в коде — перезапустить сервер (Ctrl+C, затем снова):
# (статика кэшируется браузером; cache-busting срабатывает при перезапуске)
python -m uvicorn web.app:app --port 8000 --reload
```

## Структура

```
web/
├── app.py              # точка входа FastAPI
├── auth.py             # HTTP Basic Auth
├── database.py         # запросы к SQLite (чтение + удаление/смена категории)
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
│   └── app.js          # бургер-меню, удаление, DnD, модальное окно
└── docs/
    └── backlog.md      # план разработки
```

## Деплой (Railway / Render)

```bash
uvicorn web.app:app --host 0.0.0.0 --port $PORT
```

Переменные `WEB_USER`, `WEB_PASSWORD`, `DB_PATH` задаются в настройках сервиса.

> Подробный план разработки: [`web/docs/backlog.md`](docs/backlog.md)
