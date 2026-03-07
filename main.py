import argparse

from rich.console import Console
from rich.rule import Rule

import step1
import step2
from db import init_db, insert_urls, reset_all_to_pending, reset_errors_to_pending, set_url_pending

console = Console()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="URL Parser Pipeline — импорт ссылок и парсинг заголовков",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""примеры:
  python main.py                                  полный пайплайн (step1 + step2)
  python main.py --only-parse                     только парсинг (step2)
  python main.py --only-parse --limit 50          первые 50 pending URL
  python main.py --retry-failed                   повторить URL с ошибками
  python main.py --force                          сбросить всё и начать заново
  python main.py --url https://example.com        обработать один URL
  python main.py --input links.txt                другой входной файл
  python main.py --no-progress -v                 plain вывод + детали
  python main.py --domain habr.com                только URL с habr.com
  python main.py --domain habr.com --retry-failed повторить ошибки для домена
""",
    )

    parser.add_argument(
        "--input",
        metavar="FILE",
        default="raw_links.txt",
        help="входной файл для step1 (по умолчанию: raw_links.txt)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        default=None,
        help="обработать не более N URL в step2",
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
        "--only-import",
        action="store_true",
        dest="only_import",
        help="запустить только step1 (импорт ссылок в БД)",
    )
    parser.add_argument(
        "--only-parse",
        action="store_true",
        dest="only_parse",
        help="запустить только step2 (парсинг заголовков)",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        dest="no_progress",
        help="отключить progress bar, plain вывод в консоль",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="показывать заголовок / ошибку по каждому URL",
    )
    parser.add_argument(
        "--domain",
        metavar="DOMAIN",
        default=None,
        help="обработать только URL указанного домена (напр. habr.com)",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    console.print(Rule("[bold cyan]URL Parser Pipeline[/bold cyan]"))

    init_db()

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

    # ── Флаги сброса ─────────────────────────────────────────────────────────
    if args.force:
        n = reset_all_to_pending()
        console.print(f"[yellow]--force:[/yellow] сброшено [bold]{n}[/bold] записей → pending")
    elif args.retry_failed:
        n = reset_errors_to_pending()
        console.print(f"[yellow]--retry-failed:[/yellow] сброшено [bold]{n}[/bold] ошибок → pending")

    # ── Запуск шагов ─────────────────────────────────────────────────────────
    run_import = not args.only_parse
    run_parse = not args.only_import

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

    console.print()
    console.print(Rule("[bold green]Pipeline завершён[/bold green]", style="green"))


if __name__ == "__main__":
    main()
