# Web UI — Бэклог

Веб-интерфейс для просмотра классифицированных URL из `urls.db`.
Цель: доступ с любого устройства из интернета, mobile-first.

---

## Стек

| Слой | Технология |
|------|-----------|
| Backend | FastAPI + Jinja2 |
| Frontend | Tailwind CSS (CDN, без сборки) + vanilla JS |
| БД (локально) | SQLite (`urls.db`) |
| БД (облако) | PostgreSQL (Railway / Render) — Фаза 2 |
| Авторизация | HTTP Basic Auth (`WEB_USER`, `WEB_PASSWORD`) |
| Хостинг | Railway или Render |

---

## Структура проекта

```
web/
├── app.py              # FastAPI точка входа, регистрация роутеров, Jinja2, auth
├── auth.py             # HTTP Basic Auth зависимость
├── database.py         # read-only слой к SQLite (get_conn из корневого db.py)
├── models.py           # Pydantic схемы: UrlCard, CategorySummary, SearchResult
├── routers/
│   ├── __init__.py
│   ├── pages.py        # HTML-роуты → TemplateResponse
│   └── api.py          # JSON API для AJAX
├── templates/
│   ├── base.html       # layout, Tailwind CDN, header, sidebar, бургер
│   ├── index.html      # главная: сетка карточек категорий
│   ├── category.html   # страница категории: список URL + пагинация
│   ├── search.html     # результаты поиска + форма с фильтром по категории
│   └── _url_card.html  # переиспользуемый компонент URL-карточки
├── static/
│   └── app.js          # бургер-меню (toggle sidebar на mobile)
└── docs/
    └── backlog.md      # этот файл
```

---

## Роуты

### HTML (`routers/pages.py`)

| Метод | Путь | Шаблон | Описание |
|-------|------|--------|---------|
| GET | `/` | `index.html` | Все категории со счётчиками URL |
| GET | `/category/{name}` | `category.html` | URL категории, `?page=N` |
| GET | `/search` | `search.html` | Поиск `?q=...&category=...&page=N` |

### JSON API (`routers/api.py`)

| Метод | Путь | Параметры | Описание |
|-------|------|-----------|---------|
| GET | `/api/categories` | — | Список категорий + счётчики |
| GET | `/api/urls` | `q`, `category`, `page`, `per_page` | Поиск/фильтрация URL |
| GET | `/api/stats` | — | Общая статистика |

### Системные

| Метод | Путь | Авторизация | Описание |
|-------|------|-------------|---------|
| GET | `/health` | нет | `{"status":"ok"}` для healthcheck |

---

## URL-карточка (`_url_card.html`)

```
[Title — кликабельная внешняя ссылка, target=_blank]
[description до 200 символов (серый текст, если есть)]
[badge: категория]  [domain.com — серый мелкий текст]
```

- `category` может содержать несколько тегов через запятую → рендерить каждый отдельным badge
- Hover-эффект, touch-friendly padding (min 44px)

---

## Фазы реализации

### Фаза 1 — Скелет
- [ ] Создать структуру папок `web/`
- [ ] `web/database.py` — `get_categories_with_counts()`, `get_urls_by_category()`
- [ ] `web/auth.py` — Basic Auth через `secrets.compare_digest`, env vars
- [ ] `web/app.py` — минимальный FastAPI, роут `/health`, проверка запуска
- [ ] Дополнить `requirements.txt`: `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart`
- [ ] Проверка: `uvicorn web.app:app --reload`

### Фаза 2 — Главная страница
- [ ] `base.html` — layout, Tailwind CDN, header с поиском
- [ ] `index.html` — сетка категорий (`grid-cols-2 md:grid-cols-3 lg:grid-cols-4`)
- [ ] Роут `GET /` рендерит `index.html`
- [ ] Проверка в DevTools (mobile responsive)

### Фаза 3 — Страница категории
- [ ] `_url_card.html` — компонент карточки URL
- [ ] `category.html` — список карточек + пагинация ссылками
- [ ] `database.py` — `get_urls_by_category(category, page, per_page)`
- [ ] Роут `GET /category/{name}`

### Фаза 4 — Поиск
- [ ] `database.py` — `search_urls(query, category, page, per_page)` через `LIKE`
- [ ] `search.html` — форма + результаты + пагинация
- [ ] Роут `GET /search`

### Фаза 5 — Sidebar и мобильная навигация
- [ ] Sidebar в `base.html` — список категорий, активная подсвечена
- [ ] `app.js` — бургер toggle (`hidden` класс)
- [ ] `verify_auth` подключён ко всем HTML/API роутам
- [ ] Передача `all_categories` в каждый шаблон

### Фаза 6 — Полировка
- [ ] Переменная окружения `DB_PATH` (default `"urls.db"`)
- [ ] Переменные `WEB_USER`, `WEB_PASSWORD`
- [ ] JSON API роуты (`/api/categories`, `/api/urls`, `/api/stats`)
- [ ] Проверка на реальном мобильном устройстве

### Фаза 7 — Деплой (Railway / Render)
- [ ] PostgreSQL: схема, миграция
- [ ] `web/sync.py` — скрипт SQLite → PostgreSQL
- [ ] `Procfile` / настройки Railway
- [ ] Команда запуска: `uvicorn web.app:app --host 0.0.0.0 --port $PORT`
- [ ] CI/CD: деплой при push в `master`

---

## Технические решения

| Решение | Обоснование |
|---------|------------|
| SSR + пагинация ссылками (не AJAX) | Работает без JS, URL меняется (можно поделиться), проще |
| Tailwind CDN (не сборка) | Ноль конфигурации, нет node_modules |
| Отдельный `web/database.py` | Read-only слой — UI не может случайно изменить данные |
| `LIKE` поиск (не FTS) | 7650 записей — достаточно быстро, не нужен индекс |
| Basic Auth через env vars | Личный инструмент, минимальная сложность |

---

## Новые зависимости

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
jinja2>=3.1.4
python-multipart>=0.0.9
```

---

## Статус

| Фаза | Статус |
|------|--------|
| Фаза 1 — Скелет | ⬜ не начата |
| Фаза 2 — Главная | ⬜ не начата |
| Фаза 3 — Категория | ⬜ не начата |
| Фаза 4 — Поиск | ⬜ не начата |
| Фаза 5 — Sidebar / mobile | ⬜ не начата |
| Фаза 6 — Полировка | ⬜ не начата |
| Фаза 7 — Деплой | ⬜ не начата |
