"""Download an actual accessible video source, with a visible link fallback."""
from pathlib import Path
import re
import shutil

from extract import file_hash


class QuietLogger:
    def debug(self, message):
        pass
    def warning(self, message):
        pass
    def error(self, message):
        pass


def download_video(video, post_key, output, driver=None):
    output = Path(output).resolve()
    if video.get("local_path"):
        existing = (output / video["local_path"]).resolve()
        if output in existing.parents and existing.is_file() and file_hash(existing) == video.get("sha256"):
            return True
    try:
        import yt_dlp
        folder = output / "media" / post_key
        folder.mkdir(parents=True, exist_ok=True)
        stem = "video_" + re.sub(r"[^\w-]", "_", video["id"])
        options = {
            "outtmpl": str(folder / (stem + ".%(ext)s")),
            "format": "best[ext=mp4][height<=720]/best[height<=720]/best",
            "noplaylist": True, "quiet": True, "no_warnings": True,
            "logger": QuietLogger(), "socket_timeout": 30,
            "retries": 2, "fragment_retries": 2,
            "max_filesize": 250 * 1024 * 1024,
            "cachedir": False, "overwrites": False,
        }
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except ImportError:
                pass
        if ffmpeg:
            options["ffmpeg_location"] = ffmpeg
        with yt_dlp.YoutubeDL(options) as downloader:
            if driver:
                import http.cookiejar
                for item in driver.get_cookies():
                    domain = item.get("domain", "")
                    if not (domain.lstrip(".") in ("vk.ru", "vk.com") or domain.endswith((".vk.ru", ".vk.com"))):
                        continue
                    downloader.cookiejar.set_cookie(http.cookiejar.Cookie(
                        version=0, name=item["name"], value=item["value"], port=None,
                        port_specified=False, domain=domain, domain_specified=True,
                        domain_initial_dot=domain.startswith("."), path=item.get("path", "/"),
                        path_specified=True, secure=item.get("secure", True),
                        expires=item.get("expiry"), discard="expiry" not in item,
                        comment=None, comment_url=None, rest={}, rfc2109=False))
            info = downloader.extract_info(video["url"], download=True)
            if not info or info.get("has_drm"):
                raise ValueError("No accessible unprotected video")
            candidates = [folder / (stem + "." + str(info.get("ext", "mp4")))]
            candidates += [Path(x["filepath"]) for x in info.get("requested_downloads", []) if x.get("filepath")]
            path = next((p.resolve() for p in candidates if p.is_file() and output in p.resolve().parents), None)
            if not path or path.stat().st_size == 0:
                raise ValueError("Video file was not produced")
            video.update(download_status="downloaded", local_path=path.relative_to(output).as_posix(),
                sha256=file_hash(path), byte_size=path.stat().st_size,
                mime_type="video/mp4" if path.suffix.lower() == ".mp4" else "video/" + path.suffix.lstrip("."),
                duration=info.get("duration"), width=info.get("width"), height=info.get("height"),
                download_source="yt_dlp")
            video.pop("download_error", None)
            return True
    except Exception as exc:
        # Preserve a usable title and page link; never print signed URLs/cookies.
        video.update(download_status="link_only", local_path=None, download_error=type(exc).__name__)
        print(f"Видео {video.get('id')}: файл недоступен, сохранены название и ссылка ({type(exc).__name__})", flush=True)
        return False
