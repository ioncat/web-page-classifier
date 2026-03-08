import argparse

from rich.console import Console
from rich.rule import Rule

import compare
import step1
import step2
import step3
from db import (
    accept_model as db_accept_model,
    add_tags,
    clear_model_results,
    clear_tags,
    init_compare_schema,
    init_db,
    init_tags_schema,
    insert_urls,
    reset_all_to_pending,
    reset_categories,
    reset_errors_to_pending,
    set_url_pending,
    sync_tags_from_categories,
)

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="URL Parser Pipeline — импорт, парсинг и классификация ссылок",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""примеры:
  python main.py                                         полный пайплайн (step1 + step2)
  python main.py --only-parse                            только парсинг (step2)
  python main.py --only-classify                         только классификация (step3)
  python main.py --only-classify --model llama3          классификация конкретной моделью
  python main.py --list-models                           показать доступные модели Ollama
  python main.py --add-tags python,ai,tutorial           добавить теги в справочник
  python main.py --sync-tags                             импортировать теги из category в справочник
  python main.py --re-tag                                сбросить категории и перетэггировать заново
  python main.py --re-tag --model mistral                то же, другой моделью
  python main.py --clear-tags                            очистить справочник тегов
  python main.py --only-parse --limit 50                 первые 50 pending URL
  python main.py --retry-failed                          повторить URL с ошибками
  python main.py --force                                 сбросить всё и начать заново
  python main.py --url https://example.com               обработать один URL
  python main.py --input links.txt                       другой входной файл
  python main.py --no-progress -v                        plain вывод + детали
  python main.py --only-classify --batch 10              пакетная классификация (10 URL/запрос)
  python main.py --only-classify --batch 10 --workers 4  батчинг + параллельность
  python main.py --domain habr.com                       только URL с habr.com
  python main.py --domain habr.com --retry-failed        повторить ошибки для домена
  python main.py --compare-models llama3 mistral          сравнить две модели (через пробел)
  python main.py --compare                               side-by-side таблица результатов
  python main.py --compare --export out.csv              + экспорт в CSV
  python main.py --accept-model mistral                  принять результаты модели как финальные
  python main.py --compare-clear                         очистить таблицу model_results
