"""Личные уведомления сотрудникам с учётом смен: привязка Telegram/ВК ссылкой, кнопки смены в боте,
кому уходит уведомление о заказе, автозакрытие забытой смены, API админки."""
from datetime import timedelta
from unittest import mock

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.bots.engine import BotEngine, Incoming
from apps.core.models import User
from apps.notifications import staff as staff_notify
from apps.notifications.models import Notification
from apps.notifications.tasks import end_stale_shifts, send_notification_task

from .conftest import make_user, staff_client

pytestmark = pytest.mark.django_db
VK = dict(VK_GROUP_TOKEN="vk1.a.key", VK_GROUP_ID="233702651")


def _texts(outs):
    return "\n".join(o.text for o in outs)


def test_default_notify_mode_by_role(staff):
    assert staff["owner"].notify_mode == "always"
    assert staff["florist"].notify_mode == "shift"
    assert staff["courier1"].notify_mode == "off"


@override_settings(**VK)
def test_florist_links_vk_and_toggles_shift_in_bot(staff):
    florist = staff["florist"]
    links = staff_client("owner").post(f"/api/v1/admin/staff/{florist.id}/link").json()
    assert links["vk_url"].startswith("https://vk.me/club233702651?ref=staff_")
    code = links["vk_url"].split("ref=staff_")[1]
    engine = BotEngine("vk")

    out = _texts(engine.handle(Incoming(channel="vk", user_id="555", chat_id="555", ref=f"staff_{code}")))
    florist.refresh_from_db()
    assert florist.vk_id == "555" and "привязан" in out and "не на смене" in out
    # ссылка одноразовая
    again = _texts(engine.handle(Incoming(channel="vk", user_id="777", chat_id="777", ref=f"staff_{code}")))
    assert "устарела" in again

    out = _texts(engine.handle(Incoming(channel="vk", user_id="555", chat_id="555", payload="shift:on")))
    florist.refresh_from_db()
    assert florist.on_shift and florist.shift_started_at and "Вы на смене с" in out
    out = _texts(engine.handle(Incoming(channel="vk", user_id="555", chat_id="555", text="Смена")))
    assert "Закончить смену" in str(engine.handle(Incoming(channel="vk", user_id="555", chat_id="555", text="смена"))[0].buttons)
    engine.handle(Incoming(channel="vk", user_id="555", chat_id="555", payload="shift:off"))
    florist.refresh_from_db()
    assert not florist.on_shift and florist.shift_started_at is None


def test_telegram_start_link_and_customers_cannot_use_shift(staff):
    florist = staff["florist"]
    florist.link_code, florist.link_code_expires = "abcdefgh12345678", timezone.now() + timedelta(hours=1)
    florist.save()
    engine = BotEngine("telegram")
    out = _texts(engine.handle(Incoming(channel="telegram", user_id="42", chat_id="42", text="/start staff_abcdefgh12345678")))
    florist.refresh_from_db()
    assert florist.telegram_id == "42" and "Telegram привязан" in out
    # обычный покупатель: «смена» — не команда сотрудника, кнопка смены — отказ
    out = _texts(engine.handle(Incoming(channel="telegram", user_id="99", chat_id="99", text="смена")))
    assert "Вы на смене" not in out and "не на смене" not in out
    out = _texts(engine.handle(Incoming(channel="telegram", user_id="99", chat_id="99", payload="shift:on")))
    assert "только для сотрудников" in out


def test_link_by_code_message_fallback(staff):
    florist = staff["florist"]
    florist.link_code, florist.link_code_expires = "Codefallback1234", timezone.now() + timedelta(hours=1)
    florist.save()
    out = _texts(BotEngine("vk").handle(Incoming(channel="vk", user_id="555", chat_id="555", text="staff Codefallback1234")))
    florist.refresh_from_db()
    assert florist.vk_id == "555" and "привязан" in out


def test_expired_link_is_rejected(staff):
    florist = staff["florist"]
    florist.link_code, florist.link_code_expires = "expiredcode12345", timezone.now() - timedelta(minutes=1)
    florist.save()
    assert staff_notify.link("vk", "expiredcode12345", "555") is None


def _link(user, tg="", vk="", on_shift=False):
    user.telegram_id, user.vk_id = tg, vk
    user.on_shift, user.shift_started_at = on_shift, (timezone.now() if on_shift else None)
    user.save()
    return user


