"""Проверка настроек ботов: docker compose exec backend python manage.py check_bots [--send]

Ничего не меняет. Показывает, принимает ли Telegram токен бота (и есть ли вообще связь с Telegram),
от какого сообщества ключ ВК, совпадает ли он с VK_GROUP_ID, какие у ключа права и включён ли Long Poll.
С --send отправляет тестовое сообщение сотрудникам (TELEGRAM_STAFF_CHAT_ID и VK_STAFF_PEER_ID)."""
import random

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.bots import telegram_net

VK_API = "https://api.vk.com/method/"


class Command(BaseCommand):
    help = "Проверка Telegram- и ВК-бота (токены, связь, сообщество, права ключа)"
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--send", action="store_true", help="отправить тестовое сообщение в чаты сотрудников")

    def ok(self, text):
        self.stdout.write(self.style.SUCCESS("  ✔ " + text))

    def bad(self, text):
        self.stdout.write(self.style.ERROR("  ✘ " + text))

    def info(self, text):
        self.stdout.write("  • " + text)

    def handle(self, *args, **opts):
        self.send = opts["send"]
        self.check_telegram(opts["send"])
        self.stdout.write("")
        self.check_vk()
        self.stdout.write("")
        self.check_staff()

    def check_staff(self):
        from apps.core.models import User
        from apps.notifications import staff as staff_notify

        self.stdout.write(self.style.MIGRATE_HEADING("Уведомления сотрудникам"))
        for u in User.objects.filter(is_active=True).order_by("role", "username"):
            where = ", ".join(n for n, on in (("Telegram", u.telegram_id), ("ВК", u.vk_id)) if on) or "мессенджер не привязан"
            shift = "на смене" if u.on_shift else "не на смене"
            line = f"{u.display_name} ({u.get_role_display()}): {u.get_notify_mode_display().lower()}, {shift}, {where}"
            if u.notify_mode != "off" and not (u.telegram_id or u.vk_id):
                self.bad(line + " — привязка: админка → «Уведомления»")
            else:
                self.info(line)
        people, note = staff_notify.recipients()
        names = ", ".join(u.display_name for u in people) or "никому (уведомления видны только в админке)"
        self.info(f"новый заказ сейчас получат: {names}" + (f" ({note})" if note else ""))

    # --- Telegram
    def check_telegram(self, send):
        self.stdout.write(self.style.MIGRATE_HEADING("Telegram"))
        token = settings.TELEGRAM_BOT_TOKEN
        if not token:
            self.info("TELEGRAM_BOT_TOKEN не задан — Telegram-бот выключен")
            return
        if ":" not in token:
            self.bad(f"TELEGRAM_BOT_TOKEN выглядит неверно (длина {len(token)}, нет двоеточия) — скопируйте из @BotFather")
        if settings.TELEGRAM_PROXY:
            self.info(f"прокси: {telegram_net.proxy_display()}")
        else:
            self.info("прокси: нет (напрямую)")
        if settings.TELEGRAM_API_BASE != telegram_net.DEFAULT_API_BASE:
            self.info(f"адрес Bot API: {settings.TELEGRAM_API_BASE}")
        try:
            data = telegram_net.call("getMe", "GET", timeout=15)
        except requests.RequestException as e:
            self.bad(telegram_net.no_connection_hint() + f" [{type(e).__name__}]")
            return
        except ValueError:
            self.bad("Telegram вернул не JSON — проверьте TELEGRAM_API_BASE")
            return
        if not data.get("ok"):
            self.bad(f"Telegram отклонил токен: {data.get('description')} — возьмите токен заново в @BotFather")
            return
        username = data["result"].get("username", "")
        self.ok(f"бот @{username} отвечает, токен верный")
        if settings.TELEGRAM_BOT_USERNAME and settings.TELEGRAM_BOT_USERNAME.lower() != username.lower():
            self.bad(f"TELEGRAM_BOT_USERNAME={settings.TELEGRAM_BOT_USERNAME}, а токен от @{username} — исправьте")
        elif not settings.TELEGRAM_BOT_USERNAME:
            self.info(f"TELEGRAM_BOT_USERNAME пуст — можно указать {username}")
        chat = settings.TELEGRAM_STAFF_CHAT_ID
        if not chat:
            self.info("TELEGRAM_STAFF_CHAT_ID пуст — уведомления сотрудникам в Telegram не приходят")
        elif send:
            try:
                r = telegram_net.call("sendMessage", json={"chat_id": chat, "text": "Проверка: уведомления о заказах работают ✅"})
            except requests.RequestException as e:
                self.bad(f"не удалось отправить тестовое сообщение: {type(e).__name__}")
                return
            if r.get("ok"):
                self.ok(f"тестовое сообщение отправлено в чат {chat}")
            else:
                self.bad(f"тестовое сообщение не отправлено: {r.get('description')} — "
                         "проверьте номер (/chatid в группе или @userinfobot) и что бот добавлен в группу / вы нажали Start")
        else:
            self.info(f"уведомления владельцу: чат {chat} (проверить отправку: check_bots --send)")

    # --- ВКонтакте
    def vk(self, method, **params):
        params.update(access_token=settings.VK_GROUP_TOKEN, v=settings.VK_API_VERSION)
        data = requests.post(VK_API + method, data=params, timeout=15).json()
        if "error" in data:
            err = data["error"]
            raise RuntimeError(f"{err.get('error_msg')} (код {err.get('error_code')})")
        return data["response"]

    def check_vk(self):
        self.stdout.write(self.style.MIGRATE_HEADING("ВКонтакте"))
        token, group_id = settings.VK_GROUP_TOKEN, settings.VK_GROUP_ID
        if not token or not group_id:
            self.info("VK_GROUP_TOKEN или VK_GROUP_ID не задан — ВК-бот выключен")
            return
        self.info(f"длина ключа: {len(token)} (полный ключ сообщества обычно около 200 символов)")
        try:
            resp = self.vk("groups.getById")
        except requests.RequestException as e:
            self.bad(f"нет связи с api.vk.com: {type(e).__name__}")
            return
        except RuntimeError as e:
            self.bad(f"ключ не принят: {e} — создайте новый ключ и скопируйте его целиком (кнопка «Показать»)")
            return
        groups = resp.get("groups", resp) if isinstance(resp, dict) else resp
        group = groups[0] if groups else {}
        real_id = str(group.get("id", ""))
        self.ok(f"ключ рабочий, сообщество «{group.get('name')}» (vk.com/{group.get('screen_name')}), номер {real_id}")
        if real_id != group_id:
            self.bad(f"в .env VK_GROUP_ID={group_id}, а ключ от сообщества {real_id} — укажите VK_GROUP_ID={real_id}")
            return
        self.ok("VK_GROUP_ID совпадает")
        try:
            perms = {p.get("name") for p in self.vk("groups.getTokenPermissions").get("permissions", [])}
            need = {"manage": "управление сообществом", "messages": "сообщения сообщества",
                    "photos": "фотографии (для фото букетов)"}
            missing = [label for name, label in need.items() if name not in perms]
            if missing:
                self.bad("у ключа нет прав: " + ", ".join(missing) + " — создайте ключ с этими галочками")
            else:
                self.ok("права ключа: управление, сообщения, фотографии")
        except (RuntimeError, requests.RequestException) as e:
            self.info(f"права ключа проверить не удалось: {e}")
        try:
            lp = self.vk("groups.getLongPollSettings", group_id=group_id)
            if not lp.get("is_enabled"):
                self.bad("Long Poll API выключен: Управление → Работа с API → Long Poll API → Включено")
            else:
                self.ok(f"Long Poll API включён (версия {lp.get('api_version')})")
            if not (lp.get("events") or {}).get("message_new"):
                self.bad("в «Типы событий» не отмечено «Входящее сообщение»")
            else:
                self.ok("событие «Входящее сообщение» включено")
        except (RuntimeError, requests.RequestException) as e:
            self.bad(f"настройки Long Poll недоступны: {e}")
        try:
            self.vk("groups.getLongPollServer", group_id=group_id)
            self.ok("подключение бота к ВК работает")
        except (RuntimeError, requests.RequestException) as e:
            self.bad(f"бот не может подключиться: {e}")
        self.info("в настройках сообщества также должны быть включены «Сообщения» и «Возможности ботов»")
        peer = settings.VK_STAFF_PEER_ID
        if not peer:
            self.info("VK_STAFF_PEER_ID пуст — уведомления сотрудникам в ВК не приходят")
        elif self.send:
            try:
                self.vk("messages.send", peer_id=peer, random_id=random.randint(1, 2**31),
                        message="Проверка: уведомления о заказах работают ✅")
                self.ok(f"тестовое сообщение отправлено в ВК ({peer})")
            except (RuntimeError, requests.RequestException) as e:
                self.bad(f"тестовое сообщение в ВК не отправлено: {e} — проверьте, что сообщество добавлено в беседу")
        else:
            self.info(f"уведомления сотрудникам в ВК: {peer} (проверить отправку: check_bots --send)")
