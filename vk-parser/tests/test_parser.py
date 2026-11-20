import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract import embedded_json, extract_post, index_json, latest, machine_date


def post_data(post_id=1, date=1793436232, **fields):
    return {"owner_id": -10, "id": post_id, "post_type": "post", "date": date,
            "text": "", "attachments": [], **fields}


def dom(post_id=1, content="", date=""):
    return f'<div data-testid="post" data-post-id="-10_{post_id}"><div data-testid="post-content-container">{content}</div>{date}</div>'


class ExtractionTests(unittest.TestCase):
    def test_scoped_text_with_paragraphs_br_and_image_emoji(self):
        content = '<span data-testid="post_text"><p>Первый <img class="emoji" alt="🌹"></p><p>Второй<br>абзац <a href="https://example.org/shop">Наш магазин</a></p></span>'
        html = dom(content=content) + dom(2, '<span data-testid="post_text">СОСЕД</span>')
        post = extract_post("-10_1", html, post_data(text="Первый 🌹\n\nВторой\nабзац Наш магазин"))
        self.assertEqual(post["text"], "Первый 🌹\n\nВторой\nабзац Наш магазин")
        self.assertEqual(post["status"], "complete")
        self.assertIn({"text": "Наш магазин", "url": "https://example.org/shop"}, post["links"])
        self.assertNotIn("СОСЕД", post.get("dom_text", ""))

    def test_mismatched_json_is_rejected(self):
        with self.assertRaises(ValueError):
            extract_post("-10_1", dom(), post_data(2, text="СОСЕД"))

    def test_comment_date_and_nested_repost_are_not_outer_fields(self):
        html = dom(content='<div data-testid="wall_comments_layout_root"><time datetime="2026-11-03T10:00:00+05:00">Сегодня</time><span data-testid="post_text">КОММЕНТАРИЙ</span></div>' + dom(2, '<span data-testid="post_text">РЕПОСТ</span>'))
        post = extract_post("-10_1", html)
        self.assertEqual(post["text"], "")
        self.assertIsNone(post["published_at"])

    def test_photo_metadata_and_dom_attachment_only(self):
        photo = {"owner_id": -10, "id": 77, "sizes": [
            {"url": "https://example.org/thumb.jpg", "width": 80, "height": 60},
            {"url": "https://example.org/large.jpg", "width": 1600, "height": 1200}]}
        html = dom(content='<img src="avatar.jpg"><a href="/video-10_9"><img src="video-preview.jpg"></a><div data-testid="media-grid"><a href="/photo-10_77"><img data-src="https://example.org/lazy.jpg" srcset="https://example.org/image?as=32x32,640x640 640w, https://example.org/large.jpg 1600w"></a></div>')
        data = post_data(attachments=[{"type": "photo", "photo": photo}, {"type": "video", "video": {"owner_id": -10, "id": 9, "title": "Ролик"}}])
        post = extract_post("-10_1", html, data)
        self.assertEqual(len(post["photos"]), 1)
        self.assertEqual(post["photos"][0]["source_url"], "https://example.org/large.jpg")
        self.assertEqual(post["photos"][0]["quality"], "largest_available")
        self.assertTrue(post["photos"][0]["dom_verified"])
        urls = [x["url"] for x in post["photos"][0]["candidates"]]
        self.assertIn("https://example.org/image?as=32x32,640x640", urls)
        self.assertFalse(post["videos"][0]["download_allowed"])
        self.assertEqual(post["videos"][0]["direct_sources"], [])

    def test_dom_thumbnail_is_not_original(self):
        html = dom(content='<div data-testid="media-grid"><a href="/photo-10_77"><img src="https://example.org/small.jpg"></a></div>')
        post = extract_post("-10_1", html)
        self.assertEqual(post["photos"][0]["quality"], "dom_resolution_unverified")
        self.assertEqual(post["status"], "partial")

    def test_index_does_not_include_photo_comment_or_nested_wall(self):
        data = {"items": [post_data(copy_history=[post_data(99)]), {"id": 7, "owner_id": -10, "date": 123, "text": "коммент"}]}
        self.assertEqual(set(index_json(data)), {"-10_1"})

    def test_embedded_json_is_exact_and_never_evaled(self):
        html = '<script>window.cur.apiPrefetchCache = ' + json.dumps([{"response": {"items": [post_data()]}}]) + '; throw new Error("do not execute")</script>'
        self.assertEqual(set(embedded_json(html)), {"-10_1"})
        self.assertEqual(embedded_json('<script>wall.getById is missing</script>'), {})

    def test_latest_ignores_pinning_and_deduplicates(self):
        posts = [extract_post(f"-10_{i}", dom(i), post_data(i, 1793436232 + i, is_pinned=(i == 1))) for i in range(1, 16)]
        chosen = latest([posts[0], *reversed(posts), posts[-1]], 10)
        self.assertEqual([p["post_id"] for p in chosen], list(range(6, 16)))

    def test_twenty_latest_are_sent_oldest_first_so_newest_is_on_top(self):
        from tempfile import TemporaryDirectory
        from telegram_send import build_plan
        posts = [extract_post(f"-10_{i}", dom(i), post_data(i, 1793436232 + i)) for i in range(1, 26)]
        selected = latest(reversed(posts), 20)
        with TemporaryDirectory() as folder:
            plan, errors = build_plan(folder, {"selection": {"valid": True}, "posts": selected}, "@channel")
        self.assertFalse(errors)
        self.assertEqual([op["post_key"] for op in plan["operations"]], [f"-10_{i}" for i in range(6, 26)])

    def test_machine_date_never_guesses_relative_or_timezone(self):
        self.assertIsNone(machine_date("вчера"))
        self.assertIsNone(machine_date("2026-11-03T10:00:00"))
        self.assertEqual(machine_date(1793436232000), 1793436232)
        self.assertIsNotNone(machine_date("2026-11-03T10:00:00+05:00"))


if __name__ == "__main__":
    unittest.main()
