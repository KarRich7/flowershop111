import logging

from django.conf import settings
from django.db import transaction

logger = logging.getLogger(__name__)


def enqueue(task, *args):
    """Отправляет Celery-задачу после коммита транзакции. Если брокер недоступен — выполняет синхронно."""

    def _send():
        if settings.CELERY_TASK_ALWAYS_EAGER:
            task.apply(args=args)
            return
        try:
            task.apply_async(args=args, retry=False)
        except Exception:  # noqa: BLE001 — брокер недоступен
            logger.warning("Celery broker unavailable, running %s synchronously", task.name)
            task.apply(args=args)

    transaction.on_commit(_send)
