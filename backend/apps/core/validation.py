"""Проверка данных из форм админки и сайта: понятные сообщения вместо 500 и «тихой» записи мусора.

Каждая функция возвращает очищенное значение или бросает ValidationError с текстом для пользователя
и полем details.field — по нему фронтенд подсвечивает нужное поле формы.
"""
import re
from datetime import time

from apps.core.errors import ValidationError
from apps.core.utils import normalize_phone

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}$")
NAME_RE = re.compile(r"^[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё .'\-]*$")
SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
MAX_MONEY = 100_000_000  # 1 000 000 ₽ в копейках


def fail(field, message, code="validation_error"):
    raise ValidationError(message, code=code, details={"field": field})


def text(value, field, label, *, required=False, min_len=0, max_len=255, multiline=False):
    if value is None:
        value = ""
    if not isinstance(value, (str, int, float)):
        fail(field, f"{label}: некорректное значение")
    value = CONTROL_RE.sub("", str(value))
    value = value.strip() if multiline else re.sub(r"\s+", " ", value).strip()
    if not value:
        if required:
            fail(field, f"Заполните поле «{label}»")
        return ""
    if len(value) < min_len:
        fail(field, f"{label}: минимум {min_len} символа")
    if len(value) > max_len:
        fail(field, f"{label}: не больше {max_len} символов")
    return value


def integer(value, field, label, *, min_value=None, max_value=None, required=True, allow_none=False):
    if value in (None, ""):
        if allow_none:
            return None
        if required:
            fail(field, f"Заполните поле «{label}»")
        return 0
    if isinstance(value, bool):
        fail(field, f"{label}: нужно целое число")
    try:
        f = float(str(value).replace(",", ".").replace(" ", ""))
    except (TypeError, ValueError):
        fail(field, f"{label}: нужно целое число")
    if f != int(f):
        fail(field, f"{label}: нужно целое число")
    v = int(f)
    if min_value is not None and v < min_value:
        fail(field, f"{label}: не меньше {min_value}")
    if max_value is not None and v > max_value:
        fail(field, f"{label}: не больше {max_value}")
    return v


def money(value, field, label, *, required=True, allow_none=False, min_value=0, max_value=MAX_MONEY):
    """Сумма в копейках (целое). Отрицательные и огромные значения не принимаются."""
    if value in (None, ""):
        if allow_none:
            return None
        if required:
            fail(field, f"Укажите «{label}»")
        return 0
    try:
        v = int(value)
    except (TypeError, ValueError):
        fail(field, f"{label}: некорректная сумма")
    if v < min_value:
        fail(field, f"{label}: сумма не может быть меньше {min_value // 100} ₽")
    if v > max_value:
        fail(field, f"{label}: слишком большая сумма (максимум {max_value // 100:,} ₽)".replace(",", " "))
    return v


def number(value, field, label, *, min_value=None, max_value=None):
    try:
        v = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        fail(field, f"{label}: некорректное число")
    if v != v or v in (float("inf"), float("-inf")):
        fail(field, f"{label}: некорректное число")
    if min_value is not None and v < min_value or max_value is not None and v > max_value:
        fail(field, f"{label}: допустимо от {min_value} до {max_value}")
    return v


def boolean(value):
    return value in (True, "true", "1", 1, "on", "yes")


def hex_color(value, field, label, *, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            fail(field, f"Укажите «{label}»")
        return ""
    if len(value) == 4 and re.match(r"^#[0-9A-Fa-f]{3}$", value):
        value = "#" + "".join(c * 2 for c in value[1:])
    if not HEX_RE.match(value):
        fail(field, f"{label}: цвет в формате #RRGGBB, например #3E5B36")
    return value.upper()


def phone(value, field, label="Телефон", *, required=True):
    if not value:
        if required:
            fail(field, f"Укажите «{label}»", code="invalid_phone")
        return ""
    p = normalize_phone(value)
    if not p:
        fail(field, f"{label}: номер в формате +7 900 000-00-00", code="invalid_phone")
    return p


def email(value, field, label="E-mail", *, required=False):
    value = (value or "").strip()
    if not value:
        if required:
            fail(field, f"Укажите «{label}»")
        return ""
    if len(value) > 120 or not EMAIL_RE.match(value):
        fail(field, f"{label}: адрес вида name@example.ru")
    return value


def person_name(value, field, label="Имя", *, required=True, max_len=80):
    value = text(value, field, label, required=required, max_len=max_len)
    if value and (len(value) < 2 or not NAME_RE.match(value)):
        fail(field, f"{label}: только буквы, пробел и дефис, минимум 2 символа")
    return value


def url(value, field, label, *, hosts=(), required=False):
    value = (value or "").strip()
    if not value:
        if required:
            fail(field, f"Укажите «{label}»")
        return ""
    m = re.match(r"^https://([^/\s]+)(/[^\s]*)?$", value)
    if not m or len(value) > 200:
        fail(field, f"{label}: ссылка должна начинаться с https://")
    host = m.group(1).lower().removeprefix("www.")
    if hosts and host not in hosts:
        fail(field, f"{label}: ссылка на {' или '.join(hosts)}")
    return value


def choice(value, field, label, options):
    if value not in options:
        fail(field, f"{label}: выберите значение из списка")
    return value


def hhmm(value, field, label):
    if isinstance(value, time):
        return value
    m = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", str(value or "").strip())
    if not m:
        fail(field, f"{label}: время в формате ЧЧ:ММ")
    return time(int(m.group(1)), int(m.group(2)))


def sku(value, field="sku"):
    value = (value or "").strip().upper()
    if value and (len(value) > 32 or not SKU_RE.match(value)):
        fail(field, "Артикул: латинские буквы, цифры, дефис, до 32 символов")
    return value
