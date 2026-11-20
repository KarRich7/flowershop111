from __future__ import annotations

import base64
import csv
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from selenium import webdriver
from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from extract import embedded_json, extract_post, file_hash, index_json, latest, load_selectors, refresh_status, write_json


class ManualActionRequired(RuntimeError):
    pass


ROBOT_CHECK_TITLE = re.compile(r"не\s+робот|not\s+a\s+robot", re.I)


def make_driver(args):
    cache = Path(args.cache).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    os.environ["SE_CACHE_PATH"] = str(cache)
    options = Options()
    options.page_load_strategy = "eager"
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    options.add_argument("--window-size=1440,1000")
    if os.environ.get("VK_PARSER_DOCKER") == "1":
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # In a container the system language is English; VK should look the same as on a Russian PC.
        options.add_argument("--lang=ru-RU")
        options.add_experimental_option("prefs", {"intl.accept_languages": "ru-RU,ru"})
    if args.headless:
        options.add_argument("--headless=new")
    if args.profile:
        options.add_argument("--user-data-dir=" + str(Path(args.profile).resolve()))
    if args.chrome:
        options.binary_location = str(Path(args.chrome).resolve())
    driver = webdriver.Chrome(service=Service(executable_path=args.driver) if args.driver else Service(), options=options)
    driver.set_page_load_timeout(args.timeout)
    driver.implicitly_wait(0)
    driver.execute_cdp_cmd("Network.enable", {"maxTotalBufferSize": 100_000_000, "maxResourceBufferSize": 20_000_000})
    return driver


def visible(driver, selector):
    return [x for x in driver.find_elements(By.CSS_SELECTOR, selector) if x.is_displayed()]


def on_robot_check(driver):
    if urlparse(driver.current_url).path.endswith("/challenge.html"):
        return True
    return bool(ROBOT_CHECK_TITLE.search(driver.title or ""))


def stop_on_robot_check(driver, manual=False):
    """VK shows «Проверяем, что вы не робот» to automated browsers (mostly from server IPs).
    The parser does not try to pass it: a person can do it in --manual mode, a server should
    use the official API (VK_PARSER_VK_TOKEN)."""
    if not on_robot_check(driver):
        return False
    reason = "ВК показал проверку «Проверяем, что вы не робот»"
    if not manual:
        raise ManualActionRequired(reason + ". На сервере задайте VK_PARSER_VK_TOKEN (официальный API ВК); "
                                   "на компьютере можно пройти проверку вручную: collect --manual")
    input(reason + ". Пройдите её в браузере, дождитесь стены сообщества и нажмите Enter здесь: ")
    return True


def check_blockers(driver, selectors, manual=False):
    reason = None
    if urlparse(driver.current_url).hostname in ("id.vk.ru", "id.vk.com", "login.vk.com"):
        reason = "ВК открыл обязательную авторизацию"
    for selector in selectors["blockers"]:
        if visible(driver, selector):
            reason = "Нужна ручная проверка: капча или ограничение доступа"
            break
    if not reason:
        close_optional_banners(driver, selectors)
    for dialog in visible(driver, "[role='dialog'], [aria-modal='true']"):
        if re.search(r"войти|войдите|вход|авторизац|captcha|капч|доступ|sign in|log in", dialog.text, re.I):
            reason = "ВК показал окно входа или ограничения доступа"
    if not driver.find_elements(By.CSS_SELECTOR, selectors["post"]):
        bodies = driver.find_elements(By.TAG_NAME, "body")
        if bodies and re.search(r"это закрытое сообщество|сообщество закрыто|сообщество заблокировано|страница удалена|доступ к (?:странице|сообществу) ограничен|content (?:is )?not available", bodies[0].text, re.I):
            reason = "ВК сообщил об ограничении доступа к странице"
    if not reason:
        return
    if manual:
        input(reason + ". Выполните действие в браузере, вернитесь на нужную страницу и нажмите Enter здесь: ")
        check_blockers(driver, selectors, manual=False)
    else:
        raise ManualActionRequired(reason + ". Запустите collect с --manual без --headless.")


