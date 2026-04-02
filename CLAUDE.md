# Claude Code Guidelines: Web Page Classifier

**Project:** Web Page Classification Pipeline (ETL + LLM Annotation)
**Status:** Active development
**Language Strategy:** Russian → English migration (started 2026-04-02)

---

## 🔗 Global Strategy

This project follows the unified documentation strategy:
**→ `e:\My files\0 My_Dev\ClaudeCode\my_claude\DOCUMENTATION_STRATEGY.md`**

Two-branch model:
- `master` → Full code + **English** documentation
- `docs-ru` → **Russian** documentation (backup, no code)
- Auto-sync via git hook after every commit

---

## 📋 Current Status (2026-04-02)

### Translation Progress

- [ ] `README.md` — English (in progress)
- [ ] `docs/discovery/project-overview.md` — English (in progress)
- [ ] `docs/discovery/ml-plan.md` — English (in progress)
- [ ] `docs/discovery/models-compare.md` — English (in progress)
- [ ] `docs/discovery/backlog.md` — English (in progress)
- [ ] `docs/discovery/dev-plan.md` — English (in progress)
- [ ] `docs/discovery/effort-log.md` — English (in progress)
- [ ] `docs/discovery/retrospective.md` — Optional (low public value)
- [ ] `web/README.md` — English (in progress)
- [ ] `web/docs/discovery/backlog.md` — English (in progress)

### Structure Reorganization

- [ ] Create `docs/discovery/` folder
- [ ] Create `docs/delivery/` folder
- [ ] Create `web/docs/discovery/` folder
- [ ] Create `web/docs/delivery/` folder
- [ ] Move files to appropriate folders

### Git Setup

- [ ] Create `docs-ru` branch
- [ ] Configure `.git/hooks/post-commit` for auto-sync
- [ ] Test synchronization

---

## 🎯 Project-Specific Rules

### Content Organization

```
docs/
├── discovery/
│   ├── project-overview.md     — Architecture deep-dive (ETL explanation)
│   ├── ml-plan.md              — ML classifier roadmap
│   ├── models-compare.md       — Model evaluation results
│   ├── backlog.md              — Feature backlog
│   ├── dev-plan.md             — Development phases log
│   ├── effort-log.md           — Time tracking
│   └── retrospective.md        — Lessons learned (optional)
└── delivery/
    └── (TBD — additional how-tos if needed)

web/
├── README.md                    — How to run Web UI (Delivery)
└── docs/
    ├── discovery/
    │   └── backlog.md          — Web UI feature backlog
    └── delivery/

Root README.md                    — Quick start, main CLI commands
```

### Translation Notes

- **project-overview.md** → Discovery (not Delivery) — it's architecture documentation
- **retrospective.md** → Optional (personal retrospectives have low public value)
- Code comments remain in English
- Commit messages in English

### Exceptions to Global Strategy

None currently. This project fully adheres to the global documentation strategy.

---

## 🔄 Git Workflow

### Standard Commit

```bash
# 1. Make changes to code and/or documentation
nano README.md
python step1.py  # code changes

# 2. Commit normally
git add README.md step1.py
git commit -m "docs: clarify ETL architecture / feat: add feature"

# 3. Push to remote
git push origin master

# 4. Git hook automatically syncs docs-ru (no manual action needed)
```

### Check Sync Status

```bash
git log docs-ru --oneline -5  # see recent syncs
git checkout docs-ru
git log --oneline -5          # verify latest changes
git checkout master           # return to main
```

---

## 💾 Memory & Context

### Persistent Memory

Location: `C:\Users\user\.claude\projects\E--My-files-0-My-Dev-web-page-classifier\memory\`

Key files:
- `session_context.md` — Architecture, DB stats, ML roadmap phases
- `architecture_etl.md` — ETL vs data enrichment classification
- `feedback_separate_projects.md` — Web UI and pipeline are separate projects
- `feedback_readme.md` — Always create README.md with new modules

### Project Overview

- **Type:** Data enrichment pipeline (Extract → Transform → Load)
- **Tech:** Python, SQLite, Ollama LLM, FastAPI Web UI
- **Status:** LLM phase complete (~6,050 annotated URLs), ML phase pending
- **Goal:** macro-F1 > 0.80, infer 4000 URLs/sec without GPU
- **Current model:** mistral-small3.2:24b (54.8% agreement on test corpus)
- **Hardware:** NVIDIA RTX A4000 16GB VRAM

---

## 🚀 Next Steps

1. **Restructure documentation** (move to discovery/delivery folders)
2. **Translate key documents** to English (README, ml-plan, project-overview, etc.)
3. **Create docs-ru branch** with Russian mirror
4. **Set up git hooks** for automatic synchronization
5. **Test full workflow** — commit to master, verify docs-ru syncs
6. **Update memory** with final status

---

## 📞 Questions?

Refer to:
- Global strategy: `e:\My files\0 My_Dev\ClaudeCode\my_claude\DOCUMENTATION_STRATEGY.md`
- Project memory: `memory/MEMORY.md`
- Code structure: `README.md` (once translated to English)

---

**Last updated:** 2026-04-02
**Created by:** Claude Code Agent
**Next review:** After translation is complete
