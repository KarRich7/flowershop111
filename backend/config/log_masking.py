"""Маскирование секретных токенов в журналах.

Ссылки на заказ, оплату и корзину содержат секретный токен (кто знает ссылку — видит заказ),
вход покупателя — временный токен. В журналах сервера вместо них пишется «***», чтобы
скриншот или копия журнала не давали доступ к чужим заказам. То же правило — в deploy/Caddyfile.
"""
import logging
import re

SECRET_IN_URL = re.compile(r"(/(?:order|pay|carts|track|payments)/)[^/?#\s\"]+|((?:^|[?&])(?:token|order_token)=)[^&#\s\"]*")


def mask_secrets(text):
    if not isinstance(text, str):
        return text
    return SECRET_IN_URL.sub(lambda m: (m.group(1) or m.group(2)) + "***", text)


class MaskSecretsFilter(logging.Filter):
    """Фильтр журналов Django (например, «Not Found: /api/v1/orders/track/<токен>»)."""

    def filter(self, record):
        msg = record.getMessage()
        masked = mask_secrets(msg)
        if masked != msg:
            record.msg, record.args = masked, None
        return True


try:
    from gunicorn.glogging import Logger
except ImportError:  # pragma: no cover — gunicorn есть только в контейнере/requirements
    Logger = None

if Logger is not None:
    class MaskingLogger(Logger):
        """Журнал доступа gunicorn: путь, строка запроса и Referer — без токенов."""

        def atoms(self, resp, req, environ, request_time):
            atoms = super().atoms(resp, req, environ, request_time)
            for key in ("r", "U", "q", "f"):
                atoms[key] = mask_secrets(atoms.get(key))
            return atoms
