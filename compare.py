"""
compare.py — Сравнение нескольких Ollama-моделей на одном наборе URL.

Функции:
  run_compare_models(models, ...)  — запустить несколько моделей → model_results
  show_comparison(limit, export)   — вывести side-by-side таблицу / CSV
"""
import csv
import sys

import ollama
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table

import step3
from db import (
    accept_model as db_accept_model,
    clear_model_results as db_clear_model_results,
    get_done_urls,
    get_model_results_raw,
    init_compare_schema,
    save_model_result,
)
from step3 import OLLAMA_HOST, classify_url, get_available_models

# ── Константы ─────────────────────────────────────────────────────────────────
MAX_TITLE_LEN         = 45
MAX_TAG_LEN           = 32
MAX_CONSECUTIVE_ERRS  = 3   # подряд ошибок соединения → прерывание

console = Console()


# ── Pivot-утилита ─────────────────────────────────────────────────────────────
def _pivot(raw: list[dict]) -> tuple[list[str], list[dict]]:
    """Разворачивает плоский список строк (url_id, model, category) в wide-формат.

    Возвращает:
        models — отсортированный список имён моделей
        rows   — список dict с ключами url, title, <model1>, <model2>, …
    """
    models_seen: set[str] = set()
    by_url: dict[int, dict] = {}

    for row in raw:
        uid = row["id"]
        models_seen.add(row["model"])
        if uid not in by_url:
            by_url[uid] = {"url": row["url"], "title": row["title"] or ""}
        by_url[uid][row["model"]] = row["category"] or ""

    models = sorted(models_seen)
    rows   = [by_url[uid] for uid in sorted(by_url)]
    return models, rows


