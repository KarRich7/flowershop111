from django.conf import settings

from apps.core.models import ShopSettings
from apps.core.tasks_util import enqueue
from apps.core.utils import rub
from apps.customers.models import CustomerChannel

from apps.payments.providers.registry import pay_label

from .models import Notification

CUSTOMER_STATUS_TEXT = {
    "confirmed": "✅ Заказ №{n} подтверждён. Мы начнём сборку ко времени получения.",
    "assembling": "💐 Флорист собирает заказ №{n}.",
    "handed_to_courier": "🚗 Заказ №{n} передан курьеру и скоро будет у получателя.",
    "awaiting_pickup": "🛍 Заказ №{n} готов и ждёт вас: {address}. {hours}.",
    "delivered": "🌷 Заказ №{n} доставлен/выдан. Спасибо, что выбрали нас!",
    "cancelled": "❌ Заказ №{n} отменён. {reason}",
}


def _order_url(order):
    return f"{settings.FRONTEND_URL}/order/{order.public_token}"


def _customer_channels(order):
    if not order.customer_id:
        return []
    return list(CustomerChannel.objects.filter(customer_id=order.customer_id, channel__in=["telegram", "vk"]))


def staff_recipient():
    """Куда уходят уведомления сотрудникам — для ленты в админке: «tg:… vk:…»."""
    parts = [f"tg:{settings.TELEGRAM_STAFF_CHAT_ID}" if settings.TELEGRAM_STAFF_CHAT_ID else "",
             f"vk:{settings.VK_STAFF_PEER_ID}" if settings.VK_STAFF_PEER_ID else ""]
    return " ".join(p for p in parts if p)[:64]


def create(channel, text, *, kind, recipient="", customer=None, order=None, payload=None):
    n = Notification.objects.create(channel=channel, recipient=str(recipient), text=text, kind=kind,
                                    customer=customer, order=order, payload=payload or {})
    from .tasks import send_notification_task

    enqueue(send_notification_task, n.id)
    return n


def _to_customer(order, text, kind, buttons=None):
    payload = {"buttons": buttons or [[{"text": "Статус заказа", "url": _order_url(order)}]]}
    links = _customer_channels(order)
    for link in links:
        create(link.channel, text, kind=kind, recipient=link.external_id, customer=order.customer, order=order,
               payload=payload)
    if not links and order.source == "web":
        create("sms", text, kind=kind, recipient=order.contact_phone, customer=order.customer, order=order)


def order_event(order, kind, from_status=None, **extra):
    from apps.payments.services import current_payment_url

    shop = ShopSettings.load()
    n = order.number
    if kind == "created":
        if order.source == "store":
            return
        text = f"Заказ №{n} принят. Сумма: {rub(order.total)}."
        buttons = None
        if order.status == "awaiting_payment":
            url = current_payment_url(order)
            text += f"\nОплатите заказ в течение {shop.online_reservation_minutes} мин — товар зарезервирован."
            if url:
                buttons = [[{"text": pay_label(), "url": url}], [{"text": "Статус заказа", "url": _order_url(order)}]]
        elif order.status == "awaiting_confirmation":
            d = getattr(order, "delivery", None)
            if d is not None and d.address_pending:
                text += "\nФлорист позвонит получателю, уточнит адрес и подтвердит заказ. Оплата — после подтверждения."
            else:
                text += "\nФлорист проверит возможность сборки и подтвердит заказ. Оплата — после подтверждения."
        else:
            text += "\nМы свяжемся с вами для подтверждения. Оплата при получении."
        _to_customer(order, text, "order_created", buttons)
        staff_text = (f"🆕 Новый заказ №{n} ({order.get_source_display()}) на {rub(order.total)}. "
                      f"Статус: {order.get_status_display()}. {order.contact_name}, {order.contact_phone}")
        d = getattr(order, "delivery", None)
        flags = [t for on, t in ((d is not None and d.address_pending, "адрес узнать у получателя"),
                                 (d is not None and d.surprise, "сюрприз — не звонить заранее"),
                                 (d is not None and d.anonymous, "анонимно"),
                                 (order.photo_before, "фото букета перед отправкой")) if on]
        if flags:
            staff_text += "\nОтметки: " + ", ".join(flags) + "."
        create("staff", staff_text, kind="staff_new_order", order=order, recipient=staff_recipient())
        return
    if kind == "status":
        if order.status == "awaiting_payment" and from_status == "awaiting_confirmation":
            url = current_payment_url(order)
            text = (f"Флорист подтвердил заказ №{n}. Оплатите {rub(order.total)} в течение "
                    f"{shop.online_reservation_minutes} мин.")
            buttons = [[{"text": pay_label(), "url": url}]] if url else None
            _to_customer(order, text, "payment_link", buttons)
            return
        template = CUSTOMER_STATUS_TEXT.get(order.status)
        if not template:
            return
        if order.status == "confirmed" and from_status == "new":
            template = "✅ Заказ №{n} подтверждён. Оплата при получении."
        text = template.format(n=n, address=shop.address, hours=shop.working_hours,
                               reason=order.cancel_reason or "")
        _to_customer(order, text.strip(), f"status_{order.status}")


def order_photo(order):
    """Флорист сфотографировал собранный букет — показываем покупателю до отправки."""
    if order.source == "store":
        return
    text = f"📷 Букет к заказу №{order.number} собран. Фото — на странице заказа."
    _to_customer(order, text, "order_photo", [[{"text": "Посмотреть фото", "url": _order_url(order)}]])
