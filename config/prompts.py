# =============================================================================
# prompts.py — шаблоны промптов для классификации URL
# Редактируй эти строки — скрипты подхватят изменения автоматически.
#
# Плейсхолдеры:
#   SINGLE       → {url}, {title}, {hints_line}
#   BATCH_HEADER → {hints_line}
#   BATCH_ITEM   → {i}, {url}, {title}
#   HINTS_LINE   → {hints}  (список категорий через запятую, подставляется
#                             в {hints_line} когда справочник непустой)
#
# Чтобы переключить промпт — закомментируй активный блок,
# раскомментируй нужную альтернативу.
# =============================================================================

# ── Строка-подсказка с существующими категориями ──────────────────────────────
HINTS_LINE = "Existing categories (reuse if fits): {hints}\n"


# =============================================================================
# Вариант A — «continuation + запрет» (гибрид)
# Одна строка запрета убирает предисловия, незаконченная строка
# побуждает модель дописать категорию напрямую.
# =============================================================================

# SINGLE = (
#     "URL: {url}\n"
#     "Title: {title}\n"
#     "\n"
#     "{hints_line}"
#     "Reply with the category only, no explanation.\n"
#     "Category (1–3 words, same language as title): "
# )
#
# BATCH_HEADER = (
#     "{hints_line}"
#     "Classify each web page with ONE category (1–3 words, same language as title).\n"
#     "Reply with the category only, no explanation.\n"
#     "Numbered list only. Format: 1. category"
# )
#
# BATCH_ITEM = "{i}. Title: {title}"


# =============================================================================
# Вариант B — «rule-based + few-shot» (явные правила, пример с URL)
# Запрет на конкретные виды мусора + consistency rule для hints.
# =============================================================================

SINGLE = (
    "Act as a professional technical librarian. Your goal is to organize a large database of IT articles using a consistent taxonomy.\n"
    "Your task: Assign exactly ONE high-level category to the article based on its Title.\n"
    "\n"
    "Rules:\n"
    "- Use high-level industry domains (e.g., 'Product Management' instead of 'Roadmaps', 'Data Science' instead of 'Vectorization').\n"
    "- Match the category language to the Title (Russian or English).\n"
    "- Length: 1 to 3 words max.\n"
    "- AVOID: Do not use metaphors, specific names, or clickbait words from the title (e.g., no 'Anatomy of Leviathan').\n"
    "- PRIORITIZE: Choose from the 'Existing categories' list below if a suitable match exists.\n"
    "- DISTINGUISH CONTEXT: If the title refers to history, arts, or fiction, use categories like 'История', 'Литература' or 'Научпоп' instead of technical domains.\n"
    "- FOCUS on the 'About': Ask yourself: Is this a tutorial/technical guide or a cultural review? Assign the category accordingly.\n"
    "- OUTPUT: Respond with ONLY the category name. No prefixes, quotes, or explanations.\n"
    "\n"
    "Example 1 (Specific to General):\n"
    "Title: Как устроен механизм attention в трансформерах\n"
    "Response: машинное обучение\n"
    "\n"
    "Example 2 (Avoid metaphors):\n"
    "Title: Исчезновение капитала в эпоху цифровизации\n"
    "Response: экономика\n"
    "Example 3 (Cultural/Historical context):\n"
    "Title: ЭВМ и роботы на страницах советской научной фантастики\n"
    "Response: история науки\n"
    "\n"
    "{hints_line}"
    "\n"
    "Title: {title}\n"
    "Category:"
)

BATCH_HEADER = (
    "{hints_line}"
    "Assign exactly ONE category to each web page below.\n"
    "Rules:\n"
    "- The category must be in the same language as the title (Russian or English).\n"
    "- It can be 1 word or a short phrase (up to 3 words).\n"
    "- Respond with ONLY a numbered list — one line per item, nothing else.\n"
    "- Format exactly: 1. category name"
)

BATCH_ITEM = "{i}. Title: {title}"

'''
SINGLE = (
    "Assign exactly ONE category to the following web page.\n"
    "Rules:\n"
    "- The category must be in the same language as the title (Russian or English).\n"
    "- It can be 1 word or a short phrase (up to 3 words).\n"
    "- You may use a suggested category OR invent your own — pick whatever fits best.\n"
    "- Respond with ONLY the category, nothing else.\n"
    "- Example response: machine learning\n"
    "\n"
    "{hints_line}"
    "\n"
    "URL: {url}\n"
    "Title: {title}\n"
)
'''