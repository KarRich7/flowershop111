"""Pure extraction: a post can only be joined on (owner_id, post_id)."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

BASE = "https://vk.ru/"
ID_RE = re.compile(r"(?:wall|post)?(-?\d+)_(\d+)")
DEFAULT_SELECTORS = Path(__file__).with_name("selectors.json")


def load_selectors(path=None):
    return json.loads(Path(path or DEFAULT_SELECTORS).read_text(encoding="utf-8"))


def identity(value):
    match = ID_RE.fullmatch(str(value or ""))
    return f"{int(match[1])}_{int(match[2])}" if match else None


def dom_identity(node):
    return identity(node.get("data-post-id")) or identity(node.get("id"))


def absolute(value):
    if not value:
        return ""
    value = urljoin(BASE, str(value or ""))
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return ""
    if parsed.hostname in ("vk.ru", "vk.com") and parsed.path == "/away.php":
        return absolute(parse_qs(parsed.query).get("to", [value])[0]) if "to" in parse_qs(parsed.query) else value
    return value


def unique(items, key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False)):
    result, seen = [], set()
    for item in items:
        marker = key(item)
        if marker not in seen:
            seen.add(marker)
            result.append(item)
    return result


def text_from_html(node):
    """Keep text nodes, line breaks, paragraph boundaries and image emoji alt."""
    def walk(part):
        if isinstance(part, NavigableString):
            return str(part)
        if not isinstance(part, Tag) or part.name in ("script", "style"):
            return ""
        if part.name == "br":
            return "\n"
        if part.name == "img":
            return part.get("alt", "") if "emoji" in " ".join(part.get("class", [])) else ""
        value = "".join(walk(child) for child in part.children)
        if part.name == "p":
            return "\n\n" + value + "\n\n"
        if part.name in ("div", "li"):
            return "\n" + value + "\n"
        return value
    return re.sub(r"\n[ \t]+", "\n", re.sub(r"\n{3,}", "\n\n", walk(node))).strip()


def json_text(raw):
    links = []
    def mention(match):
        target, title = match.groups()
        url = absolute(target if target.startswith(("http://", "https://")) else "/" + target)
        links.append({"text": title, "url": url})
        return title
    text = re.sub(r"\[([^\[\]|]+)\|([^\[\]]+)\]", mention, str(raw or ""))
    for match in re.finditer(r"https?://[^\s<>\[\]]+", text):
        url = match[0].rstrip(".,;!?)")
        links.append({"text": url, "url": url})
    return text, links


def machine_date(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        if number > 100_000_000_000:
            number /= 1000
        return int(number) if 1_000_000_000 <= number < 10_000_000_000 else None
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return int(parsed.timestamp()) if parsed.tzinfo else None
        except ValueError:
            return None


def index_json(value):
    """Do not mistake photos, videos or comments for wall posts."""
    found = {}
    def visit(node):
        if isinstance(node, dict):
            is_post = node.get("post_type") in ("post", "copy") or node.get("inner_type") == "wall_wallpost"
            if is_post and "owner_id" in node and "id" in node:
                key = identity(f"{node['owner_id']}_{node['id']}")
                if key:
                    found[key] = node
            for field, child in node.items():
                if field == "copy_history":
                    continue  # A repost is content of the outer post, not a wall candidate.
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return found


def embedded_json(html):
    """Decode JSON, never eval JavaScript or search a neighbour's HTML."""
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    decoder = json.JSONDecoder()
    for script in soup.select("script"):
        text = script.string or script.get_text()
        if script.get("type") in ("application/json", "application/ld+json"):
            try:
                found.update(index_json(json.loads(text)))
            except ValueError:
                pass
        for match in re.finditer(r"(?:apiPrefetchCache|__INITIAL_STATE__|__NEXT_DATA__)\s*=\s*", text):
            try:
                value, _ = decoder.raw_decode(text[match.end():])
                found.update(index_json(value))
            except ValueError:
                pass
    return found


def image_candidates(node):
    result = []
    for attr in ("src", "data-src", "data-original", "data-lazy-src", "data-src-big", "data-src-large"):
        url = absolute(node.get(attr)) if node.get(attr) else ""
        if url:
            result.append({"url": url, "width": 0, "height": 0, "attribute": attr})
    for attr in ("srcset", "data-srcset"):
        # VK URLs themselves contain commas (e.g. ?as=32x43,48x64).
        for match in re.finditer(r"(?:^|,\s*)(\S+?)\s+(\d+(?:\.\d+)?)(w|x)(?=\s*(?:,|$))", node.get(attr, "")):
            url, size, unit = match.groups()
            result.append({"url": absolute(url), "width": float(size) if unit == "w" else 0, "height": 0, "attribute": attr})
    return unique(result, key=lambda item: item["url"])


