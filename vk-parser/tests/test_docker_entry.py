import os
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docker_entry
from telegram_send import Ledger, build_plan, digest, send
from test_delivery import Session, manifest


class DockerEntryTests(unittest.TestCase):
    def test_watcher_enables_publication_and_persists_ledger(self):
        with patch.dict(os.environ, {"VK_PARSER_URL": "https://vk.ru/example",
                                     "VK_PARSER_LIMIT": "20", "VK_PARSER_INTERVAL": "90"}, clear=True):
            command = docker_entry.watch_command()
        self.assertEqual(command[command.index("--url") + 1], "https://vk.ru/example")
        self.assertEqual(command[command.index("--interval") + 1], "90")
        self.assertIn("--telegram", command)
        self.assertIn("--headless", command)
        self.assertNotIn("--publish-existing", command)
        self.assertEqual(command[command.index("--db") + 1], str(docker_entry.DATA / "delivery.sqlite3"))

    def test_menu_collects_and_publishes_selected_source(self):
        answers = ["1", "https://vk.com/example", "3", "0"]
        with patch("builtins.input", side_effect=answers), patch.object(docker_entry, "main", return_value=0) as call, patch.object(docker_entry, "publish") as publish:
            self.assertEqual(docker_entry.menu(), 0)
        command = call.call_args.args[0]
        self.assertEqual(command[:5], ["collect", "--url", "https://vk.com/example", "--limit", "3"])
        self.assertIn("--headless", command)
        publish.assert_called_once_with(Path(command[command.index("--output") + 1]))

    def test_menu_does_not_publish_failed_collection(self):
        answers = ["1", "https://vk.com/example", "3", "0"]
        with patch("builtins.input", side_effect=answers), patch.object(docker_entry, "main", return_value=2), patch.object(docker_entry, "publish") as publish:
            self.assertEqual(docker_entry.menu(), 0)
        publish.assert_not_called()

    def test_transient_browser_error_retries_then_publishes_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(docker_entry, "DATA", Path(tmp)):
            def collect(command):
                folder = Path(command[command.index("--output") + 1])
                folder.mkdir(parents=True)
                (folder / "manifest.json").write_text(json.dumps({"stop_reason": "browser_error:ElementNotInteractableException"}), encoding="utf-8")
                return 2 if not hasattr(collect, "called") else 0
            def attempt(command):
                result = collect(command)
                collect.called = True
                return result
            with patch.object(docker_entry, "main", side_effect=attempt) as call:
                folder, result = docker_entry.collect_with_retry("https://vk.ru/example", "5")
            self.assertEqual(result, 0)
            self.assertEqual(call.call_count, 2)
            self.assertTrue(folder.exists())

    def test_republish_menu_only_resets_selected_post_after_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(docker_entry, "DATA", Path(tmp)):
            folder = Path(tmp) / "archive" / "items" / "-10_1"
            folder.mkdir(parents=True)
            data = manifest()
            (folder / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
            plan, _ = build_plan(folder, data, "@channel")
            send(folder, data, "123:fake", "@channel", digest(plan), session=Session(), database=Path(tmp) / "delivery.sqlite3")
            with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "123:fake", "TELEGRAM_CHAT_ID": "@channel"}), \
                 patch("builtins.input", side_effect=["1", "да"]), patch.object(docker_entry, "publish") as publish:
                docker_entry.republish_menu()
            publish.assert_called_once_with(folder)
            ledger = Ledger(Path(tmp) / "delivery.sqlite3")
            try:
                self.assertEqual(ledger.rows(), [])
                self.assertEqual(ledger.db.execute("SELECT action FROM audit").fetchone()[0], "republish")
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