def close_optional_banners(driver, selectors):
    # Match the known suggestion's heading AND its own close control.
    for rule in selectors.get("optional_banners", []):
        for banner in visible(driver, rule["container"]):
            try:
                if rule.get("heading_pattern"):
                    headings = banner.find_elements(By.CSS_SELECTOR, rule.get("heading", "h2"))
                    if not any(re.search(rule["heading_pattern"], heading.text, re.I) for heading in headings):
                        continue
                for button in banner.find_elements(By.CSS_SELECTOR, rule["close"]):
                    if button.is_displayed() and button.is_enabled():
                        button.click()
                        def dismissed(_):
                            try:
                                return not banner.is_displayed()
                            except StaleElementReferenceException:
                                return True
                        WebDriverWait(driver, 3, poll_frequency=0.2).until(dismissed)
                        break
            except StaleElementReferenceException:
                continue
            except (ElementClickInterceptedException, TimeoutException):
                raise ManualActionRequired("Не удалось закрыть известную плашку. Проверьте окно браузера вручную.") from None


class Collector:
    def __init__(self, driver, output, selectors, manual=False):
        self.driver, self.output, self.selectors, self.manual = driver, Path(output), selectors, manual
        self.json_posts, self.html_posts, self.posts, self.json_sources = {}, {}, {}, {}
        self.owner_id = None
        self.wall_counts = {}
        self.pending_responses = set()
        self.observer = Path(__file__).with_name("observe.js").read_text(encoding="utf-8")
        self.output.mkdir(parents=True, exist_ok=True)

    def snapshot(self, label):
        folder = self.output / "diagnostics"
        folder.mkdir(exist_ok=True)
        try:
            (folder / (label + ".html")).write_text(self.driver.page_source, encoding="utf-8")
            self.driver.save_screenshot(str(folder / (label + ".png")))
        except WebDriverException as exc:
            (folder / (label + "-error.txt")).write_text(type(exc).__name__, encoding="utf-8")

    def absorb_json(self, values, source):
        changed = set()
        for key, data in values.items():
            if self.owner_id is not None and int(key.split("_")[0]) != self.owner_id:
                continue
            if self.json_posts.get(key) != data:
                self.json_posts[key] = data
                self.json_sources[key] = source
                changed.add(key)
        return changed

    def network_json(self):
        changed = set()
        for entry in self.driver.get_log("performance"):
            message = json.loads(entry["message"])["message"]
            params = message.get("params", {})
            if message["method"] == "Network.responseReceived":
                response = params["response"]
                host = urlparse(response["url"]).hostname or ""
                if (host == "vk.ru" or host.endswith(".vk.ru") or host == "vk.com" or host.endswith(".vk.com")) and params.get("type") in ("XHR", "Fetch"):
                    self.pending_responses.add(params["requestId"])
            elif message["method"] == "Network.loadingFailed":
                self.pending_responses.discard(params.get("requestId"))
        for request_id in list(self.pending_responses):
            try:
                result = self.driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": request_id})
            except WebDriverException:
                continue  # Response may still be loading; retry reading, never re-request it.
            self.pending_responses.discard(request_id)
            body = base64.b64decode(result["body"]).decode("utf-8") if result.get("base64Encoded") else result["body"]
            try:
                data = json.loads(body)
            except ValueError:
                continue
            response = data.get("response") if isinstance(data, dict) else None
            if isinstance(response, dict) and isinstance(response.get("count"), int) and isinstance(response.get("items"), list):
                items = response["items"]
                owners = {item.get("owner_id") for item in items if isinstance(item, dict) and item.get("post_type") == "post"}
                if len(owners) == 1 and len(items) == sum(isinstance(item, dict) and item.get("post_type") == "post" for item in items):
                    self.wall_counts[next(iter(owners))] = response["count"]
            changed.update(self.absorb_json(index_json(data), "browser_json_response"))
        return changed

    def harvest(self):
        check_blockers(self.driver, self.selectors, self.manual)
        changed = self.network_json()
        self.driver.execute_script(self.observer, self.selectors["post"])
        snapshots = self.driver.execute_script("return window.__vkCollector.drain()")
        if self.owner_id is None and snapshots:
            self.owner_id = int(snapshots[0]["key"].split("_")[0])
            self.json_posts = {key: data for key, data in self.json_posts.items() if int(key.split("_")[0]) == self.owner_id}
            self.posts = {key: post for key, post in self.posts.items() if int(key.split("_")[0]) == self.owner_id}
            changed.update(self.json_posts)
        if self.owner_id is None:
            return set()
        changed = {key for key in changed if int(key.split("_")[0]) == self.owner_id}
        for item in snapshots:
            if int(item["key"].split("_")[0]) != self.owner_id:
                continue
            if self.html_posts.get(item["key"]) != item["html"]:
                self.html_posts[item["key"]] = item["html"]
                changed.add(item["key"])
        # Even JSON-only candidates are preserved; never take HTML from a sibling.
        for key in changed:
            post = extract_post(key, self.html_posts.get(key), self.json_posts.get(key), self.selectors)
            post["sources"]["json_origin"] = self.json_sources.get(key)
            self.posts[key] = post
            self.save_post(key)
        return changed

    def save_post(self, key):
        if key in self.html_posts:
            path = self.output / "snapshots" / (key + ".html")
            path.parent.mkdir(exist_ok=True)
            path.write_text(self.html_posts[key], encoding="utf-8")
        write_json(self.output / "posts" / (key + ".json"), self.posts[key])

    def wait_post(self, expected=None, timeout=30):
        def ready(_):
            self.harvest()
            for key, post in self.posts.items():
                if expected and expected != key:
                    continue
                if not post["sources"]["dom"]:
                    continue
                if post["text"] or post["photos"] or post["videos"] or post["other_attachments"] or post["reposts"]:
                    return True
            return False
        WebDriverWait(self.driver, timeout, poll_frequency=0.4).until(ready)

    def open(self, url, expected=None, timeout=30):
        try:
            self.driver.get(url)
        except TimeoutException:
            # Ancillary resources may hang after the posts have already loaded.
            # The content-specific wait below still has to succeed.
            pass
        stop_on_robot_check(self.driver, manual=self.manual)
        check_blockers(self.driver, self.selectors, self.manual)
        self.absorb_json(embedded_json(self.driver.page_source), "embedded_json")
        # harvest must see inline changes, including posts not yet in DOM.
        for key in self.json_posts if self.owner_id is not None else ():
            if key not in self.posts:
                self.posts[key] = extract_post(key, self.html_posts.get(key), self.json_posts[key], self.selectors)
        self.wait_post(expected, timeout)

    def expand(self):
        for root in self.driver.find_elements(By.CSS_SELECTOR, self.selectors["post"]):
            try:
                # Expand only the text of this post, with an exact known label.
                for text in root.find_elements(By.CSS_SELECTOR, self.selectors["text"]):
                    for button in text.find_elements(By.CSS_SELECTOR, self.selectors["more"]):
                        if button.text.strip().casefold() not in ("показать полностью", "показать ещё", "показать еще", "show more"):
                            continue
                        if not button.is_displayed():
                            continue
                        self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'})", button)
                        check_blockers(self.driver, self.selectors, self.manual)
                        old = root.get_attribute("outerHTML")
                        try:
                            button.click()
                        except ElementClickInterceptedException:
                            check_blockers(self.driver, self.selectors, self.manual)
                            try:
                                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'})", button)
                                button.click()
                            except ElementClickInterceptedException:
                                raise ManualActionRequired("Кнопку раскрытия перекрыло неизвестное окно. Проверьте браузер вручную.") from None
                        def expanded(_):
                            self.harvest()
                            try:
                                return not button.is_displayed() or root.get_attribute("outerHTML") != old
                            except StaleElementReferenceException:
                                return True
                        WebDriverWait(self.driver, 5, poll_frequency=0.3).until(expanded)
            except (StaleElementReferenceException, TimeoutException):
                self.harvest()
        self.harvest()


