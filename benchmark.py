"""
benchmark.py — Поиск оптимальной комбинации --batch / --workers для step3.

Алгоритм:
  1. Берёт N done-URL из БД (одни и те же для каждого прогона)
  2. Перед каждым прогоном сбрасывает их category → NULL
  3. Запускает step3.main() с нужным batch/workers
  4. Измеряет реальное время и URL/с
  5. Выводит сравнительную таблицу, отмечает победителя

Использование:
  python benchmark.py
  python benchmark.py --model llama3 --limit 60
  python benchmark.py --limit 30 --no-warmup
"""

import argparse
import csv
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

import step3
from db import DB_PATH, get_conn, init_db, init_tags_schema

console = Console()

LOG_PATH = Path(__file__).parent / "benchmark_log.csv"
LOG_FIELDS = ["date", "model", "url_per_sec", "config"]

# ── Конфигурации для сравнения ─────────────────────────────────────────────────
CONFIGS: list[dict] = [
    dict(batch=1,  workers=1, label="baseline      "),
    dict(batch=1,  workers=2, label="parallel ×2   "),
    dict(batch=1,  workers=4, label="parallel ×4   "),
    dict(batch=5,  workers=1, label="batch=5       "),
    dict(batch=10, workers=1, label="batch=10      "),
    dict(batch=5,  workers=4, label="batch=5  ×4   "),
    dict(batch=10, workers=4, label="batch=10 ×4   "),
    dict(batch=20, workers=4, label="batch=20 ×4   "),
    dict(batch=10, workers=8, label="batch=10 ×8   "),
    dict(batch=20, workers=8, label="batch=20 ×8   "),
]


# ── Работа с БД ───────────────────────────────────────────────────────────────
def _get_benchmark_ids(n: int) -> list[int]:
    """Возвращает id первых N done-URL (с title) из БД."""
    with get_conn() as con:
        rows = con.execute(
            "SELECT id FROM urls WHERE status = 'done' AND title IS NOT NULL LIMIT ?",
            (n,),
        ).fetchall()
    return [r["id"] for r in rows]


def _reset_subset(url_ids: list[int]) -> None:
    """Сбрасывает category и tagged_by для заданного набора URL."""
    if not url_ids:
        return
    ph = ",".join("?" * len(url_ids))
    with get_conn() as con:
        con.execute(
            f"UPDATE urls SET category = NULL, tagged_by = NULL WHERE id IN ({ph})",
            url_ids,
        )


def _count_classified(url_ids: list[int]) -> int:
    """Возвращает кол-во URL из набора, получивших category после прогона."""
    if not url_ids:
        return 0
    ph = ",".join("?" * len(url_ids))
    with get_conn() as con:
        row = con.execute(
            f"SELECT COUNT(*) FROM urls WHERE id IN ({ph}) AND category IS NOT NULL",
            url_ids,
        ).fetchone()
    return row[0] if row else 0


# ── Лог результатов ───────────────────────────────────────────────────────────
def _append_log(model: str | None, best: dict) -> None:
    """Дописывает строку победителя в benchmark_log.csv."""
    write_header = not LOG_PATH.exists()
    with LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "date":        datetime.now().strftime("%Y-%m-%d %H:%M"),
            "model":       model or "auto",
            "url_per_sec": f"{best['rps']:.1f}",
            "config":      f"batch={best['batch']} workers={best['workers']}",
        })
    console.print(f"[dim]Лог записан → {LOG_PATH.name}[/dim]")


# ── Аргументы ─────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Benchmark batch/workers для step3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--model", default=None, metavar="MODEL",
        help="модель Ollama (по умолчанию: первая доступная)",
    )
    p.add_argument(
        "--limit", type=int, default=50, metavar="N",
        help="кол-во URL на каждую конфигурацию (default: 50)",
    )
    p.add_argument(
        "--no-warmup", action="store_true", dest="no_warmup",
        help="пропустить прогрев (если модель уже в VRAM)",
    )
    p.add_argument(
        "--only", nargs="+", type=int, metavar="I", dest="only",
        help="запустить только конфигурации с этими индексами (0-based)",
    )
    return p.parse_args()


