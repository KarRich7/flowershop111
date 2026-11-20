import re
from datetime import datetime

from django.utils import timezone


def rub(kopecks):
    """Форматирование суммы в копейках: 650000 -> '6 500 ₽'."""
    if kopecks is None:
        return "—"
    rubles, kop = divmod(int(kopecks), 100)
    s = f"{rubles:,}".replace(",", "\u00a0")
    if kop:
        s += f",{kop:02d}"
    return f"{s}\u00a0₽"


def normalize_phone(raw):
    """Приводит российский номер к виду +7XXXXXXXXXX. Возвращает None для некорректных номеров."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) == 11 and digits[0] in "78":
        digits = "7" + digits[1:]
    elif len(digits) == 10 and digits[0] == "9":
        digits = "7" + digits
    else:
        return None
    return "+" + digits


def mask_phone(phone):
    if not phone or len(phone) < 6:
        return phone or ""
    return phone[:4] + "***" + phone[-4:]


def local_now():
    return timezone.localtime()


def local_today():
    return timezone.localdate()


def combine_local(date, time):
    return timezone.make_aware(datetime.combine(date, time), timezone.get_current_timezone())
