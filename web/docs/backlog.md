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
├── database.py         # слой доступа к SQLite (чтение + запись + получение URL по id)
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
│   └── app.js          # бургер-меню, удаление, DnD, модальное окно, массовые операции, refetch
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
| POST | `/api/urls/{url_id}/refetch` | — | Перезагрузить title + description через пайплайн (step2) |
| DELETE | `/api/urls/{url_id}` | — | Удалить URL из БД |
| PATCH | `/api/urls/{url_id}/category` | `category` | Сменить категорию URL |
| POST | `/api/bulk-delete` | `{"ids": [...]}` | Удалить список URL за один запрос |
| POST | `/api/bulk-refetch` | `{"ids": [...]}` | Перезагрузить title + description для списка URL |

### Системные

| Метод | Путь | Авторизация | Описание |
|-------|------|-------------|---------|
| GET | `/health` | нет | `{"status":"ok"}` для healthcheck |

---

## URL-карточка (`_url_card.html`)

```
[☐] [🔄 обработать] [↔ переместить] [🗑 удалить]
[Title — кликабельная внешняя ссылка, target=_blank]
[description (серый текст, если есть)]
#id  domain.com  [badge: категория]
```

Карточка разбита на ряды: кнопки действий — первый ряд (выравнивание по левому краю), title — второй ряд.

- `category` может содержать несколько тегов через запятую → каждый отдельным badge
- Hover-эффект, touch-friendly padding
- Кнопка 🔄 обработки: `fetch POST /api/urls/{id}/refetch` → перезагрузка title + description → reload страницы
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
- [x] Счётчики категорий в sidebar обновляются live после удаления / перемещения

### Фаза 4 — Массовые операции ✅
- [x] `POST /api/bulk-delete` — удаление списка URL за один запрос
- [x] `database.delete_urls_bulk(ids)` — DELETE ... WHERE id IN (...)
- [x] Режим выбора: кнопка «Выбрать» на страницах категории и поиска
- [x] Чекбоксы на карточках — скрыты по умолчанию, видны только в режиме выбора
- [x] Нижняя панель действий (`#bulk-bar`): счётчик, «Выбрать все», «Отмена», «Удалить выбранные»
- [x] После массового удаления: анимация карточек, обновление счётчиков в sidebar, выход из режима выбора

### Фаза 4.5 — Refetch (обработка пайплайном из UI) ✅
- [x] `POST /api/urls/{id}/refetch` — перезагрузка title + description для одного URL
- [x] `POST /api/bulk-refetch` — то же для списка URL
- [x] `database.get_url_by_id()`, `database.get_urls_by_ids()` — получение URL по id
- [x] Вызов пайплайна через subprocess: `set_url_pending()` + `step2.main(urls=[...])` (без step1/step3)
- [x] Автоопределение Python-интерпретатора пайплайна (`venv/Scripts/python.exe`, env `PIPELINE_PYTHON`)
- [x] Обход проблемы Rich в pipe-режиме: `TERM=dumb`, `NO_COLOR=1`, `PYTHONIOENCODING=utf-8`
- [x] Кнопка 🔄 на карточке — обработать один URL (спиннер → reload)
- [x] «Обработать выбранные» в массовом режиме (bulk-bar)

### Фаза 5 — Полировка
- [ ] Проверка на реальном мобильном устройстве
- [ ] Пустые состояния (нет URL в категории, нет результатов поиска)

### Фаза 6 — Деплой (Railway / Render)
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
| Отдельный `web/database.py` | Слой доступа к SQLite — чтение + управление записями |
| `LIKE` поиск (не FTS) | 7650 записей — достаточно быстро, индекс не нужен |
| Basic Auth через env vars | Личный инструмент, минимальная сложность |
| Нативный HTML5 DnD (без SortableJS) | Достаточно для десктопа, ноль зависимостей |
| Модальное окно для смены категории | Работает на мобайле и десктопе, не требует DnD |
| Refetch через subprocess | UI не зависит от пайплайна (разные venv); вызывает step2 через CLI |
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
| Фаза 4 — Массовые операции | ✅ готово |
| Фаза 4.5 — Refetch из UI | ✅ готово |
| Фаза 5 — Полировка | ⬜ не начата |
| Фаза 6 — Деплой | ⬜ не начата |