# ── Точка входа ───────────────────────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    console.print(Panel("[bold cyan]Benchmark: batch × workers[/bold cyan]"))

    init_db()
    init_tags_schema()

    # ── Набор URL для теста ───────────────────────────────────────────────────
    url_ids = _get_benchmark_ids(args.limit)
    if not url_ids:
        console.print("[red]Нет done-URL с заголовками. Сначала запустите step1 + step2.[/red]")
        return

    N = len(url_ids)
    if N < args.limit:
        console.print(f"[yellow]В БД только {N} подходящих URL (запрошено {args.limit})[/yellow]")
    console.print(
        f"URL для теста: [bold yellow]{N}[/bold yellow]  |  "
        f"Конфигураций: [bold cyan]{len(CONFIGS)}[/bold cyan]\n"
    )

    # ── Выбор конфигураций ────────────────────────────────────────────────────
    configs = (
        [CONFIGS[i] for i in args.only if 0 <= i < len(CONFIGS)]
        if args.only
        else CONFIGS
    )

    # ── Прогрев модели ────────────────────────────────────────────────────────
    if not args.no_warmup:
        console.print("[dim]Прогрев модели (1 URL)...[/dim]")
        _reset_subset(url_ids[:1])
        step3.main(
            model=args.model, limit=1,
            no_progress=True, verbose=False,
            workers=1, batch=1,
        )
        console.print("[dim]Прогрев завершён.[/dim]\n")

    # ── Прогоны ───────────────────────────────────────────────────────────────
    results: list[dict] = []

    for cfg in configs:
        label = cfg["label"].strip()
        console.print(Rule(f"[cyan]{label}[/cyan]  batch={cfg['batch']} workers={cfg['workers']}", style="cyan"))

        _reset_subset(url_ids)

        t0 = time.perf_counter()
        step3.main(
            model=args.model,
            limit=N,
            no_progress=True,
            verbose=False,
            workers=cfg["workers"],
            batch=cfg["batch"],
        )
        elapsed = time.perf_counter() - t0

        done = _count_classified(url_ids)
        rps  = done / elapsed if elapsed > 0 else 0.0

        results.append({**cfg, "done": done, "elapsed": elapsed, "rps": rps})
        console.print(
            f"  [dim]→[/dim] {done}/{N} URL  "
            f"за [bold]{elapsed:.1f}[/bold] с  =  "
            f"[bold cyan]{rps:.1f}[/bold cyan] URL/с\n"
        )

    # ── Итоговая таблица ──────────────────────────────────────────────────────
    if not results:
        return

    console.print(Rule("[bold green]Итоги[/bold green]", style="green"))

    baseline_rps = results[0]["rps"] or 1.0
    best_rps     = max(r["rps"] for r in results)

    table = Table(
        show_header=True,
        header_style="bold cyan",
        show_lines=False,
        box=None,
        pad_edge=True,
    )
    table.add_column("Конфигурация",  style="bold",    min_width=16)
    table.add_column("batch",         justify="right", min_width=5)
    table.add_column("workers",       justify="right", min_width=7)
    table.add_column("время, с",      justify="right", min_width=8)
    table.add_column("URL/с",         justify="right", min_width=7)
    table.add_column("vs baseline",   justify="right", min_width=10)

    for r in sorted(results, key=lambda x: -x["rps"]):
        is_best  = abs(r["rps"] - best_rps) < 0.01
        speedup  = r["rps"] / baseline_rps if baseline_rps > 0 else 0.0
        label    = r["label"].strip()

        if is_best:
            label   = f"[bold green]★ {label}[/bold green]"
            rps_str = f"[bold green]{r['rps']:.1f}[/bold green]"
            sp_str  = f"[bold green]×{speedup:.1f}[/bold green]"
        else:
            rps_str = f"{r['rps']:.1f}"
            sp_str  = f"×{speedup:.1f}"

        table.add_row(
            label,
            str(r["batch"]),
            str(r["workers"]),
            f"{r['elapsed']:.1f}",
            rps_str,
            sp_str,
        )

    console.print(table)

    best = max(results, key=lambda x: x["rps"])
    console.print(
        f"\n[dim]Запустить победителя:[/dim] "
        f"[bold]python main.py --only-classify "
        f"--batch {best['batch']} --workers {best['workers']}[/bold]"
    )

    # Лог пишем только при полном прогоне (не --only)
    if not args.only:
        _append_log(args.model, best)


if __name__ == "__main__":
    main()
