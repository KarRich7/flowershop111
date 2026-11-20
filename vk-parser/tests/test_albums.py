import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract import file_hash
from telegram_send import (Ledger, ORDER_FOOTER, build_plan, digest, legacy_operation_keys,
                           post_body, post_message, publication_parts, send)
from test_delivery import Response, Session, manifest


class AlbumSession(Session):
    def __init__(self, response=None, failure=None):
        super().__init__(response=response, failure=failure)
        self.requests, self.streams = [], []

    def post(self, url, **kwargs):
        self.calls += 1
        self.requests.append((url, kwargs))
        self.streams.extend(item[1] for item in kwargs.get("files", {}).values())
        if self.failure:
            raise self.failure
        if self.response.body != {"ok": True, "result": {"message_id": 123}}:
            return self.response
        if url.endswith("/sendMediaGroup"):
            media = json.loads(kwargs["data"]["media"])
            assert len(media) == len(kwargs["files"])
            assert all(not item[1].closed and item[1].read() for item in kwargs["files"].values())
            return Response(body={"ok": True, "result": [{"message_id": 100 + i} for i in range(len(media))]})
        return Response()


class AlbumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        footer = patch("telegram_send.read_footer", return_value=ORDER_FOOTER)
        footer.start()
        self.addCleanup(footer.stop)

    def tearDown(self):
        self.temp.cleanup()

    def data(self, photos=4, video=False):
        data = manifest()
        value = data["posts"][0]
        for i in range(photos):
            path = self.root / f"photo{i}.jpg"
            path.write_bytes(b"photo " + str(i).encode())
            value["photos"].append({"id": f"-10_{1000+i}", "local_path": path.name,
                "mime_type": "image/jpeg", "download_status": "downloaded", "sha256": file_hash(path)})
        if video:
            path = self.root / "video.mp4"
            path.write_bytes(b"video")
            value["videos"].append({"id": "-10_99", "title": "Ролик", "url": "https://vk.ru/video-10_99",
                "local_path": path.name, "mime_type": "video/mp4", "download_status": "downloaded", "sha256": file_hash(path)})
        return data

    def test_post_has_exact_footer_and_no_generated_source_or_date(self):
        value = manifest()["posts"][0]
        value["text"] += "\n\n" + ORDER_FOOTER
        message = post_message(value)
        self.assertTrue(message.endswith(ORDER_FOOTER))
        self.assertEqual(message.count(ORDER_FOOTER), 1)
        self.assertNotIn("Источник:", message)
        self.assertNotIn("Опубликовано:", message)
        self.assertNotIn(value["published_iso"], message)

    def test_four_photos_are_one_album_with_caption(self):
        data = self.data()
        plan, errors = build_plan(self.root, data, "@channel")
        self.assertFalse(errors)
        self.assertEqual(len(plan["operations"]), 1)
        operation = plan["operations"][0]
        self.assertEqual(operation["method"], "sendMediaGroup")
        self.assertEqual(len(operation["files"]), 4)
        self.assertEqual(operation["payload"]["media"][0]["caption"], post_message(data["posts"][0]))
        self.assertTrue(all("caption" not in item for item in operation["payload"]["media"][1:]))

    def test_single_photo_and_single_video_have_caption(self):
        for photos, video, expected in ((1, False, "sendPhoto"), (0, True, "sendVideo")):
            with self.subTest(expected=expected):
                data = self.data(photos, video)
                plan, errors = build_plan(self.root, data, "@channel")
                self.assertFalse(errors)
                self.assertEqual(len(plan["operations"]), 1)
                self.assertEqual(plan["operations"][0]["method"], expected)
                self.assertTrue(plan["operations"][0]["payload"]["caption"].endswith(ORDER_FOOTER))

    def test_photo_and_video_share_an_album(self):
        data = self.data(2, True)
        plan, _ = build_plan(self.root, data, "@channel")
        self.assertEqual(len(plan["operations"]), 1)
        self.assertEqual([x["type"] for x in plan["operations"][0]["payload"]["media"]], ["photo", "photo", "video"])

    def test_more_than_ten_attachments_are_batched_without_loss(self):
        data = self.data(21)
        plan, errors = build_plan(self.root, data, "@channel")
        self.assertFalse(errors)
        operations = plan["operations"]
        self.assertEqual([len(x.get("files", [x])) for x in operations], [10, 10, 1])
        paths = [item["file"] for operation in operations for item in operation.get("files", [operation])]
        self.assertEqual(len(set(paths)), 21)
        for operation in operations:
            caption = operation["payload"]["media"][0]["caption"] if "media" in operation["payload"] else operation["payload"]["caption"]
            self.assertTrue(caption.endswith(ORDER_FOOTER))

    def test_long_caption_continues_without_losing_emoji_or_paragraphs(self):
        data = self.data(2)
        post = data["posts"][0]
        post["text"] = ("🌷 Первый абзац\n\nДругой абзац с подробным описанием. " * 180).strip()
        plan, errors = build_plan(self.root, data, "@channel")
        self.assertFalse(errors)
        operations = plan["operations"]
        caption = operations[0]["payload"]["media"][0]["caption"]
        self.assertLessEqual(len(caption.encode("utf-16-le")) // 2, 1024)
        fragments = [caption] + [item["payload"]["text"] for item in operations[1:]]
        self.assertTrue(all(value.endswith(ORDER_FOOTER) for value in fragments))
        reconstructed = "".join(value[:-len("\n\n" + ORDER_FOOTER)] for value in fragments)
        self.assertEqual(reconstructed, post_body(post))
        self.assertTrue(all(len(value.encode("utf-16-le")) // 2 <= 4096 for value in fragments[1:]))

    def test_success_records_all_message_ids_and_never_reuploads(self):
        data = self.data()
        plan, _ = build_plan(self.root, data, "@channel")
        session = AlbumSession()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session, interval=0)
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session, interval=0)
        self.assertEqual(session.calls, 1)
        self.assertTrue(all(stream.closed for stream in session.streams))
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            row = ledger.rows()[0]
            self.assertEqual(row["message_id"], 100)
            self.assertEqual(json.loads(row["message_ids"]), [100, 101, 102, 103])
            self.assertEqual(row["expected_count"], 4)
        finally:
            ledger.close()

    def test_incomplete_album_reply_is_unknown_and_not_retried(self):
        data = self.data()
        plan, _ = build_plan(self.root, data, "@channel")
        session = AlbumSession(response=Response(body={"ok": True, "result": [{"message_id": 100}]}))
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        with self.assertRaisesRegex(RuntimeError, "Сначала сверка"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 1)
        self.assertTrue(all(stream.closed for stream in session.streams))

    def test_album_timeout_closes_all_streams_and_requires_manual_resolution(self):
        data = self.data()
        plan, _ = build_plan(self.root, data, "@channel")
        session = AlbumSession(failure=requests.Timeout("no reply"))
        with self.assertRaisesRegex(RuntimeError, "неизвестен"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertTrue(all(stream.closed for stream in session.streams))
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            key = plan["operations"][0]["operation_key"]
            with self.assertRaises(ValueError):
                ledger.resolve("123:@channel", "-10_1", key, "sent", "Проверено", message_id=100)
            ledger.resolve("123:@channel", "-10_1", key, "sent", "Все сообщения сверены", message_ids=[100, 101, 102, 103])
        finally:
            ledger.close()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 1)

    def mark_legacy(self, data, partial=False):
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            keys = sorted(legacy_operation_keys(data["posts"][0]))
            for key in keys[:1] if partial else keys:
                operation = {"post_key": "-10_1", "operation_key": key, "method": "sendMessage", "payload": {"text": "old"}}
                ledger.reserve("123:@channel", operation)
                ledger.finish("123:@channel", operation, "sent", message_id=42)
        finally:
            ledger.close()

    def test_completed_legacy_post_is_not_republished_as_an_album(self):
        data = self.data()
        self.mark_legacy(data)
        plan, _ = build_plan(self.root, data, "@channel")
        session = AlbumSession()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 0)

    def test_partial_legacy_post_requires_review_without_duplicating_media(self):
        data = self.data()
        self.mark_legacy(data, partial=True)
        plan, _ = build_plan(self.root, data, "@channel")
        session = AlbumSession()
        with self.assertRaisesRegex(RuntimeError, "старом формате"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 0)

    def test_old_sqlite_schema_is_migrated_without_losing_rows(self):
        path = self.root / "old.sqlite3"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE operations(destination TEXT,post_key TEXT,operation_key TEXT,payload_hash TEXT,status TEXT,message_id INTEGER,error TEXT,updated_at TEXT,PRIMARY KEY(destination,post_key,operation_key))")
        db.execute("INSERT INTO operations VALUES ('123:@channel','-10_1','text:0','hash','sent',42,NULL,'old')")
        db.commit()
        db.close()
        ledger = Ledger(path)
        try:
            row = ledger.rows()[0]
            self.assertEqual(row["message_id"], 42)
            self.assertEqual(row["expected_count"], 1)
        finally:
            ledger.close()
