"""Создаёт владельца магазина из переменных OWNER_USERNAME / OWNER_PASSWORD, если владельца ещё нет.

Нужна для «чистой» установки без демо-данных (SEED_DEMO=false). Существующих пользователей и пароли
не меняет. Забыли пароль владельца — смените его командой:
    docker compose exec backend python manage.py changepassword owner
"""
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand

from apps.core.models import User


class Command(BaseCommand):
    help = "Создать владельца из OWNER_USERNAME/OWNER_PASSWORD, если в базе нет ни одного владельца"

    def handle(self, *args, **opts):
        if User.objects.filter(role=User.Role.OWNER, is_active=True).exists():
            return
        username = (os.environ.get("OWNER_USERNAME") or "owner").strip()
        password = os.environ.get("OWNER_PASSWORD") or ""
        if not password:
            self.stdout.write(self.style.WARNING(
                "Владельца в базе нет. Задайте OWNER_PASSWORD (от 10 символов) в .env и перезапустите backend: "
                "docker compose up -d backend"))
            return
        try:
            validate_password(password)
        except ValidationError as e:
            self.stdout.write(self.style.ERROR("OWNER_PASSWORD слишком простой: " + " ".join(e.messages)))
            return
        u = User.objects.filter(username=username).first() or User(username=username)
        u.role, u.is_active, u.is_staff, u.is_superuser = User.Role.OWNER, True, True, True
        u.set_password(password)
        u.save()
        self.stdout.write(self.style.SUCCESS(f"Создан владелец «{username}». Пароль — из OWNER_PASSWORD; "
                                             "после первого входа можно убрать его из .env."))
