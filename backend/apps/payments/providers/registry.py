from django.conf import settings

from .rollypay import RollyPayProvider
from .simulator import SimulatorProvider
from .yookassa import YooKassaProvider

PROVIDERS = {SimulatorProvider.code: SimulatorProvider, YooKassaProvider.code: YooKassaProvider,
             RollyPayProvider.code: RollyPayProvider}


def get_provider(code=None):
    code = code or settings.PAYMENT_PROVIDER
    if code not in PROVIDERS:
        raise RuntimeError(f"Платёжный провайдер «{code}» не подключён")
    return PROVIDERS[code]()


def is_test_mode():
    """Тестовая оплата (симулятор или тестовый режим кассы): деньги не списываются — так и пишем покупателю."""
    if settings.PAYMENT_PROVIDER == SimulatorProvider.code:
        return True
    return settings.PAYMENT_PROVIDER == RollyPayProvider.code and bool(settings.ROLLYPAY_TEST_MODE)


def online_enabled():
    """Принимаем ли онлайн-оплату. В боевом режиме (PRODUCTION) без настоящей кассы онлайн-оплата выключена,
    чтобы покупатели не «оплачивали» заказы на тестовой странице. Управляется ONLINE_PAYMENTS=auto|on|off."""
    return bool(getattr(settings, "ONLINE_PAYMENTS_ENABLED", True))


def cod_allowed(shop_settings):
    """Оплата при получении: включается в настройках магазина, а без онлайн-оплаты доступна всегда."""
    return bool(shop_settings.allow_cash_on_delivery) or not online_enabled()


def pay_label(text="Оплатить"):
    return f"{text} (тестовый режим)" if is_test_mode() else text