def test_recipients_follow_shifts(staff):
    owner = _link(staff["owner"], tg="1")
    on = _link(staff["florist"], vk="2", on_shift=True)
    off = _link(make_user("florist2", User.Role.FLORIST), vk="3")
    _link(staff["courier1"], vk="4", on_shift=True)  # курьеру уведомления о заказах не нужны (режим «Не присылать»)
    people, note = staff_notify.recipients()
    assert people == [owner, on] and note == ""
    assert off not in people


def test_nobody_on_shift_falls_back_to_owner_with_warning(staff):
    owner = _link(staff["owner"], tg="1")
    owner.notify_mode = "shift"
    owner.save()
    _link(staff["florist"], vk="2")
    people, note = staff_notify.recipients()
    assert people == [owner] and "никто не отметился на смене" in note


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_STAFF_CHAT_ID="", VK_STAFF_PEER_ID="",
                   FRONTEND_URL="https://cvetyurala.ru", **VK)
def test_staff_notification_reaches_only_people_on_shift(staff):
    _link(staff["owner"], tg="1")
    _link(staff["florist"], tg="2", vk="22", on_shift=True)
    _link(make_user("florist2", User.Role.FLORIST), vk="3")  # не на смене
    n = Notification.objects.create(channel="staff", kind="support_request", text="💬 Вопрос")
    with mock.patch("apps.notifications.tasks.send_telegram") as tg, mock.patch("apps.notifications.tasks.send_vk") as vk:
        send_notification_task(n.id)
    assert sorted(c.args[0] for c in tg.call_args_list) == ["1", "2"]
    vk.assert_not_called()  # у флориста есть Telegram — дубль в ВК не нужен
    assert tg.call_args.args[2] == [[{"text": "Открыть админку", "url": "https://cvetyurala.ru/admin"}]]
    n.refresh_from_db()
    assert n.status == "sent" and "Telegram" in n.recipient


@override_settings(TELEGRAM_BOT_TOKEN="123:abc", TELEGRAM_STAFF_CHAT_ID="", VK_STAFF_PEER_ID="", **VK)
def test_telegram_down_person_gets_vk_instead(staff):
    staff["owner"].notify_mode = "off"
    staff["owner"].save()
    _link(staff["florist"], tg="2", vk="22", on_shift=True)
    n = Notification.objects.create(channel="staff", kind="support_request", text="💬 Вопрос")
    with mock.patch("apps.notifications.tasks.send_telegram", side_effect=RuntimeError("timeout")), \
            mock.patch("apps.notifications.tasks.send_vk") as vk:
        send_notification_task(n.id)
    assert vk.call_args.args[0] == "22"
    n.refresh_from_db()
    assert n.status == "sent" and "(Telegram): timeout" in n.error


@override_settings(STAFF_SHIFT_MAX_HOURS=14, **VK)
def test_forgotten_shift_is_closed_automatically(staff):
    florist = _link(staff["florist"], vk="2", on_shift=True)
    User.objects.filter(pk=florist.pk).update(shift_started_at=timezone.now() - timedelta(hours=15))
    fresh = _link(make_user("florist2", User.Role.FLORIST), vk="3", on_shift=True)
    with mock.patch("apps.notifications.tasks.send_vk") as vk:
        end_stale_shifts()
    florist.refresh_from_db()
    fresh.refresh_from_db()
    assert not florist.on_shift and fresh.on_shift
    assert vk.call_args.args[0] == "2" and "закрыта автоматически" in vk.call_args.args[1]


def test_admin_api_my_shift_and_owner_controls(staff):
    c = staff_client("florist")
    r = c.patch("/api/v1/admin/me/notify", {"on_shift": True}, format="json").json()
    assert r["on_shift"] is True and r["on_shift_now"] == [staff["florist"].display_name]
    assert "telegram_url" in c.post("/api/v1/admin/me/notify/link").json()
    # флорист не может управлять другими
    assert c.patch(f"/api/v1/admin/staff/{staff['owner'].id}", {"on_shift": True}, format="json").status_code == 403
    assert c.post(f"/api/v1/admin/staff/{staff['owner'].id}/link").status_code == 403
    owner = staff_client("owner")
    _link(staff["florist"], tg="2", on_shift=True)
    r = owner.patch(f"/api/v1/admin/staff/{staff['florist'].id}",
                    {"notify_mode": "always", "on_shift": False, "unlink": "telegram"}, format="json").json()
    assert r["notify_mode"] == "always" and r["on_shift"] is False and r["telegram_linked"] is False
    assert owner.patch(f"/api/v1/admin/staff/{staff['florist'].id}", {"notify_mode": "sometimes"},
                       format="json").status_code == 400
