# ML Classifier for url-parser — Development Plan

**Planning date:** 03.08.2026
**Hardware:** AMD Ryzen 5 5500 / NVIDIA RTX A4000 (16GB VRAM) / 64GB DDR4
**Context:** LLM labeling (step3) generates noisy labels → use them as training data for fast specialized classifier.

---

## Motivation

Current LLM classification (step3 / Ollama):

| Problem | Manifestation |
|----------|------------|
| Inconsistent case | `manage teams` / `Manage teams` |
| Russian/English duplicates | `AI-assistants` and `ИИ-ассистенты` — same thing |
| Junk bucket | `Equipment and tools` — 20+ unrelated topics |
| Speed | ~2–5 sec/URL, needs running Ollama |
| Non-determinism | one URL → different tag on re-run |

ML classifier goals:

- **4000 URLs in ~2 seconds** (vs ~2–4 hours via Ollama)
- Deterministic result
- No GPU/Ollama at inference
- macro-F1 > 0.80

---

## Phase 0 — Distribution Analysis (1 day)

Look at real top categories before fixing taxonomy:

```sql
SELECT category, COUNT(*) as cnt
FROM urls
WHERE category IS NOT NULL
GROUP BY category
ORDER BY cnt DESC
LIMIT 50;
```

**Artifact:** understanding of real topic distribution in corpus.

---

## Phase 1 — Fix Taxonomy (1–2 days)

**Prerequisite for everything else.** Without closed category list, can't train classifier.

### Preliminary L1-Category List

| # | Category | What includes |
|---|-----------|-------------|
| 1 | Artificial Intelligence | LLM, agents, neural nets, RAG, ChatGPT |
| 2 | Programming | Python, algorithms, patterns, async |
| 3 | Data Science | ML/DL, analytics, Kaggle, models, stats |
| 4 | DevOps and infrastructure | Docker, CI/CD, servers, cloud, serverless |
| 5 | Databases | SQL, PostgreSQL, NoSQL, DWH, Elasticsearch |
| 6 | Security | cybersecurity, vulnerabilities, pentest |
| 7 | Management and leadership | projects, teams, agile, scrum, retros |
| 8 | Business | startups, marketing, product, metrics, MVP |
| 9 | IoT and hardware | ESP32, smart home, electronics, NAS |
| 10 | Web development | frontend, API, UX, browser, HTTP |
| 11 | Career and learning | interviews, courses, experience, advice |
| 12 | Finance and trading | algo-trading, crypto, investments |
| 13 | Science and research | physics, math, cognitive science, history |
| 14 | Productivity | tools, automation, Obsidian |
| 15 | Other | everything else |

> List adjusted per Phase 0 results.

**Artifact:** `taxonomy.json` — category list with descriptions and examples:

```json
[
  {
    "name": "Artificial Intelligence",
    "description": "Articles about LLM, AI agents, neural nets, RAG",
    "examples": ["GPT-4 for business", "Building RAG system", "Agents in 2025"]
  },
  ...
]
```

---

## Phase 2 — Data Labeling (3–5 days)

### Step 2.1 — LLM Labeling with Fixed Taxonomy (`--strict`)

Implement `--strict` mode in step3 (already in backlog as P1):

```bash
# Model chooses ONLY from taxonomy.json, doesn't invent
python main.py --re-tag --strict --model qwen2.5-coder:7b --batch 10 --workers 4
```

Prompt in `--strict` mode changes from:
```
"You may use a suggested category OR invent your own"
```
to:
```
"You MUST choose exactly one category from this list: [list]
Respond with ONLY the category name, exactly as written."
```

### Step 2.2 — Dataset Export

New script `export_dataset.py`:

```bash
python export_dataset.py --output dataset.jsonl
# Line format:
# {"text": "How variables work in Python [SEP] habr.com", "label": "Programming"}
```

Model input = `f"{title} [SEP] {domain}"` — domain provides important context
(github.com → likely code; habr.com → technical blog).

> **Note on dataset diversity.** Corpus formed from one user's bookmarks:
> ~70% articles — IT/AI/programming, remaining 30% — science-pop, business,
> career, productivity. Normal for personal tool, but model works worse on
> topics with few examples (finance, IoT, history). When expanding corpus,
> deliberately add examples from rare categories.

### Step 2.3 — Manual Validation (critical)

```bash
# New flag for manual fixes
python main.py --fix-category URL "Correct category"
```

Validation strategy:
- 20–30 random examples per category
- Fix categories with low obviousness first
- **Goal: ≥50 clean examples per category** = ~750–1000 checked records

> With 15 categories and ~4000 URLs — we almost have enough data.
> Manual validation needed only for cleanliness, not volume.

**Artifact:** `dataset.jsonl` (~4000 lines, ~1000 manually verified).

---

## Phase 3 — Model Training (1 day)

### Stack

```
PyTorch + HuggingFace Transformers + scikit-learn (metrics)
```

### Base Model Choice

| Model | Size | VRAM | Training (RTX A4000) | Inference CPU |
|--------|------|------|----------------------|--------------|
| `rubert-tiny2` | 30M | ~1GB | ~30 sec | <1 ms |
| `xlm-roberta-base` | 280M | ~3GB | ~3 min | ~2 ms |
| `xlm-roberta-large` | 560M | ~6GB | ~8 min | ~5 ms |

