from celery import shared_task


@shared_task(name="orders.expire_reservations")
def expire_reservations_task():
    from .services import expire_overdue_orders

    return expire_overdue_orders()
