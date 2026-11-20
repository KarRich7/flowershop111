import json
from pathlib import Path
from extract import file_hash


def verify(folder):
    root = Path(folder).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    errors, photos, videos = [], 0, 0
    posts = manifest["posts"]
    if not manifest.get("selection", {}).get("valid"):
        errors.append("Выборка не подтверждена")
    if len({post["key"] for post in posts}) != len(posts):
        errors.append("Повторяющиеся ID")
    dates = [post.get("published_at") for post in posts]
    if any(date is None for date in dates) or dates != sorted(date for date in dates if date is not None):
        errors.append("Не подтверждён порядок дат")
    for post in posts:
        if post["status"] != "complete":
            errors.append(f"{post['key']}: {post['status']}: {', '.join(post['issues'])}")
        for kind in ("photos", "videos"):
            for item in post[kind]:
                if not item.get("local_path"):
                    if kind == "photos":
                        errors.append(f"Нет файла фото {item['id']}")
                    elif not item.get("url"):
                        errors.append(f"Нет ни файла, ни ссылки видео {item['id']}")
                    continue
                path = (root / item["local_path"]).resolve()
                if root not in path.parents or not path.is_file():
                    errors.append(f"Отсутствует файл {item['local_path']}")
                elif file_hash(path) != item.get("sha256"):
                    errors.append(f"Не совпадает SHA-256 {item['local_path']}")
                elif kind == "photos":
                    photos += 1
                else:
                    videos += 1
    return {"posts": len(posts), "photos": photos, "video_files": videos,
            "video_links_only": sum(not item.get("local_path") for post in posts for item in post["videos"]),
            "errors": errors, "ok": not errors}
