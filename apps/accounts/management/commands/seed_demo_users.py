"""Har bir rol uchun demo foydalanuvchi yaratish (idempotent).

Ishlatilishi: python manage.py seed_demo_users
Barcha demo userlar paroli: Najot2026!
"""
from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from apps.accounts.models import Role, User

DEMO_PASSWORD = "Najot2026!"

# (login, rol kodi, familiya, ism)
DEMO_USERS: tuple[tuple[str, str, str, str], ...] = (
    ("superadmin", Role.Code.SUPER_ADMIN, "Tizim", "Egasi"),
    ("administrator", Role.Code.ADMINISTRATOR, "Boshqaruv", "Xodimi"),
    ("direktor", Role.Code.DIRECTOR, "Klinika", "Direktori"),
    ("bosh_shifokor", Role.Code.CHIEF_DOCTOR, "Bosh", "Shifokor"),
    ("registratura", Role.Code.RECEPTION, "Qabul", "Xodimi"),
    ("shifokor", Role.Code.DOCTOR, "Davolovchi", "Shifokor"),
    ("hamshira", Role.Code.NURSE, "Katta", "Hamshira"),
    ("palata_hamshira", Role.Code.WARD_NURSE, "Palata", "Hamshirasi"),
    ("laborant", Role.Code.LAB, "Laboratoriya", "Xodimi"),
    ("radiolog", Role.Code.RADIOLOGY, "Radiologiya", "Xodimi"),
    # ("farmatsevt", Role.Code.PHARMACY, "Dorixona", "Xodimi"),
    ("ombor", Role.Code.WAREHOUSE, "Ombor", "Mudiri"),
    ("kassir", Role.Code.CASHIER, "Kassa", "Xodimi"),
    ("buxgalter", Role.Code.ACCOUNTANT, "Hisob", "Xodimi"),
    ("jarrohlik_admin", Role.Code.SURGERY_ADMIN, "Jarrohlik", "Administratori"),
    ("jarroh", Role.Code.SURGEON, "Jarroh", "Shifokor"),
    ("avtoklav", Role.Code.STERILIZATION, "Sterilizatsiya", "Xodimi"),
    ("tablo", Role.Code.TABLO, "Navbat", "Tablosi"),
    ("auditor", Role.Code.AUDITOR, "Nazorat", "Auditori"),
    ("viewer", Role.Code.VIEWER, "Kuzatuvchi", "Xodim"),
)


class Command(BaseCommand):
    help = "Har bir rol uchun demo user yaratadi (parol: Najot2026!)."

    def handle(self, *args: Any, **options: Any) -> None:
        created = 0
        reset = 0
        for username, role_code, last_name, first_name in DEMO_USERS:
            role = Role.all_objects.filter(code=role_code).first()
            if role is None:
                self.stderr.write(f"Rol topilmadi: {role_code} (seed_roles bajarilganmi?)")
                continue
            user = User.all_objects.filter(username=username).first()
            if user is not None:
                # Mavjud demo user — parolni va faollikni tiklaymiz (login kafolatlanadi)
                user.set_password(DEMO_PASSWORD)
                if not user.is_active:
                    user.is_active = True
                if user.role_id is None:
                    user.role = role
                user.save()
                reset += 1
                continue
            user = User(
                username=username,
                first_name=first_name,
                last_name=last_name,
                role=role,
            )
            user.set_password(DEMO_PASSWORD)
            user.save()
            created += 1
            self.stdout.write(f"  + {username:18} -> {role.name}")
        self.stdout.write(self.style.SUCCESS(
            f"Demo userlar tayyor: +{created} yangi, {reset} ta parol tiklandi. "
            f"Parol (hammasi): {DEMO_PASSWORD}"
        ))
