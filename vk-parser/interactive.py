"""The no-argument Python entry point."""
from datetime import datetime
from pathlib import Path

from extract import write_json
from settings import DEFAULT_PATH, ROOT, load_settings, setup_telegram


def number(prompt, default, minimum=1):
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        try:
            result = int(value or default)
            if result >= minimum:
                return result
        except ValueError:
            pass
        print(f"Введите целое число не меньше {minimum}.")


def yes(prompt, default=False):
    value = input(prompt + (" [Д/н]: " if default else " [д/Н]: ")).strip().casefold()
    return default if not value else value in ("д", "да", "y", "yes")


def menu():
    from vk_parser import main
    while True:
        print("\nВК → архив → Telegram")
        print("1. Собрать последние посты")
        print("2. Постоянно следить за новыми постами")
        print("3. Подключить Telegram-канал")
        print("4. Проверить сохранённые файлы")
        print("0. Выход")
        choice = input("Выбор: ").strip()
        if choice == "0":
            return 0
        try:
            settings = load_settings()
            if choice == "3":
                setup_telegram()
                continue
            if choice == "4":
                folder = input("Папка результата/архива: ").strip().strip('"')
                main(["verify", folder])
                continue
            if choice not in ("1", "2"):
                print("Выберите пункт 0–4.")
                continue
            url = input(f"Адрес сообщества [{settings['url']}]: ").strip() or settings["url"]
            limit = number("Сколько последних постов сохранить сначала", settings["limit"])
            settings.update(url=url, limit=limit)
            write_json(DEFAULT_PATH, settings)
            if choice == "1":
                folder = ROOT / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
                code = main(["collect", "--url", url, "--limit", str(limit), "--output", str(folder)])
                print("Предпросмотр: " + str(folder / "preview.html"))
                if code == 0 and settings.get("telegram") and yes("Отправить эту выборку в подключённый канал?"):
                    from settings import get_token
                    from telegram_send import build_plan, digest, send
                    import json
                    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
                    chat_id = settings["telegram"]["chat_id"]
                    plan, errors = build_plan(folder, manifest, chat_id)
                    if errors:
                        raise ValueError("; ".join(errors))
                    send(folder, manifest, get_token(settings), chat_id, digest(plan), database=ROOT / "delivery.sqlite3")
            else:
                interval = number("Интервал проверки, секунд", settings["interval"], minimum=15)
                settings["interval"] = interval
                write_json(DEFAULT_PATH, settings)
                command = ["watch", "--url", url, "--limit", str(limit), "--interval", str(interval),
                           "--output", str(ROOT / settings["archive"]), "--manual", "--profile", str(ROOT / ".vk-profile")]
                if yes("Автоматически публиковать новые посты в Telegram?"):
                    if not settings.get("telegram"):
                        settings = setup_telegram()
                    print("Получатель: " + settings["telegram"].get("chat_title", settings["telegram"]["chat_id"]))
                    command.append("--telegram")
                    if yes("Также отправить начальную выборку постов при первом запуске?"):
                        command.append("--publish-existing")
                main(command)
        except (ValueError, RuntimeError, OSError) as exc:
            print(str(exc))
        except (EOFError, KeyboardInterrupt):
            print("\nЗавершено.")
            return 0
