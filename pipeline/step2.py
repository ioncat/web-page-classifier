import random
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse as _urlparse

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

from db import (
    get_done_without_description,
    get_errors,
    get_pending,
    get_pending_by_domain,
    get_stats,
    init_db,
    update_description,
    update_url,
    TRANSIENT_CODES,
)
from config.settings import (
    BASE_HEADERS,
    DELAY_MAX,
    DELAY_MIN,
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    RETRY_BACKOFF,
    USER_AGENTS,
)

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


# ── JS challenge bypass ──────────────────────────────────────────────────────
_JS_CHALLENGE_RE = re.compile(r'defaultHash\s*=\s*"([a-f0-9]{32,})"')

# Максимальный размер ответа, при котором проверяем на challenge.
# Настоящие страницы обычно > 1 КБ, challenge-заглушки — 300–600 байт.
_CHALLENGE_MAX_LEN = 1500


def _try_js_challenge(resp: requests.Response, session: requests.Session,
                      url: str, headers: dict) -> requests.Response | None:
    """Если ответ — JS challenge с defaultHash, ставит cookie и повторяет запрос.
    Возвращает новый Response или None если это не challenge.
    """
    if len(resp.text) > _CHALLENGE_MAX_LEN:
        return None
    m = _JS_CHALLENGE_RE.search(resp.text)
    if not m:
        return None
    hash_val = m.group(1)
    domain = _urlparse(url).netloc
    session.cookies.set("challenge_passed", hash_val, domain=domain, path="/")
    console.log(f"[yellow]⚡ JS challenge[/yellow] → cookie set, retry: [dim]{url[:80]}[/dim]")
    return session.get(url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True)


# ── Получение метаданных страницы ────────────────────────────────────────────
def _extract_json_ld(soup: BeautifulSoup) -> dict:
    """Ищет первый <script type="application/ld+json"> и возвращает распарсенный dict.
    Если тегов несколько — возвращает первый с полем 'name' или 'description'.
    """
    import json
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
            # data может быть списком
            if isinstance(data, list):
                data = next((d for d in data if isinstance(d, dict)), {})
            if isinstance(data, dict) and ("name" in data or "description" in data):
                return data
        except (ValueError, TypeError):
            continue
    return {}


def _extract_description(soup: BeautifulSoup) -> str | None:
    """Извлекает описание страницы.
    Порядок приоритета: og:description → meta description → JSON-LD description → H1 → первый <p>.
    """
    for attr, name in [("property", "og:description"), ("name", "description")]:
        tag = soup.find("meta", attrs={attr: name})
        if tag and tag.get("content"):
            desc = tag["content"].strip()
            if desc:
                return desc

    ld = _extract_json_ld(soup)
    if ld.get("description"):
        return ld["description"].strip()

    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(strip=True)

    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 40:
            return text[:300]

    return None


