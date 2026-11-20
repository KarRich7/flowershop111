import logging

import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

from apps.bots import telegram_net
from apps.customers.models import CustomerChannel

from .models import Notification

logger = logging.getLogger(__name__)
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


def _is_public_url(url):
    return url.startswith("https://") or (url.startswith("http://") and not any(h in url for h in LOCAL_HOSTS))


def send_telegram(chat_id, text, buttons=None):
    rows, extra = [], []
    for row in buttons or []:
        r = []
        for b in row:
            if _is_public_url(b["url"]):
                r.append({"text": b["text"], "url": b["url"]})
            else:  # Telegram не принимает localhost-ссылки в кнопках — передаём текстом
                extra.append(f"{b['text']}: {b['url']}")
        if r:
            rows.append(r)
    body = {"chat_id": chat_id, "text": "\n".join([text] + extra), "disable_web_page_preview": True}
    if rows:
        body["reply_markup"] = {"inline_keyboard": rows}
    data = telegram_net.call("sendMessage", json=body)
    new_id = (data.get("parameters") or {}).get("migrate_to_chat_id")
    if not data.get("ok") and new_id:  # группа стала супергруппой — у неё новый номер
        logger.warning("Группа Telegram получила новый номер %s — впишите в .env TELEGRAM_STAFF_CHAT_ID=%s", new_id, new_id)
        body["chat_id"] = new_id
        data = telegram_net.call("sendMessage", json=body)
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API error"))


def send_vk(peer_id, text, buttons=None):
    import json
    import random

    lines = [text] + [f"{b['text']}: {b['url']}" for row in buttons or [] for b in row]
    params = {"peer_id": peer_id, "random_id": random.randint(1, 2**31), "message": "\n".join(lines),
              "access_token": settings.VK_GROUP_TOKEN, "v": settings.VK_API_VERSION, "dont_parse_links": 1}
    r = requests.post("https://api.vk.com/method/messages.send", data=params, timeout=15).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("error_msg", "VK API error"))


def _send_personal(user, text, buttons):
    """Одному сотруднику: сначала Telegram, если он недоступен — ВК (без дублей в оба мессенджера)."""
    errors = []
    if settings.TELEGRAM_BOT_TOKEN and user.telegram_id:
        try:
            send_telegram(user.telegram_id, text, buttons)
            return "Telegram", errors
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{user.display_name} (Telegram): {exc}")
    if settings.VK_GROUP_TOKEN and user.vk_id:
        try:
            send_vk(user.vk_id, text, buttons)
            return "ВК", errors
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{user.display_name} (ВК): {exc}")
    return None, errors


def send_to_staff(text, buttons=None):
    """Уведомление сотрудникам: лично тем, кто на смене (и с режимом «Всегда»), а также в общую группу
    Telegram и беседу ВК, если они заданы в .env. Возвращает (куда отправлено, ошибки)."""
    from . import staff

    sent, errors = [], []
    people, note = staff.recipients()
    full = f"{text}\n{note}" if note else text
    for user in people:
        where, errs = _send_personal(user, full, buttons)
        errors += errs
        if where:
            sent.append(f"{user.display_name} ({where})")
    groups = []
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_STAFF_CHAT_ID:
        groups.append(("группа Telegram", lambda: send_telegram(settings.TELEGRAM_STAFF_CHAT_ID, text, buttons)))
    if settings.VK_GROUP_TOKEN and settings.VK_STAFF_PEER_ID:
        groups.append(("беседа ВК", lambda: send_vk(settings.VK_STAFF_PEER_ID, text, buttons)))
    for name, send in groups:
        try:
            send()
            sent.append(name)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}: {exc}")
    return sent, errors


def _staff_buttons(n):
    base = settings.FRONTEND_URL.rstrip("/")
    if n.order_id:
        return [[{"text": "Открыть заказ", "url": f"{base}/admin/orders/{n.order_id}"}]]
    return [[{"text": "Открыть админку", "url": f"{base}/admin"}]]


@shared_task(name="staff.end_stale_shifts")
def end_stale_shifts():
    """Закрывает забытые смены и сообщает об этом сотруднику."""
    from . import staff

    hours = staff.shift_max_hours()
    for user in staff.stale_shifts():
        staff.set_shift(user, False)
        text = (f"⏹ Смена закрыта автоматически — прошло {hours} ч. Уведомления о заказах больше не приходят.\n"
                "Если вы ещё работаете, начните смену заново: команда /smena (в ВК — слово «смена»).")
        _send_personal(user, text, None)


@shared_task(name="notifications.send", bind=True, max_retries=3, default_retry_delay=30)
def send_notification_task(self, notification_id):
    n = Notification.objects.filter(pk=notification_id, status=Notification.Status.PENDING).first()
    if not n:
        return
    buttons = (n.payload or {}).get("buttons")
    try:
        if n.channel in ("telegram", "vk"):
            link = CustomerChannel.objects.filter(channel=n.channel, external_id=n.recipient).first()
            token = settings.TELEGRAM_BOT_TOKEN if n.channel == "telegram" else settings.VK_GROUP_TOKEN
            if link and link.is_simulated:
                n.status, n.error = Notification.Status.DEMO, "Доставлено в локальный симулятор"
            elif not token:
                n.status, n.error = Notification.Status.SKIPPED, "Токен бота не задан"
            elif n.channel == "telegram":
                send_telegram(link.chat_id if link else n.recipient, n.text, buttons)
                n.status = Notification.Status.SENT
            else:
                send_vk(link.chat_id if link else n.recipient, n.text, buttons)
                n.status = Notification.Status.SENT
        elif n.channel == "staff":
            sent, errors = send_to_staff(n.text, _staff_buttons(n))
            if errors and not sent:
                raise RuntimeError("; ".join(errors))
            if sent:
                n.status, n.error = Notification.Status.SENT, "; ".join(errors)[:255]
                n.recipient = ", ".join(sent)[:64]
            else:
                n.status, n.error = Notification.Status.DEMO, "Показано в ленте админ-панели (никто из сотрудников не привязал Telegram/ВК)"
        elif n.channel == "sms":
            n.status, n.error = Notification.Status.SKIPPED, "SMS-шлюз не подключён"
        n.sent_at = timezone.now()
        n.save(update_fields=["status", "error", "sent_at", "recipient"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("Notification %s failed: %s", n.id, exc)
        if self.request.retries < self.max_retries and not settings.CELERY_TASK_ALWAYS_EAGER:
            raise self.retry(exc=exc)
        n.status, n.error = Notification.Status.FAILED, str(exc)[:255]
        n.save(update_fields=["status", "error"])
