# =============================================================================
# domain_rules.py — правила категоризации по домену
#
# Если домен URL совпадает с ключом — применяется правило:
#   {"category": "..."}  → категория назначается напрямую, без LLM
#   {"section": "..."}   → LLM выбирает только из категорий этого раздела
#   {"section": "...", "category": "..."}  → категория напрямую (оба уровня известны)
#
# Домен указывается без www. и без протокола.
# Поддомены НЕ матчатся автоматически — указывайте явно (например, "docs.python.org").
# Категория ДОЛЖНА быть из TAXONOMY, раздел — из TAXONOMY_SECTIONS.
# =============================================================================

from config.taxonomy import TAXONOMY, TAXONOMY_SECTIONS

# Быстрый lookup: section_name → [categories]
_SECTION_CATS: dict[str, list[str]] = {
    name: cats for name, cats in TAXONOMY_SECTIONS
}

DOMAIN_RULES: dict[str, dict[str, str]] = {
    # ── L0: раздел известен, L1 определяет LLM ─────────────────────────────
    "habr.com": {"section": "IT и разработка"},

    # ── L1: категория известна, LLM не нужна ────────────────────────────────
    "flibusta.is": {"category": "Книги"},
    "youtube.com": {"category": "Медиа и контент"},
    "youtu.be": {"category": "Медиа и контент"},
    "rozetka.com.ua": {"category": "Интернет-магазин"},
    "amazon.com": {"category": "Интернет-магазин"},

    # ── L0 + L1: оба уровня известны ────────────────────────────────────────
    "github.com": {"section": "IT и разработка", "category": "Программирование"},
    "gitlab.com": {"section": "IT и разработка", "category": "Программирование"},
    "stackoverflow.com": {"section": "IT и разработка", "category": "Программирование"},
}

# ── Валидация ────────────────────────────────────────────────────────────────
_taxonomy_set = set(TAXONOMY)
_section_set = set(_SECTION_CATS.keys())

for _domain, _rule in DOMAIN_RULES.items():
    if "category" in _rule and _rule["category"] not in _taxonomy_set:
        raise ValueError(
            f"domain_rules.py: категория {_rule['category']!r} для домена {_domain!r} "
            f"отсутствует в TAXONOMY"
        )
    if "section" in _rule and _rule["section"] not in _section_set:
        raise ValueError(
            f"domain_rules.py: раздел {_rule['section']!r} для домена {_domain!r} "
            f"отсутствует в TAXONOMY_SECTIONS"
        )
