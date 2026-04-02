# Web UI — web-page-classifier

Web interface for browsing and managing classified URLs.
Mobile-first.

## Stack

- **Backend:** FastAPI + Jinja2
- **Frontend:** Tailwind CSS (CDN) + vanilla JS
- **Database:** SQLite locally → PostgreSQL in cloud

## Installation

Web UI is a separate project with its own virtualenv:

```bash
cd web/
python -m venv venv

# Activation (PowerShell)
.\venv\Scripts\Activate.ps1

# Activation (cmd)
.\venv\Scripts\activate.bat

pip install -r requirements.txt
```

> Pipeline and Web UI are separate projects with separate environments. `venv/` at project root not needed for web UI.

## Environment Variables

| Variable | Default | Description |
|------------|-------------|---------|
| `WEB_USER` | — | Login for Basic Auth |
| `WEB_PASSWORD` | — | Password for Basic Auth |
| `DB_PATH` | `../urls.db` | Path to SQLite DB (relative to `web/`) |
| `PIPELINE_PYTHON` | `../venv/Scripts/python.exe` (auto) | Path to pipeline Python interpreter for refetch |

Locally can set in `.env` or directly in terminal:

```bash
export WEB_USER=admin
export WEB_PASSWORD=secret
```

## Features

- **Browse** URLs by categories, search by title / description / URL, sorting (newest / oldest / alphabetical)
- **Recent feed** (`/recent`) — all URLs, newest first, with sorting
- **Uncategorized** (`/uncategorized`) — URLs awaiting classification
- **Sorting** — newest first / oldest first / alphabetical (on all pages)
- **Delete** URLs from DB (button on card)
- **Change category** — from fixed taxonomy (31 categories):
  - Desktop: drag card to category in sidebar (highlights green)
  - Mobile / desktop: button ↔ → modal with taxonomy category list
  - Sets `manual_override=1` — LLM won't overwrite manual choice on `--only-classify`
  - Icon ✎ on card shows category assigned manually
- **Processing (refetch)** — reload title and description via pipeline:
  - Button on card — process one URL
  - Bulk: "Select" → check → "Process selected"
  - Calls `set_url_pending()` + `step2.main()` via subprocess (pipeline venv)
  - No import (step1), no classification (step3) — only fetch metadata
- **Bulk operations**: "Select" button → check needed → delete / process
  - "Select all" — checks all cards on page
  - Category counters in sidebar update instantly, no reload

## Run Locally

Run from `web/` folder with activated venv:

```bash
cd web/
.\venv\Scripts\Activate.ps1           # PowerShell
# or
.\venv\Scripts\activate.bat           # cmd

python -m uvicorn app:app --port 8000 --reload

# Open in browser
http://localhost:8000
# Default login: admin / changeme

# After changes — restart server (Ctrl+C, then again):
# static cached in browser; cache-busting on restart
```

## Structure

```
web/
├── app.py              # FastAPI entry point
├── auth.py             # HTTP Basic Auth
├── database.py         # SQLite queries (read + manage + taxonomy)
├── routers/
│   ├── pages.py        # HTML routes (/, /category, /recent, /uncategorized, /search)
│   └── api.py          # JSON API (CRUD + refetch + bulk)
├── templates/
│   ├── base.html       # base layout + category change modal (taxonomy)
│   ├── index.html      # main (categories)
│   ├── category.html   # category view
│   ├── recent.html     # recent feed
│   ├── uncategorized.html  # uncategorized URLs
│   ├── search.html     # search results
│   └── components/
│       ├── card.html       # URL card (draggable, with buttons)
│       ├── sidebar.html    # sidebar with categories + counters
│       └── modal.html      # category select modal
├── static/
│   ├── style.css       # Tailwind + custom (drag & drop, animations)
│   └── app.js          # vanilla JS (drag, AJAX, bulk ops, notifications)
├── requirements.txt
└── .env                # local settings (user/password)
```

## Customization

**Colors and theme:** `static/style.css`
**Categories sidebar:** auto-generated from DB + `config/taxonomy.py`
**Auth:** set `WEB_USER` and `WEB_PASSWORD` env vars

## Deployment Notes

- **Locally:** SQLite in project folder (`../urls.db` relative to `web/`)
- **Cloud:** switch `database.py` to PostgreSQL connection, keep API same
- **HTTPS:** deploy behind Nginx/Apache with SSL, or use Gunicorn + systemd
- **Authentication:** Basic Auth fine for personal tool; for team use add JWT/OAuth

Example Gunicorn run:

```bash
cd web/
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```
