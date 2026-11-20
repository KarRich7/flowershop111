import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract import extract_post
from telegram_send import Ledger, build_plan, digest, send, split_text


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body or {"ok": True, "result": {"message_id": 123}}

    def json(self):
        return self.body


class Session:
    def __init__(self, failure=None, response=None):
        self.calls, self.failure, self.response = 0, failure, response or Response()

    def post(self, *args, **kwargs):
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.response


def manifest():
    post = extract_post("-10_1", '<div data-testid="post" data-post-id="-10_1"><span data-testid="post_text">Тест 🌹</span></div>',
                        {"owner_id": -10, "id": 1, "date": 1793436232, "text": "Тест 🌹", "attachments": []})
    return {"selection": {"valid": True}, "candidate_count": 1, "posts": [post]}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_success_is_logged_and_rerun_does_not_duplicate(self):
        data = manifest()
        plan, errors = build_plan(self.root, data, "@channel")
        self.assertFalse(errors)
        session = Session()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 1)
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            self.assertEqual(ledger.rows()[0]["message_id"], 123)
            self.assertEqual(ledger.rows()[0]["status"], "sent")
        finally:
            ledger.close()

    def test_timeout_is_unknown_and_rerun_never_retries(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        session = Session(failure=requests.Timeout("secret token should not be logged"))
        with self.assertRaisesRegex(RuntimeError, "неизвестен"):
            send(self.root, data, "123:secret", "@channel", digest(plan), session=session)
        with self.assertRaisesRegex(RuntimeError, "Сначала сверка"):
            send(self.root, data, "123:secret", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 1)
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            row = ledger.rows()[0]
            self.assertEqual(row["status"], "unknown")
            self.assertEqual(row["error"], "Timeout")
        finally:
            ledger.close()

    def test_unresolved_post_does_not_block_a_different_new_post(self):
        first = manifest()
        plan, _ = build_plan(self.root, first, "@channel")
        failure = Session(failure=requests.Timeout())
        with self.assertRaises(RuntimeError):
            send(self.root, first, "123:fake", "@channel", digest(plan), session=failure)
        second = manifest()
        second["posts"][0]["key"] = "-10_2"
        second["posts"][0]["post_id"] = 2
        new_plan, errors = build_plan(self.root, second, "@channel")
        self.assertFalse(errors)
        success = Session()
        send(self.root, second, "123:fake", "@channel", digest(new_plan), session=success)
        self.assertEqual(success.calls, 1)
        with self.assertRaisesRegex(RuntimeError, "Сначала сверка"):
            send(self.root, first, "123:fake", "@channel", digest(plan), session=success)
        self.assertEqual(success.calls, 1)

    def test_crash_after_reservation_blocks_a_second_process(self):
        operation = {"post_key": "-10_1", "operation_key": "text:0", "method": "sendMessage", "payload": {"text": "A"}}
        first = Ledger(self.root / "journal.sqlite3")
        second = Ledger(self.root / "journal.sqlite3")
        try:
            self.assertTrue(first.reserve("1:@channel", operation))
            with self.assertRaisesRegex(RuntimeError, "inflight"):
                second.reserve("1:@channel", operation)
            second.resolve("1:@channel", "-10_1", "text:0", "sent", "Проверено вручную", message_id=42)
            self.assertFalse(first.reserve("1:@channel", operation))
        finally:
            first.close()
            second.close()

    def test_republish_resets_only_selected_confirmed_post_and_audits(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        session = Session()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            self.assertEqual(ledger.reset_sent_post("123:@channel", "-10_1"), 1)
            self.assertEqual(ledger.rows(), [])
            self.assertEqual(ledger.db.execute("SELECT action FROM audit").fetchone()[0], "republish")
        finally:
            ledger.close()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 2)

    def test_republish_does_not_reset_unconfirmed_or_other_post(self):
        ledger = Ledger(self.root / "journal.sqlite3")
        try:
            operation = {"post_key": "-10_1", "operation_key": "text:0", "method": "sendMessage", "payload": {"text": "A"}}
            ledger.reserve("123:@channel", operation)
            with self.assertRaisesRegex(RuntimeError, "неподтверждённая"):
                ledger.reset_sent_post("123:@channel", "-10_1")
            self.assertEqual(ledger.reset_sent_post("123:@channel", "-10_2"), 0)
            self.assertEqual(ledger.rows()[0]["status"], "inflight")
        finally:
            ledger.close()

    def test_rejected_request_and_5xx_have_different_outcomes(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        session = Session(response=Response(403, {"ok": False, "error_code": 403}))
        with self.assertRaisesRegex(RuntimeError, "failed"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            ledger.resolve("123:@channel", "-10_1", plan["operations"][0]["operation_key"], "retry", "Бот добавлен в канал; проверено, что сообщения нет")
        finally:
            ledger.close()
        session.response = Response(502)
        with self.assertRaisesRegex(RuntimeError, "unknown"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)

    def test_telegram_429_waits_and_retries_without_reordering(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        class RateLimitedSession(Session):
            def post(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return Response(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 2}})
                return Response()
        session = RateLimitedSession()
        with patch("telegram_send.time.sleep") as sleep:
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session, interval=0)
        self.assertEqual(session.calls, 2)
        sleep.assert_called_once_with(3)
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            self.assertEqual(ledger.rows()[0]["status"], "sent")
        finally:
            ledger.close()

    def test_interrupt_while_waiting_for_429_leaves_safe_pending_state(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        session = Session(response=Response(429, {"ok": False, "error_code": 429, "parameters": {"retry_after": 5}}))
        with patch("telegram_send.time.sleep", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                send(self.root, data, "123:fake", "@channel", digest(plan), session=session, interval=0)
        ledger = Ledger(self.root / "delivery.sqlite3")
        try:
            self.assertEqual(ledger.rows()[0]["status"], "pending")
        finally:
            ledger.close()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=Session(), interval=0)

    def test_429_without_retry_after_stops_instead_of_guessing(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        session = Session(response=Response(429, {"ok": False, "error_code": 429}))
        with self.assertRaisesRegex(RuntimeError, "failed"):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session, interval=0)
        self.assertEqual(session.calls, 1)

    def test_confirmation_binds_destination_and_payload(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        session = Session()
        with self.assertRaises(ValueError):
            send(self.root, data, "123:fake", "@different", digest(plan), session=session)
        data["posts"][0]["text"] += " ИЗМЕНЕНО"
        with self.assertRaises(ValueError):
            send(self.root, data, "123:fake", "@channel", digest(plan), session=session)
        self.assertEqual(session.calls, 0)

    def test_lossless_utf16_splitting(self):
        for text in ("A " + "Б" * 3997 + "🌹🌹", "🌹" * 10000, "Первая\n\nВторая " * 1000):
            parts = split_text(text)
            self.assertEqual("".join(parts), text)
            self.assertTrue(all(len(x.encode("utf-16-le")) // 2 <= 4000 for x in parts))

    def test_shared_database_deduplicates_across_collection_folders(self):
        data = manifest()
        plan, _ = build_plan(self.root, data, "@channel")
        second_run = self.root / "second-run"
        second_run.mkdir()
        database = self.root / "shared.sqlite3"
        session = Session()
        send(self.root, data, "123:fake", "@channel", digest(plan), session=session, database=database)
        send(second_run, data, "123:fake", "@channel", digest(plan), session=session, database=database)
        self.assertEqual(session.calls, 1)


if __name__ == "__main__":
    unittest.main()
