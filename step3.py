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
from rich.prompt import IntPrompt
from rich.table import Table

from db import get_done_unclassified, get_tags, init_db, init_tags_schema, set_category

# ── Параметры ─────────────────────────────────────────────────────────────────
OLLAMA_HOST = "http://localhost:11434"

console = Console()


# ── Клиент Ollama ─────────────────────────────────────────────────────────────
def _build_client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_HOST)


def get_available_models(client: ollama.Client) -> list[str]:
    """Возвращает список имён моделей, доступных в Ollama."""
    resp = client.list()
    return [m.model for m in resp.models]


# ── Выбор модели ──────────────────────────────────────────────────────────────
def _print_models_table(models: list[str]) -> None:
    table = Table(
        title="Доступные модели Ollama",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("#", style="dim", justify="right")
    table.add_column("Модель", style="bold")
    for i, name in enumerate(models, 1):
        table.add_row(str(i), name)
    console.print(table)


def _select_model_interactively(available: list[str]) -> str:
    """Показывает список моделей и просит пользователя выбрать одну."""
    _print_models_table(available)

    if len(available) == 1:
        console.print(
            f"[dim]Единственная доступная модель — выбрана автоматически:[/dim] "
            f"[bold]{available[0]}[/bold]\n"
        )
        return available[0]

    while True:
        idx = IntPrompt.ask(
            f"[bold]Выберите модель[/bold] [dim](1–{len(available)})[/dim]",
            console=console,
        )
        if 1 <= idx <= len(available):
            selected = available[idx - 1]
            console.print(f"Выбрана модель: [bold green]{selected}[/bold green]\n")
            return selected
        console.print(f"[red]Введите число от 1 до {len(available)}[/red]")


# ── Промпт и классификация ────────────────────────────────────────────────────
def _build_prompt(title: str, url: str, hints: list[str]) -> str:
    hints_part = (
        f"Tag suggestions (use them if they fit, or create your own): {', '.join(hints)}\n"
        if hints
        else "No tag suggestions provided — create appropriate tags yourself.\n"
    )
    return (
        "Classify the following web page by assigning 1 to 3 short topic tags.\n"
        "Rules:\n"
        "- Tags must be in the same language as the title (Russian or English).\n"
        "- You may use the suggested tags OR invent your own — pick whatever fits best.\n"
        "- Respond with ONLY a comma-separated list of tags, nothing else.\n"
        "- Example response: python, tutorial, beginner\n\n"
        f"{hints_part}"
        f"\nURL: {url}\n"
        f"Title: {title or '(no title)'}\n"
    )


def classify_url(
    client: ollama.Client,
    model: str,
    url: str,
    title: str,
    hints: list[str],
) -> str:
    """Запрашивает у Ollama теги для URL. Возвращает строку тегов через запятую."""
    prompt = _build_prompt(title or "", url, hints)
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.message.content.strip()

    # Берём первую непустую строку, разбиваем по запятым, чистим каждый тег
    first_line = next((ln for ln in raw.splitlines() if ln.strip()), "")
    tags = [t.strip().strip("\"'.,;:-") for t in first_line.split(",")]
    tags = [t for t in tags if t][:5]  # максимум 5 тегов, без пустых
    return ", ".join(tags)


# ── Точка входа ───────────────────────────────────────────────────────────────
def main(
    model: str | None = None,
    limit: int | None = None,
    list_models_flag: bool = False,
    no_progress: bool = False,
    verbose: bool = False,
) -> None:
    """
    model            — имя модели Ollama; если None — интерактивный выбор
    limit            — обработать не более N URL
    list_models_flag — показать список моделей и выйти
    no_progress      — plain вывод без rich progress bar
    verbose          — показывать присвоенные теги по каждому URL
    """
    console.print(Panel("[bold cyan]Step 3 — Классификация через Ollama LLM[/bold cyan]"))

    init_db()
    init_tags_schema()

    # ── Подключение к Ollama ───────────────────────────────────────────────────
    client = _build_client()
    try:
        available = get_available_models(client)
    except Exception as exc:
        console.print(
            f"[red]Не удалось подключиться к Ollama ({OLLAMA_HOST}):[/red] {exc}\n"
            "[dim]Убедитесь, что Ollama запущена: ollama serve[/dim]"
        )
        sys.exit(1)

    # ── --list-models ──────────────────────────────────────────────────────────
    if list_models_flag:
        if available:
            _print_models_table(available)
        else:
            console.print(
                "[yellow]Моделей не найдено.[/yellow] "
                "Загрузите модель: [bold]ollama pull llama3[/bold]"
            )
        return

    if not available:
        console.print(
            "[red]Нет доступных моделей.[/red] "
            "Загрузите модель: [bold]ollama pull llama3[/bold]"
        )
        sys.exit(1)

    # ── Выбор модели: CLI-флаг или интерактивный ──────────────────────────────
    if model is not None:
        # Передан через --model — используем без вопросов
        if model not in available:
            console.print(
                f"[yellow]Предупреждение:[/yellow] модель [bold]{model}[/bold] "
                "не найдена в Ollama. Попытка использовать всё равно..."
            )
        else:
            console.print(f"Модель: [bold]{model}[/bold]\n")
    else:
        # Интерактивный выбор
        model = _select_model_interactively(available)

    # ── Теги-подсказки из справочника ─────────────────────────────────────────
    hints = get_tags()
    if hints:
        preview = ", ".join(hints[:10]) + ("..." if len(hints) > 10 else "")
        console.print(
            f"Тегов-подсказок: [bold]{len(hints)}[/bold] — [dim]{preview}[/dim]\n"
            "[dim](модель может использовать их или создать собственные)[/dim]"
        )
    else:
        console.print(
            "[dim]Справочник тегов пуст — модель создаст теги самостоятельно.[/dim]\n"
            "[dim]Совет: добавьте подсказки через --add-tags тег1,тег2,...[/dim]"
        )

    # ── URL для классификации ─────────────────────────────────────────────────
    rows = get_done_unclassified()
    if limit is not None:
        rows = rows[:limit]

    if not rows:
        console.print(
            "\n[green]Нет URL для классификации.[/green] "
            "Все обработанные записи уже имеют категорию."
        )
        return

    console.print(f"\nК классификации: [bold yellow]{len(rows)}[/bold yellow] URL\n")

    # ── Обработка ─────────────────────────────────────────────────────────────
    done_count = 0
    error_count = 0

    if no_progress:
        total = len(rows)
        for i, row in enumerate(rows, 1):
            url, title = row["url"], row["title"] or ""
            print(f"[{i}/{total}] {url}", flush=True)
            try:
                category = classify_url(client, model, url, title, hints)
                set_category(url, category, model=model)
                done_count += 1
                if verbose:
                    print(f"  Tags: {category}")
            except Exception as exc:
                error_count += 1
                print(f"  ERROR: {exc}")
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
            task = progress.add_task("Классификация...", total=len(rows))

            for row in rows:
                url, title = row["url"], row["title"] or ""
                short_url = url[:60] + "…" if len(url) > 60 else url
                progress.update(task, description=f"[dim]{short_url}[/dim]")

                try:
                    category = classify_url(client, model, url, title, hints)
                    set_category(url, category, model=model)
                    done_count += 1
                    if verbose:
                        console.log(f"[green]OK[/green] {category}")
                except Exception as exc:
                    error_count += 1
                    if verbose:
                        console.log(f"[red]ERR[/red] {exc}")

                progress.advance(task)

    # ── Итоги ─────────────────────────────────────────────────────────────────
    summary = Table(
        title="Итоги классификации",
        show_header=True,
        header_style="bold magenta",
    )
    summary.add_column("Статус", style="cyan")
    summary.add_column("Кол-во", justify="right", style="bold")
    summary.add_row("[green]Классифицировано[/green]", f"[green]{done_count}[/green]")
    summary.add_row("[red]Ошибок[/red]", f"[red]{error_count}[/red]")
    summary.add_row("Итого", str(done_count + error_count))
    console.print(summary)
    console.print(Panel("[green]Готово.[/green]"))


if __name__ == "__main__":
    main()
