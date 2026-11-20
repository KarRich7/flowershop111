"""Личные уведомления сотрудникам о новых заказах и обращениях — с учётом смен.

Каждый сотрудник привязывает свой Telegram и/или ВК одноразовой ссылкой из админки
(t.me/<бот>?start=staff_<код> или vk.me/club<id>?ref=staff_<код>) и выбирает режим:
  «Всегда» (по умолчанию у владельца), «Только на смене» (у флористов), «Не присылать» (у курьеров).
Смену начинают и заканчивают кнопкой в боте (команда /smena или слово «смена») или в админке.
Забытая смена закрывается сама через STAFF_SHIFT_MAX_HOURS часов.
Если на смене никого нет и режим «Всегда» ни у кого не выбран — уведомление получают владельцы,
чтобы заказ не потерялся.
"""
import secrets
from datetime import timedelta

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.core.models import User

LINK_TTL = timedelta(hours=24)
FIELD = {"telegram": "telegram_id", "vk": "vk_id"}


def new_link(user):
    """Одноразовые ссылки привязки Telegram/ВК (действуют 24 ч, после привязки сгорают)."""
    from apps.customers.login import telegram_username, vk_link_base

    user.link_code = secrets.token_urlsafe(15)  # 20 символов A-Za-z0-9_-
    user.link_code_expires = timezone.now() + LINK_TTL
    user.save(update_fields=["link_code", "link_code_expires"])
    tg = telegram_username() if settings.TELEGRAM_BOT_TOKEN else ""
    vk = vk_link_base() if settings.VK_GROUP_TOKEN else ""
    return {
        "telegram_url": f"https://t.me/{tg}?start=staff_{user.link_code}" if tg else "",
        "vk_url": f"{vk}?ref=staff_{user.link_code}" if vk else "",
        "expires_at": user.link_code_expires.isoformat(),
        "code_message": f"staff {user.link_code}",  # запасной способ: отправить боту это сообщение
        "telegram_hint": "" if tg else ("Telegram-бот не настроен: нужен TELEGRAM_BOT_TOKEN и TELEGRAM_BOT_USERNAME "
                                        "(имя бота без @) в .env"),
        "vk_hint": "" if vk else "ВК-бот не настроен: нужен VK_GROUP_TOKEN и VK_GROUP_ID в .env",
    }


def link(channel, code, external_id):
    """Привязать чат к сотруднику по коду из ссылки. Возвращает сотрудника или None (код неверный/устарел)."""
    if not code:
        return None
    user = User.objects.filter(is_active=True, link_code=code, link_code_expires__gt=timezone.now()).first()
    if not user:
        return None
    field = FIELD[channel]
    User.objects.filter(**{field: str(external_id)}).exclude(pk=user.pk).update(**{field: ""})  # один чат — один сотрудник
    setattr(user, field, str(external_id))
    user.link_code, user.link_code_expires = "", None
    user.save(update_fields=[field, "link_code", "link_code_expires"])
    return user


def unlink(user, channel):
    setattr(user, FIELD[channel], "")
    user.save(update_fields=[FIELD[channel]])


def staff_for(channel, external_id):
    if not external_id:
        return None
    return User.objects.filter(is_active=True, **{FIELD[channel]: str(external_id)}).first()


def set_shift(user, on):
    on = bool(on)
    if user.on_shift != on:
        user.on_shift = on
        user.shift_started_at = timezone.now() if on else None
        user.save(update_fields=["on_shift", "shift_started_at"])
    return user


def on_shift_names(exclude=None):
    qs = User.objects.filter(is_active=True, on_shift=True)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return [u.display_name for u in qs.order_by("first_name", "username")]


def recipients():
    """Кому сейчас отправлять: (сотрудники, заметка к тексту). Только с привязанным мессенджером."""
    linked = list(User.objects.filter(is_active=True).exclude(notify_mode=User.NotifyMode.OFF)
                  .filter(Q(telegram_id__gt="") | Q(vk_id__gt="")).order_by("id"))
    chosen = [u for u in linked if u.notify_mode == User.NotifyMode.ALWAYS or u.on_shift]
    nobody = not User.objects.filter(is_active=True, on_shift=True).exists()
    note = "⚠️ Сейчас никто не отметился на смене." if nobody else ""
    if not chosen:  # чтобы заказ не потерялся — владельцам
        chosen = [u for u in linked if u.role == User.Role.OWNER]
    return chosen, note


def shift_max_hours():
    return max(1, int(getattr(settings, "STAFF_SHIFT_MAX_HOURS", 14) or 14))


def stale_shifts():
    """Смены, которые забыли закрыть."""
    border = timezone.now() - timedelta(hours=shift_max_hours())
    return User.objects.filter(on_shift=True, shift_started_at__lt=border)