def photo_from_json(photo):
    sizes = [x for x in photo.get("sizes", []) if absolute(x.get("url"))]
    original = photo.get("orig_photo") or {}
    if original.get("url"):
        best, quality = original, "original_from_metadata"
    elif sizes:
        best, quality = max(sizes, key=lambda x: x.get("width", 0) * x.get("height", 0)), "largest_available"
    else:
        best, quality = {}, "unavailable"
    return {"id": f"{photo.get('owner_id')}_{photo.get('id')}",
            "url": f"{BASE}photo{photo.get('owner_id')}_{photo.get('id')}",
            "source_url": absolute(best["url"]) if best.get("url") else None,
            "width": best.get("width"), "height": best.get("height"), "quality": quality,
            "download_status": "pending", "local_path": None,
            "candidates": [{"url": absolute(x["url"]), "width": x.get("width"), "height": x.get("height")} for x in sizes]}


def video_from_json(video):
    files = video.get("files") or {}
    sources = [{"url": absolute(url), "quality": name} for name, url in files.items()
               if re.fullmatch(r"mp4_\d+", name) and isinstance(url, str) and absolute(url)]
    return {"id": f"{video.get('owner_id')}_{video.get('id')}", "title": video.get("title", ""),
            "description": video.get("description", ""),
            "url": f"{BASE}video{video.get('owner_id')}_{video.get('id')}",
            "direct_sources": sources, "download_allowed": bool(video.get("can_download")),
            "download_status": "link_only", "local_path": None}


