# =============================================================================
# prompts.py — шаблоны промптов для классификации URL
# Редактируй эти строки — скрипты подхватят изменения автоматически.
#
# Плейсхолдеры:
#   SINGLE          → {title}, {description_line}, {taxonomy}
#   BATCH_HEADER    → {taxonomy}
#   BATCH_ITEM      → {i}, {title}
#   DESCRIPTION_LINE → {description}
#   TAXONOMY_LINE    → {taxonomy}  (список категорий из config/taxonomy.py)
#
# Модель выбирает ТОЛЬКО из фиксированной таксономии.
# =============================================================================

# ── Строка с описанием страницы (подставляется только если description != None) ─
DESCRIPTION_LINE = "Description: {description}\n"

# ── Строка с таксономией ─────────────────────────────────────────────────────
TAXONOMY_LINE = "Allowed categories: {taxonomy}\n"


# =============================================================================
# Промпт: фиксированная таксономия (модель ОБЯЗАНА выбрать из списка)
# =============================================================================

SINGLE = (
    "You are a professional librarian organizing a database of web pages.\n"
    "Assign exactly ONE category from the list below.\n"
    "\n"
    "STRICT RULE: You MUST choose from this list. Do NOT invent new categories.\n"
    "{taxonomy}"
    "\n"
    "Title: {title}\n"
    "{description_line}"
    "Category:"
)

BATCH_HEADER = (
    "You are a professional librarian organizing a database of web pages.\n"
    "Assign exactly ONE category from the list below to each item.\n"
    "\n"
    "STRICT RULE: You MUST choose from this list. Do NOT invent new categories.\n"
    "{taxonomy}"
    "\n"
    "Respond with ONLY a numbered list. Format: 1. Category name"
)

BATCH_ITEM = "{i}. Title: {title}"