"""Docker entry point: unattended watcher or a terminal menu for one-off collections."""
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from vk_parser import main

DATA = Path("/data")
CHROME_ARGS = ["--headless", "--chrome", "/usr/bin/chromium", "--driver", "/usr/bin/chromedriver", "--cache", "/data/cache"]


def watch_command():
    return ["watch", "--url", os.environ.get("VK_PARSER_URL", "https://vk.ru/cvetyurala"),
            "--limit", os.environ.get("VK_PARSER_LIMIT", "10"),
            "--interval", os.environ.get("VK_PARSER_INTERVAL", "60"),
            "--max-catchup", os.environ.get("VK_PARSER_MAX_CATCHUP", "1000"),
            "--output", str(DATA / "archive"), "--telegram",
            "--db", str(DATA / "delivery.sqlite3"), *CHROME_ARGS]


def publish(folder):
    from telegram_send import build_plan, digest, send

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise ValueError("Для публикации задайте VK_PARSER_TELEGRAM_BOT_TOKEN и VK_PARSER_TELEGRAM_CHAT_ID в .env.")
    folder = Path(folder)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    plan, errors = build_plan(folder, manifest, chat_id)
    if errors:
        raise ValueError("Публикация остановлена: " + "; ".join(errors))
    send(folder, manifest, token, chat_id, digest(plan), database=DATA / "delivery.sqlite3")
    print("Публикация завершена. Уже отправленные посты повторно не публикуются.", flush=True)


def collect_with_retry(url, limit):
    # Chrome can lose a clickable element while VK redraws the page. Start a
    # fresh browser and keep each failed run for diagnosis; never publish it.
    retryable = {"browser_error:ElementNotInteractableException",
                 "browser_error:StaleElementReferenceException"}
    for attempt in range(3):
        name = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8]
        folder = DATA / "runs" / name
        result = main(["collect", "--url", url, "--limit", limit, "--output", str(folder), *CHROME_ARGS])
        if result == 0:
            return folder, result
        try:
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return folder, result
        if manifest.get("stop_reason") not in retryable or attempt == 2:
            return folder, result
        print(f"ВК обновил страницу во время сбора. Повторяю попытку {attempt + 2} из 3...", flush=True)
    return folder, result


def republish_menu():
    from telegram_send import Ledger, build_plan

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise ValueError("Для публикации задайте реквизиты Telegram в .env.")
    entries = []
    for path in (DATA / "archive" / "items").glob("*/manifest.json"):
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            posts = manifest.get("posts", [])
            if len(posts) == 1 and posts[0].get("status") == "complete":
                entries.append((posts[0], path.parent, manifest))
        except (OSError, ValueError, TypeError):
            continue
    entries.sort(key=lambda entry: (entry[0].get("published_at") or 0, entry[0].get("key") or ""), reverse=True)
    if not entries:
        print("В архиве пока нет полностью сохранённых постов.")
        return
    print("\nСохранённые посты (сначала новые):")
    for index, (post, _, _) in enumerate(entries, 1):
        text = " ".join((post.get("text") or "(пост без текста)").split())[:90]
        print(f"{index}. {post.get('published_iso', '')} | {post['key']} | {text}")
    choice = input("Номер поста для повторной отправки (0 — отмена): ").strip()
    if choice == "0":
        return
    if not choice.isdigit() or not 1 <= int(choice) <= len(entries):
        raise ValueError("Нет поста с таким номером.")
    post, folder, manifest = entries[int(choice) - 1]
    _, errors = build_plan(folder, manifest, chat_id)
    if errors:
        raise ValueError("Нельзя отправить пост: " + "; ".join(errors))
    print("Повторная отправка создаст новую публикацию в Telegram: " + str(post.get("url", post["key"])))
    if input("Отправить ещё раз? Введите да: ").strip().casefold() not in ("да", "yes"):
        print("Отменено.")
        return
    ledger = Ledger(DATA / "delivery.sqlite3")
    try:
        ledger.reset_sent_post(token.split(":", 1)[0] + ":" + str(chat_id), post["key"])
    finally:
        ledger.close()
    publish(folder)


def menu():
    while True:
        print("\nПарсер ВКонтакте\n1. Собрать последние посты и опубликовать в Telegram\n2. Повторно отправить сохранённый пост\n0. Выход")
        try:
            choice = input("Выбор: ").strip()
            if choice == "0":
                return 0
            if choice == "2":
                republish_menu()
                continue
            if choice != "1":
                print("Выберите 1, 2 или 0.")
                continue
            default_url = os.environ.get("VK_PARSER_URL", "https://vk.ru/cvetyurala")
            url = input(f"Адрес сообщества [{default_url}]: ").strip() or default_url
            from watcher import source_key
            source_key(url)
            limit = input("Сколько последних постов собрать [10]: ").strip() or "10"
            if not limit.isdigit() or int(limit) < 1:
                print("Введите положительное целое число.")
                continue
            folder, result = collect_with_retry(url, limit)
            print(f"Папка на компьютере: {os.environ.get('VK_PARSER_DATA_DIR', './vk-parser-data')}/runs/{folder.name}")
            if result:
                print("Сбор не завершён; подробности и диагностика находятся в этой папке.")
            else:
                print("Отправка собранных постов в подключённый Telegram-канал...")
                publish(folder)
        except (EOFError, KeyboardInterrupt):
            print("\nЗавершено.")
            return 0
        except (ValueError, RuntimeError, OSError) as exc:
            print(str(exc))


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    command = sys.argv[1:] or ["watch"]
    if command == ["watch"]:
        if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get("TELEGRAM_CHAT_ID"):
            print("Задайте VK_PARSER_TELEGRAM_BOT_TOKEN и VK_PARSER_TELEGRAM_CHAT_ID в .env для автопубликации.", file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(main(watch_command()))
    if command == ["menu"]:
        raise SystemExit(menu())
    if len(command) == 2 and command[0] == "publish":
        try:
            publish(command[1])
        except (ValueError, RuntimeError, OSError) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(0)
    raise SystemExit(main(command))
