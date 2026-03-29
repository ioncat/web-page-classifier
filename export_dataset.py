# =============================================================================
# export_dataset.py — экспорт БД в JSONL для обучения ML-классификатора
#
# Формат строки:
#   {"text": "title [SEP] description [SEP] domain", "label": "Категория"}
#
# Использование:
#   python export_dataset.py                          → dataset.jsonl
#   python export_dataset.py -o train.jsonl           → указанный файл
#   python export_dataset.py --no-description         → без description
#   python export_dataset.py --stats                  → распределение по категориям
#   python export_dataset.py --min-per-class 10       → только категории с ≥10 примеров
# =============================================================================

import argparse
import json
import sys
import io
from collections import Counter
from urllib.parse import urlparse

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from db import get_conn, init_db
from config.taxonomy import TAXONOMY

if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

console = Console()

TAXONOMY_SET = {c.lower() for c in TAXONOMY}


def _extract_domain(url: str) -> str:
    """Извлекает домен без www."""
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except Exception:
        return ""


def _fetch_exportable_rows() -> list[dict]:
    """Выбирает done-записи с title и category из таксономии."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT url, title, description, category
                 FROM urls
                WHERE status = 'done'
                  AND title IS NOT NULL AND title != ''
                  AND category IS NOT NULL AND category != ''
                ORDER BY id"""
        ).fetchall()
    return [dict(r) for r in rows]


def _build_text(title: str, description: str | None, domain: str,
                include_description: bool) -> str:
    """Формирует текстовое представление для модели."""
    parts = [title.strip()]
    if include_description and description and description.strip():
        desc = description.strip()
        if len(desc) > 200:
            desc = desc[:200]
        parts.append(desc)
    parts.append(domain)
    return " [SEP] ".join(parts)


def export(
    output: str = "dataset.jsonl",
    include_description: bool = True,
    min_per_class: int = 0,
    stats_only: bool = False,
) -> None:
    init_db()
    rows = _fetch_exportable_rows()

    if not rows:
        console.print("[red]Нет данных для экспорта.[/red] "
                       "Нужны done-записи с title и category.")
        return

    # Фильтр: только категории из таксономии
    valid = []
    skipped_taxonomy = 0
    for r in rows:
        if r["category"].lower() in TAXONOMY_SET:
            valid.append(r)
        else:
            skipped_taxonomy += 1

    # Подсчёт по категориям
    cat_counts = Counter(r["category"] for r in valid)

    # Фильтр по min_per_class
    if min_per_class > 1:
        allowed_cats = {c for c, n in cat_counts.items() if n >= min_per_class}
        before = len(valid)
        valid = [r for r in valid if r["category"] in allowed_cats]
        skipped_min = before - len(valid)
    else:
        skipped_min = 0
        allowed_cats = set(cat_counts.keys())

    # Пересчёт после фильтра
    cat_counts = Counter(r["category"] for r in valid)

    # ── Показать статистику ──
    t = Table(title="Распределение по категориям", show_lines=False)
    t.add_column("#", justify="right", style="dim")
    t.add_column("Категория", style="cyan")
    t.add_column("Кол-во", justify="right", style="bold")
    t.add_column("Доля", justify="right", style="dim")

    total = len(valid)
    for i, (cat, cnt) in enumerate(cat_counts.most_common(), 1):
        pct = f"{cnt * 100 / total:.1f}%"
        t.add_row(str(i), cat, str(cnt), pct)

    console.print(t)
    console.print()

    # Сводка
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", min_width=30)
    grid.add_column(justify="right", style="bold")
    grid.add_row("Записей в экспорте:", str(total))
    grid.add_row("Категорий:", str(len(cat_counts)))
    if skipped_taxonomy:
        grid.add_row("[yellow]Пропущено (вне таксономии):[/yellow]",
                     f"[yellow]{skipped_taxonomy}[/yellow]")
    if skipped_min:
        grid.add_row(f"[yellow]Пропущено (< {min_per_class} примеров):[/yellow]",
                     f"[yellow]{skipped_min}[/yellow]")
    console.print(Panel(grid, title="[bold cyan]Сводка[/bold cyan]", expand=False))

    if stats_only:
        return

    # ── Записать JSONL ──
    written = 0
    with open(output, "w", encoding="utf-8") as f:
        for r in valid:
            domain = _extract_domain(r["url"])
            text = _build_text(r["title"], r["description"], domain,
                               include_description)
            line = json.dumps(
                {"text": text, "label": r["category"]},
                ensure_ascii=False,
            )
            f.write(line + "\n")
            written += 1

    console.print(f"\n[green]Записано {written} строк → [bold]{output}[/bold][/green]")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Экспорт БД в JSONL-датасет для обучения ML-классификатора",
    )
    parser.add_argument(
        "-o", "--output",
        default="dataset.jsonl",
        metavar="FILE",
        help="выходной файл (по умолчанию: dataset.jsonl)",
    )
    parser.add_argument(
        "--no-description",
        action="store_true",
        dest="no_description",
        help="не включать description в текст (только title + domain)",
    )
    parser.add_argument(
        "--min-per-class",
        type=int,
        default=0,
        metavar="N",
        dest="min_per_class",
        help="экспортировать только категории с ≥N примеров",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="только показать распределение, без записи файла",
    )

    args = parser.parse_args()

    export(
        output=args.output,
        include_description=not args.no_description,
        min_per_class=args.min_per_class,
        stats_only=args.stats,
    )


if __name__ == "__main__":
    main()
