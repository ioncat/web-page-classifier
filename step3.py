import csv
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

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

from db import add_tags, get_done_unclassified, get_tags, init_db, init_tags_schema, set_category
from config.settings import (
    BAD_TAG_PREFIXES,
    BAD_TAG_WORDS,
    DRY_RUN_LOG,
    MAX_CONSECUTIVE_CONN_ERRORS,
    NUM_PREDICT_PER_URL,
    NUM_PREDICT_SINGLE,
    OLLAMA_HOST,
    OLLAMA_REQUEST_TIMEOUT,
    OLLAMA_TEMPERATURE,
    TAG_MAX_LEN,
    TAG_MAX_WORDS,
)

console = Console()

# ── Клиент Ollama ─────────────────────────────────────────────────────────────
def _build_client() -> ollama.Client:
    return ollama.Client(host=OLLAMA_HOST, timeout=OLLAMA_REQUEST_TIMEOUT)


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
from config.prompts import BATCH_HEADER, BATCH_ITEM, DESCRIPTION_LINE, HINTS_LINE, SINGLE


def _build_prompt(title: str, url: str, hints: list[str], description: str | None = None) -> str:
    hints_line = HINTS_LINE.format(hints=", ".join(hints)) + "\n" if hints else ""
    desc_line = DESCRIPTION_LINE.format(description=description[:200]) if description else ""
    return SINGLE.format(url=url, title=title or "(no title)", hints_line=hints_line, description_line=desc_line)


def _build_batch_prompt(items: list[dict], hints: list[str]) -> str:
    """Промпт для пакетной классификации N URL за один запрос к модели."""
    hints_line = HINTS_LINE.format(hints=", ".join(hints)) + "\n\n" if hints else ""
    lines = [BATCH_HEADER.format(hints_line=hints_line), ""]
    for i, item in enumerate(items, 1):
        title = item["title"] or "(no title)"
        desc = item.get("description")
        desc_suffix = f"\n   {DESCRIPTION_LINE.format(description=desc[:150])}" if desc else ""
        lines.append(BATCH_ITEM.format(i=i, url=item["url"], title=title) + desc_suffix)
    return "\n".join(lines)


def classify_url(
    client: ollama.Client,
    model: str,
    url: str,
    title: str,
    hints: list[str],
    no_think: bool = False,
    description: str | None = None,
) -> str:
    """Запрашивает у Ollama теги для одного URL. Возвращает строку тегов через запятую.

    Исключения:
        ollama.ResponseError  — API-ошибка (неверная модель, ошибка сервера и т.п.)
        ValueError            — модель вернула пустой ответ
        Exception             — ошибка соединения (Ollama недоступна)
    """
    prompt = _build_prompt(title or "", url, hints, description=description)
    options: dict = {"num_predict": NUM_PREDICT_SINGLE, "temperature": OLLAMA_TEMPERATURE}
    if no_think:
        options["think"] = False
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options=options,
    )
    raw = resp.message.content.strip()

    first_line = next((ln for ln in raw.splitlines() if ln.strip()), "")
    # Берём всю строку как одну категорию (убираем кавычки/пунктуацию по краям)
    tag = first_line.strip().strip("\"'.,;:-")
    tags = [tag] if tag else []

    if not tags:
        raise ValueError(f"Модель вернула пустой ответ: {raw!r}")

    return ", ".join(tags)


def classify_batch(
    client: ollama.Client,
    model: str,
    items: list[dict],   # каждый: {"url": str, "title": str | None}
    hints: list[str],
    no_think: bool = False,
) -> list[str | None]:
    """Классифицирует пакет URL за один запрос к модели.

    Возвращает список строк тегов или None (если парсинг ответа не удался
    для данной позиции). Для None-элементов вызывающая сторона делает fallback
    на classify_url.
    """
    prompt = _build_batch_prompt(items, hints)
    options: dict = {"num_predict": len(items) * NUM_PREDICT_PER_URL, "temperature": OLLAMA_TEMPERATURE}
    if no_think:
        options["think"] = False
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        options=options,
    )
    raw = resp.message.content.strip()

    results: list[str | None] = [None] * len(items)
    for line in raw.splitlines():
        m = re.match(r"^(\d+)[.)]\s+(.+)$", line.strip())
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < len(items):
                tag = m.group(2).strip().strip("\"'.,;:-")
                if tag:
                    results[idx] = tag
    return results


