"""Optional real Selenium tests, entirely local; no VK login or Telegram calls."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from collect import Collector, ManualActionRequired, check_blockers, close_optional_banners, stop_on_robot_check
from extract import load_selectors


@unittest.skipUnless(os.environ.get("VK_TEST_DRIVER"), "Set VK_TEST_DRIVER to a local chromedriver executable")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        options = Options()
        options.add_argument("--headless=new")
        if os.environ.get("VK_PARSER_DOCKER") == "1":
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        cls.driver = webdriver.Chrome(service=Service(os.environ["VK_TEST_DRIVER"]), options=options)

    @classmethod
    def tearDownClass(cls):
        cls.driver.quit()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.selectors = load_selectors()

    def tearDown(self):
        self.temp.cleanup()

    def page(self, html):
        self.driver.get("data:text/html;charset=utf-8," + quote("<!doctype html><meta charset='utf-8'>" + html))
        return Collector(self.driver, self.temp.name, self.selectors)

    def test_delayed_content_and_removed_posts_are_retained(self):
        collector = self.page('''<div data-testid="post" data-post-id="-10_1" id="p"></div>
            <script>setTimeout(() => document.querySelector('#p').innerHTML =
            '<span data-testid="post_text">Первый 🌹</span>', 250)</script>''')
        collector.wait_post(timeout=5)
        self.assertEqual(collector.posts["-10_1"]["text"], "Первый 🌹")
        self.driver.execute_script('''document.querySelector('#p').remove();
          const next = document.createElement('div');
          next.dataset.testid = 'post'; next.dataset.postId = '-10_2';
          next.innerHTML = '<span data-testid="post_text">Второй</span>';
          document.body.append(next);
          const transient = next.cloneNode(true); transient.dataset.postId = '-10_3';
          document.body.append(transient); transient.remove();''')
        def saved(_):
            collector.harvest()
            return "-10_2" in collector.posts and "-10_3" in collector.posts
        WebDriverWait(self.driver, 5).until(saved)
        self.assertEqual(set(collector.posts), {"-10_1", "-10_2", "-10_3"})

    def test_only_known_expand_control_inside_post_is_clicked(self):
        collector = self.page('''<button onclick="window.wrong=true">Показать ещё</button>
          <div data-testid="post" data-post-id="-10_1">
          <span data-testid="post_text">Начало
          <span role="button" tabindex="0" data-id="showMoreButton"
          onclick="this.parentElement.append(' Продолжение');this.remove()">Показать ещё</span>
          </span></div>''')
        collector.wait_post(timeout=5)
        collector.expand()
        self.assertIn("Продолжение", collector.posts["-10_1"]["text"])
        self.assertFalse(self.driver.execute_script("return Boolean(window.wrong)"))

    def test_expand_scrolls_above_a_fixed_bottom_banner(self):
        collector = self.page('''<div style="height:1800px"></div>
          <div data-testid="post" data-post-id="-10_1"><span data-testid="post_text">Начало
          <button data-id="showMoreButton" onclick="this.parentElement.append(' Продолжение');this.remove()">Показать ещё</button>
          </span></div><div style="height:1000px"></div>
          <div style="position:fixed;bottom:0;left:0;right:0;height:160px;background:blue;z-index:10000">Плашка</div>''')
        collector.wait_post(timeout=5)
        collector.expand()
        self.assertIn("Продолжение", collector.posts["-10_1"]["text"])

    def test_login_modal_stops_and_is_not_closed(self):
        collector = self.page('''<div role="dialog" aria-modal="true"><h2>Войдите ВКонтакте, чтобы смотреть посты</h2>
          <button aria-label="Закрыть" onclick="window.wrong=true">×</button><button>Войти</button></div>''')
        with self.assertRaises(ManualActionRequired):
            collector.harvest()
        self.assertFalse(self.driver.execute_script("return Boolean(window.wrong)"))

    def test_optional_close_is_scoped_to_configured_banner(self):
        self.page('''<button aria-label="Закрыть" onclick="window.wrong=true">×</button>
          <div id="known-cookie-banner"><button aria-label="Закрыть" onclick="this.parentElement.remove()">×</button></div>''')
        self.selectors["optional_banners"] = [{"container": "#known-cookie-banner", "close": "button[aria-label='Закрыть']"}]
        close_optional_banners(self.driver, self.selectors)
        self.assertFalse(self.driver.execute_script("return Boolean(window.wrong)"))
        self.assertFalse(self.driver.execute_script("return Boolean(document.querySelector('#known-cookie-banner'))"))

    def login_suggestion(self, close=None):
        close = close or '''<div role="button" tabindex="0"
          onclick="window.dismissed=(window.dismissed||0)+1;this.parentElement.remove()">
          <span>Закрыть</span><svg class="vkuiIcon--cancel_20"></svg></div>'''
        return f'''<div data-testid="modalbox" role="dialog" aria-modal="true">{close}
          <h2>Войдите ВКонтакте, чтобы смотреть посты от «Цветы Урала»</h2>
          <button>Войти</button><button>Создать аккаунт</button></div>'''

    def test_known_login_suggestion_is_dismissed_when_it_reappears(self):
        collector = self.page('''<button aria-label="Закрыть" onclick="window.wrong=true">×</button>
          <div data-testid="post" data-post-id="-10_1"><span data-testid="post_text">Текст</span></div>'''
          + self.login_suggestion())
        collector.wait_post(timeout=5)
        self.assertEqual(self.driver.execute_script("return window.dismissed"), 1)
        self.driver.execute_script("document.body.insertAdjacentHTML('beforeend', arguments[0])", self.login_suggestion())
        collector.harvest()
        self.assertEqual(self.driver.execute_script("return window.dismissed"), 2)
        self.assertFalse(self.driver.execute_script("return Boolean(window.wrong)"))
        self.assertIn("-10_1", collector.posts)

    def test_english_login_suggestion_is_dismissed(self):
        suggestion = self.login_suggestion().replace(
            'Войдите ВКонтакте, чтобы смотреть посты от «Цветы Урала»',
            'Sign up to view Цветы Урала')
        collector = self.page('<div data-testid="post" data-post-id="-10_1"><span data-testid="post_text">Текст</span></div>' + suggestion)
        collector.wait_post(timeout=5)
        self.assertEqual(self.driver.execute_script("return window.dismissed"), 1)

    def test_similar_modal_without_known_close_control_is_not_dismissed(self):
        collector = self.page(self.login_suggestion('<button aria-label="Закрыть" onclick="window.wrong=true">×</button>'))
        with self.assertRaises(ManualActionRequired):
            collector.harvest()
        self.assertFalse(self.driver.execute_script("return Boolean(window.wrong)"))

    def test_captcha_is_not_dismissed_as_a_login_suggestion(self):
        collector = self.page('<div id="captcha">Пройдите проверку</div>' + self.login_suggestion())
        with self.assertRaises(ManualActionRequired):
            collector.harvest()
        self.assertFalse(self.driver.execute_script("return Boolean(window.dismissed)"))

    def test_robot_check_stops_with_api_hint_and_is_not_clicked(self):
        self.page('''<title>Проверяем, что вы не робот</title>
            <button class="start" onclick="window.clicked = true">Продолжить</button>''')
        with self.assertRaises(ManualActionRequired) as caught:
            stop_on_robot_check(self.driver)
        self.assertIn("VK_PARSER_VK_TOKEN", str(caught.exception))
        self.assertFalse(self.driver.execute_script("return Boolean(window.clicked)"))

    def test_robot_check_waits_for_a_person_in_manual_mode(self):
        self.page('<title>Проверяем, что вы не робот</title><button>Продолжить</button>')
        with patch("builtins.input", return_value="") as prompt:
            self.assertTrue(stop_on_robot_check(self.driver, manual=True))
        prompt.assert_called_once()

    def test_normal_page_is_not_a_robot_check(self):
        self.page('<title>Цветы Урала</title><button>Продолжить</button>')
        self.assertFalse(stop_on_robot_check(self.driver))

if __name__ == "__main__":
    unittest.main()
