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
| БД (облако) | PostgreSQL (Railway / Render) — Фаза 7 |
| Авторизация | HTTP Basic Auth (`WEB_USER`, `WEB_PASSWORD`) |
| Хостинг | Railway или Render |

---

## Структура проекта

```
web/
├── app.py              # FastAPI точка входа, регистрация роутеров, Jinja2, auth
├── auth.py             # HTTP Basic Auth зависимость
├── database.py         # read-only слой к SQLite
├── routers/
│   ├── __init__.py
│   ├── pages.py        # HTML-роуты → TemplateResponse
│   └── api.py          # JSON API
├── templates/
│   ├── base.html       # layout, Tailwind CDN, header, sidebar, бургер
│   ├── index.html      # главная: сетка карточек категорий
│   ├── category.html   # страница категории: список URL + пагинация
│   ├── search.html     # результаты поиска + форма с фильтром по категории
│   └── _url_card.html  # переиспользуемый компонент URL-карточки
├── static/
│   └── app.js          # бургер-меню (toggle sidebar на mobile)
├── requirements.txt    # зависимости только для UI (отдельно от пайплайна)
├── README.md           # инструкция по запуску
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
| DELETE | `/api/urls/{url_id}` | — | Удалить URL из БД |
| PATCH | `/api/urls/{url_id}/category` | `category` | Сменить категорию URL |

### Системные

| Метод | Путь | Авторизация | Описание |
|-------|------|-------------|---------|
| GET | `/health` | нет | `{"status":"ok"}` для healthcheck |

---

## URL-карточка (`_url_card.html`)

```
[Title — кликабельная внешняя ссылка, target=_blank]
[description (серый текст, если есть)]
[badge: категория]  [domain.com]  [🗑 удалить]
```

- `category` может содержать несколько тегов через запятую → каждый отдельным badge
- Hover-эффект, touch-friendly padding
- Кнопка 🗑 удаления: `fetch DELETE /api/urls/{id}` → карточка исчезает без перезагрузки
- Кнопка ↔ "Переместить": модальное окно (мобайл) или drag на sidebar (десктоп) → `PATCH /api/urls/{id}/category`

---

## Фазы реализации

### Фаза 1 — Скелет ✅
- [x] Структура папок `web/`
- [x] `web/database.py` — `get_categories_with_counts()`, `get_urls_by_category()`, `search_urls()`
- [x] `web/auth.py` — Basic Auth через `secrets.compare_digest`, env vars
- [x] `web/app.py` — FastAPI, роут `/health`, монтирование static/templates
- [x] `web/requirements.txt` — отдельный от пайплайна
- [x] Smoke test: `python -c "from web.app import app"` → OK

### Фаза 2 — Шаблоны и главная ✅
- [x] `base.html` — sticky header, sidebar (desktop), drawer + overlay (mobile)
- [x] `index.html` — сетка категорий `grid-cols-2 md:grid-cols-3 lg:grid-cols-4`
- [x] `_url_card.html` — title, description, domain, category badges
- [x] `category.html` — список карточек + пагинация ссылками
- [x] `search.html` — форма + фильтр по категории + результаты + пагинация
- [x] `app.js` — бургер toggle (drawer + overlay)
- [x] Роуты `GET /`, `/category/{name}`, `/search`
- [x] JSON API `GET /api/categories`, `/api/urls`, `/api/stats`
- [x] Запуск: `python -m uvicorn web.app:app --port 8000 --reload` → 200 OK

### Фаза 3 — Управление данными ✅
- [x] `DELETE /api/urls/{id}` — удаление URL из БД
- [x] Кнопка 🗑 на карточке + confirm → анимация исчезновения карточки без перезагрузки
- [x] `PATCH /api/urls/{id}/category` — смена категории
- [x] DnD (десктоп): `draggable="true"` + drag events, sidebar подсвечивается зелёным при наведении
- [x] Модальное окно (мобайл + десктоп): кнопка ↔ → список категорий → PATCH → обновление badge
- [x] Без SortableJS — нативный HTML5 DnD достаточен для десктопа

### Фаза 4 — Полировка
- [ ] Проверка на реальном мобильном устройстве
- [ ] Пустые состояния (нет URL в категории, нет результатов поиска)
- [ ] Счётчик категорий обновляется после удаления/перемещения

### Фаза 5 — Деплой (Railway / Render)
- [ ] PostgreSQL: схема, миграция
- [ ] `web/sync.py` — скрипт SQLite → PostgreSQL
- [ ] `Procfile` / настройки Railway
- [ ] Команда: `uvicorn web.app:app --host 0.0.0.0 --port $PORT`
- [ ] CI/CD: деплой при push в `master`

---

## Технические решения

| Решение | Обоснование |
|---------|------------|
| SSR + пагинация ссылками (не AJAX) | Работает без JS, URL меняется (можно поделиться) |
| Tailwind CDN (без сборки) | Ноль конфигурации, нет node_modules |
| Отдельный `web/database.py` | Read-only слой — UI не меняет данные пайплайна |
| `LIKE` поиск (не FTS) | 7650 записей — достаточно быстро, индекс не нужен |
| Basic Auth через env vars | Личный инструмент, минимальная сложность |
| Нативный HTML5 DnD (без SortableJS) | Достаточно для десктопа, ноль зависимостей |
| Модальное окно для смены категории | Работает на мобайле и десктопе, не требует DnD |
| `web/requirements.txt` отдельно | UI и пайплайн — разные проекты, разные окружения |

---

## Зависимости

| Файл | Назначение | Содержимое |
|------|-----------|-----------|
| `requirements.txt` | Пайплайн (локально) | `requests`, `ollama`, `rich`, `beautifulsoup4`, `openpyxl` |
| `web/requirements.txt` | Веб UI (сервер) | `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart` |

```bash
pip install -r web/requirements.txt
```

---

## Статус

| Фаза | Статус |
|------|--------|
| Фаза 1 — Скелет | ✅ готово |
| Фаза 2 — Шаблоны и главная | ✅ готово |
| Фаза 3 — Управление данными | ✅ готово |
| Фаза 4 — Полировка | ⬜ не начата |
| Фаза 5 — Деплой | ⬜ не начата |
