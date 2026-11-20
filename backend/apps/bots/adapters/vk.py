"""Адаптер ВКонтакте: Bots Long Poll API + messages.send. Обычные сообщения сообщества
с inline-клавиатурой (кнопки с payload), без мини-приложений."""
import json
import logging
import random
import time
from pathlib import Path

import requests
from django.conf import settings
from django.core.cache import cache

from apps.bots.engine import BotEngine, Incoming

logger = logging.getLogger("bots.vk")
API = "https://api.vk.com/method/"


class VKError(Exception):
    pass


class VKApi:
    def __init__(self, token, version):
        self.token, self.version = token, version
        self.http = requests.Session()

    def call(self, method, **params):
        params.update(access_token=self.token, v=self.version)
        data = self.http.post(API + method, data=params, timeout=30).json()
        if "error" in data:
            raise VKError(f"{method}: {data['error'].get('error_msg')}")
        return data["response"]


def keyboard(out):
    """VK inline-клавиатура: до 6 рядов и 5 кнопок в ряду, подпись до 40 символов."""
    rows = []
    for row in out.buttons:
        r = []
        for b in row[:5]:
            if b.url:
                r.append({"action": {"type": "open_link", "link": b.url, "label": b.text[:40]}})
            elif b.payload:
                r.append({"action": {"type": "text", "label": b.text[:40], "payload": json.dumps({"cmd": b.payload})},
                          "color": "positive" if b.payload in ("checkout", "confirm:yes") else "secondary"})
            # кнопки «номер» и «геопозиция» в inline-клавиатуре ВК недоступны — пользователь пишет текстом
        if r:
            rows.append(r)
    if not rows:
        return None
    if len(rows) > 6:
        rows = rows[:5] + [rows[-1]]
    return json.dumps({"inline": True, "buttons": rows}, ensure_ascii=False)


CHAT_PEER_START = 2_000_000_000  # peer_id бесед ВК начинаются с 2000000001


def chat_reply(msg, group_id):
    """Сообщение в беседе: там бот не продаёт, а только подсказывает номер беседы для уведомлений сотрудникам —
    когда сообщество добавили в беседу или написали /chatid (с упоминанием сообщества). На остальное молчит."""
    peer = msg.get("peer_id")
    action = msg.get("action") or {}
    invited = action.get("type") == "chat_invite_user" and str(action.get("member_id")) == f"-{group_id}"
    if invited or "/chatid" in (msg.get("text") or "").lower():
        return (f"Номер этой беседы: {peer}\n\n"
                "Чтобы сюда приходили уведомления о новых заказах и обращениях покупателей, впишите на сервере "
                f"в файл .env строку:\nVK_STAFF_PEER_ID={peer}\n"
                "и перезапустите: docker compose up -d --force-recreate backend celery-worker vk-bot")
    return None


class VKBot:
    def __init__(self):
        self.api = VKApi(settings.VK_GROUP_TOKEN, settings.VK_API_VERSION)
        self.group_id = settings.VK_GROUP_ID
        self.engine = BotEngine("vk")

    def upload_photo(self, peer_id, rel_path):
        key = f"vk_photo:{rel_path}"
        cached = cache.get(key)
        if cached:
            return cached
        path = Path(settings.MEDIA_ROOT) / rel_path
        if not path.exists():
            return None
        server = self.api.call("photos.getMessagesUploadServer", peer_id=peer_id)
        with open(path, "rb") as f:
            up = requests.post(server["upload_url"], files={"photo": f}, timeout=60).json()
        saved = self.api.call("photos.saveMessagesPhoto", photo=up["photo"], server=up["server"], hash=up["hash"])[0]
        att = f"photo{saved['owner_id']}_{saved['id']}"
        cache.set(key, att, 60 * 60 * 24 * 30)
        return att

    def user_name(self, user_id):
        """Имя пользователя ВК (для приветствия и карточки клиента), кешируется на сутки."""
        key = f"vk_name:{user_id}"
        name = cache.get(key)
        if name is None:
            try:
                u = self.api.call("users.get", user_ids=user_id)[0]
                name = f"{u.get('first_name', '')} {u.get('last_name', '')}".strip()
            except Exception:  # noqa: BLE001
                name = ""
            cache.set(key, name, 60 * 60 * 24)
        return name

    def send(self, peer_id, out):
        params = {"peer_id": peer_id, "random_id": random.randint(1, 2**31), "message": out.text[:4000],
                  "dont_parse_links": 1}
        kb = keyboard(out)
        if kb:
            params["keyboard"] = kb
        if out.photo:
            try:
                att = self.upload_photo(peer_id, out.photo)
                if att:
                    params["attachment"] = att
            except Exception as e:  # noqa: BLE001
                logger.warning("photo upload failed: %s", e)
        self.api.call("messages.send", **params)

    def on_message(self, msg):
        if int(msg.get("peer_id") or 0) > CHAT_PEER_START:  # беседа сотрудников
            reply = chat_reply(msg, self.group_id)
            if reply:
                self.api.call("messages.send", peer_id=msg["peer_id"], random_id=random.randint(1, 2**31), message=reply)
            return
        payload = None
        if msg.get("payload"):
            try:
                payload = json.loads(msg["payload"]).get("cmd")
            except (ValueError, AttributeError):
                payload = None
        coords = (msg.get("geo") or {}).get("coordinates") or {}
        location = (coords["latitude"], coords["longitude"]) if "latitude" in coords and "longitude" in coords else None
        inc = Incoming(channel="vk", user_id=str(msg["from_id"]), chat_id=str(msg["peer_id"]),
                       text=msg.get("text", ""), payload=payload, location=location, ref=msg.get("ref") or None,
                       display_name=self.user_name(msg["from_id"]))
        for out in self.engine.handle(inc):
            self.send(msg["peer_id"], out)

    def run(self):
        try:
            server = self.api.call("groups.getLongPollServer", group_id=self.group_id)
        except VKError as e:
            logger.error("ВК не принял настройки бота: %s. Проверка ключа и сообщества: "
                         "docker compose exec backend python manage.py check_bots", e)
            time.sleep(30)  # не перезапускаться слишком часто, пока ключ неверный
            raise
        logger.info("VK bot started (group %s, Bots Long Poll)", self.group_id)
        ts = server["ts"]
        while True:
            try:
                r = requests.get(server["server"], params={"act": "a_check", "key": server["key"], "ts": ts, "wait": 25},
                                 timeout=35).json()
            except requests.RequestException as e:
                logger.warning("long poll error: %s", e)
                time.sleep(3)
                continue
            if "failed" in r:
                if r["failed"] == 1:
                    ts = r["ts"]
                else:
                    server = self.api.call("groups.getLongPollServer", group_id=self.group_id)
                    ts = server["ts"]
                continue
            ts = r["ts"]
            for upd in r.get("updates", []):
                if upd.get("type") == "message_new":
                    msg = upd["object"]["message"]
                    try:
                        self.on_message(msg)
                    except Exception:  # noqa: BLE001
                        logger.exception("failed to handle VK message")