def extract_post(key, html=None, data=None, selectors=None):
    selectors = selectors or load_selectors()
    if not identity(key):
        raise ValueError("Некорректный ID поста")
    if data is not None and identity(f"{data.get('owner_id')}_{data.get('id')}") != key:
        raise ValueError("JSON относится к другому посту")
    owner, post_id = map(int, key.split("_"))
    post = {"key": key, "owner_id": owner, "post_id": post_id, "url": f"{BASE}wall{key}",
            "published_at": None, "published_iso": None, "text": "", "raw_text": None,
            "links": [], "photos": [], "videos": [], "other_attachments": [], "reposts": [],
            "sources": {"json": data is not None, "dom": False}, "issues": [], "status": "unavailable"}
    dom_text, dom_photos, dom_videos = "", [], []
    folded = False
    if html:
        soup = BeautifulSoup(html, "html.parser")
        root = next((x for x in soup.select(selectors["post"]) if dom_identity(x) == key), None)
        if root:
            post["sources"]["dom"] = True
            # Remove nested posts and comments before looking for ANY field.
            for nested in list(root.select(selectors["post"])):
                nested.decompose()
            for excluded in list(root.select(selectors["exclude"])):
                excluded.decompose()
            for date in root.select(selectors["date"]):
                for attr in ("datetime", "data-ts", "data-date", "data-timestamp"):
                    post["published_at"] = post["published_at"] or machine_date(date.get(attr))
            content = root.select_one(selectors["content"]) or root
            text_node = content.select_one(selectors["text"])
            if text_node:
                folded = bool(text_node.select_one(selectors["more"]))
                inner = text_node.select_one(selectors["text_inner"])
                if inner:
                    dom_text = text_from_html(inner)
                else:
                    for more in list(text_node.select(selectors["more"])):
                        more.decompose()
                    dom_text = text_from_html(text_node)
                for anchor in text_node.select("a[href]"):
                    url = absolute(anchor.get("href"))
                    if url:
                        post["links"].append({"text": text_from_html(anchor), "url": url})
            for anchor in content.select(selectors["photo"]):
                if text_node and anchor in text_node.descendants:
                    continue
                images = anchor.select("img, source")
                candidates = unique([x for node in images for x in image_candidates(node)], key=lambda item: item["url"])
                if candidates:
                    best = max(candidates, key=lambda item: (item["attribute"] in ("data-original", "data-src-big"), item["width"]))
                    match = re.search(r"photo(-?\d+_\d+)", anchor.get("href", ""))
                    dom_photos.append({"id": match[1] if match else hashlib.sha256(best["url"].encode()).hexdigest()[:16],
                        "url": absolute(anchor.get("href")), "source_url": best["url"],
                        "quality": "dom_resolution_unverified", "candidates": candidates,
                        "download_status": "pending", "local_path": None})
            for anchor in content.select(selectors["video"]):
                if text_node and anchor in text_node.descendants:
                    continue
                match = re.search(r"(?:video|clip)(-?\d+_\d+)", anchor.get("href", ""))
                dom_videos.append({"id": match[1] if match else anchor.get("data-video", ""),
                    "title": anchor.get("aria-label") or anchor.get("title") or text_from_html(anchor),
                    "url": absolute(anchor.get("href")), "direct_sources": [], "download_allowed": False,
                    "download_status": "link_only", "local_path": None})
    if data is not None:
        post["published_at"] = machine_date(data.get("date")) or post["published_at"]
        post["raw_text"] = data.get("text")
        post["text"], links = json_text(data.get("text", ""))
        post["links"].extend(links)
        for item in data.get("attachments", []):
            kind = item.get("type")
            value = item.get(kind) or {}
            if kind == "photo":
                post["photos"].append(photo_from_json(value))
            elif kind == "video":
                post["videos"].append(video_from_json(value))
            elif kind == "link":
                post["links"].append({"text": value.get("title", ""), "url": absolute(value.get("url"))})
            elif kind == "action_button" and (value.get("action") or {}).get("url"):
                post["links"].append({"text": value.get("title", ""), "url": absolute(value["action"]["url"])})
            elif kind == "action_button" and (value.get("action") or {}).get("type") == "open_conversation" and value["action"].get("peer_id"):
                post["links"].append({"text": value.get("title", ""), "url": f"{BASE}im?sel={value['action']['peer_id']}"})
            else:
                post["other_attachments"].append({"type": kind, "title": value.get("title"), "url": value.get("url")})
                post["issues"].append("unsupported_attachment:" + str(kind))
        post["reposts"] = [{"owner_id": x.get("owner_id"), "post_id": x.get("id"),
                            "text": x.get("text"), "url": f"{BASE}wall{x.get('owner_id')}_{x.get('id')}"}
                           for x in data.get("copy_history", [])]
        if post["reposts"]:
            post["issues"].append("repost_requires_review")
        if not all(field in data for field in ("date", "text", "attachments")):
            post["issues"].append("incomplete_json_schema")
        if data.get("is_deleted") or data.get("is_unavailable"):
            post["issues"].append("post_unavailable")
        if dom_text and re.sub(r"\s+", "", dom_text) != re.sub(r"\s+", "", post["text"]):
            post["issues"].append("text_sources_disagree")
            post["dom_text"] = dom_text
    else:
        post["text"] = dom_text
        post["issues"].append("json_post_not_found")
        if folded:
            post["issues"].append("text_not_expanded")
    if not post["sources"]["dom"]:
        post["issues"].append("dom_post_not_found")
    for field, dom_values in (("photos", dom_photos), ("videos", dom_videos)):
        by_id = {x["id"]: x for x in post[field]}
        for item in dom_values:
            if item["id"] in by_id:
                by_id[item["id"]]["dom_verified"] = True
                if field == "photos":
                    by_id[item["id"]]["candidates"].extend(item["candidates"])
            else:
                post[field].append(item)
                if data is not None:
                    post["issues"].append("attachment_sources_disagree")
    if any(x.get("quality") in ("unavailable", "dom_resolution_unverified") for x in post["photos"]):
        post["issues"].append("photo_resolution_unverified")
    if any(not x.get("title") or not x.get("url") for x in post["videos"]):
        post["issues"].append("video_metadata_missing")
    if post["published_at"] is None:
        post["issues"].append("machine_date_missing")
    else:
        post["published_iso"] = datetime.fromtimestamp(post["published_at"], timezone.utc).isoformat()
    post["links"] = unique([x for x in post["links"] if x.get("url")])
    post["issues"] = sorted(set(post["issues"]))
    return refresh_status(post)


def refresh_status(post):
    if not any((post["sources"]["json"], post["sources"]["dom"])) or "post_unavailable" in post["issues"]:
        post["status"] = "unavailable"
    else:
        post["status"] = "partial" if post["issues"] else "complete"
    return post


def latest(posts, limit=10):
    dated = {x["key"]: x for x in posts if x.get("published_at") is not None}
    chosen = sorted(dated.values(), key=lambda x: (x["published_at"], x["owner_id"], x["post_id"]), reverse=True)[:limit]
    return list(reversed(chosen))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