""",
    )

    # ── Step 1 / импорт ───────────────────────────────────────────────────────
    parser.add_argument(
        "--input",
        metavar="FILE",
        default="raw_links.txt",
        help="входной файл для step1 (по умолчанию: raw_links.txt)",
    )

    # ── Step 2 / парсинг ─────────────────────────────────────────────────────
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        default=None,
        help="обработать не более N URL в step2 / step3",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="сбросить все записи в pending и обработать заново",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        dest="retry_failed",
        help="повторить обработку URL с ошибками",
    )
    parser.add_argument(
        "--url",
        metavar="URL",
        default=None,
        help="добавить и обработать один конкретный URL (пропускает step1)",
    )
    parser.add_argument(
        "--domain",
        metavar="DOMAIN",
        default=None,
        help="обработать только URL указанного домена (напр. habr.com)",
    )

    # ── Step 3 / классификация ────────────────────────────────────────────────
    parser.add_argument(
        "--model",
        metavar="MODEL",
        default=None,
        help="модель Ollama для step3 (по умолчанию: первая доступная)",
    )
    parser.add_argument(
        "--list-models",
        action="store_true",
        dest="list_models",
        help="показать список доступных моделей Ollama и выйти",
    )
    parser.add_argument(
        "--add-tags",
        metavar="TAGS",
        default=None,
        dest="add_tags",
        help="добавить теги-подсказки в справочник (через запятую: тег1,тег2,...)",
    )
    parser.add_argument(
        "--sync-tags",
        action="store_true",
        dest="sync_tags",
        help="синхронизировать справочник из накопленных category в БД и выйти",
    )
    parser.add_argument(
        "--re-tag",
        action="store_true",
        dest="re_tag",
        help="сбросить category/tagged_by у всех done-URL и запустить step3 заново "
             "(справочник тегов сохраняется как подсказки)",
    )
    parser.add_argument(
        "--clear-tags",
        action="store_true",
        dest="clear_tags",
        help="очистить справочник тегов (таблицу tags) и выйти",
    )

    # ── Сравнение моделей ─────────────────────────────────────────────────────
    parser.add_argument(
        "--compare-models",
        metavar="MODEL",
        nargs="+",
        default=None,
        dest="compare_models",
        help="запустить несколько моделей и сохранить результаты для сравнения. "
             "Модели через пробел или запятую: llama3 mistral  /  llama3,mistral",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="показать side-by-side таблицу результатов сравнения моделей",
    )
    parser.add_argument(
        "--export",
        metavar="FILE",
        default=None,
        help="экспортировать результаты сравнения в CSV (используется вместе с --compare)",
    )
    parser.add_argument(
        "--accept-model",
        metavar="MODEL",
        default=None,
        dest="accept_model",
        help="принять результаты выбранной модели как финальные (копирует в urls.category)",
    )
    parser.add_argument(
        "--compare-clear",
        action="store_true",
        dest="compare_clear",
        help="очистить таблицу model_results (все результаты сравнения)",
    )

    # ── Управление пайплайном ─────────────────────────────────────────────────
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--only-import",
        action="store_true",
        dest="only_import",
        help="запустить только step1 (импорт ссылок в БД)",
    )
    mode_group.add_argument(
        "--only-parse",
        action="store_true",
        dest="only_parse",
        help="запустить только step2 (парсинг заголовков)",
    )
    mode_group.add_argument(
        "--only-classify",
        action="store_true",
        dest="only_classify",
        help="запустить только step3 (классификация через Ollama)",
    )

    # ── Вывод ─────────────────────────────────────────────────────────────────
    parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="отключить progress bar, plain вывод в консоль",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="показывать заголовок / теги / ошибку по каждому URL",
    )
    parser.add_argument(
        "--workers",
        type=int,
        metavar="N",
        default=1,
        help="кол-во параллельных запросов к Ollama (по умолчанию: 1). "
             "Для реального параллелизма также установите OLLAMA_NUM_PARALLEL=N перед ollama serve",
    )
    parser.add_argument(
        "--batch",
        type=int,
        metavar="N",
        default=1,
        help="кол-во URL в одном запросе к модели — батчинг (по умолчанию: 1). "
             "Увеличьте до 5–20 для лучшей утилизации GPU. "
             "Пример: --batch 10 --workers 4",
    )
    parser.add_argument(
        "--no-think",
        action="store_true",
        dest="no_think",
        help="отключить thinking-режим модели: передаёт {think: false} в Ollama. "
             "Необходимо для qwen3, deepseek-r1 и других thinking-моделей — "
             "без этого флага они тратят все токены на рассуждения и возвращают пустой ответ.",
    )

    return parser.parse_args()


def _check_conflicts(args: argparse.Namespace) -> None:
    """Останавливает программу при конфликтующих или бессмысленных флагах."""
    import sys

    errors: list[tuple[str, str]] = []  # (проблема, подсказка)

    if args.compare_models:
        for flag, name in [
            (args.only_classify, "--only-classify"),
            (args.only_parse,    "--only-parse"),
            (args.only_import,   "--only-import"),
            (args.re_tag,        "--re-tag"),
        ]:
            if flag:
                errors.append((
                    f"--compare-models и {name} несовместимы",
                    f"Уберите {name} — сравнение моделей запускает собственную классификацию",
                ))

    step3_runs = args.only_classify or args.re_tag or bool(args.compare_models)
    if args.batch > 1 and not step3_runs:
        errors.append((
            "--batch требует запуска step3, но он не включён",
            "Добавьте --only-classify  (или --re-tag / --compare-models)",
        ))
    if args.workers > 1 and not step3_runs:
        errors.append((
            "--workers требует запуска step3, но он не включён",
            "Добавьте --only-classify  (или --re-tag / --compare-models)",
        ))

    if not errors:
        return

    for problem, hint in errors:
        console.print(f"[bold red]Ошибка:[/bold red] {problem}")
        console.print(f"  [dim]→ {hint}[/dim]")
    console.print()
    sys.exit(1)


def main() -> None:
    args = parse_args()

    console.print(Rule("[bold cyan]URL Parser Pipeline[/bold cyan]"))

    _check_conflicts(args)

    init_db()
    init_tags_schema()
    init_compare_schema()

    # ── --compare-models ───────────────────────────────────────────────────────
    if args.compare_models:
        # nargs='+' → список; каждый элемент может содержать запятые ("m1,m2")
        models = []
        for item in args.compare_models:
            models.extend(m.strip() for m in item.split(",") if m.strip())
        compare.run_compare_models(
            models=models,
            limit=args.limit,
            no_progress=args.no_progress,
            verbose=args.verbose,
            domain=args.domain,
            workers=args.workers,
            no_think=args.no_think,
        )
        return

    # ── --compare [--export FILE] ──────────────────────────────────────────────
    if args.compare:
        compare.show_comparison(limit=args.limit, export=args.export)
        return

    # ── --accept-model ─────────────────────────────────────────────────────────
    if args.accept_model:
        n = db_accept_model(args.accept_model)
        if n:
            console.print(
                f"[green]--accept-model:[/green] принята модель "
                f"[bold cyan]{args.accept_model}[/bold cyan] — "
                f"обновлено [bold]{n}[/bold] записей в urls.category"
            )
        else:
            console.print(
                f"[yellow]--accept-model:[/yellow] нет результатов для модели "
                f"[bold]{args.accept_model}[/bold] в model_results. "
                f"Сначала запустите [bold]--compare-models[/bold]."
            )
        console.print(Rule("[bold green]Готово[/bold green]", style="green"))
        return

    # ── --compare-clear ────────────────────────────────────────────────────────
    if args.compare_clear:
        n = clear_model_results()
        console.print(
            f"[yellow]--compare-clear:[/yellow] удалено [bold]{n}[/bold] строк из model_results"
        )
        console.print(Rule("[bold green]Готово[/bold green]", style="green"))
        return

    # ── --clear-tags ───────────────────────────────────────────────────────────
    if args.clear_tags:
        n = clear_tags()
        console.print(f"[yellow]--clear-tags:[/yellow] удалено [bold]{n}[/bold] тегов из справочника")
        console.print(Rule("[bold green]Готово[/bold green]", style="green"))
        return

    # ── --sync-tags ────────────────────────────────────────────────────────────
    if args.sync_tags:
        added, skipped = sync_tags_from_categories()
        console.print(
            f"[cyan]--sync-tags:[/cyan] добавлено [bold green]{added}[/bold green] новых тегов, "
            f"[dim]{skipped}[/dim] уже были в справочнике"
        )
        console.print(Rule("[bold green]Готово[/bold green]", style="green"))
        return

    # ── --re-tag ───────────────────────────────────────────────────────────────
    if args.re_tag:
        n = reset_categories()
        console.print(
            f"[yellow]--re-tag:[/yellow] сброшено категорий: [bold]{n}[/bold] "
            f"[dim](справочник тегов сохранён как подсказки)[/dim]"
        )
        # Сразу запускаем step3 с теми же параметрами
        console.print()
        console.print(Rule("[dim]Step 3 — Классификация[/dim]", style="dim"))
        step3.main(
            model=args.model,
            limit=args.limit,
            no_progress=args.no_progress,
            verbose=args.verbose,
            workers=args.workers,
            batch=args.batch,
            no_think=args.no_think,
        )
        console.print()
        console.print(Rule("[bold green]Pipeline завершён[/bold green]", style="green"))
        return

    # ── --list-models ──────────────────────────────────────────────────────────
    if args.list_models:
        step3.main(list_models_flag=True)
        return

    # ── --add-tags ─────────────────────────────────────────────────────────────
    if args.add_tags:
        names = [t.strip() for t in args.add_tags.split(",") if t.strip()]
        added, skipped = add_tags(names)
        console.print(
            f"[cyan]--add-tags:[/cyan] добавлено [bold green]{added}[/bold green], "
            f"пропущено [dim]{skipped}[/dim] (дубликаты)"
        )

    # ── Режим одного URL ──────────────────────────────────────────────────────
    if args.url:
        console.print(f"[cyan]Режим одного URL:[/cyan] {args.url}")
        insert_urls([args.url])
        set_url_pending(args.url)
        step2.main(
            urls=[args.url],
            no_progress=args.no_progress,
            verbose=args.verbose,
        )
        console.print(Rule("[bold green]Готово[/bold green]", style="green"))
        return

    # ── Флаги сброса ──────────────────────────────────────────────────────────
    if args.force:
        n = reset_all_to_pending()
        console.print(f"[yellow]--force:[/yellow] сброшено [bold]{n}[/bold] записей → pending")
    elif args.retry_failed:
        n = reset_errors_to_pending()
        console.print(f"[yellow]--retry-failed:[/yellow] сброшено [bold]{n}[/bold] ошибок → pending")

    # ── Запуск шагов ──────────────────────────────────────────────────────────
    run_import   = not args.only_parse and not args.only_classify
    run_parse    = not args.only_import and not args.only_classify
    run_classify = args.only_classify  # явно запрошено; в полном пайплайне — нет

    if run_import:
        console.print()
        console.print(Rule("[dim]Step 1 — Импорт ссылок[/dim]", style="dim"))
        step1.main(input_file=args.input)

    if run_parse:
        console.print()
        console.print(Rule("[dim]Step 2 — Парсинг заголовков[/dim]", style="dim"))
        step2.main(
            limit=args.limit,
            no_progress=args.no_progress,
            verbose=args.verbose,
            domain=args.domain,
        )

    if run_classify:
        console.print()
        console.print(Rule("[dim]Step 3 — Классификация[/dim]", style="dim"))
        step3.main(
            model=args.model,
            limit=args.limit,
            no_progress=args.no_progress,
            verbose=args.verbose,
            workers=args.workers,
            batch=args.batch,
            no_think=args.no_think,
        )

    console.print()
    console.print(Rule("[bold green]Pipeline завершён[/bold green]", style="green"))


if __name__ == "__main__":
    main()
