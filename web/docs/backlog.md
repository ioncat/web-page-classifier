# Web UI — Бэклог

Веб-интерфейс для просмотра и управления классифицированными URL из `urls.db`.
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
├── database.py         # слой доступа к SQLite (чтение + запись + таксономия)
├── routers/
│   ├── __init__.py
│   ├── pages.py        # HTML-роуты → TemplateResponse
│   └── api.py          # JSON API
├── templates/
│   ├── base.html       # layout, Tailwind CDN, header, sidebar, модалка категории
│   ├── index.html      # главная: сетка карточек категорий
│   ├── category.html   # страница категории: список URL + пагинация + сортировка
│   ├── recent.html     # лента новых URL (все, новые сверху)
│   ├── uncategorized.html # URL без категории
│   ├── search.html     # результаты поиска + форма с фильтром по категории
│   ├── _url_card.html  # переиспользуемый компонент URL-карточки
│   └── _sort_bar.html  # переиспользуемый компонент выбора сортировки
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
| GET | `/category/{name}` | `category.html` | URL категории, `?page=N&sort=...` |
| GET | `/recent` | `recent.html` | Все URL, новые сверху, `?page=N&sort=...` |
| GET | `/uncategorized` | `uncategorized.html` | URL без категории, `?page=N&sort=...` |
| GET | `/search` | `search.html` | Поиск `?q=...&category=...&page=N&sort=...` |

### JSON API (`routers/api.py`)

