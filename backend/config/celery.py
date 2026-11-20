import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
app = Celery("cvety")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.conf.beat_schedule = {
    "expire-unpaid-reservations": {"task": "orders.expire_reservations", "schedule": 60.0},
    "end-stale-staff-shifts": {"task": "staff.end_stale_shifts", "schedule": 600.0},
}
