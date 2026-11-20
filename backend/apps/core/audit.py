from .models import AuditLog


def client_ip(request):
    """IP клиента с учётом доверенных прокси (как в лимитах запросов). Некорректное значение — None."""
    if request is None:
        return None
    import ipaddress

    from rest_framework.throttling import BaseThrottle

    try:
        ip = BaseThrottle().get_ident(request)
        return str(ipaddress.ip_address(str(ip).strip()))
    except (ValueError, TypeError, AttributeError):
        return None


def audit(user, action, entity=None, request=None, actor_label="", **data):
    entity_type = entity_id = ""
    if entity is not None:
        entity_type = entity._meta.label_lower
        entity_id = str(entity.pk)
    return AuditLog.objects.create(
        user=user if getattr(user, "is_authenticated", False) else None,
        actor_label=actor_label or (getattr(user, "username", "") if user else "system"),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data,
        ip=client_ip(request),
    )
