"""4. Два покупателя одновременно пытаются купить последний букет."""
import threading

import pytest
from django.db import connection

from apps.carts import services as carts
from apps.inventory.services import InsufficientStock
from apps.orders import services as orders
from apps.orders.models import Order


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("channels", [("web", "web"), ("web", "telegram"), ("telegram", "vk")])
def test_last_bouquet_sold_only_once(shop, channels):
    b = shop.bouquet(assembled=1)  # последний готовый букет, под заказ не собирается
    carts_ = []
    for ch in channels:
        cart = carts.create_cart(ch)
        carts.add_product(cart, b.id, 1)
        carts_.append(cart)

    barrier = threading.Barrier(len(carts_))
    results = []

    def buy(cart, n):
        try:
            barrier.wait()
            results.append(("ok", orders.place_order(cart, shop.order_data(key=f"race-{n}")).pk))
        except InsufficientStock as e:
            results.append(("sold_out", e.message))
        except Exception as e:  # noqa: BLE001
            results.append(("error", repr(e)))
        finally:
            connection.close()

    threads = [threading.Thread(target=buy, args=(c, i)) for i, c in enumerate(carts_)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    kinds = sorted(r[0] for r in results)
    assert kinds == ["ok", "sold_out"], results
    bal = shop.balance(b.inventory_item)
    assert (bal.quantity, bal.reserved) == (1, 1)
    assert Order.objects.exclude(status="cancelled").count() == 1


@pytest.mark.django_db(transaction=True)
def test_parallel_store_sale_and_web_order(shop):
    """Продавец в магазине и покупатель на сайте одновременно берут последний букет."""
    from apps.core.models import User

    florist = User.objects.create_user("f", password="x" * 12, role="florist")
    b = shop.bouquet(assembled=1)
    cart = carts.create_cart("web")
    carts.add_product(cart, b.id, 1)
    barrier = threading.Barrier(2)
    results = []

    def web_buy():
        try:
            barrier.wait()
            orders.place_order(cart, shop.order_data())
            results.append("web")
        except Exception:  # noqa: BLE001
            results.append("web_fail")
        finally:
            connection.close()

    def store_buy():
        try:
            barrier.wait()
            orders.store_sale([{"product_id": b.id, "quantity": 1}], "cash", florist)
            results.append("store")
        except Exception:  # noqa: BLE001
            results.append("store_fail")
        finally:
            connection.close()

    ts = [threading.Thread(target=web_buy), threading.Thread(target=store_buy)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert sorted(results) in (["store", "web_fail"], ["store_fail", "web"]), results
    bal = shop.balance(b.inventory_item)
    assert bal.quantity - bal.reserved == 0
    assert bal.quantity >= 0 and bal.reserved <= bal.quantity
