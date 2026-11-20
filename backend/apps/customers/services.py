from django.db import transaction

from apps.core.errors import ValidationError
from apps.core.utils import normalize_phone

from .models import Customer, CustomerChannel


def find_or_create_customer(name, phone, email="", preferred=None):
    """Находит клиента по телефону или создаёт нового. preferred — клиент из канала бота."""
    norm = normalize_phone(phone)
    if not norm:
        raise ValidationError("Укажите корректный номер телефона в формате +7XXXXXXXXXX", code="invalid_phone")
    existing = Customer.objects.filter(phone=norm).order_by("id").first()
    if existing:
        customer = existing
        if preferred and preferred.pk != existing.pk:
            CustomerChannel.objects.filter(customer=preferred).update(customer=existing)
    elif preferred:
        customer = preferred
        customer.phone = norm
    else:
        customer = Customer(phone=norm)
    if name and not customer.name:
        customer.name = name.strip()[:160]
    if email and not customer.email:
        customer.email = email.strip()
    customer.save()
    return customer


@transaction.atomic
def get_or_create_channel_customer(channel, external_id, chat_id="", display_name="", username="", simulated=False):
    link = CustomerChannel.objects.select_related("customer").filter(channel=channel, external_id=str(external_id)).first()
    if link:
        changed = [f for f, val in (("display_name", display_name), ("username", username)) if val and getattr(link, f) != val]
        for f in changed:
            setattr(link, f, (display_name if f == "display_name" else username)[:160])
        if changed:
            link.save(update_fields=changed)
        return link.customer, link
    customer = Customer.objects.create(name=display_name[:160])
    link = CustomerChannel.objects.create(
        customer=customer, channel=channel, external_id=str(external_id), chat_id=str(chat_id or external_id),
        username=username or "", display_name=display_name or "", is_simulated=simulated,
    )
    return customer, link
