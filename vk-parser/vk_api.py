"""Official VK API source (wall.get with a service key).

The browser source opens vk.ru like a visitor. From server addresses VK may ask
such browsers to prove they are human; the API is the supported way for programs
to read an open community wall, so the server uses it when VK_PARSER_VK_TOKEN is set.
"""
from __future__ import annotations

import csv
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from extract import extract_post, latest, refresh_status, write_json

API_URL = "https://api.vk.com/method/wall.get"
API_VERSION = "5.199"
USER_AGENT = "cvety-urala-vk-parser/1.0"
RETRYABLE = {6, 9, 10}  # too many requests per second, flood control, internal error
MESSAGES = {
    5: "ВК отклонил ключ доступа (VK_PARSER_VK_TOKEN): проверьте, что это сервисный ключ приложения и он не отозван",
    15: "ВК не даёт читать эту стену: сообщество закрытое или стена скрыта",
    18: "Страница ВК удалена или заблокирована",
    29: "Достигнут суточный лимит запросов к ВК; парсер продолжит позже",
    30: "Профиль/сообщество ВК закрыто",
    100: "ВК не нашёл такое сообщество: проверьте VK_PARSER_URL",
    113: "ВК не нашёл такое сообщество: проверьте VK_PARSER_URL",
    1116: "ВК отклонил ключ доступа (VK_PARSER_VK_TOKEN)",
}


class VkApiError(RuntimeError):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def wall_target(url):
    """https://vk.ru/cvetyurala -> {"domain": "cvetyurala"}; /club123 -> {"owner_id": -123}."""
    path = urlparse(url).path.strip("/").split("/")[0]
    if not path:
        raise ValueError("Укажите адрес стены/сообщества на vk.ru или vk.com")
    match = re.fullmatch(r"(?:club|public|event)(\d+)", path)
    if match:
        return {"owner_id": -int(match[1])}
    match = re.fullmatch(r"id(\d+)", path)
    if match:
        return {"owner_id": int(match[1])}
    if not re.fullmatch(r"[A-Za-z0-9_.]+", path):
        raise ValueError("Не удалось понять адрес сообщества ВК: " + path)
    return {"domain": path}


def fetch_wall(url, token, count, offset=0, session=None, attempts=3, sleep=time.sleep):
    """One wall.get page. The key goes in the POST body, never in URLs or messages."""
    if not token:
        raise ValueError("Не задан ключ доступа ВК (VK_PARSER_VK_TOKEN)")
    own = session is None
    session = session or requests.Session()
    params = {**wall_target(url), "count": max(1, min(100, int(count))), "offset": int(offset),
              "v": API_VERSION, "access_token": token}
    try:
        for attempt in range(attempts):
            try:
                response = session.post(API_URL, data=params, timeout=(10, 30), headers={"User-Agent": USER_AGENT})
                response.raise_for_status()
                data = response.json()
            except (requests.RequestException, ValueError) as exc:
                if attempt + 1 < attempts:
                    sleep(2 * (attempt + 1))
                    continue
                raise VkApiError("Нет ответа от API ВК (" + type(exc).__name__ + ")") from None
            error = data.get("error")
            if error:
                code = error.get("error_code")
                if code in RETRYABLE and attempt + 1 < attempts:
                    sleep(1.5 * (attempt + 1))
                    continue
                raise VkApiError(MESSAGES.get(code, f"API ВК вернул ошибку {code}: {error.get('error_msg', '')}"), code)
            body = data.get("response") or {}
            return int(body.get("count") or 0), list(body.get("items") or [])
    finally:
        if own:
            session.close()


def post_from_api(item):
    """Same post structure as the browser source; wall.get items use the JSON schema extract_post knows."""
    item = {"text": "", "attachments": [], **item}  # VK may omit empty fields
    key = f"{item.get('owner_id')}_{item.get('id')}"
    post = extract_post(key, data=item)
    post["sources"]["api"] = True
    # The browser source cross-checks JSON with the page; the official API is the source itself.
    post["issues"] = sorted(set(post["issues"]) - {"dom_post_not_found"})
    return refresh_status(post)


def scan(url, token, limit, session=None, sleep=time.sleep):
    """Newest `limit` posts plus a look-ahead, like the browser scan. Returns (selected, candidates, total)."""
    wanted = max(limit * 2, limit + 5) + 1  # +1: a pinned post is returned first regardless of its date
    items, offset, total = [], 0, 0
    while len(items) < wanted:
        total, batch = fetch_wall(url, token, wanted - len(items), offset, session=session, sleep=sleep)
        if not batch:
            break
        items.extend(batch)
        offset += len(batch)
        if offset >= total:
            break
    posts = {}
    for item in items:
        if item.get("owner_id") is None or item.get("id") is None:
            continue
        post = post_from_api(item)
        posts[post["key"]] = post
    return latest(posts.values(), limit), list(posts.values()), total


def api_collect(args, session=None):
    """`collect` through the API: the same run folder as the browser collect (without page snapshots)."""
    from collect import download_media

    output = Path(args.output).resolve()
    if (output / "manifest.json").exists():
        raise ValueError("Папка уже содержит результат. Укажите новую --output, чтобы сохранить журнал и файлы.")
    output.mkdir(parents=True, exist_ok=True)
    reason, posts, candidates, total = "vk_api", [], [], None
    try:
        posts, candidates, total = scan(args.url, args.vk_token, args.limit, session=session)
    except VkApiError as exc:
        reason = "vk_api_error:" + str(exc)
        print("Сбор прерван: " + str(exc), flush=True)
    if posts and not args.no_download:
        download_media(posts, output, None, args.download_videos)
    else:
        for post in posts:
            if post["photos"]:
                post["issues"].append("media_not_downloaded")
                refresh_status(post)
    owner_ids = sorted({p["owner_id"] for p in posts})
    target = min(args.limit, total) if total is not None else args.limit
    valid = bool(posts) and len(posts) == target and len(owner_ids) == 1 and reason == "vk_api"
    manifest = {"schema_version": 1, "source_url": args.url, "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_count": args.limit, "candidate_count": len(candidates), "wall_count_reported": total,
        "stop_reason": reason, "owner_id": owner_ids[0] if len(owner_ids) == 1 else None,
        "selection": {"valid": valid, "order": "oldest_to_newest", "unknown_date_keys": [],
            "lookahead_reached": len(candidates) > len(posts),
            "scope": "Newest by date from the official VK API wall.get (pinned post excluded unless it is among the newest)."},
        "posts": posts}
    for post in candidates:
        write_json(output / "posts" / (post["key"] + ".json"), post)
    write_json(output / "manifest.json", manifest)
    with (output / "posts.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["key", "published_iso", "status", "text", "url"])
        writer.writeheader()
        writer.writerows({k: p.get(k, "") for k in writer.fieldnames} for p in posts)
    return manifest
