"""Continuous polling with a persistent seen set, catch-up and delivery queue."""
from __future__ import annotations

import copy
import json
import logging
from logging.handlers import RotatingFileHandler
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from extract import file_hash, refresh_status, write_json
from telegram_send import build_plan, digest, preview, send


def source_key(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or parsed.hostname not in ("vk.ru", "vk.com", "www.vk.ru", "www.vk.com") or not parsed.path.strip("/"):
        raise ValueError("Укажите адрес стены/сообщества на vk.ru или vk.com")
    return "https://vk.ru/" + parsed.path.strip("/").casefold()


class WatchStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS sources(source TEXT PRIMARY KEY, baseline INTEGER NOT NULL)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS posts (
            source TEXT, post_key TEXT, published_at INTEGER, state TEXT, eligible INTEGER,
            data TEXT, folder TEXT, delivered INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(source,post_key))""")
        self.db.commit()

    def close(self):
        self.db.close()

    def known(self, source):
        return {row[0] for row in self.db.execute("SELECT post_key FROM posts WHERE source=?", (source,))}

    def initialized(self, source):
        return self.db.execute("SELECT baseline FROM sources WHERE source=?", (source,)).fetchone() is not None

    def overlaps(self, source, posts):
        if not self.initialized(source):
            return True
        known = self.known(source)
        if any(post["key"] in known for post in posts):
            return True
        # If all recent anchors were deleted, dates older than the saved baseline
        # still prove that the scan has covered the publication window.
        baseline = self.db.execute("SELECT baseline FROM sources WHERE source=?", (source,)).fetchone()[0]
        return any(post["published_at"] < baseline for post in posts)

    def ingest(self, source, selected, candidates, publish_existing=False):
        if not selected or any(p.get("published_at") is None for p in selected):
            raise ValueError("Нельзя двигать состояние без постов с машинными датами")
        first = not self.initialized(source)
        if not self.overlaps(source, selected):
            raise ValueError("Нет пересечения с прошлым просмотром: нужно увеличить глубину сбора")
        known = self.known(source)
        baseline = max(p["published_at"] for p in selected) if first else self.db.execute("SELECT baseline FROM sources WHERE source=?", (source,)).fetchone()[0]
        selected_keys = {p["key"] for p in selected}
        added = 0
        with self.db:
            if first:
                self.db.execute("INSERT INTO sources VALUES (?,?)", (source, baseline))
            for post in (candidates if first else selected):
                if post["key"] in known:
                    row = self.db.execute("SELECT state,data FROM posts WHERE source=? AND post_key=?", (source, post["key"])).fetchone()
                    if row["state"] == "pending" and post["key"] in selected_keys:
                        fresh = copy.deepcopy(post)
                        previous = json.loads(row["data"])
                        for kind in ("photos", "videos"):
                            previous_media = {item["id"]: item for item in previous[kind]}
                            for item in fresh[kind]:
                                old = previous_media.get(item["id"], {})
                                for field in ("local_path", "sha256", "byte_size", "mime_type", "download_status"):
                                    if old.get("local_path") and field in old:
                                        item[field] = old[field]
                        self.db.execute("UPDATE posts SET data=? WHERE source=? AND post_key=?", (json.dumps(fresh, ensure_ascii=False), source, post["key"]))
                    continue
                archive = post["key"] in selected_keys and (first or post["published_at"] >= baseline)
                eligible = (publish_existing if first else True) if archive else False
                self.db.execute("INSERT INTO posts(source,post_key,published_at,state,eligible,data,folder) VALUES (?,?,?,?,?,?,?)",
                    (source, post["key"], post.get("published_at"), "pending" if archive else "baseline",
                     int(eligible), json.dumps(post, ensure_ascii=False), None))
                added += int(archive)
        return added

    def rows(self, source):
        return [dict(row) for row in self.db.execute("""SELECT * FROM posts WHERE source=?
            ORDER BY published_at,
                     CAST(SUBSTR(post_key, 1, INSTR(post_key, '_') - 1) AS INTEGER),
                     CAST(SUBSTR(post_key, INSTR(post_key, '_') + 1) AS INTEGER)""", (source,))]

    def archived(self, source, key, post, folder):
        with self.db:
            self.db.execute("UPDATE posts SET state=?,data=?,folder=? WHERE source=? AND post_key=?",
                ("saved" if post["status"] == "complete" else "pending", json.dumps(post, ensure_ascii=False), str(folder), source, key))

    def delivered(self, source, key):
        with self.db:
            self.db.execute("UPDATE posts SET delivered=1 WHERE source=? AND post_key=?", (source, key))


def one_post_manifest(post, source):
    return {"schema_version": 1, "source_url": source,
        "created_at": datetime.now(timezone.utc).isoformat(), "candidate_count": 1,
        "requested_count": 1, "selection": {"valid": True, "order": "oldest_to_newest"}, "posts": [post]}


def write_post_text(folder, post):
    lines = ["Пост ВКонтакте", "Ссылка: " + str(post.get("url") or ""),
             "Дата (UTC): " + str(post.get("published_iso") or ""), "", "Текст:", post.get("text") or "(без текста)", "", "Вложения:"]
    for item in post.get("photos", []) + post.get("videos", []):
        lines.append("- " + str(item.get("local_path") or item.get("url") or "недоступно"))
    if len(lines) == 8:
        lines.append("(нет)")
    (Path(folder) / "post.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def archive_pending(store, source, root, driver, download_videos=True):
    from collect import download_media
    count = 0
    for row in store.rows(source):
        if row["state"] != "pending":
            continue
        post = json.loads(row["data"])
        post["issues"] = [issue for issue in post["issues"] if issue not in ("media_not_downloaded", "media_download_failed", "media_source_missing")]
        folder = root / "items" / post["key"]
        folder.mkdir(parents=True, exist_ok=True)
        download_media([post], folder, driver, download_videos=download_videos)
        refresh_status(post)
        manifest = one_post_manifest(post, source)
        write_json(folder / "manifest.json", manifest)
        write_post_text(folder, post)
        preview(folder, manifest)
        store.archived(source, post["key"], post, folder)
        count += post["status"] == "complete"
    return count


def export_archive(store, source, root):
    posts = []
    for row in store.rows(source):
        if not row["folder"]:
            continue
        post = json.loads(row["data"])
        for item in post.get("photos", []) + post.get("videos", []):
            if item.get("local_path"):
                item["local_path"] = (Path("items") / post["key"] / item["local_path"]).as_posix()
        posts.append(post)
    if posts:
        manifest = one_post_manifest(posts[0], source)
        manifest.update(posts=posts, candidate_count=len(posts), requested_count=len(posts))
        write_json(root / "manifest.json", manifest)
        preview(root, manifest)


def deliver_pending(store, source, token, chat_id, database, sender=send):
    count = 0
    for row in store.rows(source):
        if not row["eligible"] or row["delivered"]:
            continue
        if row["state"] != "saved":
            break  # Preserve publication order if earlier media is incomplete.
        folder = Path(row["folder"])
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
        plan, errors = build_plan(folder, manifest, chat_id)
        if errors:
            raise RuntimeError("Публикация ожидает проверки: " + "; ".join(errors))
        # --telegram / the interactive auto-publish choice authorizes future
        # complete posts for this configured source and destination.
        sender(folder, manifest, token, chat_id, digest(plan), database=database)
        store.delivered(source, row["post_key"])
        count += 1
    return count


def pause(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def acquire_lock(root):
    stream = (Path(root) / "watch.lock").open("a+b")
    if stream.tell() == 0:
        stream.write(b"0")
        stream.flush()
    stream.seek(0)
    try:
        import os
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.close()
        raise RuntimeError("Для этой папки архива уже запущено наблюдение") from None
    return stream


def watch(args, token=None, chat_id=None):
    from collect import _collect_with_driver, make_driver
    source = source_key(args.url)
    root = Path(args.output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    lock = acquire_lock(root)
    work = root / "work"
    work.mkdir(exist_ok=True)
    log = logging.getLogger("vk_watch." + str(root))
    log.setLevel(logging.INFO)
    handler = RotatingFileHandler(root / "watch.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    log.addHandler(handler)
    store = WatchStore(root / "watch.sqlite3")
    driver, failures, cycles = None, 0, 0
    api_token = getattr(args, "vk_token", None)
    try:
        if args.telegram and (not token or not chat_id):
            raise ValueError("Сначала подключите канал командой telegram-setup")
        print(f"Наблюдение: {source}; проверка каждые {args.interval} с; архив: {root}")
        print("Источник: " + ("официальный API ВК (ключ VK_PARSER_VK_TOKEN)" if api_token else "браузер Chromium"))
        print("Telegram: " + (str(chat_id) + ", автоматическая публикация новых постов" if args.telegram else "выключен"))
        print("Остановка: Ctrl+C. После перезапуска используется сохранённое состояние.")
        while True:
            cycles += 1
            try:
                if driver is None and not api_token:
                    driver = make_driver(args)
                limit = args.limit
                while True:
                    with tempfile.TemporaryDirectory(prefix="scan-", dir=work) as temp:
                        if api_token:
                            from vk_api import scan as api_scan
                            selected, api_candidates, total = api_scan(args.url, api_token, limit)
                            if not selected:
                                raise RuntimeError("Сбор не завершён: API ВК не вернул постов")
                            manifest = {"source_url": args.url, "created_at": datetime.now(timezone.utc).isoformat(),
                                        "requested_count": limit, "candidate_count": len(api_candidates),
                                        "wall_count_reported": total, "stop_reason": "vk_api",
                                        "selection": {"valid": True, "order": "oldest_to_newest"}, "posts": selected}
                        else:
                            api_candidates = None
                            scan_args = copy.copy(args)
                            scan_args.output, scan_args.limit, scan_args.no_download = temp, limit, True
                            scan_args.watch_mode = True
                            manifest = _collect_with_driver(scan_args, driver, Path(temp))
                            if not manifest["selection"]["valid"]:
                                for image in (Path(temp) / "diagnostics").glob("*"):
                                    shutil.copy2(image, root / ("last-error" + image.suffix))
                                raise RuntimeError("Сбор не завершён: " + manifest["stop_reason"])
                            selected = manifest["posts"]
                            total = manifest.get("wall_count_reported")
                        if not store.overlaps(source, selected):
                            if limit >= args.max_catchup or (total is not None and limit >= total):
                                raise RuntimeError("Не найден прошлый просмотр. Состояние сохранено; увеличьте --max-catchup.")
                            limit = min(limit * 2, args.max_catchup, total or args.max_catchup)
                            print(f"Между проверками появилось больше постов: расширяю просмотр до {limit}")
                            continue
                        candidates = api_candidates if api_candidates is not None else [
                            json.loads(path.read_text(encoding="utf-8")) for path in (Path(temp) / "posts").glob("*.json")]
                        added = store.ingest(source, selected, candidates, args.publish_existing)
                        for post in selected:
                            snapshot = Path(temp) / "snapshots" / (post["key"] + ".html")
                            if snapshot.exists():
                                target = root / "items" / post["key"] / "post.html"
                                target.parent.mkdir(parents=True, exist_ok=True)
                                if not target.exists():
                                    shutil.copy2(snapshot, target)
                        write_json(root / "last_scan.json", {key: value for key, value in manifest.items() if key != "posts"})
                        break
                saved = archive_pending(store, source, root, driver, args.download_videos)
                if added or saved:
                    export_archive(store, source, root)
                if args.telegram:
                    try:
                        sent = deliver_pending(store, source, token, chat_id, args.db)
                        if sent:
                            print(f"Опубликовано новых постов: {sent}")
                    except (RuntimeError, ValueError, OSError) as exc:
                        print(str(exc))
                        log.warning("Публикация остановлена: %s", str(exc))
                failures = 0
                message = f"Проверка {cycles}: новых/начальных {added}, сохранено {saved}"
                print(message, flush=True)
                log.info(message)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                # Error messages from third-party HTTP clients can contain secrets.
                message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else type(exc).__name__
                print("Проверка не завершена: " + message, flush=True)
                log.warning("Проверка не завершена: %s", message)
                failures += 1
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None
            if args.cycles and cycles >= args.cycles:
                break
            pause(min(300, args.interval * (2 ** min(failures, 3))))
    except KeyboardInterrupt:
        print("Наблюдение остановлено. Состояние и архив сохранены.")
    finally:
        if driver is not None:
            driver.quit()
        store.close()
        log.removeHandler(handler)
        handler.close()
        lock.close()