**Choice: `xlm-roberta-base`** — optimal quality/speed balance.
Understands Russian and English, works well on short texts.

### Training Parameters (`train_classifier.py`)

```python
model = AutoModelForSequenceClassification.from_pretrained(
    "xlm-roberta-base",
    num_labels=len(taxonomy)   # 15
)

# Input: f"{title} [SEP] {domain}"  (tokenized together)
# Output: category index → taxonomy[idx]

batch_size    = 32      # RTX A4000 handles easily
epochs        = 5       # usually enough
learning_rate = 2e-5    # standard for BERT fine-tune
warmup_steps  = 100
weight_decay  = 0.01

train / val / test = 70 / 15 / 15  # stratified split
```

### Evaluation Metrics

```
accuracy      — overall accuracy
macro-F1      — important: classes imbalanced (Habr → lots of AI/programming)
confusion matrix → see where model confuses (e.g., AI vs Data Science)

Goal: macro-F1 > 0.80
```

**Artifacts:**
- `models/url_classifier/` — saved HuggingFace model (~500MB)
- `models/url_classifier/confusion_matrix.png` — error matrix
- `models/url_classifier/metrics.json` — accuracy, F1 per class

---

## Phase 4 — Pipeline Integration (2 days)

### New `step4.py` — ML Classifier

```
pipeline:
  step1 (import) → step2 (parse) → step3 (LLM) OR step4 (ML)

                                     ↓ confidence < threshold
                                  fallback → step3 (LLM)
```

**Logic of step4:**
1. Load model from `models/url_classifier/`
2. Classify in batches (CPU: 500 URLs/sec, GPU: instant)
3. For each URL: category + confidence (softmax score)
4. If confidence < `--ml-confidence` (default 0.70) → fallback to LLM

### New Flags in `main.py`

```bash
python main.py --only-ml-classify                    # step4 only (ML)
python main.py --only-ml-classify --ml-confidence 0.8  # strict threshold
python main.py --ml-model models/url_classifier      # model path
```

### DB Storage

```sql
-- Add ml_confidence column to urls
ALTER TABLE urls ADD COLUMN ml_confidence REAL;

-- tagged_by stores: "NextAgent/Convo:latest" (LLM) or "xlm-roberta-base" (ML)
```

---

## Phase 5 — Iteration (ongoing)

```
New URLs
    → step4 (ML, instant)
    → confidence < 0.70 → step3 (LLM, slow)
    → human fixes via --fix-category
    → accumulated 200+ fixes → retrain (3 min)
    → new model version → deploy
```

**Active learning:** when reviewing, show examples with lowest
confidence first — most useful for training.

**Retraining cycle:** monthly or when ~200 new verified examples accumulated.

---

## Long-Term Directions

### Hierarchical Taxonomy (L1 → L2 → L3)

Current classification — flat L1 list. Next level:

```
L1: Artificial Intelligence
  L2: LLM
    L3: RAG, Fine-tuning, Prompting
  L2: Computer Vision
  L2: MLOps
```

Approaches:
- **Cascading classifiers** — separate model per level (L1 → if "AI" → L2-AI → ...). Simple, interpretable.
- **Multi-label** — one model predicts all levels. Complex, faster.

Prerequisite: stable L1 taxonomy (Phases 1–3 of this plan).

### Feature Enrichment (step2)

Current model input: `title [SEP] domain`. Planned:

| Feature | Source | Value |
|---------|--------|-------|
| `og:description` | `<meta property="og:description">` | Often more informative than title |
| `meta description` | `<meta name="description">` | Page summary |
| `og:title` | `<meta property="og:title">` | Alternative title |

New input: `f"{title} [SEP] {description[:200]} [SEP] {domain}"`.

Tradeoff: more tokens → slightly slower LLM, but ML classifier benefits.

---

## What Needs Implementation

| Task | File | Phase | Priority |
|--------|------|------|-----------|
| `--strict` mode in step3 | `step3.py` | 2.1 | P0 (prerequisite) |
| `export_dataset.py` | new | 2.2 | P0 |
| `--fix-category` flag | `main.py`, `db.py` | 2.3 | P1 |
| `taxonomy.json` | new | 1 | P0 |
| `train_classifier.py` | new | 3 | P1 |
| `step4.py` | new | 4 | P1 |
| `--only-ml-classify` and `--ml-confidence` | `main.py` | 4 | P1 |
| `ml_confidence` column in DB | `db.py` | 4 | P2 |
| Active learning UI | new | 5 | P2 |

---

## Time Estimate

| Phase | Task | Time |
|------|--------|-------|
| 0 | Distribution analysis | 2 h |
| 1 | Taxonomy + taxonomy.json | 1–2 days |
| 2.1 | --strict mode + run | 4 h |
| 2.2 | export_dataset.py | 2 h |
| 2.3 | Manual validation | 2–4 days |
| 3 | train_classifier.py + training | 1 day |
| 4 | step4.py + integration | 1–2 days |
| **Total** | | **~2 weeks** |

> Bottleneck — Phase 2.3 (manual validation). Can't automate,
> but can minimize via good `--strict` prompt at Phase 2.1.
