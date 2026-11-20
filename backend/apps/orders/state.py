"""Конечный автомат статусов заказа. Любой переход вне таблицы запрещён."""
from .models import Order

S = Order.Status

TRANSITIONS = {
    S.NEW: {S.AWAITING_CONFIRMATION, S.AWAITING_PAYMENT, S.CONFIRMED, S.CANCELLED},
    S.AWAITING_CONFIRMATION: {S.AWAITING_PAYMENT, S.CONFIRMED, S.CANCELLED},
    S.AWAITING_PAYMENT: {S.CONFIRMED, S.CANCELLED},
    S.CONFIRMED: {S.ASSEMBLING, S.CANCELLED},
    S.ASSEMBLING: {S.READY, S.CANCELLED},
    S.READY: {S.HANDED_TO_COURIER, S.AWAITING_PICKUP, S.CANCELLED},
    S.HANDED_TO_COURIER: {S.DELIVERED},
    S.AWAITING_PICKUP: {S.DELIVERED, S.CANCELLED},
    S.DELIVERED: {S.COMPLETED},
    S.COMPLETED: set(),
    S.CANCELLED: set(),
}

# Переходы, разрешённые курьеру (только по назначенным ему заказам)
COURIER_TRANSITIONS = {
    (S.READY, S.HANDED_TO_COURIER),
    (S.HANDED_TO_COURIER, S.DELIVERED),
}

# Статусы, в которых действует резерв с ограниченным сроком
HOLD_STATUSES = {S.NEW, S.AWAITING_CONFIRMATION, S.AWAITING_PAYMENT}
# Статусы до фактического списания (резерв ещё активен)
PRE_FULFILLMENT = {S.NEW, S.AWAITING_CONFIRMATION, S.AWAITING_PAYMENT, S.CONFIRMED, S.ASSEMBLING}
ACTIVE_STATUSES = set(S.values) - {S.COMPLETED, S.CANCELLED}


def label(status):
    return S(status).label


def allowed_targets(order, user=None):
    """Переходы для кнопок в админке: таблица переходов с учётом способа получения, оплаты и роли.
    Сами проверки повторяются на сервере при переходе (services._guards)."""
    F, PM = Order.Fulfillment, Order.PaymentMethod
    out = []
    for to in TRANSITIONS[S(order.status)]:
        if to == S.HANDED_TO_COURIER and order.fulfillment != F.DELIVERY:
            continue
        if to == S.AWAITING_PICKUP and order.fulfillment != F.PICKUP:
            continue
        if to == S.AWAITING_PAYMENT and order.payment_method != PM.ONLINE:
            continue
        if to == S.CONFIRMED and order.payment_method == PM.ONLINE and order.payment_status != Order.PaymentStatus.PAID:
            continue  # онлайн-заказ подтверждается оплатой
        if to == S.COMPLETED and order.payment_status != Order.PaymentStatus.PAID:
            continue
        if user is not None and getattr(user, "role", "") == "courier" and (order.status, to) not in COURIER_TRANSITIONS:
            continue
        out.append(to)
    return sorted(out, key=list(S.values).index)