def fetch_page_meta(url: str) -> dict:
    """Загружает страницу и возвращает {"title": str|None, "description": str|None}.
    Перед запросом делает случайную паузу.
    При ReadTimeout / ConnectionError — экспоненциальный backoff.
    """
    _polite_delay()

    attempt = 0
    while True:
        try:
            hdrs = _random_headers()
            resp = _session.get(
                url,
                headers=hdrs,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()

            # JS challenge bypass (anti-bot cookie)
            resp2 = _try_js_challenge(resp, _session, url, hdrs)
            if resp2 is not None:
                resp2.raise_for_status()
                resp = resp2

            soup = BeautifulSoup(resp.text, "html.parser")

            title = soup.title.string.strip() if soup.title and soup.title.string else None
            if not title:
                og_title = soup.find("meta", attrs={"property": "og:title"})
                if og_title and og_title.get("content"):
                    title = og_title["content"].strip()
            if not title:
                ld = _extract_json_ld(soup)
                if ld.get("name"):
                    title = ld["name"].strip()

            description = _extract_description(soup)
            return {"title": title, "description": description}

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


def fetch_title(url: str) -> str | None:
    """Обёртка для обратной совместимости. Возвращает только title."""
    return fetch_page_meta(url)["title"]


# ── Вспомогательные функции параллельного режима ─────────────────────────────
def _interleave_by_domain(urls: list[str]) -> list[str]:
    """Round-robin по доменам: habr1, github1, medium1, habr2, github2, ...
    Гарантирует что два воркера никогда не стартуют с одного домена одновременно.
    """
    groups: dict[str, list[str]] = defaultdict(list)
    for url in urls:
        domain = _urlparse(url).netloc.lower().removeprefix("www.")
        groups[domain].append(url)
    result: list[str] = []
    queues = list(groups.values())
    while any(queues):
        for q in queues:
            if q:
                result.append(q.pop(0))
    return result


def _fetch_one(url: str) -> tuple[str, str | None, str | None, str | None, int | None]:
    """Загружает один URL. Возвращает (url, title, description, error_msg, error_code).
    error_code — HTTP-статус (404, 503 и т.п.) или None для сетевых ошибок.
    """
    try:
        meta = fetch_page_meta(url)
        return url, meta["title"], meta["description"], None, None
    except requests.exceptions.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else None
        return url, None, None, str(exc), code
    except Exception as exc:
        return url, None, None, str(exc), None


def _process_parallel(pending: list[str], workers: int, verbose: bool) -> tuple[int, int]:
    """Параллельная обработка с round-robin по доменам, Rich progress."""
    ordered = _interleave_by_domain(pending)
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
        task = progress.add_task("Обработка...", total=len(ordered))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futs = {executor.submit(_fetch_one, url): url for url in ordered}
            try:
                for fut in as_completed(futs):
                    url, title, description, error, error_code = fut.result()
                    if error:
                        update_url(url, status="error", error=error, error_code=error_code)
                        error_count += 1
                        if verbose:
                            code_str = f" [HTTP {error_code}]" if error_code else ""
                            console.log(f"[red]ERR{code_str}[/red] {error}")
                    else:
                        update_url(url, status="done", title=title, description=description)
                        done_count += 1
                        if verbose:
                            console.log(f"[green]OK[/green] {title or '—'}")
                    progress.advance(task)
            except KeyboardInterrupt:
                console.print("\n[yellow]Прерывание по Ctrl+C...[/yellow]")

    return done_count, error_count


def _process_parallel_plain(pending: list[str], workers: int, verbose: bool) -> tuple[int, int]:
    """Параллельная обработка без Rich progress (--no-progress)."""
    ordered = _interleave_by_domain(pending)
    done_count = 0
    error_count = 0
    total = len(ordered)
    completed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futs = {executor.submit(_fetch_one, url): url for url in ordered}
        try:
            for fut in as_completed(futs):
                url, title, description, error, error_code = fut.result()
                completed += 1
                if error:
                    update_url(url, status="error", error=error, error_code=error_code)
                    error_count += 1
                    code_str = f" [HTTP {error_code}]" if error_code else ""
                    print(f"[{completed}/{total}] ERR{code_str} {url}: {error}", flush=True)
                else:
                    update_url(url, status="done", title=title, description=description)
                    done_count += 1
                    if verbose:
                        print(f"[{completed}/{total}] OK {title or '—'}", flush=True)
                    else:
                        print(f"[{completed}/{total}] {url}", flush=True)
        except KeyboardInterrupt:
            print("\nПрерывание по Ctrl+C...")

    return done_count, error_count


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
            meta = fetch_page_meta(url)
            update_url(url, status="done", title=meta["title"], description=meta["description"])
            done_count += 1
            if verbose:
                print(f"  OK: {meta['title']}")
        except requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            error_msg = str(e)
            update_url(url, status="error", error=error_msg, error_code=code)
            error_count += 1
            print(f"  ERROR [HTTP {code}]: {error_msg}")
        except Exception as e:
            error_msg = str(e)
            update_url(url, status="error", error=error_msg, error_code=None)
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
                meta = fetch_page_meta(url)
                update_url(url, status="done", title=meta["title"], description=meta["description"])
                done_count += 1
                if verbose:
                    console.log(f"[green]OK[/green] {meta['title'] or '—'}")
            except requests.exceptions.HTTPError as e:
                code = e.response.status_code if e.response is not None else None
                error_msg = str(e)
                update_url(url, status="error", error=error_msg, error_code=code)
                error_count += 1
                if verbose:
                    console.log(f"[red]ERR [HTTP {code}][/red] {error_msg}")
            except Exception as e:
                error_msg = str(e)
                update_url(url, status="error", error=error_msg, error_code=None)
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
    workers: int = 1,
) -> None:
    """
    limit       — обработать не более N URL
    no_progress — plain вывод вместо rich progress bar
    verbose     — показывать заголовок / ошибку по каждому URL
    urls        — список конкретных URL (если None — берёт pending из БД)
    domain      — фильтровать только URL указанного домена
    workers     — кол-во параллельных потоков (round-robin по доменам)
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

    if workers > 1:
        if no_progress:
            done_count, error_count = _process_parallel_plain(pending, workers, verbose)
        else:
            done_count, error_count = _process_parallel(pending, workers, verbose)
    elif no_progress:
        done_count, error_count = _process_plain(pending, verbose)
    else:
        done_count, error_count = _process_rich(pending, verbose)

    _print_summary(done_count, error_count, domain=domain)
    console.print(Panel("[green]Готово.[/green]"))


def refetch_descriptions(
    limit: int | None = None,
    no_progress: bool = False,
    verbose: bool = False,
    domain: str | None = None,
    workers: int = 1,
) -> None:
    """Дозаполняет description для done-записей, у которых он пустой.
    Не меняет status, title или другие поля.
    """
    from urllib.parse import urlparse

    console.print(Panel("[bold cyan]Step 2 — Дозаполнение description[/bold cyan]"))

    init_db()

    urls = get_done_without_description()

    if domain:
        domain_norm = domain.lower().removeprefix("www.")
        urls = [
            u for u in urls
            if urlparse(u).netloc.lower().removeprefix("www.") == domain_norm
        ]
        console.print(f"Фильтр по домену: [cyan]{domain}[/cyan] → [bold]{len(urls)}[/bold] URL")

    if limit is not None:
        urls = urls[:limit]

    if not urls:
        console.print("[green]Нет URL без description.[/green]")
        return

    console.print(f"Без description: [bold yellow]{len(urls)}[/bold yellow] URL\n")

    got_count = 0    # реально записано (description != None)
    no_tag_count = 0  # страница получена, но тег отсутствует
    error_count = 0   # HTTP-ошибка / таймаут / исключение

    def _process_one(url: str) -> tuple[str, str | None, str | None]:
        """Возвращает (url, description, error_msg).
        description=None означает «страница доступна, но тег не найден».
        """
        try:
            meta = fetch_page_meta(url)
            return url, meta["description"], None
        except Exception as exc:
            return url, None, str(exc)

    def _handle_result(url: str, description: str | None, error: str | None) -> None:
        nonlocal got_count, no_tag_count, error_count
        if error:
            error_count += 1
            return
        if description:
            update_description(url, description)
            got_count += 1
        else:
            no_tag_count += 1

    if workers > 1:
        ordered = _interleave_by_domain(urls)
        if no_progress:
            total = len(ordered)
            completed = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futs = {executor.submit(_process_one, u): u for u in ordered}
                try:
                    for fut in as_completed(futs):
                        url, description, error = fut.result()
                        completed += 1
                        _handle_result(url, description, error)
                        if error:
                            print(f"[{completed}/{total}] ERR {url}: {error}", flush=True)
                        elif verbose:
                            short = (description or "")[:80]
                            print(f"[{completed}/{total}] {'OK ' if description else 'NO_TAG'} {short or url}", flush=True)
                        else:
                            print(f"[{completed}/{total}] {url}", flush=True)
                except KeyboardInterrupt:
                    print("\nПрерывание по Ctrl+C...")
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
                task = progress.add_task("Дозаполнение...", total=len(ordered))
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futs = {executor.submit(_process_one, u): u for u in ordered}
                    try:
                        for fut in as_completed(futs):
                            url, description, error = fut.result()
                            _handle_result(url, description, error)
                            if verbose:
                                if error:
                                    console.log(f"[red]ERR[/red] {error}")
                                elif description:
                                    console.log(f"[green]OK[/green] {description[:80]}")
                                else:
                                    console.log(f"[dim]NO_TAG[/dim] {url[:80]}")
                            progress.advance(task)
                    except KeyboardInterrupt:
                        console.print("\n[yellow]Прерывание по Ctrl+C...[/yellow]")
    else:
        total = len(urls)
        if no_progress:
            for i, url in enumerate(urls, 1):
                print(f"[{i}/{total}] {url}", flush=True)
                url_, description, error = _process_one(url)
                _handle_result(url_, description, error)
                if error:
                    print(f"  ERR: {error}")
                elif verbose:
                    print(f"  {'OK' if description else 'NO_TAG'}: {(description or '')[:80] or '—'}")
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
                task = progress.add_task("Дозаполнение...", total=total)
                for url in urls:
                    short_url = url[:60] + "…" if len(url) > 60 else url
                    progress.update(task, description=f"[dim]{short_url}[/dim]")
                    _, description, error = _process_one(url)
                    _handle_result(url, description, error)
                    if verbose:
                        if error:
                            console.log(f"[red]ERR[/red] {error}")
                        elif description:
                            console.log(f"[green]OK[/green] {description[:80]}")
                        else:
                            console.log(f"[dim]NO_TAG[/dim] {url[:80]}")
                    progress.advance(task)

    summary = Table(title="Итоги дозаполнения", show_header=True, header_style="bold magenta")
    summary.add_column("Статус", style="cyan")
    summary.add_column("Кол-во", justify="right", style="bold")
    summary.add_row("[green]Записано description[/green]", f"[green]{got_count}[/green]")
    summary.add_row("[dim]Страница OK, тег отсутствует[/dim]", f"[dim]{no_tag_count}[/dim]")
    summary.add_row("[red]Ошибка HTTP / таймаут[/red]", f"[red]{error_count}[/red]")
    summary.add_row("Итого обработано", str(got_count + no_tag_count + error_count))
    console.print(summary)
    console.print(Panel("[green]Готово.[/green]"))


if __name__ == "__main__":
    main()
