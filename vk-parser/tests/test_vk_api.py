"""Official VK API source: no network, VK answers are simulated."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vk_api
from vk_api import VkApiError, api_collect, fetch_wall, post_from_api, scan, wall_target
from watcher import WatchStore

TOKEN = "service-key-secret"


def item(index, date=None, pinned=False, photo=True):
    data = {"owner_id": -10, "id": index, "date": date or 1793436200 + index * 60, "text": f"Пост {index}"}
    if pinned:
        data["is_pinned"] = 1
    if photo:
        data["attachments"] = [{"type": "photo", "photo": {"owner_id": -10, "id": 500 + index,
            "sizes": [{"type": "x", "url": f"https://sun9-1.userapi.com/s{index}.jpg", "width": 604, "height": 403}],
            "orig_photo": {"url": f"https://sun9-1.userapi.com/o{index}.jpg", "width": 1280, "height": 853}}}]
    return data


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    """Returns a wall of `items` (newest first, pinned on top) or queued raw answers."""
    def __init__(self, items=(), answers=()):
        self.items, self.answers, self.calls = list(items), list(answers), []

    def post(self, url, data=None, timeout=None, headers=None):
        self.calls.append({"url": url, "data": dict(data)})
        if self.answers:
            return FakeResponse(self.answers.pop(0))
        offset, count = data["offset"], data["count"]
        return FakeResponse({"response": {"count": len(self.items), "items": self.items[offset:offset + count]}})

    def close(self):
        pass


def wall(newest, oldest=1, pinned=None):
    items = [item(i) for i in range(newest, oldest - 1, -1)]
    if pinned is not None:
        items.insert(0, item(pinned, pinned=True))
        items = [x for i, x in enumerate(items) if i == 0 or x["id"] != pinned]
    return items


class VkApiTests(unittest.TestCase):
    def test_wall_address_forms(self):
        self.assertEqual(wall_target("https://vk.ru/cvetyurala"), {"domain": "cvetyurala"})
        self.assertEqual(wall_target("https://vk.com/club236279991"), {"owner_id": -236279991})
        self.assertEqual(wall_target("https://vk.ru/public5"), {"owner_id": -5})
        self.assertEqual(wall_target("https://vk.ru/id7"), {"owner_id": 7})
        with self.assertRaises(ValueError):
            wall_target("https://vk.ru/")

    def test_key_is_sent_in_body_and_never_in_url_or_errors(self):
        session = FakeSession(answers=[{"error": {"error_code": 5, "error_msg": "User authorization failed: " + TOKEN}}])
        with self.assertRaises(VkApiError) as caught:
            fetch_wall("https://vk.ru/cvetyurala", TOKEN, 10, session=session, sleep=lambda s: None)
        self.assertEqual(caught.exception.code, 5)
        self.assertNotIn(TOKEN, str(caught.exception))
        self.assertNotIn(TOKEN, session.calls[0]["url"])
        self.assertEqual(session.calls[0]["data"]["access_token"], TOKEN)
        self.assertEqual(session.calls[0]["data"]["domain"], "cvetyurala")

    def test_too_many_requests_is_retried(self):
        session = FakeSession(answers=[{"error": {"error_code": 6, "error_msg": "Too many requests per second"}},
                                       {"response": {"count": 1, "items": [item(1)]}}])
        total, items = fetch_wall("https://vk.ru/cvetyurala", TOKEN, 5, session=session, sleep=lambda s: None)
        self.assertEqual((total, len(items), len(session.calls)), (1, 1, 2))

    def test_missing_key_is_reported(self):
        with self.assertRaises(ValueError):
            fetch_wall("https://vk.ru/cvetyurala", "", 5, session=FakeSession())

    def test_api_post_is_complete_with_original_photo(self):
        post = post_from_api(item(3))
        self.assertEqual(post["status"], "complete", post["issues"])
        self.assertTrue(post["sources"]["api"])
        self.assertEqual(post["text"], "Пост 3")
        self.assertEqual(post["photos"][0]["source_url"], "https://sun9-1.userapi.com/o3.jpg")
        self.assertEqual(post["photos"][0]["quality"], "original_from_metadata")

    def test_text_only_post_without_attachments_field(self):
        post = post_from_api(item(4, photo=False))
        self.assertEqual((post["status"], post["photos"]), ("complete", []))

    def test_repost_still_requires_review(self):
        data = item(5)
        data["copy_history"] = [{"owner_id": -20, "id": 1, "text": "чужой пост"}]
        self.assertEqual(post_from_api(data)["status"], "partial")

    def test_scan_selects_newest_and_skips_old_pinned_post(self):
        session = FakeSession(wall(20, pinned=2))
        selected, candidates, total = scan("https://vk.ru/cvetyurala", TOKEN, 3, session=session)
        self.assertEqual([p["post_id"] for p in selected], [18, 19, 20])  # oldest -> newest
        self.assertIn("-10_2", {p["key"] for p in candidates})
        self.assertEqual(total, 20)
        self.assertEqual(len(session.calls), 1)

    def test_scan_pages_through_large_catchup(self):
        session = FakeSession(wall(300))
        selected, candidates, total = scan("https://vk.ru/cvetyurala", TOKEN, 60, session=session)
        self.assertEqual(len(selected), 60)
        self.assertEqual([c["data"]["offset"] for c in session.calls], [0, 100])
        self.assertEqual(len(candidates), 121)

    def test_collect_writes_a_publishable_run_folder(self):
        def downloaded(posts, output, driver, download_videos=False):
            self.assertIsNone(driver)
            for post in posts:
                for photo in post["photos"]:
                    photo.update(download_status="downloaded", local_path="media/x.jpg", sha256="0")
        args = SimpleNamespace(url="https://vk.ru/cvetyurala", vk_token=TOKEN, limit=3, no_download=False, download_videos=True)
        with tempfile.TemporaryDirectory() as temp, patch("collect.download_media", side_effect=downloaded):
            args.output = temp
            manifest = api_collect(args, session=FakeSession(wall(10)))
            self.assertTrue(manifest["selection"]["valid"])
            self.assertEqual([p["status"] for p in manifest["posts"]], ["complete"] * 3)
            self.assertTrue((Path(temp) / "posts.csv").exists())
            saved = json.loads((Path(temp) / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["stop_reason"], "vk_api")

    def test_collect_reports_api_error_without_crashing(self):
        args = SimpleNamespace(url="https://vk.ru/cvetyurala", vk_token=TOKEN, limit=3, no_download=False, download_videos=True)
        with tempfile.TemporaryDirectory() as temp:
            args.output = temp
            manifest = api_collect(args, session=FakeSession(answers=[{"error": {"error_code": 15, "error_msg": "Access denied"}}]))
            self.assertFalse(manifest["selection"]["valid"])

    def test_watch_uses_api_without_browser_and_queues_only_new_posts(self):
        from watcher import watch
        walls = [wall(10), wall(11)]

        def fake_scan(url, token, limit, session=None, sleep=None):
            self.assertEqual(token, TOKEN)
            return scan(url, token, limit, session=FakeSession(walls.pop(0) if len(walls) > 1 else walls[0]))

        def downloaded(posts, output, driver, download_videos=False):
            self.assertIsNone(driver)
            for post in posts:
                for photo in post["photos"]:
                    path = Path(output) / "media" / (photo["id"] + ".jpg")
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"jpg")
                    photo.update(download_status="downloaded", local_path=path.relative_to(output).as_posix(),
                                 sha256=vk_api.__name__, mime_type="image/jpeg", byte_size=3)

        with tempfile.TemporaryDirectory() as temp:
            args = SimpleNamespace(url="https://vk.ru/cvetyurala", output=temp, limit=3, interval=15, max_catchup=100,
                                   cycles=2, telegram=False, publish_existing=False, db=str(Path(temp) / "d.sqlite3"),
                                   download_videos=False, vk_token=TOKEN)
            with patch("vk_api.scan", side_effect=fake_scan), patch("collect.download_media", side_effect=downloaded), \
                 patch("collect.make_driver", side_effect=AssertionError("browser must not start")), \
                 patch("watcher.pause"):
                watch(args)
            store = WatchStore(Path(temp) / "watch.sqlite3")
            try:
                rows = {row["post_key"]: row for row in store.rows("https://vk.ru/cvetyurala")}
            finally:
                store.close()
            self.assertEqual(rows["-10_11"]["state"], "saved")
            self.assertEqual(rows["-10_11"]["eligible"], 1)
            self.assertEqual(rows["-10_10"]["eligible"], 0)  # initial selection is archived, not published
            self.assertEqual(rows["-10_10"]["state"], "saved")


if __name__ == "__main__":
    unittest.main()
