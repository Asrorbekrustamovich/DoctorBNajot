"""Standart rollarni yaratish: python manage.py seed_roles"""
from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.services import seed_default_roles


class Command(BaseCommand):
    help = "Standart RBAC rollarini yaratadi (idempotent)."

    def handle(self, *args: Any, **options: Any) -> None:
        roles = seed_default_roles()
        self.stdout.write(self.style.SUCCESS(f"{len(roles)} ta rol tayyor."))
        for role in roles:
            flag = " [faqat ko'rish]" if role.is_read_only else ""
            self.stdout.write(f"  - {role.name} ({role.code}){flag}")
