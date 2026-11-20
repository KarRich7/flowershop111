"""Reviewed, resumable Telegram delivery with conservative unknown outcomes."""
from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import time
import re
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

import requests

from extract import file_hash

ORDER_FOOTER = "бот для заказов тг: @flowerfromuralbot"
FOOTER_PATH = Path(__file__).resolve().with_name("post_footer.txt")
FORMAT_PREFIX = "v2:"


def read_footer(path=None):
    path = Path(path or FOOTER_PATH)
    return path.read_text(encoding="utf-8-sig").strip() if path.exists() else ORDER_FOOTER


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def split_text(text, max_units=4000):
    # Conservative UTF-16 budget, without losing whitespace or splitting emoji pairs.
    if max_units < 2:
        raise ValueError("max_units must be at least 2")
    parts, start = [], 0
    while start < len(text):
        end, units, last_break = start, 0, None
        while end < len(text):
            width = 2 if ord(text[end]) > 0xFFFF else 1
            if units + width > max_units:
                break
            units += width
            end += 1
            if text[end - 1] in "\n ":
                last_break = end
        cut = last_break if end < len(text) and last_break and last_break > (start + end) // 2 else end
        parts.append(text[start:cut])
        start = cut
    return parts


def local_media_path(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("Вложение отсутствует или находится вне папки результата")
    return path


def post_body(post, footer=None):
    footer = read_footer() if footer is None else footer
    parts = [post.get("text", "")]
    for link in post.get("links", []):
        parts.append(f"{link['text']} — {link['url']}" if link.get("text") else link["url"])
    for video in post.get("videos", []):
        if video.get("description") and video["description"] not in parts:
            parts.append(video["description"])
    if post.get("other_attachments") or post.get("reposts"):
        parts.append("Есть вложения, требующие проверки в исходной публикации.")
    body = "\n\n".join(x for x in parts if x)
    for suffix in sorted({ORDER_FOOTER, footer} - {""}, key=len, reverse=True):
        body = re.sub(r"(?im)^[ \t]*" + re.escape(suffix) + r"[ \t]*$", "", body)
    return body.strip()


def with_footer(text, footer=None):
    footer = read_footer() if footer is None else footer
    return text + "\n\n" + footer if text and footer else text or footer


def post_message(post, footer=None):
    footer = read_footer() if footer is None else footer
    return with_footer(post_body(post, footer), footer)


def publication_parts(post, has_media, footer=None):
    footer = read_footer() if footer is None else footer
    body = post_body(post, footer)
    limit = 1024 if has_media else 4000
    reserve = len(footer.encode("utf-16-le")) // 2 + 2 if footer else 0
    if len(footer.encode("utf-16-le")) // 2 > limit or (body and limit - reserve < 2):
        raise ValueError("Подпись в post_footer.txt слишком длинная. Сократите её для отправки.")
    if not body:
        return [footer]
    if not has_media:
        return [with_footer(part, footer) for part in split_text(body, 4000 - reserve)]
    chunks = split_text(body, 1024 - reserve)
    first = chunks[0] if chunks else ""
    rest = "".join(chunks[1:])
    return [with_footer(first, footer)] + [with_footer(part, footer) for part in split_text(rest, 4000 - reserve)]


def media_batches(items):
    return [items[index:index + 10] for index in range(0, len(items), 10)]


def build_plan(root, manifest, chat_id, allow_partial=False):
    footer = read_footer()
    posts = manifest["posts"]
    errors, operations = [], []
    if not manifest.get("selection", {}).get("valid"):
        errors.append("Не подтверждена выборка нужного количества постов с точными датами")
    if not posts:
        errors.append("Нет постов")
    if len({p["key"] for p in posts}) != len(posts):
        errors.append("В manifest есть повторяющиеся ID")
    dates = [p.get("published_at") for p in posts]
    if any(d is None for d in dates) or dates != sorted(d for d in dates if d is not None):
        errors.append("Нужны точные даты и порядок от старого к новому")
    for post in posts:
        if post["status"] != "complete" and not allow_partial:
            errors.append(f"{post['key']}: {post['status']}; проверьте issues")
        attachments, documents = [], []
        for kind in ("photos", "videos"):
            for media in post.get(kind, []):
                if kind == "videos" and media.get("download_status") == "link_only":
                    continue
                if not media.get("local_path"):
                    if kind == "photos":
                        errors.append(f"{post['key']}: фотография {media['id']} не скачана")
                    continue
                path = local_media_path(root, media["local_path"])
                sha256 = file_hash(path)
                if sha256 != media.get("sha256"):
                    errors.append(f"{post['key']}: изменился файл {media['local_path']}")
                is_photo = kind == "photos"
                size = path.stat().st_size
                if not is_photo and size > 50 * 1024 * 1024:
                    continue  # Keep metadata and the large file in the local archive.
                # Exact saved bytes are retained locally; Telegram may recompress sendPhoto.
                method, field = ("sendPhoto", "photo") if is_photo and size <= 10 * 1024 * 1024 and media.get("mime_type") in ("image/jpeg", "image/png") else ("sendDocument", "document")
                if not is_photo and media.get("mime_type") == "video/mp4":
                    method, field = "sendVideo", "video"
                if size > 50 * 1024 * 1024:
                    errors.append(f"{post['key']}: файл больше лимита отправки 50 МБ")
                item = {"type": "photo" if method == "sendPhoto" else "video" if method == "sendVideo" else "document",
                        "file": media["local_path"], "sha256": sha256,
                        "mime_type": media.get("mime_type", "application/octet-stream")}
                (documents if method == "sendDocument" else attachments).append(item)
        batches = media_batches(attachments) + media_batches(documents)
        parts = publication_parts(post, bool(batches), footer)
        if not batches:
            for index, text in enumerate(parts):
                if not text:
                    errors.append(f"{post['key']}: нет текста и доступных вложений для отправки")
                    continue
                operations.append({"post_key": post["key"], "operation_key": f"{FORMAT_PREFIX}text:{index}",
                    "method": "sendMessage", "payload": {"text": text, "link_preview_options": {"is_disabled": True}}})
            continue
        for index, batch in enumerate(batches):
            caption = parts[0] if index == 0 else footer
            operation = {"post_key": post["key"], "operation_key": f"{FORMAT_PREFIX}media:{index}"}
            if len(batch) == 1:
                item = batch[0]
                kind = item["type"]
                operation.update(method={"photo": "sendPhoto", "video": "sendVideo", "document": "sendDocument"}[kind],
                    payload={"caption": caption, **({"supports_streaming": True} if kind == "video" else {})},
                    file=item["file"], field=kind, sha256=item["sha256"], mime_type=item["mime_type"])
            else:
                files, media_payload = [], []
                for number, item in enumerate(batch):
                    field = f"media{number}"
                    files.append({"field": field, "file": item["file"], "sha256": item["sha256"], "mime_type": item["mime_type"]})
                    entry = {"type": item["type"], "media": "attach://" + field}
                    if number == 0:
                        entry["caption"] = caption
                    if item["type"] == "video":
                        entry["supports_streaming"] = True
                    media_payload.append(entry)
                operation.update(method="sendMediaGroup", payload={"media": media_payload}, files=files)
            operations.append(operation)
            if index == 0:
                for number, text in enumerate(parts[1:], 1):
                    operations.append({"post_key": post["key"], "operation_key": f"{FORMAT_PREFIX}text:{number}",
                        "method": "sendMessage", "payload": {"text": text, "link_preview_options": {"is_disabled": True}}})
    if not chat_id:
        errors.append("Укажите --chat-id для подтверждения конкретного получателя")
    plan = {"chat_id": str(chat_id or ""), "allow_partial": allow_partial, "footer": footer, "operations": operations,
            "review": [{"key": p["key"], "status": p["status"], "issues": p["issues"]} for p in posts]}
    return plan, sorted(set(errors))


def preview(root, manifest, chat_id=None, allow_partial=False):
    root = Path(root)
    plan, errors = build_plan(root, manifest, chat_id, allow_partial)
    fingerprint = digest(plan)
    sections = []
    for post in manifest["posts"]:
        media = []
        for photo in post["photos"]:
            if photo.get("local_path"):
                local_media_path(root, photo["local_path"])
                src = html.escape(photo["local_path"], quote=True)
                media.append(f'<a href="{src}"><img loading="lazy" src="{src}" alt="Фото публикации"></a>')
            media.append('<p class="meta">' + html.escape(f"Фото {photo['id']}: {photo['quality']}; {photo['download_status']}") + '</p>')
        for video in post.get("videos", []):
            if video.get("local_path"):
                local_media_path(root, video["local_path"])
                src = html.escape(video["local_path"], quote=True)
                media.append(f'<video controls preload="metadata" style="max-width:100%;max-height:480px" src="{src}"></video>')
            media.append('<p class="meta">' + html.escape(f"Видео {video['id']}: {video['download_status']}") + '</p>')
        sections.append(f'<article><h2>{html.escape(post["key"])} · {html.escape(post["status"])}</h2>'
                        f'<p class="meta">{html.escape(post.get("published_iso") or "Нет машинной даты")}</p>'
                        f'<pre>{html.escape(post_message(post, plan["footer"]))}</pre>{"".join(media)}'
                        f'<p class="issues">{html.escape(", ".join(post["issues"]))}</p></article>')
    warning = '<br>'.join(html.escape(x) for x in errors) or "Можно отправлять после проверки этого предпросмотра."
    document = ('<!doctype html><html lang="ru"><meta charset="utf-8"><title>ВК: предпросмотр</title>'
        '<style>body{max-width:950px;margin:32px auto;padding:0 20px;font:16px/1.5 system-ui;background:#f5f5f2;color:#222}'
        'article{background:white;padding:24px;margin:20px 0;border:1px solid #ddd;border-radius:10px}'
        'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}img{max-width:270px;max-height:350px;margin:6px}'
        '.meta{color:#555;font-size:13px}.issues{color:#923b12}code{overflow-wrap:anywhere}</style>'
        f'<h1>Посты ВК → Telegram</h1><p>Получатель: <b>{html.escape(str(chat_id or "не задан"))}</b></p>'
        f'<p>Порядок: от старого к новому. Кандидатов: {manifest["candidate_count"]}.</p>'
        f'<p>{warning}</p><p>Код подтверждения: <code>{fingerprint}</code></p>'
        + ''.join(sections) + '</html>')
    (root / "preview.html").write_text(document, encoding="utf-8")
    return fingerprint, errors


class Ledger:
    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS operations (
            destination TEXT NOT NULL, post_key TEXT NOT NULL, operation_key TEXT NOT NULL,
            payload_hash TEXT NOT NULL, status TEXT NOT NULL, message_id INTEGER,
            error TEXT, updated_at TEXT NOT NULL,
            PRIMARY KEY(destination, post_key, operation_key))""")
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(operations)")}
        if "message_ids" not in columns:
            self.db.execute("ALTER TABLE operations ADD COLUMN message_ids TEXT")
        if "expected_count" not in columns:
            self.db.execute("ALTER TABLE operations ADD COLUMN expected_count INTEGER NOT NULL DEFAULT 1")
        self.db.execute("""CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY, destination TEXT, post_key TEXT, operation_key TEXT,
            action TEXT, note TEXT, created_at TEXT)""")
        self.db.commit()

    def close(self):
        self.db.close()

    def reserve(self, destination, operation):
        key = (destination, operation["post_key"], operation["operation_key"])
        fingerprint = digest(operation)
        now = datetime.now(timezone.utc).isoformat()
        try:
            self.db.execute("BEGIN IMMEDIATE")
            row = self.db.execute("SELECT * FROM operations WHERE destination=? AND post_key=? AND operation_key=?", key).fetchone()
            if row:
                if row["payload_hash"] != fingerprint:
                    raise RuntimeError("Содержимое ранее зарегистрированной операции изменилось; нужна ручная проверка")
                if row["status"] == "sent":
                    self.db.commit()
                    return False
                if row["status"] != "pending":
                    raise RuntimeError(f"Отправка остановлена: {key[1]}/{key[2]} имеет статус {row['status']}. Проверьте Telegram и журнал.")
                self.db.execute("UPDATE operations SET status='inflight', updated_at=? WHERE destination=? AND post_key=? AND operation_key=?", (now, *key))
            else:
                expected = len(operation["files"]) if operation["method"] == "sendMediaGroup" else 1
                self.db.execute("""INSERT INTO operations
                    (destination,post_key,operation_key,payload_hash,status,message_id,error,updated_at,expected_count)
                    VALUES (?,?,?,?,?,?,?,?,?)""", (*key, fingerprint, "inflight", None, None, now, expected))
            self.db.commit()  # Durable BEFORE any HTTP request.
            return True
        except BaseException:
            self.db.rollback()
            raise

    def finish(self, destination, operation, status, message_id=None, error=None):
        key = (destination, operation["post_key"], operation["operation_key"])
        ids = message_id if isinstance(message_id, list) else [message_id] if message_id is not None else []
        expected = len(operation["files"]) if operation["method"] == "sendMediaGroup" else 1
        if status == "sent" and (len(ids) != expected or len(set(ids)) != expected):
            raise ValueError("Нет подтверждённых ID всех сообщений операции")
        with self.db:
            self.db.execute("UPDATE operations SET status=?, message_id=?, message_ids=?, error=?, updated_at=? WHERE destination=? AND post_key=? AND operation_key=?",
                (status, ids[0] if ids else None, json.dumps(ids) if ids else None,
                 error, datetime.now(timezone.utc).isoformat(), *key))

    def rows(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM operations ORDER BY updated_at, destination, post_key, operation_key")]

    def reset_sent_post(self, destination, post_key):
        """Allow an explicitly selected, fully confirmed post to be sent again."""
        try:
            self.db.execute("BEGIN IMMEDIATE")
            rows = self.db.execute("SELECT operation_key,status,message_ids FROM operations WHERE destination=? AND post_key=?", (destination, post_key)).fetchall()
            if any(row["status"] != "sent" for row in rows):
                raise RuntimeError("У поста есть неподтверждённая отправка. Сначала проверьте Telegram и выполните сверку журнала.")
            now = datetime.now(timezone.utc).isoformat()
            for row in rows:
                self.db.execute("INSERT INTO audit(destination,post_key,operation_key,action,note,created_at) VALUES (?,?,?,?,?,?)",
                                (destination, post_key, row["operation_key"], "republish", "Предыдущие ID сообщений: " + str(row["message_ids"]), now))
            self.db.execute("DELETE FROM operations WHERE destination=? AND post_key=?", (destination, post_key))
            self.db.commit()
            return len(rows)
        except BaseException:
            self.db.rollback()
            raise

    def resolve(self, destination, post_key, operation_key, action, note, message_id=None, message_ids=None):
        if not note:
            raise ValueError("Нужно объяснение ручной сверки --note")
        ids = message_ids or ([message_id] if message_id else [])
        if action == "sent" and not ids:
            raise ValueError("Для sent нужен подтверждённый --message-id из Telegram")
        key = (destination, post_key, operation_key)
        with self.db:
            row = self.db.execute("SELECT status,expected_count FROM operations WHERE destination=? AND post_key=? AND operation_key=?", key).fetchone()
            if not row:
                raise ValueError("Операция не найдена")
            if row["status"] == "sent":
                raise ValueError("Уже подтверждённое сообщение нельзя автоматически сбросить")
            if action == "sent" and (len(ids) != row["expected_count"] or len(set(ids)) != len(ids) or any(type(value) is not int or value <= 0 for value in ids)):
                raise ValueError(f"Для этой операции нужны все {row['expected_count']} ID сообщений: --message-ids 101,102,...")
            now = datetime.now(timezone.utc).isoformat()
            self.db.execute("UPDATE operations SET status=?,message_id=?,message_ids=?,error=NULL,updated_at=? WHERE destination=? AND post_key=? AND operation_key=?",
                            ("sent" if action == "sent" else "pending", ids[0] if ids else None,
                             json.dumps(ids) if ids else None, now, *key))
            self.db.execute("INSERT INTO audit(destination,post_key,operation_key,action,note,created_at) VALUES (?,?,?,?,?,?)",
                            (*key, action, note, now))


def deliver_one(session, token, chat_id, operation, root):
    payload = {"chat_id": chat_id, **operation["payload"]}
    if operation["method"] == "sendMediaGroup":
        with ExitStack() as stack:
            files = {}
            for item in operation["files"]:
                path = local_media_path(root, item["file"])
                stream = stack.enter_context(path.open("rb"))
                files[item["field"]] = (path.name, stream, item["mime_type"])
            payload["media"] = json.dumps(payload["media"], ensure_ascii=False)
            response = session.post(f"https://api.telegram.org/bot{token}/sendMediaGroup",
                data=payload, files=files, timeout=(15, 180))
    elif "file" in operation:
        path = local_media_path(root, operation["file"])
        # A local error after reserve is also treated as uncertain, conservatively.
        with path.open("rb") as stream:
            response = session.post(f"https://api.telegram.org/bot{token}/{operation['method']}",
                data=payload, files={operation["field"]: (path.name, stream, operation.get("mime_type", "application/octet-stream"))}, timeout=(15, 120))
    else:
        response = session.post(f"https://api.telegram.org/bot{token}/{operation['method']}", json=payload, timeout=(15, 60))
    # A 5xx or unparseable reply might follow successful publication.
    if response.status_code >= 500:
        return "unknown", None, "http_5xx"
    try:
        result = response.json()
    except ValueError:
        return "unknown", None, "invalid_response"
    if not isinstance(result, dict):
        return "unknown", None, "invalid_response"
    if response.status_code == 429 and result.get("ok") is False and result.get("error_code") == 429:
        parameters = result.get("parameters")
        retry_after = parameters.get("retry_after") if isinstance(parameters, dict) else None
        if type(retry_after) is int and retry_after >= 0:
            return "rate_limited", retry_after, "telegram_rejected_429"
    if result.get("ok") is False and 400 <= response.status_code < 500:
        return "failed", None, "telegram_rejected_" + str(result.get("error_code", response.status_code))
    message = result.get("result")
    if operation["method"] == "sendMediaGroup":
        if result.get("ok") is True and isinstance(message, list):
            ids = [item.get("message_id") for item in message if isinstance(item, dict)]
            expected = len(operation["files"])
            if len(ids) == expected and all(type(value) is int and value > 0 for value in ids) and len(set(ids)) == expected:
                return "sent", ids, None
        return "unknown", None, "incomplete_album_response"
    if result.get("ok") is True and isinstance(message, dict) and isinstance(message.get("message_id"), int):
        return "sent", message["message_id"], None
    return "unknown", None, "unconfirmed_response"


def legacy_operation_keys(post):
    # Old releases sent a separate source/date text and individual attachments.
    parts = [post.get("text", "")]
    for link in post.get("links", []):
        parts.append(f"{link['text']} — {link['url']}" if link.get("text") else link["url"])
    for video in post.get("videos", []):
        parts.append(f"Видео: {video.get('title') or 'без названия'}\n{video['url']}")
        if video.get("description"):
            parts.append(video["description"])
    if post.get("other_attachments") or post.get("reposts"):
        parts.append("Есть вложения, требующие проверки в исходной публикации.")
    parts.append(f"Источник: {post['url']}\nОпубликовано: {post['published_iso']}")
    keys = {f"text:{index}" for index, _ in enumerate(split_text("\n\n".join(value for value in parts if value)))}
    for kind in ("photos", "videos"):
        for item in post.get(kind, []):
            if not item.get("local_path") or (kind == "videos" and (item.get("download_status") == "link_only" or item.get("byte_size", 0) > 50 * 1024 * 1024)):
                continue
            keys.add(f"{kind}:{item['id']}")
    return keys


def send(root, manifest, token, chat_id, confirmation, allow_partial=False, session=None, database=None, interval=3.1):
    plan, errors = build_plan(root, manifest, chat_id, allow_partial)
    if errors:
        raise ValueError("\n".join(errors))
    if confirmation != digest(plan):
        raise ValueError("Код подтверждения не совпадает с предпросмотром. Выполните preview с тем же --chat-id.")
    if not token or ":" not in token:
        raise ValueError("Задайте TELEGRAM_BOT_TOKEN в окружении")
    destination = token.split(":", 1)[0] + ":" + str(chat_id)
    ledger = Ledger(Path(database) if database else Path(root) / "delivery.sqlite3")
    owned_session = session is None
    session = session or requests.Session()  # requests does not retry POST automatically.
    next_send = 0.0
    try:
        rows = ledger.rows()
        # An uncertain post must never be retried without checking Telegram.
        # It should not block an unrelated new post in a separate collection.
        post_keys = {post["key"] for post in manifest["posts"]}
        if any(row["destination"] == destination and row["post_key"] in post_keys and
               row["status"] in ("inflight", "unknown", "failed") for row in rows):
            raise RuntimeError("В журнале есть inflight/unknown/failed для выбранного поста. Сначала сверка в Telegram и команда resolve.")
        skip_posts = set()
        for post in manifest["posts"]:
            previous = [row for row in rows if row["destination"] == destination and row["post_key"] == post["key"] and not row["operation_key"].startswith(FORMAT_PREFIX)]
            if not previous:
                continue
            completed = {row["operation_key"] for row in previous if row["status"] == "sent"}
            if legacy_operation_keys(post) <= completed:
                skip_posts.add(post["key"])
            else:
                raise RuntimeError(f"{post['key']}: есть незавершённая отправка в старом формате. Нужна ручная сверка; повтор альбомом остановлен.")
        for operation in plan["operations"]:
            if operation["post_key"] in skip_posts:
                continue
            if "file" in operation:
                local_media_path(root, operation["file"])
            for item in operation.get("files", []):
                local_media_path(root, item["file"])
            while True:
                delay = next_send - time.monotonic()
                if delay > 0:
                    time.sleep(delay)  # Telegram rate pacing, never DOM readiness.
                if not ledger.reserve(destination, operation):
                    break
                try:
                    status, message_id, error = deliver_one(session, token, chat_id, operation, root)
                    next_send = time.monotonic() + interval
                except BaseException as exc:
                    # Do not log exception text: it can expose the bot token in a URL.
                    ledger.finish(destination, operation, "unknown", error=type(exc).__name__)
                    raise RuntimeError("Результат запроса неизвестен. Сверьте Telegram; автоматический повтор запрещён.") from None
                if status == "rate_limited":
                    # Telegram explicitly rejected the request: no message was sent.
                    # Save a retryable state before waiting so interruption is safe.
                    ledger.finish(destination, operation, "pending", error=error)
                    wait = message_id + 1
                    print(f"Telegram просит подождать {wait} с. Затем отправка продолжится автоматически.", flush=True)
                    time.sleep(wait)
                    continue
                ledger.finish(destination, operation, status, message_id, error)
                if status != "sent":
                    raise RuntimeError(f"Остановка: {status}; выполните ручную сверку и resolve.")
                print(f"Отправлено {operation['post_key']} / {operation['operation_key']}: message_id={message_id}", flush=True)
                break
    finally:
        ledger.close()
        if owned_session:
            session.close()
