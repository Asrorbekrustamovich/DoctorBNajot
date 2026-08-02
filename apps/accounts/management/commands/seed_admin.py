"""Dastlabki superuser yaratish (idempotent): python manage.py seed_admin"""
from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.models import User

DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "Admin2026!"


class Command(BaseCommand):
    help = "admin superuser yaratadi (mavjud bo'lsa tegmaydi)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--username", default=DEFAULT_USERNAME)
        parser.add_argument("--password", default=DEFAULT_PASSWORD)

    def handle(self, *args: Any, **options: Any) -> None:
        username: str = options["username"]
        if User.all_objects.filter(username=username).exists():
            self.stdout.write(f"'{username}' allaqachon mavjud — o'zgartirilmadi.")
            return
        user = User(username=username, is_staff=True, is_superuser=True)
        user.set_password(options["password"])
        user.save()
        self.stdout.write(self.style.SUCCESS(
            f"Superuser yaratildi: {username} / {options['password']} "
            "(birinchi kirishdan keyin parolni almashtiring!)"
        ))
