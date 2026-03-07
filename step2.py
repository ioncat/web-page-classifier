import random
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
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
from rich.table import Table

from db import get_errors, get_pending, get_pending_by_domain, get_stats, init_db, update_url

# ── Параметры краулера ────────────────────────────────────────────────────────
REQUEST_TIMEOUT   = (10, 30)   # (connect, read) в секундах
DELAY_MIN         = 2.0        # минимальная пауза между запросами (сек)
DELAY_MAX         = 5.0        # максимальная пауза
MAX_RETRIES       = 3          # попыток на URL
RETRY_BACKOFF     = 2          # множитель backoff: 2^1=2s, 2^2=4s, 2^3=8s

USER_AGENTS = [
    # Chrome / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Safari / macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    # Firefox / Linux
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge / Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]

BASE_HEADERS = {
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.7,en;q=0.5",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "DNT": "1",
}

console = Console()


# ── Сессия с автоматическим retry для HTTP-ошибок ────────────────────────────
def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session: requests.Session = _build_session()


def _polite_delay() -> None:
    """Случайная пауза перед запросом."""
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def _random_headers() -> dict:
    """Случайный User-Agent при каждом вызове."""
    return {**BASE_HEADERS, "User-Agent": random.choice(USER_AGENTS)}


# ── Получение заголовка с ручным retry для таймаутов ─────────────────────────
def fetch_title(url: str) -> str | None:
    """Загружает страницу и возвращает содержимое <title>.
    Перед запросом делает случайную паузу.
    При ReadTimeout / ConnectionError — экспоненциальный backoff.
    """
    _polite_delay()

    attempt = 0
    while True:
        try:
            resp = _session.get(
                url,
                headers=_random_headers(),
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            return soup.title.string.strip() if soup.title and soup.title.string else None

        except (requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout) as exc:
            attempt += 1
            if attempt > MAX_RETRIES:
                raise
            wait = RETRY_BACKOFF ** attempt  # 2s → 4s → 8s
            console.log(
                f"[yellow]⚠ Retry {attempt}/{MAX_RETRIES}[/yellow] "
                f"({type(exc).__name__}, ждём {wait:.0f}s): [dim]{url}[/dim]"
            )
            time.sleep(wait)

        except requests.exceptions.RequestException:
            raise  # HTTP-ошибки — не ретраим вручную (urllib3 уже обработал)


# ── Вывод статистики БД ───────────────────────────────────────────────────────
def print_db_stats(stats: dict) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column(justify="right", style="bold")
    table.add_row("Всего в БД:", str(stats["total"]))
    table.add_row("[green]Обработано:[/green]", f"[green]{stats['done']}[/green]")
    table.add_row("[yellow]Ожидает:[/yellow]", f"[yellow]{stats['pending']}[/yellow]")
    table.add_row("[red]Ошибок:[/red]", f"[red]{stats['error']}[/red]")
    console.print(Panel(table, title="[bold cyan]Состояние БД[/bold cyan]"))


# ── Режимы обработки ──────────────────────────────────────────────────────────
def _process_plain(pending: list[str], verbose: bool) -> tuple[int, int]:
    """Обработка без rich progress bar — plain вывод (для --no-progress)."""
    done_count = 0
    error_count = 0
    total = len(pending)

    for i, url in enumerate(pending, 1):
        print(f"[{i}/{total}] {url}", flush=True)
        try:
            title = fetch_title(url)
            update_url(url, status="done", title=title)
            done_count += 1
            if verbose:
                print(f"  OK: {title}")
        except Exception as e:
            error_msg = str(e)
            update_url(url, status="error", error=error_msg)
            error_count += 1
            print(f"  ERROR: {error_msg}")

    return done_count, error_count


def _process_rich(pending: list[str], verbose: bool) -> tuple[int, int]:
    """Обработка с rich progress bar."""
    done_count = 0
    error_count = 0

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
        task = progress.add_task("Обработка...", total=len(pending))

        for url in pending:
            short_url = url[:60] + "…" if len(url) > 60 else url
            progress.update(task, description=f"[dim]{short_url}[/dim]")

            try:
                title = fetch_title(url)
                update_url(url, status="done", title=title)
                done_count += 1
                if verbose:
                    console.log(f"[green]OK[/green] {title or '—'}")
            except Exception as e:
                error_msg = str(e)
                update_url(url, status="error", error=error_msg)
                error_count += 1
                if verbose:
                    console.log(f"[red]ERR[/red] {error_msg}")

            progress.advance(task)

    return done_count, error_count


def _print_summary(done_count: int, error_count: int, domain: str | None = None) -> None:
    from urllib.parse import urlparse

    summary = Table(title="Итоги обработки", show_header=True, header_style="bold magenta")
    summary.add_column("Статус", style="cyan")
    summary.add_column("Кол-во", justify="right", style="bold")
    summary.add_row("[green]Успешно[/green]", f"[green]{done_count}[/green]")
    summary.add_row("[red]Ошибок[/red]", f"[red]{error_count}[/red]")
    summary.add_row("Итого", str(done_count + error_count))
    console.print(summary)

    all_errors = get_errors()
    if domain:
        domain_norm = domain.lower().removeprefix("www.")
        errors = [
            e for e in all_errors
            if urlparse(e["url"]).netloc.lower().removeprefix("www.") == domain_norm
        ]
    else:
        errors = all_errors

    if errors:
        err_table = Table(
            title=f"[red]Ошибки ({len(errors)})[/red]",
            show_header=True,
            header_style="bold red",
        )
        err_table.add_column("URL", style="yellow", no_wrap=False, max_width=60)
        err_table.add_column("Ошибка", style="dim", no_wrap=False, max_width=60)
        for row in errors:
            err_table.add_row(row["url"], row["error"] or "—")
        console.print(err_table)
        console.print(
            "[dim]Для повторной обработки:[/dim] "
            "[bold]python main.py --retry-failed[/bold]"
        )


# ── Точка входа ───────────────────────────────────────────────────────────────
def main(
    limit: int | None = None,
    no_progress: bool = False,
    verbose: bool = False,
    urls: list[str] | None = None,
    domain: str | None = None,
) -> None:
    """
    limit       — обработать не более N URL
    no_progress — plain вывод вместо rich progress bar
    verbose     — показывать заголовок / ошибку по каждому URL
    urls        — список конкретных URL (если None — берёт pending из БД)
    domain      — фильтровать только URL указанного домена
    """
    console.print(Panel("[bold cyan]Step 2 — Парсинг заголовков страниц[/bold cyan]"))

    init_db()

    if urls is None:
        stats = get_stats()
        print_db_stats(stats)
        if domain:
            pending = get_pending_by_domain(domain)
            console.print(f"Фильтр по домену: [cyan]{domain}[/cyan] → [bold]{len(pending)}[/bold] URL")
        else:
            pending = get_pending()
    else:
        pending = urls

    if limit is not None:
        pending = pending[:limit]

    if not pending:
        msg = f"домена [cyan]{domain}[/cyan]" if domain else "обработки"
        console.print(f"[green]Нет URL для {msg}.[/green] Все ссылки уже обработаны.")
        return

    console.print(f"К обработке: [bold yellow]{len(pending)}[/bold yellow] URL\n")

    if no_progress:
        done_count, error_count = _process_plain(pending, verbose)
    else:
        done_count, error_count = _process_rich(pending, verbose)

    _print_summary(done_count, error_count, domain=domain)
    console.print(Panel("[green]Готово.[/green]"))


if __name__ == "__main__":
    main()
