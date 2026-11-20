import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract import extract_post, file_hash, write_json
from watcher import WatchStore, acquire_lock, deliver_pending, one_post_manifest, source_key
from telegram_send import build_plan
from verify_saved import verify


def post(index, date=None):
    return extract_post(f"-10_{index}", f'<div data-testid="post" data-post-id="-10_{index}"><span data-testid="post_text">Пост {index}</span></div>',
        {"owner_id": -10, "id": index, "date": date or 1793436200 + index, "text": f"Пост {index}", "attachments": []})


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = "https://vk.ru/example"
        self.path = self.root / "watch.sqlite3"
        self.store = WatchStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_restart_remembers_baseline_and_only_enqueues_new_ids(self):
        initial = [post(1), post(2)]
        self.assertEqual(self.store.ingest(self.source, initial, initial), 2)
        self.assertFalse(any(row["eligible"] for row in self.store.rows(self.source)))
        self.store.close()
        self.store = WatchStore(self.path)
        newer = [post(2), post(3)]
        self.assertEqual(self.store.ingest(self.source, newer, newer), 1)
        self.assertEqual(self.store.ingest(self.source, newer, newer), 0)
        self.assertEqual([row["post_key"] for row in self.store.rows(self.source) if row["eligible"]], ["-10_3"])

    def test_no_overlap_refuses_to_advance_or_lose_posts(self):
        self.store.ingest(self.source, [post(1), post(2)], [post(1), post(2)])
        with self.assertRaises(ValueError):
            self.store.ingest(self.source, [post(8), post(9)], [post(8), post(9)])
        self.assertEqual(self.store.known(self.source), {"-10_1", "-10_2"})
        catchup = [post(index) for index in range(2, 10)]
        self.assertEqual(self.store.ingest(self.source, catchup, catchup), 7)

    def test_new_same_second_is_not_lost(self):
        initial = post(1, 1793436232)
        self.store.ingest(self.source, [initial], [initial])
        newer = post(2, 1793436232)
        self.assertEqual(self.store.ingest(self.source, [initial, newer], [initial, newer]), 1)

    def test_old_backfilled_posts_are_not_treated_as_new(self):
        self.store.ingest(self.source, [post(10), post(11)], [post(10), post(11)])
        older = post(1)
        self.store.ingest(self.source, [older, post(11), post(12)], [older, post(11), post(12)])
        row = next(row for row in self.store.rows(self.source) if row["post_key"] == older["key"])
        self.assertEqual(row["state"], "baseline")

    def save(self, value):
        folder = self.root / value["key"]
        write_json(folder / "manifest.json", one_post_manifest(value, self.source))
        self.store.archived(self.source, value["key"], value, folder)

    def test_delivery_failure_preserves_queue_and_order(self):
        values = [post(1), post(2)]
        self.store.ingest(self.source, values, values, publish_existing=True)
        for value in values:
            self.save(value)
        calls = []
        def interrupted(folder, manifest, *args, **kwargs):
            calls.append(manifest["posts"][0]["key"])
            raise RuntimeError("unknown")
        with self.assertRaises(RuntimeError):
            deliver_pending(self.store, self.source, "1:fake", "-1001", self.root / "delivery.db", sender=interrupted)
        self.assertEqual(calls, ["-10_1"])
        self.assertFalse(any(row["delivered"] for row in self.store.rows(self.source)))
        def ok(folder, manifest, *args, **kwargs):
            calls.append(manifest["posts"][0]["key"])
        self.assertEqual(deliver_pending(self.store, self.source, "1:fake", "-1001", self.root / "delivery.db", sender=ok), 2)
        self.assertEqual(deliver_pending(self.store, self.source, "1:fake", "-1001", self.root / "delivery.db", sender=ok), 0)
        self.assertEqual(calls, ["-10_1", "-10_1", "-10_2"])

    def test_incomplete_earlier_post_blocks_later_publication(self):
        values = [post(1), post(2)]
        self.store.ingest(self.source, values, values, publish_existing=True)
        self.save(values[1])
        self.assertEqual(deliver_pending(self.store, self.source, "1:fake", "-1001", self.root / "d.db", sender=lambda *a, **k: self.fail("sent")), 0)

    def test_same_second_posts_are_delivered_in_numeric_vk_order(self):
        values = [post(10, 1793436232), post(2, 1793436232)]
        self.store.ingest(self.source, values, values, publish_existing=True)
        for value in values:
            self.save(value)
        sent = []
        def record(folder, manifest, *args, **kwargs):
            sent.append(manifest["posts"][0]["post_id"])
        self.assertEqual(deliver_pending(self.store, self.source, "1:fake", "-1001", self.root / "d.db", sender=record), 2)
        self.assertEqual(sent, [2, 10])

    def test_single_instance_archive_lock(self):
        lock = acquire_lock(self.root)
        try:
            with self.assertRaises(RuntimeError):
                acquire_lock(self.root)
        finally:
            lock.close()
        acquire_lock(self.root).close()

    def test_source_aliases_share_state(self):
        self.assertEqual(source_key("https://vk.com/Example/?from=other"), self.source)

    def test_pending_post_refreshes_expired_urls_without_losing_saved_files(self):
        original = post(1)
        original["photos"] = [{"id": "-10_7", "source_url": "https://example.org/expired",
            "local_path": "media/photo.jpg", "sha256": "saved-hash", "download_status": "downloaded"}]
        self.store.ingest(self.source, [original], [original])
        fresh = copy.deepcopy(original)
        fresh["photos"][0].update(source_url="https://example.org/fresh", local_path=None, download_status="pending")
        self.store.ingest(self.source, [fresh], [fresh])
        saved = json.loads(self.store.rows(self.source)[0]["data"])
        self.assertEqual(saved["photos"][0]["source_url"], "https://example.org/fresh")
        self.assertEqual(saved["photos"][0]["local_path"], "media/photo.jpg")

    def test_ctrl_c_during_scan_reaches_watcher(self):
        from collect import _collect_with_driver
        args = SimpleNamespace(selectors=None, manual=False, url=self.source, timeout=1, watch_mode=True)
        with patch("collect.Collector") as collector:
            collector.return_value.open.side_effect = KeyboardInterrupt()
            with self.assertRaises(KeyboardInterrupt):
                _collect_with_driver(args, object(), self.root)

    def test_verify_detects_missing_and_changed_video_bytes(self):
        value = post(1)
        path = self.root / "video.mp4"
        path.write_bytes(b"video test bytes")
        value["videos"] = [{"id": "-10_99", "title": "Видео", "url": "https://vk.ru/video-10_99",
            "local_path": "video.mp4", "download_status": "downloaded", "mime_type": "video/mp4", "sha256": file_hash(path)}]
        manifest = one_post_manifest(value, self.source)
        write_json(self.root / "manifest.json", manifest)
        self.assertTrue(verify(self.root)["ok"])
        plan, errors = build_plan(self.root, manifest, "-1001")
        self.assertFalse(errors)
        self.assertEqual(plan["operations"][-1]["method"], "sendVideo")
        path.write_bytes(b"changed")
        self.assertFalse(verify(self.root)["ok"])
        path.unlink()
        self.assertFalse(verify(self.root)["ok"])


class SettingsTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows DPAPI")
    def test_token_is_protected_and_roundtrips_without_plaintext(self):
        from settings import protect_token
        token = "12345:fake-test-token"
        encrypted = protect_token(token)
        self.assertNotIn(token, encrypted)
        self.assertEqual(protect_token(encrypted, decrypt=True), token)

    def test_setup_checks_channel_permissions_and_stores_numeric_destination(self):
        import settings
        calls = []
        def read(token, method, params=None):
            calls.append(method)
            return {"getMe": {"id": 123, "username": "test_bot"},
                    "getChat": {"id": -100123, "type": "channel", "title": "Тестовый канал"},
                    "getChatMember": {"status": "administrator", "can_post_messages": True}}[method]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            with patch.object(settings, "api_read", side_effect=read):
                value = settings.setup_telegram(path, input_fn=lambda prompt: "@channel", secret_fn=lambda prompt: "123:fake-only")
            self.assertEqual(value["telegram"]["chat_id"], "-100123")
            self.assertNotIn("123:fake-only", path.read_text(encoding="utf-8"))
            self.assertEqual(calls, ["getMe", "getChat", "getChatMember"])

    def test_setup_refuses_missing_publication_rights(self):
        import settings
        def read(token, method, params=None):
            return {"getMe": {"id": 123}, "getChat": {"id": -1001, "type": "channel"},
                    "getChatMember": {"status": "member"}}[method]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "settings.json"
            with patch.object(settings, "api_read", side_effect=read), self.assertRaises(ValueError):
                settings.setup_telegram(path, input_fn=lambda prompt: "@channel", secret_fn=lambda prompt: "123:fake")
            self.assertFalse(path.exists())

    def test_python_without_arguments_opens_menu(self):
        from vk_parser import main
        with patch("builtins.input", return_value="0"):
            self.assertEqual(main([]), 0)

    def test_interactive_number_reprompts_invalid_input(self):
        from interactive import number
        with patch("builtins.input", side_effect=["bad", "0", "5"]):
            self.assertEqual(number("Количество", 10), 5)


class VideoTests(unittest.TestCase):
    def test_unavailable_video_keeps_title_and_link(self):
        from video_download import download_video
        value = {"id": "-10_99", "url": "https://vk.ru/video-10_99", "title": "Название"}
        unavailable = SimpleNamespace(YoutubeDL=lambda options: (_ for _ in ()).throw(RuntimeError("not available")))
        with tempfile.TemporaryDirectory() as temp, patch.dict(sys.modules, {"yt_dlp": unavailable}):
            self.assertFalse(download_video(value, "-10_1", temp))
        self.assertEqual(value["url"], "https://vk.ru/video-10_99")
        self.assertEqual(value["title"], "Название")
        self.assertEqual(value["download_status"], "link_only")

    def test_saved_video_is_not_downloaded_again(self):
        from video_download import download_video
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "video.mp4"
            path.write_bytes(b"saved")
            value = {"id": "-10_99", "local_path": "video.mp4", "sha256": file_hash(path)}
            unavailable = SimpleNamespace(YoutubeDL=lambda options: self.fail("Repeated download"))
            with patch.dict(sys.modules, {"yt_dlp": unavailable}):
                self.assertTrue(download_video(value, "-10_1", temp))