def download_media(posts, output, driver, download_videos=False):
    output = Path(output)
    session = requests.Session()
    # Without a browser (official API source) the downloader introduces itself honestly.
    session.headers["User-Agent"] = driver.execute_script("return navigator.userAgent") if driver is not None else "cvety-urala-vk-parser/1.0"
    session.headers["Referer"] = "https://vk.ru/"
    # Do not copy browser cookies to arbitrary CDN hosts.
    for post in posts:
        for media in post["photos"]:
            kind = "photo"
            if media.get("local_path"):
                existing = (output / media["local_path"]).resolve()
                if output.resolve() in existing.parents and existing.is_file() and file_hash(existing) == media.get("sha256"):
                    continue
            url = media.get("source_url")
            if not url:
                media["download_status"] = "unavailable"
                post["issues"].append("media_source_missing")
                continue
            temp = None
            try:
                with session.get(url, stream=True, timeout=(15, 60)) as response:
                    response.raise_for_status()
                    mime = response.headers.get("Content-Type", "").split(";")[0].lower()
                    if not mime.startswith("image/" if kind == "photo" else "video/") or mime == "image/svg+xml":
                        raise ValueError("Неожиданный тип содержимого: " + mime)
                    extension = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif", "video/mp4": ".mp4"}.get(mime, ".bin")
                    relative = Path("media") / post["key"] / (kind + "_" + re.sub(r"[^\w-]", "_", media["id"]) + extension)
                    path = output / relative
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temp = path.with_suffix(path.suffix + ".part")
                    size = 0
                    with temp.open("wb") as stream:
                        for chunk in response.iter_content(128 * 1024):
                            size += len(chunk)
                            if size > 250 * 1024 * 1024:
                                raise ValueError("Вложение превысило лимит 250 МБ")
                            stream.write(chunk)
                    if not size:
                        raise ValueError("Пустое вложение")
                    temp.replace(path)
                    media.update(download_status="downloaded", local_path=relative.as_posix(),
                                 sha256=file_hash(path), mime_type=mime, byte_size=size)
            except (requests.RequestException, OSError, ValueError) as exc:
                if temp and temp.exists():
                    temp.unlink()
                media["download_status"] = "failed"
                # Requests exceptions include signed URLs: record the class, not credentials.
                media["download_error"] = type(exc).__name__
                post["issues"].append("media_download_failed")
        if download_videos:
            from video_download import download_video
            for video in post["videos"]:
                download_video(video, post["key"], output, driver)
        post["issues"] = sorted(set(post["issues"]))
        refresh_status(post)
    session.close()