# ── Обработка одного URL с разделением типов ошибок ───────────────────────────
class _OllamaDown(Exception):
    """Сигнал прерывания цикла — Ollama недоступна."""


def _process_one(
    client: ollama.Client,
    model: str,
    url: str,
    title: str,
    hints: list[str],
    consecutive_conn_errors: int,
    no_think: bool = False,
    description: str | None = None,
) -> tuple[str | None, int]:
    """Классифицирует один URL. Возвращает (category, новый consecutive_conn_errors).

    Поднимает _OllamaDown, если достигнут лимит подряд идущих ошибок соединения.
    """
    try:
        category = classify_url(client, model, url, title, hints, no_think=no_think, description=description)
        return category, 0

    except ollama.ResponseError as exc:
        msg = f"ResponseError [{exc.status_code}]: {exc.error}"
        raise RuntimeError(msg) from exc

    except ValueError:
        raise

    except Exception as exc:
        consecutive_conn_errors += 1
        if consecutive_conn_errors >= MAX_CONSECUTIVE_CONN_ERRORS:
            raise _OllamaDown(
                f"Ollama недоступна ({MAX_CONSECUTIVE_CONN_ERRORS} ошибок подряд): {exc}"
            ) from exc
        raise RuntimeError(f"Ошибка соединения: {exc}") from exc


# ── Обновление справочника тегов ─────────────────────────────────────────────
def _is_valid_tag(tag: str) -> bool:
    """Отфильтровывает мусор: длинные строки, URL, предложения."""
    if len(tag) > TAG_MAX_LEN:
        return False
    low = tag.lower()
    if any(low.startswith(p) for p in BAD_TAG_PREFIXES):
        return False
    if any(w in low for w in BAD_TAG_WORDS):
        return False
    if len(tag.split()) > TAG_MAX_WORDS:
        return False
    return True


def _update_hints(category: str, hints: list[str]) -> int:
    """Добавляет теги из category в справочник и в список hints текущего запуска.
    Возвращает количество новых тегов (не было в справочнике ранее).
    """
    new_tags = [t.strip() for t in category.split(",") if t.strip() and _is_valid_tag(t.strip())]
    added, _ = add_tags(new_tags)
    for tag in new_tags:
        if tag not in hints:
            hints.append(tag)
    return added


# ── Вывод итогов ──────────────────────────────────────────────────────────────
def _print_summary(done_count: int, error_count: int, aborted: bool = False, elapsed: float = 0.0) -> None:
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
    if aborted:
        summary.add_row("[yellow]Прервано[/yellow]", "[yellow]Ollama недоступна[/yellow]")
    if elapsed > 0:
        mins, secs = divmod(int(elapsed), 60)
        time_str = f"{mins}м {secs}с" if mins else f"{secs}с"
        total = done_count + error_count
        speed = f"  [dim]({total / elapsed:.1f} URL/с)[/dim]" if elapsed > 0 and total > 0 else ""
        summary.add_row("[dim]Время[/dim]", f"[dim]{time_str}{speed}[/dim]")
    console.print(summary)


# ── Dry-run лог ───────────────────────────────────────────────────────────────
_DRY_RUN_LOG_FIELDS = ["date", "model", "elapsed_sec", "url_per_sec", "processed", "config"]


