"""python vk_parser.py --help"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from telegram_send import Ledger, preview, send


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        from interactive import menu
        return menu()
    from settings import DEFAULT_PATH, ROOT, get_token, load_settings
    config = load_settings()
    parser = argparse.ArgumentParser(description="ВК через Selenium: сбор → предпросмотр → отдельная подтверждённая отправка")
    default_db = str(Path(__file__).resolve().with_name("delivery.sqlite3"))
    commands = parser.add_subparsers(dest="command", required=True)
    gather = commands.add_parser("collect", help="Собрать посты и скачать доступные вложения")
    gather.add_argument("--url", default="https://vk.ru/cvetyurala")
    gather.add_argument("--output")
    gather.add_argument("--limit", type=int, default=10)
    gather.add_argument("--max-scrolls", type=int, default=40)
    gather.add_argument("--scroll-timeout", type=float, default=3)
    gather.add_argument("--timeout", type=float, default=30)
    gather.add_argument("--headless", action="store_true")
    gather.add_argument("--manual", action="store_true", help="Ожидать ручного входа/капчи в открытом браузере")
    gather.add_argument("--profile", help="Отдельная папка профиля Chrome для ручного входа")
    gather.add_argument("--cache", default=".selenium-cache")
    gather.add_argument("--driver", help="Путь к уже установленному chromedriver.exe")
    gather.add_argument("--chrome", help="Путь к Chrome, если не найден автоматически")
    gather.add_argument("--selectors", help="Свой selectors.json")
    gather.add_argument("--no-download", action="store_true")
    gather.add_argument("--download-videos", action="store_true", default=True, help="Скачивать доступные видео (по умолчанию)")
    gather.add_argument("--video-links-only", action="store_false", dest="download_videos", help="Сохранять видео только как ссылки")
    gather.add_argument("--vk-token", default=os.environ.get("VK_PARSER_VK_TOKEN") or None,
                        help="Сервисный ключ приложения ВК: читать стену через официальный API вместо браузера "
                             "(по умолчанию — переменная VK_PARSER_VK_TOKEN)")
    monitor = commands.add_parser("watch", parents=[gather], add_help=False, help="Постоянно собирать новые посты")
    monitor.add_argument("--interval", type=int, default=60)
    monitor.add_argument("--telegram", action="store_true", help="Автоматически публиковать новые посты в подключённый канал")
    monitor.add_argument("--publish-existing", action="store_true", help="При первом запуске также опубликовать начальную выборку")
    monitor.add_argument("--db", default=default_db)
    monitor.add_argument("--max-catchup", type=int, default=1000)
    monitor.add_argument("--cycles", type=int, default=0, help="Для проверки: остановиться после N циклов; 0 — постоянно")
    commands.add_parser("telegram-setup", help="Подключить своего бота и канал")
    verifier = commands.add_parser("verify", help="Проверить данные, наличие файлов и SHA-256")
    verifier.add_argument("folder")
    for name in ("preview", "send"):
        sub = commands.add_parser(name)
        sub.add_argument("folder", help="Папка результата collect")
        sub.add_argument("--chat-id", default=os.environ.get("TELEGRAM_CHAT_ID") or config.get("telegram", {}).get("chat_id"))
        sub.add_argument("--allow-partial", action="store_true", help="Явно разрешить проверенные вручную partial-посты")
        if name == "send":
            sub.add_argument("--confirm", help="SHA-256 из preview для этого получателя и содержимого")
            sub.add_argument("--db", default=default_db, help="Общий SQLite-журнал для всех сборов")
    journal = commands.add_parser("journal", help="Показать журнал, не выполняя сетевых запросов")
    journal.add_argument("--db", default=default_db)
    resolve = commands.add_parser("resolve", help="Ручная сверка неопределённого результата; перед запуском остановите все send")
    resolve.add_argument("--db", default=default_db)
    resolve.add_argument("--destination", required=True, help="destination из journal, включая ID бота")
    resolve.add_argument("--post", required=True)
    resolve.add_argument("--operation", required=True)
    resolve.add_argument("--action", choices=("sent", "retry"), required=True)
    resolve.add_argument("--message-id", type=int)
    resolve.add_argument("--message-ids", help="Для альбома: все ID сообщений через запятую")
    resolve.add_argument("--note", required=True, help="Результат ручной проверки в Telegram")
    args = parser.parse_args(argv)
    try:
        if args.command in ("collect", "watch") and args.output is None:
            args.output = str(ROOT / "archive") if args.command == "watch" else "run"
        if args.command == "telegram-setup":
            from settings import setup_telegram
            setup_telegram()
            return 0
        if args.command == "verify":
            from verify_saved import verify
            result = verify(args.folder)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["ok"] else 2
        if args.command == "watch":
            if args.manual and args.headless:
                raise ValueError("Для --manual уберите --headless")
            if args.limit < 1 or args.interval < 15 or args.max_catchup < args.limit or args.cycles < 0:
                raise ValueError("Проверьте лимит, интервал (от 15 с), max-catchup и cycles")
            if args.no_download:
                raise ValueError("Постоянный режим сохраняет вложения. Для сбора только метаданных используйте collect --no-download.")
            from watcher import watch
            watch(args, get_token(config) if args.telegram else None,
                  os.environ.get("TELEGRAM_CHAT_ID") or config.get("telegram", {}).get("chat_id"))
            return 0
        if args.command == "collect":
            if args.manual and args.headless:
                raise ValueError("Для --manual нужен видимый браузер: уберите --headless")
            if args.limit < 1 or args.max_scrolls < 1 or args.timeout <= 0 or args.scroll_timeout <= 0:
                raise ValueError("Лимиты и таймауты должны быть положительными")
            from collect import collect
            result = collect(args)
            fingerprint, errors = preview(Path(args.output), result)
            print(f"Результат: {Path(args.output).resolve()}\nПостов: {len(result['posts'])}; complete: {sum(p['status'] == 'complete' for p in result['posts'])}")
            print("Откройте preview.html. Для кода отправки повторите preview с --chat-id.")
            return 0 if result["selection"]["valid"] else 2
        if args.command in ("journal", "resolve"):
            path = Path(args.db).resolve()
            if not path.exists():
                raise ValueError("Журнал ещё не создан; отправок не было")
            ledger = Ledger(path)
            try:
                if args.command == "journal":
                    print(json.dumps(ledger.rows(), ensure_ascii=False, indent=2))
                else:
                    ids = [int(value.strip()) for value in args.message_ids.split(",")] if args.message_ids else None
                    ledger.resolve(args.destination, args.post, args.operation, args.action, args.note, args.message_id, message_ids=ids)
                    print("Результат ручной сверки сохранён")
            finally:
                ledger.close()
            return 0
        root = Path(args.folder).resolve()
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if args.command == "preview" or not args.confirm:
            fingerprint, errors = preview(root, manifest, args.chat_id, args.allow_partial)
            print(f"Предпросмотр: {root / 'preview.html'}\nКод подтверждения: {fingerprint}")
            if errors:
                print("\n".join(errors))
            else:
                print("После проверки: send <папка> --chat-id <получатель> --confirm " + fingerprint)
            return 2 if errors else 0
        send(root, manifest, get_token(config), args.chat_id, args.confirm, args.allow_partial, database=args.db)
        return 0
    except (ValueError, RuntimeError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