| Метод | Путь | Параметры | Описание |
|-------|------|-----------|---------|
| GET | `/api/categories` | — | Список категорий + счётчики |
| GET | `/api/urls` | `q`, `category`, `page`, `per_page` | Поиск/фильтрация URL |
| GET | `/api/stats` | — | Общая статистика |
| POST | `/api/urls/{url_id}/refetch` | — | Перезагрузить title + description через пайплайн (step2) |
| DELETE | `/api/urls/{url_id}` | — | Удалить URL из БД |
| PATCH | `/api/urls/{url_id}/category` | `{"category": "..."}` | Сменить категорию URL (ставит `manual_override=1`) |
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
#id  domain.com  [badge: категория]  [✎ если manual_override]
```

Карточка разбита на ряды: кнопки действий — первый ряд (выравнивание по левому краю), title — второй ряд.

- `category` отображается badge-ом
- Hover-эффект, touch-friendly padding
- Кнопка 🔄 обработки: `fetch POST /api/urls/{id}/refetch` → перезагрузка title + description → reload страницы
- Кнопка 🗑 удаления: `fetch DELETE /api/urls/{id}` → карточка исчезает без перезагрузки
- Кнопка ↔ "Переместить": модальное окно с таксономией (30 категорий) или drag на sidebar → `PATCH /api/urls/{id}/category` → `manual_override=1`
- Иконка ✎ рядом с badge если категория назначена вручную

---

## Фазы реализации

### Фаза 1 — Скелет ✅
- [x] Структура папок `web/`
- [x] `web/database.py` — `get_categories_with_counts()`, `get_urls_by_category()`, `search_urls()`
- [x] `web/auth.py` — Basic Auth через `secrets.compare_digest`, env vars
- [x] `web/app.py` — FastAPI, роут `/health`, монтирование static/templates
- [x] `web/requirements.txt` — отдельный от пайплайна

### Фаза 2 — Шаблоны и главная ✅
- [x] `base.html` — sticky header, sidebar (desktop), drawer + overlay (mobile)
- [x] `index.html` — сетка категорий
- [x] `_url_card.html` — title, description, domain, category badges
- [x] `category.html` — список карточек + пагинация
- [x] `search.html` — форма + фильтр по категории + результаты + пагинация
- [x] `app.js` — бургер toggle (drawer + overlay)
- [x] Роуты `GET /`, `/category/{name}`, `/search`
- [x] JSON API

### Фаза 3 — Управление данными ✅
- [x] `DELETE /api/urls/{id}` — удаление URL из БД
- [x] Кнопка 🗑 на карточке + confirm → анимация исчезновения
- [x] `PATCH /api/urls/{id}/category` — смена категории
- [x] DnD (десктоп): `draggable="true"` + drag events, sidebar подсвечивается зелёным
- [x] Модальное окно (мобайл + десктоп): кнопка ↔ → список категорий → PATCH → обновление badge
- [x] Счётчики категорий в sidebar обновляются live

### Фаза 4 — Массовые операции ✅
- [x] `POST /api/bulk-delete` — массовое удаление
- [x] Режим выбора: кнопка «Выбрать», чекбоксы, нижняя панель действий
- [x] «Выбрать все», «Отмена», «Удалить выбранные»

### Фаза 4.5 — Refetch (обработка пайплайном из UI) ✅
- [x] `POST /api/urls/{id}/refetch` — одиночная обработка
- [x] `POST /api/bulk-refetch` — массовая обработка
- [x] Вызов пайплайна через subprocess (без step1/step3)
- [x] Автоопределение Python-интерпретатора пайплайна

### Фаза 5 — Таксономия и ручная классификация ✅
- [x] `config/taxonomy.py` — 30 фиксированных категорий
- [x] Модалка смены категории показывает таксономию (не текущие из БД)
- [x] `manual_override` колонка — защита от перезаписи LLM
- [x] Иконка ✎ на карточке при ручной классификации
- [x] Страница `/recent` — лента новых URL с сортировкой
- [x] Страница `/uncategorized` — URL без категории
- [x] Сортировка (новые / старые / по алфавиту) на всех страницах
- [x] Ссылки «Новые» и «Без категории» в header

### Фаза 6 — Полировка
- [ ] Проверка на реальном мобильном устройстве
- [ ] Пустые состояния (нет URL в категории, нет результатов поиска)

### Фаза 7 — Деплой (Railway / Render)
- [ ] PostgreSQL: схема, миграция
- [ ] `web/sync.py` — скрипт SQLite → PostgreSQL
- [ ] `Procfile` / настройки Railway
- [ ] CI/CD: деплой при push в `master`

---

## Технические решения

| Решение | Обоснование |
|---------|------------|
| SSR + пагинация ссылками (не AJAX) | Работает без JS, URL меняется (можно поделиться) |
| Tailwind CDN (без сборки) | Ноль конфигурации, нет node_modules |
| Отдельный `web/database.py` | Слой доступа к SQLite — чтение + управление записями |
| `LIKE` поиск (не FTS) | ~7600 записей — достаточно быстро, индекс не нужен |
| Basic Auth через env vars | Личный инструмент, минимальная сложность |
| Нативный HTML5 DnD (без SortableJS) | Достаточно для десктопа, ноль зависимостей |
| Модалка с таксономией | 30 категорий из `config/taxonomy.py` — единый источник для LLM и UI |
| `manual_override` флаг | Ручные назначения защищены от перезаписи LLM; потенциальные обучающие данные |
| Refetch через subprocess | UI не зависит от пайплайна (разные venv); вызывает step2 через CLI |
| `web/requirements.txt` отдельно | UI и пайплайн — разные проекты, разные окружения |

---

## Зависимости

| Файл | Назначение | Содержимое |
|------|-----------|-----------|
| `requirements.txt` | Пайплайн (локально) | `requests`, `ollama`, `rich`, `beautifulsoup4`, `openpyxl` |
| `web/requirements.txt` | Веб UI (сервер) | `fastapi`, `uvicorn[standard]`, `jinja2`, `python-multipart` |

---

## Статус

| Фаза | Статус |
|------|--------|
| Фаза 1 — Скелет | ✅ готово |
| Фаза 2 — Шаблоны и главная | ✅ готово |
| Фаза 3 — Управление данными | ✅ готово |
| Фаза 4 — Массовые операции | ✅ готово |
| Фаза 4.5 — Refetch из UI | ✅ готово |
| Фаза 5 — Таксономия и ручная классификация | ✅ готово |
| Фаза 6 — Полировка | ⬜ не начата |
| Фаза 7 — Деплой | ⬜ не начата |
