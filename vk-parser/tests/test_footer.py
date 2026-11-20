import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import telegram_send
from telegram_send import ORDER_FOOTER, build_plan, post_message, publication_parts, read_footer
from test_delivery import manifest


class FooterTests(unittest.TestCase):
    def test_video_title_and_service_url_are_not_added_to_message(self):
        post = manifest()["posts"][0]
        post["text"] = ""
        post["videos"] = [{"title": "Клип @cvetyurala", "url": "https://vk.ru/video-236279991_456239541", "description": "Свежие цветы 🌹"}]
        text = post_message(post)
        self.assertIn("Свежие цветы 🌹", text)
        self.assertNotIn("Клип @cvetyurala", text)
        self.assertNotIn("Видео:", text)
        self.assertNotIn("https://vk.ru/video-236279991_456239541", text)

    def test_description_already_in_post_text_is_not_duplicated(self):
        post = manifest()["posts"][0]
        post["text"] = "Описание букета"
        post["videos"] = [{"description": "Описание букета"}]
        self.assertEqual(post_message(post).count("Описание букета"), 1)

    def test_utf8_bom_and_windows_multiline_footer(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "post_footer.txt"
            path.write_bytes(("\ufeff" + ORDER_FOOTER + "\r\nДоставка по городу\r\n").encode("utf-8"))
            self.assertEqual(read_footer(path), ORDER_FOOTER + "\nДоставка по городу")

    def test_footer_changes_are_read_for_next_plan_without_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "post_footer.txt"
            with patch.object(telegram_send, "FOOTER_PATH", path):
                path.write_text(ORDER_FOOTER, encoding="utf-8")
                first, _ = build_plan(temp, manifest(), "@channel")
                path.write_text(ORDER_FOOTER + "\nДоставка по Кондратово", encoding="utf-8")
                second, _ = build_plan(temp, manifest(), "@channel")
            self.assertNotEqual(first["operations"][0]["payload"]["text"], second["operations"][0]["payload"]["text"])
            self.assertTrue(second["operations"][0]["payload"]["text"].endswith("Доставка по Кондратово"))
            self.assertEqual(second["footer"], ORDER_FOOTER + "\nДоставка по Кондратово")

    def test_multiline_footer_already_in_text_appears_once(self):
        footer = ORDER_FOOTER + "\nДоставка по Кондратово"
        post = manifest()["posts"][0]
        post["text"] += "\n\n" + footer
        text = post_message(post, footer)
        self.assertEqual(text.count(ORDER_FOOTER), 1)
        self.assertEqual(text.count("Доставка по Кондратово"), 1)
        self.assertTrue(text.endswith(footer))

    def test_caption_budget_includes_multiline_footer_and_emoji(self):
        footer = ORDER_FOOTER + "\n🌷 Доставка ежедневно\nЗаказы принимаем до 21:00"
        post = manifest()["posts"][0]
        post["text"] = "Очень красивый букет 🌹\n\n" * 100
        parts = publication_parts(post, True, footer)
        self.assertTrue(all(text.endswith(footer) for text in parts))
        self.assertLessEqual(len(parts[0].encode("utf-16-le")) // 2, 1024)
        self.assertTrue(all(len(text.encode("utf-16-le")) // 2 <= 4096 for text in parts[1:]))

    def test_missing_footer_file_uses_default(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(read_footer(Path(temp) / "missing.txt"), ORDER_FOOTER)

    def test_empty_file_disables_footer_without_extra_blank_lines(self):
        self.assertEqual(post_message(manifest()["posts"][0], ""), "Тест 🌹")

    def test_overlong_footer_has_a_clear_error(self):
        with self.assertRaisesRegex(ValueError, "post_footer.txt"):
            publication_parts(manifest()["posts"][0], True, "🌹" * 600)

    def test_links_from_actual_post_are_preserved(self):
        post = manifest()["posts"][0]
        post["links"] = [{"text": "Наш магазин", "url": "https://example.org/shop"}]
        self.assertIn("Наш магазин — https://example.org/shop", post_message(post))
