
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.accounts.models import User

renames = {
    "maxmurdova_shaxnoza": "shaxnoza_maxmurdova",
    "meretova_ayqibat": "ayqibat_meretova",
    "sabirova_farida": "farida_sabirova",
    "avezmatova_mexrijamol": "mexrijamol_avezmatova",
    "bayaubaeva_qizilgul": "qizilgul_bayaubaeva",
    "kelimbetova_sabira": "sabira_kelimbetova"
}

for old_username, new_username in renames.items():
    try:
        u = User._base_manager.get(username=old_username)
        u.username = new_username
        u.set_password("Najot2026!")
        u.save()
        print(f"Renamed {old_username} to {new_username}")
    except User.DoesNotExist:
        print(f"User {old_username} not found")


