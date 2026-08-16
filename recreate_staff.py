
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.accounts.models import User, Role

def create_user(username, role_code, last_name, first_name):
    role = Role.objects.get(code=role_code)
    try:
        # User._base_manager to bypass any soft delete filters
        u = User._base_manager.get(username=username)
        u.is_active = True
        u.is_deleted = False # if it exists
        u.role = role
        u.last_name = last_name
        u.first_name = first_name
        u.set_password("Najot2026!")
        u.save()
        print(f"Updated existing {username}")
    except User.DoesNotExist:
        u = User._base_manager.create(
            username=username,
            role=role, last_name=last_name, first_name=first_name, is_active=True
        )
        u.set_password("Najot2026!")
        u.save()
        print(f"Created new {username}")

create_user("muzaffar_allayarov", Role.Code.DOCTOR, "Allayarov", "Muzaffar")
create_user("maxmurdova_shaxnoza", Role.Code.NURSE, "Maxmurdova", "Shaxnoza")
create_user("meretova_ayqibat", Role.Code.NURSE, "Meretova", "Ayqibat")
create_user("sabirova_farida", Role.Code.NURSE, "Sabirova", "Farida")
create_user("avezmatova_mexrijamol", Role.Code.NURSE, "Avezmatova", "Mexrijamol")
create_user("bayaubaeva_qizilgul", Role.Code.NURSE, "Bayaubaeva", "Qizilgul")
create_user("kelimbetova_sabira", Role.Code.NURSE, "Kelimbetova", "Sabira")
create_user("shahnoza", Role.Code.NURSE, "Shahnoza", "Nurse")
create_user("registratura", Role.Code.RECEPTION, "Registratura", "Xodimi")
create_user("kassir", Role.Code.CASHIER, "Kassir", "Xodimi")

