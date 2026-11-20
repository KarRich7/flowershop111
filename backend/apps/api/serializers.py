"""Сериализация моделей в JSON (явные функции — прозрачно, какие данные отдаются наружу)."""
from django.conf import settings

from apps.carts.services import product_available
from apps.core import site_content
from apps.core.models import ShopSettings
from apps.core.utils import mask_phone
from apps.orders.state import allowed_targets, label


def media_url(f):
    if not f:
        return None
    try:
        return f.url
    except ValueError:
        return None


def _free_from():
    from apps.delivery.models import DeliveryZone

    values = [z for z in DeliveryZone.objects.filter(is_active=True).values_list("free_from", flat=True) if z]
    return min(values) if values else None


def _geocoder_name():
    from apps.delivery import geo

    return geo.provider() if geo.enabled() else None


def zone(z, admin=False):
    data = {"id": z.id, "name": z.name, "description": z.description, "price": z.price, "free_from": z.free_from,
            "color": z.color or "#5B7F4F", "polygons": z.polygons or []}
    if admin:
        data.update({"is_active": z.is_active, "sort_order": z.sort_order})
    return data


def _customer_login():
    from apps.customers.login import channels_available

    return channels_available()


def _online():
    from apps.payments.providers.registry import online_enabled

    return online_enabled()


def _payment_test():
    from apps.payments.providers.registry import is_test_mode

    return is_test_mode()


def _cod(s):
    from apps.payments.providers.registry import cod_allowed

    return cod_allowed(s)


def shop_public(s: ShopSettings):
    return {
        "shop_name": s.shop_name, "tagline": s.tagline, "logo": media_url(s.logo), "hero_image": media_url(s.hero_image),
        "city": s.city, "address": s.address, "phone": s.phone, "email": s.email, "working_hours": s.working_hours,
        "telegram_url": s.telegram_url, "vk_url": s.vk_url, "primary_color": s.primary_color,
        "accent_color": s.accent_color, "background_color": s.background_color, "florist_fee": s.florist_fee,
        "online_reservation_minutes": s.online_reservation_minutes, "pickup_ready_minutes": s.pickup_ready_minutes,
        "min_custom_stems": s.min_custom_stems, "max_custom_stems": s.max_custom_stems,
        "preorder_threshold_days": s.preorder_threshold_days, "max_order_days_ahead": s.max_order_days_ahead,
        "min_lead_minutes": s.min_lead_minutes,
        "flowers_section_enabled": s.flowers_section_enabled,
        "constructor_section_enabled": s.constructor_section_enabled,
        "orders_enabled": s.orders_enabled,
        "orders_closed_message": site_content.orders_closed_message(s),
        "seo": {
            "site_url": site_content.site_url(),
            "pages": site_content.seo_pages(s),
            "yandex_verification": s.yandex_verification,
            "google_verification": s.google_verification,
            "organization": site_content.organization(s, media_url),
        },
        "payment_test_mode": _online() and _payment_test(),
        "online_payment_enabled": _online(),
        "allow_cash_on_delivery": _cod(s),
        "demo_notice": bool(getattr(settings, "SHOW_DEMO_NOTICE", False)),
        "free_delivery_from": _free_from(),
        "maps": {
            "yandex_api_key": settings.YANDEX_MAPS_API_KEY,
            "geocoder": _geocoder_name(),
            "center": [s.shop_lat, s.shop_lon],
            "shop": [s.shop_lat, s.shop_lon],
        },
        "customer_login": _customer_login(),
        "bots": {
            "telegram_connected": bool(settings.TELEGRAM_BOT_TOKEN),
            "vk_connected": bool(settings.VK_GROUP_TOKEN and settings.VK_GROUP_ID),
            "simulator_enabled": settings.BOT_SIMULATOR_ENABLED,
        },
    }