def collect(args):
    if getattr(args, "vk_token", None):
        from vk_api import api_collect
        print("Источник: официальный API ВК (ключ VK_PARSER_VK_TOKEN)", flush=True)
        return api_collect(args)
    output = Path(args.output).resolve()
    if (output / "manifest.json").exists():
        raise ValueError("Папка уже содержит результат. Укажите новую --output, чтобы сохранить журнал и файлы.")
    try:
        driver = make_driver(args)
    except WebDriverException as exc:
        raise RuntimeError("Не удалось запустить Chrome (" + type(exc).__name__ + "). Проверьте доступ Selenium Manager к сети или задайте --driver.") from None
    try:
        return _collect_with_driver(args, driver, output)
    finally:
        driver.quit()


def _collect_with_driver(args, driver, output):
    collector = Collector(driver, output, load_selectors(args.selectors), manual=args.manual)
    reason, blocked, scan_lookahead = "max_scrolls", False, False
    try:
        collector.open(args.url, timeout=args.timeout)
        collector.snapshot("initial")
        idle = 0
        for step in range(args.max_scrolls):
            collector.expand()
            chosen = latest(collector.posts.values(), args.limit)
            available = collector.wall_counts.get(collector.owner_id)
            target_count = min(args.limit, available) if available is not None else args.limit
            candidate_target = min(max(args.limit * 2, args.limit + 5), available) if available is not None else max(args.limit * 2, args.limit + 5)
            print(f"Прокрутка {step}: {len(collector.posts)} кандидатов, {len(collector.html_posts)} DOM-блоков", flush=True)
            if len(collector.posts) >= candidate_target and len(chosen) == target_count and all(p["sources"]["dom"] for p in chosen):
                reason, scan_lookahead = "lookahead_reached", True
                break
            before = set(collector.posts)
            collector.harvest()
            driver.execute_script("window.scrollBy(0, Math.max(300, window.innerHeight * 0.75))")
            def new_posts(_):
                collector.harvest()
                return bool(set(collector.posts) - before)
            try:
                WebDriverWait(driver, args.scroll_timeout, poll_frequency=0.4).until(new_posts)
                idle = 0
            except TimeoutException:
                bottom = driver.execute_script("return window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 10")
                idle = idle + 1 if bottom else 0
                if idle >= 2:
                    reason = "end_or_access_limit"
                    break
        # Direct public post pages provide DOM verification for prefetched JSON candidates.
        for post in latest(collector.posts.values(), args.limit):
            if not post["sources"]["dom"]:
                collector.open(post["url"], expected=post["key"], timeout=args.timeout)
                collector.expand()
        collector.harvest()
        collector.snapshot("last")
    except ManualActionRequired as exc:
        reason, blocked = str(exc), True
        collector.snapshot("manual-action-required")
        print(reason, flush=True)
    except (TimeoutException, WebDriverException) as exc:
        reason, blocked = "browser_error:" + type(exc).__name__, True
        collector.snapshot("browser-error")
        print("Сбор прерван: " + reason, flush=True)
    except (EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt) and getattr(args, "watch_mode", False):
            raise
        reason, blocked = "manual_input_interrupted", True
        collector.snapshot("interrupted")
    posts = latest(collector.posts.values(), args.limit)
    if not args.no_download and not blocked:
        download_media(posts, output, driver, args.download_videos)
    else:
        for post in posts:
            if post["photos"]:
                post["issues"].append("media_not_downloaded")
                refresh_status(post)
    unknown_dates = [p["key"] for p in collector.posts.values() if p["published_at"] is None]
    owner_ids = sorted({p["owner_id"] for p in posts})
    total = collector.wall_counts.get(collector.owner_id)
    required_candidates = max(args.limit * 2, args.limit + 5)
    if total is not None:
        required_candidates = min(total, required_candidates)
    enough_candidates = len(collector.posts) >= required_candidates
    target_count = min(args.limit, total) if total is not None else args.limit
    selection_valid = len(posts) == target_count and bool(posts) and not unknown_dates and not blocked and len(owner_ids) == 1 and enough_candidates
    manifest = {"schema_version": 1, "source_url": args.url, "created_at": datetime.now(timezone.utc).isoformat(),
        "requested_count": args.limit, "candidate_count": len(collector.posts), "wall_count_reported": total, "stop_reason": reason, "owner_id": collector.owner_id,
        "selection": {"valid": selection_valid, "order": "oldest_to_newest", "unknown_date_keys": unknown_dates,
            "lookahead_reached": scan_lookahead,
            "scope": "Newest by machine date among observed wall posts; scroll lookahead is not a proof of full wall coverage."},
        "posts": posts}
    for key in collector.posts:
        collector.save_post(key)
    write_json(output / "manifest.json", manifest)
    with (output / "posts.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["key", "published_iso", "status", "text", "url"])
        writer.writeheader()
        writer.writerows({k: p.get(k, "") for k in writer.fieldnames} for p in posts)
    return manifest