def _append_dryrun_log(
    model: str,
    elapsed: float,
    classified: int,
    limit: int | None,
    batch: int,
    workers: int,
) -> None:
    log_path = Path(DRY_RUN_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not log_path.exists()
    cfg_parts = [f"limit={limit or 'all'}"]
    if batch > 1:
        cfg_parts.append(f"batch={batch}")
    if workers > 1:
        cfg_parts.append(f"workers={workers}")
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_DRY_RUN_LOG_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerow({
            "date":        datetime.now().strftime("%Y-%m-%d %H:%M"),
            "model":       model,
            "elapsed_sec": f"{elapsed:.1f}",
            "url_per_sec": f"{classified / elapsed:.2f}" if elapsed > 0 and classified > 0 else "0",
            "processed":   classified,
            "config":      " ".join(cfg_parts),
        })
    console.print(f"[dim]Dry-run лог → {log_path}[/dim]")


# ── Точка входа ───────────────────────────────────────────────────────────────
def main(
    model: str | None = None,
    limit: int | None = None,
    list_models_flag: bool = False,
    no_progress: bool = False,
    verbose: bool = False,
    workers: int = 1,
    batch: int = 1,
    no_think: bool = False,
    dry_run: bool = False,
    no_description: bool = False,
) -> None:
    """
    model            — имя модели Ollama; если None — интерактивный выбор
    limit            — обработать не более N URL
    list_models_flag — показать список моделей и выйти
    no_progress      — plain вывод без rich progress bar
    verbose          — показывать присвоенные теги по каждому URL
    workers          — кол-во параллельных потоков к Ollama
    batch            — кол-во URL в одном запросе к модели (батчинг)
    no_think         — отключить thinking-режим (для qwen3, deepseek-r1 и др.)
    dry_run          — не писать в БД, только показать результаты классификации
    no_description   — не передавать og:description в промпт (быстрее, меньше токенов)
    """
    _t0 = time.perf_counter()

    console.print(Panel("[bold cyan]Step 3 — Классификация через Ollama LLM[/bold cyan]"))

    if dry_run:
        console.print("[yellow bold]⚠ dry-run:[/yellow bold] [dim]классификация без записи в БД[/dim]\n")

    # verbose всегда включён в dry-run — иначе не видно результатов
    _verbose = verbose or dry_run

    # Wrappers: в dry_run режиме не пишем в БД
    def _sc(url: str, cat: str) -> None:
        if not dry_run:
            set_category(url, cat, model=model)

    def _uh(cat: str, h: list) -> int:
        if not dry_run:
            return _update_hints(cat, h)
        return 0

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
        if model not in available:
            console.print(
                f"[yellow]Предупреждение:[/yellow] модель [bold]{model}[/bold] "
                "не найдена в Ollama. Попытка использовать всё равно..."
            )
        else:
            console.print(f"Модель: [bold]{model}[/bold]\n")
    else:
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
    if no_description:
        rows = [{**r, "description": None} for r in rows]

    if not rows:
        console.print(
            "\n[green]Нет URL для классификации.[/green] "
            "Все обработанные записи уже имеют категорию."
        )
        return

    total_urls = len(rows)
    mode_parts = []
    if workers > 1:
        mode_parts.append(f"{workers} потока")
    if batch > 1:
        mode_parts.append(f"пакет {batch} URL/запрос")
    mode_str = f" [dim]({', '.join(mode_parts)})[/dim]" if mode_parts else ""
    console.print(f"\nК классификации: [bold yellow]{total_urls}[/bold yellow] URL{mode_str}\n")

    # ── Вспомогательная: разбивка на куски ────────────────────────────────────
    def _iter_chunks(lst: list, n: int):
        for i in range(0, len(lst), n):
            yield lst[i : i + n]

    # ── Обработка ─────────────────────────────────────────────────────────────
    done_count  = 0
    error_count = 0
    aborted     = False

    if workers > 1:
        # ── Параллельный режим (ThreadPoolExecutor) ────────────────────────────
        _abort  = threading.Event()
        _h_lock = threading.Lock()
        _ce_cnt = [0]
        _ce_lk  = threading.Lock()

        if batch > 1:
            # ── Параллельный пакетный режим ───────────────────────────────────
            def _worker_batch(chunk: list[dict]):
                if _abort.is_set():
                    return "skip", chunk, []
                hints_snap = list(hints)
                try:
                    cats = classify_batch(client, model, chunk, hints_snap, no_think=no_think)
                except Exception as exc:
                    with _ce_lk:
                        _ce_cnt[0] += 1
                        if _ce_cnt[0] >= MAX_CONSECUTIVE_CONN_ERRORS:
                            _abort.set()
                    return "conn_err", chunk, str(exc)

                results = []
                for row, cat in zip(chunk, cats):
                    if cat is None:
                        # Fallback: одиночный запрос для этого URL
                        try:
                            cat = classify_url(
                                client, model, row["url"], row["title"] or "", hints_snap,
                                no_think=no_think, description=row.get("description"),
                            )
                        except Exception:
                            results.append((row["url"], None))
                            continue
                    _sc(row["url"], cat)
                    with _h_lock:
                        _uh(cat, hints)
                    results.append((row["url"], cat))
                with _ce_lk:
                    _ce_cnt[0] = 0
                return "ok", chunk, results

            chunks = list(_iter_chunks(rows, batch))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_worker_batch, c) for c in chunks]
                total_chunks = len(futs)

                try:
                    if no_progress:
                        for i, fut in enumerate(as_completed(futs), 1):
                            status, chunk, data = fut.result()
                            n = len(chunk)
                            if status == "ok":
                                ok_n = sum(1 for _, c in data if c)
                                done_count  += ok_n
                                error_count += n - ok_n
                                print(
                                    f"[batch {i}/{total_chunks}] OK:{ok_n} ERR:{n - ok_n}",
                                    flush=True,
                                )
                                if _verbose:
                                    for url, cat in data:
                                        status_str = "OK " if cat else "ERR"
                                        print(f"  {status_str} {url[:60]}" + (f"\n  {cat}" if cat else ""))
                            elif status != "skip":
                                error_count += n
                                print(f"[batch {i}/{total_chunks}] ERR [{status}] {data}", flush=True)
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
                            task = progress.add_task(
                                f"[dim]workers={workers} batch={batch}[/dim]",
                                total=total_urls,
                            )
                            for fut in as_completed(futs):
                                status, chunk, data = fut.result()
                                n = len(chunk)
                                if status == "ok":
                                    ok_n = sum(1 for _, c in data if c)
                                    done_count  += ok_n
                                    error_count += n - ok_n
                                    if _verbose:
                                        for url, cat in data:
                                            if cat:
                                                console.log(f"[green]OK[/green] {cat}")
                                            else:
                                                console.log(f"[red]ERR[/red] parse failed: {url[:50]}")
                                elif status != "skip":
                                    error_count += n
                                    if _verbose:
                                        console.log(f"[red]ERR[/red] [{status}] {data}")
                                progress.advance(task, n)
                except KeyboardInterrupt:
                    _abort.set()
                    for f in futs:
                        f.cancel()
                    console.print("\n[yellow]Прерывание по Ctrl+C — ожидаем текущих запросов...[/yellow]")
                    aborted = True

        else:
            # ── Параллельный одиночный режим ──────────────────────────────────
            def _worker(row: dict):
                if _abort.is_set():
                    return "skip", row["url"], None
                url, title = row["url"], row["title"] or ""
                try:
                    cat = classify_url(client, model, url, title, list(hints), no_think=no_think,
                                       description=row.get("description"))
                    _sc(url, cat)
                    with _h_lock:
                        _uh(cat, hints)
                    with _ce_lk:
                        _ce_cnt[0] = 0
                    return "ok", url, cat
                except ollama.ResponseError as exc:
                    return "api_err", url, f"ResponseError [{exc.status_code}]: {exc.error}"
                except ValueError as exc:
                    return "empty", url, str(exc)
                except Exception as exc:
                    with _ce_lk:
                        _ce_cnt[0] += 1
                        if _ce_cnt[0] >= MAX_CONSECUTIVE_CONN_ERRORS:
                            _abort.set()
                    return "conn_err", url, str(exc)

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futs = [pool.submit(_worker, r) for r in rows]

                try:
                    if no_progress:
                        total = len(futs)
                        for i, fut in enumerate(as_completed(futs), 1):
                            status, url, data = fut.result()
                            short = url[:70]
                            if status == "ok":
                                done_count += 1
                                line = f"[{i}/{total}] OK  {short}"
                                if _verbose:
                                    line += f"\n  {data}"
                                print(line, flush=True)
                            elif status != "skip":
                                error_count += 1
                                print(f"[{i}/{total}] ERR [{status}] {short}\n  {data}", flush=True)
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
                            task = progress.add_task(
                                f"[dim]workers={workers}[/dim]", total=len(rows)
                            )
                            for fut in as_completed(futs):
                                status, url, data = fut.result()
                                if status == "ok":
                                    done_count += 1
                                    if _verbose:
                                        console.log(f"[green]OK[/green] {data}")
                                elif status != "skip":
                                    error_count += 1
                                    if _verbose:
                                        console.log(f"[red]ERR[/red] [{status}] {data}")
                                progress.advance(task)
                except KeyboardInterrupt:
                    _abort.set()
                    for f in futs:
                        f.cancel()
                    console.print("\n[yellow]Прерывание по Ctrl+C — ожидаем текущих запросов...[/yellow]")
                    aborted = True

        aborted = aborted or _abort.is_set()
        if aborted:
            console.print("[bold red]Прерывание:[/bold red] Ollama недоступна")

    else:
        # ── Последовательный режим (workers == 1) ──────────────────────────────
        conn_errors = 0

        def _handle_error(err_msg: str, is_plain: bool) -> None:
            nonlocal error_count
            error_count += 1
            if is_plain:
                print(f"  ERROR: {err_msg}")
            elif _verbose:
                console.log(f"[red]ERR[/red] {err_msg}")

        if batch > 1:
            # ── Последовательный пакетный режим ──────────────────────────────
            chunks = list(_iter_chunks(rows, batch))
            total_chunks = len(chunks)

            if no_progress:
                for ci, chunk in enumerate(chunks, 1):
                    print(f"[batch {ci}/{total_chunks}, {len(chunk)} URL]", flush=True)
                    try:
                        cats = classify_batch(client, model, chunk, hints, no_think=no_think)
                        for row, cat in zip(chunk, cats):
                            url, title = row["url"], row["title"] or ""
                            desc = row.get("description")
                            if cat is None:
                                # Fallback: одиночный запрос
                                try:
                                    cat, conn_errors = _process_one(
                                        client, model, url, title, hints, conn_errors,
                                        no_think=no_think, description=desc,
                                    )
                                    _sc(url, cat)
                                    _uh(cat, hints)
                                    done_count += 1
                                    if _verbose:
                                        print(f"  OK(fb) {url[:60]}\n    {cat}")
                                except _OllamaDown as exc:
                                    console.print(f"\n[bold red]Прерывание:[/bold red] {exc}")
                                    aborted = True
                                    break
                                except Exception as exc:
                                    _handle_error(str(exc), is_plain=True)
                            else:
                                _sc(url, cat)
                                _uh(cat, hints)
                                done_count += 1
                                if _verbose:
                                    print(f"  OK  {url[:60]}\n    {cat}")
                        if aborted:
                            break
                    except _OllamaDown as exc:
                        console.print(f"\n[bold red]Прерывание:[/bold red] {exc}")
                        aborted = True
                        break
                    except Exception as exc:
                        # Весь батч упал — fallback на одиночные запросы
                        print(f"  BATCH ERR: {exc} → fallback", flush=True)
                        for row in chunk:
                            url, title = row["url"], row["title"] or ""
                            desc = row.get("description")
                            try:
                                cat, conn_errors = _process_one(
                                    client, model, url, title, hints, conn_errors,
                                    no_think=no_think, description=desc,
                                )
                                _sc(url, cat)
                                _uh(cat, hints)
                                done_count += 1
                                if _verbose:
                                    print(f"  OK  {url[:60]}\n    {cat}")
                            except _OllamaDown as exc2:
                                console.print(f"\n[bold red]Прерывание:[/bold red] {exc2}")
                                aborted = True
                                break
                            except Exception as exc2:
                                _handle_error(str(exc2), is_plain=True)
                        if aborted:
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
                    task = progress.add_task("Классификация...", total=total_urls)

                    for ci, chunk in enumerate(chunks, 1):
                        progress.update(
                            task, description=f"[dim]batch {ci}/{total_chunks}[/dim]"
                        )
                        try:
                            cats = classify_batch(client, model, chunk, hints, no_think=no_think)
                            for row, cat in zip(chunk, cats):
                                url, title = row["url"], row["title"] or ""
                                desc = row.get("description")
                                if cat is None:
                                    try:
                                        cat, conn_errors = _process_one(
                                            client, model, url, title, hints, conn_errors,
                                            no_think=no_think, description=desc,
                                        )
                                        _sc(url, cat)
                                        _uh(cat, hints)
                                        done_count += 1
                                        if _verbose:
                                            console.log(f"[green]OK(fb)[/green] {cat}")
                                    except _OllamaDown as exc:
                                        console.log(f"[bold red]Прерывание:[/bold red] {exc}")
                                        aborted = True
                                        break
                                    except Exception as exc:
                                        _handle_error(str(exc), is_plain=False)
                                else:
                                    _sc(url, cat)
                                    _uh(cat, hints)
                                    done_count += 1
                                    if _verbose:
                                        console.log(f"[green]OK[/green] {cat}")
                                progress.advance(task)
                            if aborted:
                                break
                        except _OllamaDown as exc:
                            console.log(f"[bold red]Прерывание:[/bold red] {exc}")
                            aborted = True
                            break
                        except Exception as exc:
                            # Весь батч упал — fallback на одиночные запросы
                            if _verbose:
                                console.log(f"[yellow]BATCH ERR[/yellow] {exc} → fallback")
                            for row in chunk:
                                url, title = row["url"], row["title"] or ""
                                desc = row.get("description")
                                try:
                                    cat, conn_errors = _process_one(
                                        client, model, url, title, hints, conn_errors,
                                        no_think=no_think, description=desc,
                                    )
                                    _sc(url, cat)
                                    _uh(cat, hints)
                                    done_count += 1
                                    if _verbose:
                                        console.log(f"[green]OK(fb)[/green] {cat}")
                                except _OllamaDown as exc2:
                                    console.log(f"[bold red]Прерывание:[/bold red] {exc2}")
                                    aborted = True
                                    break
                                except Exception as exc2:
                                    _handle_error(str(exc2), is_plain=False)
                                progress.advance(task)
                            if aborted:
                                break

        else:
            # ── Последовательный одиночный режим ─────────────────────────────
            if no_progress:
                total = len(rows)
                for i, row in enumerate(rows, 1):
                    url, title = row["url"], row["title"] or ""
                    desc = row.get("description")
                    print(f"[{i}/{total}] {url}", flush=True)
                    try:
                        category, conn_errors = _process_one(
                            client, model, url, title, hints, conn_errors,
                            no_think=no_think, description=desc,
                        )
                        _sc(url, category)
                        new_in_dict = _uh(category, hints)
                        done_count += 1
                        if _verbose:
                            suffix = f" (+{new_in_dict} в справочник)" if new_in_dict else ""
                            print(f"  Tags: {category}{suffix}")
                    except _OllamaDown as exc:
                        console.print(f"\n[bold red]Прерывание:[/bold red] {exc}")
                        aborted = True
                        break
                    except Exception as exc:
                        _handle_error(str(exc), is_plain=True)
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
                        desc = row.get("description")
                        short_url = url[:60] + "…" if len(url) > 60 else url
                        progress.update(task, description=f"[dim]{short_url}[/dim]")

                        try:
                            category, conn_errors = _process_one(
                                client, model, url, title, hints, conn_errors,
                                no_think=no_think, description=desc,
                            )
                            _sc(url, category)
                            new_in_dict = _uh(category, hints)
                            done_count += 1
                            if _verbose:
                                suffix = (
                                    f" [dim](+{new_in_dict} в справочник)[/dim]"
                                    if new_in_dict
                                    else ""
                                )
                                console.log(f"[green]OK[/green] {category}{suffix}")
                        except _OllamaDown as exc:
                            console.log(f"[bold red]Прерывание:[/bold red] {exc}")
                            aborted = True
                            break
                        except Exception as exc:
                            _handle_error(str(exc), is_plain=False)

                        progress.advance(task)

    # ── Итоги ─────────────────────────────────────────────────────────────────
    elapsed = time.perf_counter() - _t0
    _print_summary(done_count, error_count, aborted=aborted, elapsed=elapsed)
    if dry_run:
        _append_dryrun_log(model or "auto", elapsed, done_count, limit, batch, workers)
    if aborted:
        console.print(
            "[dim]Запустите снова когда Ollama будет доступна — "
            "уже классифицированные URL будут пропущены.[/dim]"
        )
    console.print(
        Panel("[green]Готово.[/green]" if not aborted else "[yellow]Завершено с ошибками.[/yellow]")
    )


if __name__ == "__main__":
    main()
