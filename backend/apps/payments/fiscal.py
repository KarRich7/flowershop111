"""Подготовка данных чека по 54-ФЗ. Онлайн-касса пока не подключена: данные сохраняются в платеже
и передаются провайдеру, когда он поддерживает фискализацию."""


def build_receipt(order):
    items = []
    for it in order.items.all():
        items.append({
            "description": it.name[:128], "quantity": it.quantity, "price": it.unit_price,
            "amount": it.line_total, "vat_code": "none", "payment_subject": "commodity", "payment_mode": "full_payment",
        })
    if order.delivery_cost:
        items.append({"description": "Доставка", "quantity": 1, "price": order.delivery_cost,
                      "amount": order.delivery_cost, "vat_code": "none", "payment_subject": "service",
                      "payment_mode": "full_payment"})
    return {"customer": {"phone": order.contact_phone, "email": order.contact_email}, "items": items,
            "total": order.total, "currency": "RUB", "fiscalized": False}