def product(p, avail=None, detail=False):
    images = [{"url": media_url(i.image), "alt": i.alt or p.name} for i in p.images.all()]
    available = product_available(p, avail) if p.is_active else 0
    data = {
        "id": p.id, "slug": p.slug, "name": p.name, "type": p.type, "type_label": p.get_type_display(),
        "category": p.category, "species": p.species, "color": p.color, "color_hex": p.color_hex,
        "short_description": p.short_description, "price": p.price, "available": available,
        "in_stock": available > 0, "image": images[0]["url"] if images else None, "is_featured": p.is_featured,
        "constructor_image": media_url(p.constructor_image),
        "made_to_order": p.allow_made_to_order, "inventory_item_id": p.inventory_item_id, "unit": p.inventory_item.get_unit_display(),
    }
    if detail:
        data.update({"description": p.description, "images": images, "height_cm": p.height_cm,
                     "photo_credit": p.photo_credit, "composition": []})
        recipe = getattr(p.inventory_item, "recipe", None)
        if recipe:
            data["composition"] = [
                {"name": c.item.name, "quantity": c.quantity}
                for c in recipe.components.select_related("item").all()
                if c.item.category in ("flower", "greenery")
            ]
    return data


def _design(item):
    """Эскиз индивидуального букета для отрисовки на сайте и в админке."""
    c = item.composition or {}
    if item.item_type != "custom_bouquet":
        return None
    from apps.catalog.builder import design_catalog

    d = {k: c.get(k) for k in ("flowers", "greenery", "packaging_id", "ribbon_id", "card_id", "card_text", "layout")}
    d["florist_choice"] = bool(c.get("florist_choice"))
    d["items"] = design_catalog(c)
    return d


def _notify_channels(o):
    """Мессенджеры, куда приходят уведомления по заказу (покупатель вошёл через бота)."""
    if not o.customer_id:
        return []
    from apps.customers.models import CustomerChannel

    labels = {"telegram": "Telegram", "vk": "ВКонтакте"}
    rows = CustomerChannel.objects.filter(customer_id=o.customer_id, channel__in=list(labels)).values_list("channel", flat=True)
    return [{"channel": c, "label": labels[c]} for c in dict.fromkeys(rows)]


def order_public(o):
    from apps.delivery.services import ready_time
    from apps.payments.services import current_payment_url

    shop = ShopSettings.load()
    delivery = getattr(o, "delivery", None)
    data = {
        "number": o.number, "token": o.public_token, "created_at": o.created_at, "source": o.source,
        "source_label": o.get_source_display(), "status": o.status, "status_label": o.get_status_display(),
        "payment_status": o.payment_status, "payment_status_label": o.get_payment_status_display(),
        "payment_method": o.payment_method, "payment_method_label": o.get_payment_method_display(),
        "fulfillment": o.fulfillment, "fulfillment_label": o.get_fulfillment_display(),
        "date": o.fulfillment_date, "time_from": o.time_from, "time_to": o.time_to,
        "items_total": o.items_total, "delivery_cost": o.delivery_cost, "total": o.total,
        "contact_name": o.contact_name, "contact_phone": mask_phone(o.contact_phone),
        "recipient_name": o.recipient_name, "comment": o.comment, "card_text": o.card_text,
        "is_preorder": o.is_preorder, "requires_confirmation": o.requires_confirmation,
        "reservation_expires_at": o.reservation_expires_at, "cancel_reason": o.cancel_reason,
        "items": [
            {"name": i.name, "quantity": i.quantity, "unit_price": i.unit_price, "line_total": i.line_total,
             "type": i.product_type, "composition": (i.composition or {}).get("lines"), "design": _design(i)}
            for i in o.items.all()
        ],
        "history": [
            {"status": e.to_status, "label": label(e.to_status), "at": e.created_at}
            for e in o.events.all() if e.to_status
        ],
        "payment_url": current_payment_url(o) if o.status == "awaiting_payment" else None,
        "notify_channels": _notify_channels(o),
        "photo_before": o.photo_before,
        "photos": [{"id": ph.id, "url": media_url(ph.image), "at": ph.created_at} for ph in o.photos.all()],
        "shop": {"address": shop.address, "phone": shop.phone, "working_hours": shop.working_hours},
    }
    if delivery:
        data["delivery"] = {"address": delivery.address, "apartment": delivery.apartment,
                            "zone": delivery.zone.name if delivery.zone else "", "status": delivery.status,
                            "status_label": delivery.get_status_display(), "lat": delivery.lat, "lon": delivery.lon,
                            "ask_recipient": delivery.ask_recipient, "address_pending": delivery.address_pending,
                            "surprise": delivery.surprise, "anonymous": delivery.anonymous}
    if o.fulfillment == "pickup":
        data["pickup"] = {"address": o.pickup_point or shop.address, "ready_at": ready_time(o)}
    return data


