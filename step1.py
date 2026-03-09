import os
import re

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from db import init_db, insert_urls
from config.settings import DEFAULT_INPUT_FILE

LINK_PATTERN = re.compile(r"https?://[^\s|<>\"'`]+")
TRAILING_JUNK = re.compile(r"[.,;!?)]+$")

console = Console()


def extract_links(text: str) -> list[str]:
    raw = LINK_PATTERN.findall(text)
    cleaned = [TRAILING_JUNK.sub("", url) for url in raw]
    return list(dict.fromkeys(cleaned))  # дедупликация с сохранением порядка


def main(input_file: str = DEFAULT_INPUT_FILE) -> None:
    console.print(Panel("[bold cyan]Step 1 — Импорт ссылок в БД[/bold cyan]"))

    if not os.path.exists(input_file):
        console.print(
            f"[bold red]Ошибка:[/bold red] файл '[yellow]{input_file}[/yellow]' не найден.\n"
            f"Текущая директория: [dim]{os.getcwd()}[/dim]"
        )
        raise SystemExit(1)

    init_db()

    with open(input_file, "r", encoding="utf-8") as f:
        raw_data = f.read()

    links = extract_links(raw_data)
    found = len(links)

    if not links:
        console.print("[yellow]Ссылки не найдены в файле.[/yellow]")
        return

    console.print(f"Найдено ссылок в файле: [bold]{found}[/bold]")

    added, skipped = insert_urls(links)

    table = Table(title="Результат импорта", show_header=True, header_style="bold magenta")
    table.add_column("Показатель", style="cyan")
    table.add_column("Кол-во", justify="right", style="bold")

    table.add_row("Найдено в файле", str(found))
    table.add_row("Добавлено в БД", f"[green]{added}[/green]")
    table.add_row("Пропущено (дубликаты)", f"[dim]{skipped}[/dim]")

    console.print(table)
    console.print(Panel(f"[green]Готово.[/green] Запустите [bold]step2.py[/bold] для обработки."))


if __name__ == "__main__":
    main()