# ── Отображение / экспорт ─────────────────────────────────────────────────────
def show_comparison(limit: int | None = None, export: str | None = None) -> None:
    """Выводит side-by-side таблицу результатов сравнения.

    limit  — показать не более N строк
    export — путь к CSV-файлу для экспорта (None = только терминал)
    """
    init_compare_schema()
    raw = get_model_results_raw()

    if not raw:
        console.print(
            "[yellow]Нет данных для сравнения.[/yellow]\n"
            "Сначала запустите: [bold]python main.py --compare-models llama3,mistral[/bold]"
        )
        return

    models, rows = _pivot(raw)
    total_rows = len(rows)

    if limit:
        rows = rows[:limit]

    # Короткие имена моделей (без :latest и т.п.)
    short_names = [m.split(":")[0] for m in models]

    # ── Rich-таблица ──────────────────────────────────────────────────────────
    table = Table(
        title=f"Сравнение моделей — {len(rows)}/{total_rows} URL × {len(models)} моделей",
        show_header=True,
        header_style="bold cyan",
        show_lines=True,
        expand=False,
    )
    table.add_column("Заголовок", style="dim", max_width=MAX_TITLE_LEN, no_wrap=False)
    for short in short_names:
        table.add_column(short, max_width=MAX_TAG_LEN, no_wrap=False)

    for row in rows:
        title_cell = (row["title"] or row["url"])[:MAX_TITLE_LEN]
        tag_cells  = [row.get(m) or "[dim]—[/dim]" for m in models]
        table.add_row(title_cell, *tag_cells)

    console.print(table)

    # ── CSV-экспорт ───────────────────────────────────────────────────────────
    if export:
        fieldnames = ["url", "title"] + short_names
        with open(export, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                out = {"url": row["url"], "title": row["title"]}
                for m, short in zip(models, short_names):
                    out[short] = row.get(m, "")
                writer.writerow(out)
        console.print(
            f"\n[green]Экспортировано:[/green] [bold]{export}[/bold] "
            f"[dim]({len(rows)} строк, {len(models)} моделей)[/dim]"
        )


# ── Запуск нескольких моделей ─────────────────────────────────────────────────
def run_compare_models(
    models: list[str],
    limit: int | None = None,
    no_progress: bool = False,
    verbose: bool = False,
) -> None:
    """Прогоняет каждую модель через все done-URL и сохраняет в model_results.

    Справочник тегов (tags) в этом режиме НЕ обновляется —
    чистый эксперимент без побочных эффектов.
    """
    init_compare_schema()

    rows = get_done_urls()
    if limit:
        rows = rows[:limit]

    if not rows:
        console.print(
            "[yellow]Нет done-URL.[/yellow] "
            "Сначала запустите step1 + step2: [bold]python main.py[/bold]"
        )
        return

    # Подключение к Ollama и проверка доступных моделей
    client = ollama.Client(host=OLLAMA_HOST)
    try:
        available = get_available_models(client)
    except Exception as exc:
        console.print(f"[red]Ollama недоступна ({OLLAMA_HOST}):[/red] {exc}")
        sys.exit(1)

    # Фильтруем модели, которых нет в Ollama
    valid, skipped = [], []
    for m in models:
        (valid if m in available else skipped).append(m)
    if skipped:
        console.print(
            f"[yellow]Пропущены (не найдены в Ollama):[/yellow] {', '.join(skipped)}"
        )
    if not valid:
        console.print("[red]Нет доступных моделей для запуска.[/red]")
        sys.exit(1)

    console.print(
        f"URL: [bold yellow]{len(rows)}[/bold yellow]  |  "
        f"Модели: [bold cyan]{', '.join(m.split(':')[0] for m in valid)}[/bold cyan]\n"
    )

    # Подсказки пустые — режим сравнения изолирован от справочника
    hints: list[str] = []

    for model in valid:
        console.print(Rule(f"[cyan]{model.split(':')[0]}[/cyan]", style="cyan"))

        done_count  = 0
        error_count = 0
        conn_errors = 0
        aborted     = False

        if no_progress:
            total = len(rows)
            for i, row in enumerate(rows, 1):
                url, title, uid = row["url"], row["title"] or "", row["id"]
                print(f"[{i}/{total}] {url}", flush=True)
                try:
                    category = classify_url(client, model, url, title, hints)
                    save_model_result(uid, model, category)
                    done_count  += 1
                    conn_errors  = 0
                    if verbose:
                        print(f"  {category}")
                except ollama.ResponseError as exc:
                    error_count += 1
                    print(f"  API ERR [{exc.status_code}]: {exc.error}")
                except ValueError as exc:
                    error_count += 1
                    print(f"  EMPTY: {exc}")
                except Exception as exc:
                    error_count += 1
                    conn_errors += 1
                    print(f"  ERR: {exc}")
                    if conn_errors >= MAX_CONSECUTIVE_ERRS:
                        console.print(
                            f"\n[bold red]Прерывание:[/bold red] "
                            f"Ollama недоступна ({MAX_CONSECUTIVE_ERRS} ошибок подряд)"
                        )
                        aborted = True
                        break
        else:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            ) as progress:
                task = progress.add_task(model.split(":")[0], total=len(rows))

                for row in rows:
                    url, title, uid = row["url"], row["title"] or "", row["id"]
                    short = url[:55] + "…" if len(url) > 55 else url
                    progress.update(task, description=f"[dim]{short}[/dim]")

                    try:
                        category = classify_url(client, model, url, title, hints)
                        save_model_result(uid, model, category)
                        done_count  += 1
                        conn_errors  = 0
                        if verbose:
                            console.log(f"[green]OK[/green] {category}")
                    except ollama.ResponseError as exc:
                        error_count += 1
                        if verbose:
                            console.log(f"[red]API ERR[/red] [{exc.status_code}] {exc.error}")
                    except ValueError as exc:
                        error_count += 1
                        if verbose:
                            console.log(f"[red]EMPTY[/red] {exc}")
                    except Exception as exc:
                        error_count += 1
                        conn_errors += 1
                        if verbose:
                            console.log(f"[red]ERR[/red] {exc}")
                        if conn_errors >= MAX_CONSECUTIVE_ERRS:
                            console.log(
                                f"[bold red]Прерывание:[/bold red] "
                                f"Ollama недоступна ({MAX_CONSECUTIVE_ERRS} ошибок подряд)"
                            )
                            aborted = True
                            break

                    progress.advance(task)

        status_parts = [
            f"[green]{done_count} OK[/green]",
            f"[red]{error_count} ERR[/red]",
        ]
        if aborted:
            status_parts.append("[yellow]ПРЕРВАНО[/yellow]")
        console.print("  " + "  ".join(status_parts))

        if aborted:
            console.print("[dim]Ollama упала — остановка сравнения.[/dim]")
            break

    console.print()
    console.print(Rule("[bold green]Сравнение завершено[/bold green]", style="green"))
    console.print(
        "[dim]Просмотр:[/dim] [bold]python main.py --compare[/bold]  |  "
        "[dim]Принять модель:[/dim] [bold]python main.py --accept-model <имя>[/bold]"
    )