def user(u):
    return {"id": u.id, "username": u.username, "first_name": u.first_name, "last_name": u.last_name,
            "name": u.display_name, "role": u.role, "role_label": u.get_role_display(), "phone": u.phone,
            "is_active": u.is_active, "is_demo": u.is_demo,
            "notify_mode": u.notify_mode, "notify_mode_label": u.get_notify_mode_display(),
            "telegram_linked": bool(u.telegram_id), "vk_linked": bool(u.vk_id), "on_shift": u.on_shift,
            "shift_started_at": u.shift_started_at.isoformat() if u.shift_started_at else None}


def order_admin(o, viewer):
    data = order_public(o)
    courier_view = viewer.role == "courier"
    delivery = getattr(o, "delivery", None)
    data.update({
        "id": o.id, "contact_phone": o.contact_phone, "recipient_phone": o.recipient_phone,
        "allowed_transitions": [{"status": s, "label": label(s)} for s in allowed_targets(o, viewer)],
        "created_by": o.created_by.display_name if o.created_by else None,
    })
    if delivery:
        data["delivery"].update({
            "entrance": delivery.entrance, "floor": delivery.floor, "address_verified": delivery.address_verified,
            "courier": user(delivery.courier) if delivery.courier else None, "assigned_at": delivery.assigned_at,
            "delivered_at": delivery.delivered_at,
        })
    if courier_view:  # курьеру — только то, что нужно для доставки
        data.pop("history", None)
        return data
    data.update({
        "contact_email": o.contact_email, "snapshot": o.snapshot,
        "customer": {"id": o.customer_id, "name": o.customer.name, "phone": o.customer.phone} if o.customer else None,
        "events": [
            {"type": e.event_type, "from": e.from_status, "to": e.to_status, "to_label": label(e.to_status) if e.to_status else "",
             "message": e.message, "actor": e.actor_label, "at": e.created_at, "data": e.data}
            for e in o.events.all()
        ],
        "payments": [
            {"id": p.id, "provider": p.provider, "amount": p.amount, "status": p.status, "status_label": p.get_status_display(),
             "is_test": p.is_test, "created_at": p.created_at, "paid_at": p.paid_at, "failure_reason": p.failure_reason,
             "url": p.confirmation_url}
            for p in o.payments.all()
        ],
        "reservations": [
            {"item": r.item.name, "quantity": r.quantity, "kind": r.get_kind_display(), "status": r.get_status_display(),
             "expires_at": r.expires_at}
            for r in o.reservations.select_related("item").all()
        ],
        "notifications": [
            {"channel": n.get_channel_display(), "status": n.get_status_display(), "text": n.text, "at": n.created_at,
             "error": n.error}
            for n in o.notifications.all()[:20]
        ],
    })
    data["items"] = [
        {"name": i.name, "sku": i.sku, "quantity": i.quantity, "unit_price": i.unit_price, "line_total": i.line_total,
         "type": i.product_type, "composition": (i.composition or {}).get("lines"), "plan": i.fulfillment_plan,
         "wishes": (i.composition or {}).get("wishes"), "card_text": (i.composition or {}).get("card_text"),
         "design": _design(i)}
        for i in o.items.all()
    ]
    return data


def inventory_item(i, bal=None):
    bal = bal or {"quantity": 0, "reserved": 0}
    product = getattr(i, "product", None)
    available = bal["quantity"] - bal["reserved"]
    return {
        "id": i.id, "sku": i.sku, "name": i.name, "category": i.category, "category_label": i.get_category_display(),
        "unit": i.unit, "unit_label": i.get_unit_display(), "purchase_price": i.purchase_price, "sale_price": i.sale_price,
        "quantity": bal["quantity"], "reserved": bal["reserved"], "available": available, "min_stock": i.min_stock,
        "low": available <= i.min_stock, "is_active": i.is_active,
        "product_id": product.id if product else None, "image": media_url(product.images.first().image) if product and product.images.first() else None,
    }
