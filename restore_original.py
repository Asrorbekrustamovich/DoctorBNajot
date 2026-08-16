
import os
import django
import sys

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.accounts.models import User

# the correct names that were soft deleted
correct_names = [
    "shaxnoza_maxmurdova",
    "ayqibat_meretova",
    "farida_sabirova",
    "mexrijamol_avezmatova",
    "qizilgul_bayaubaeva",
    "sabira_kelimbetova"
]

wrong_names = [
    "maxmurdova_shaxnoza",
    "meretova_ayqibat",
    "sabirova_farida",
    "avezmatova_mexrijamol",
    "bayaubaeva_qizilgul",
    "kelimbetova_sabira"
]

# delete the wrong ones we just created
for w in wrong_names:
    try:
        u = User._base_manager.get(username=w)
        u.delete() # hard delete or soft delete, whatever, we can just change their usernames to something else
        print(f"Deleted {w}")
    except Exception as e:
        print(e)

# restore the correct ones
for c in correct_names:
    try:
        u = User._base_manager.get(username=c)
        u.is_active = True
        u.is_deleted = False
        u.set_password("Najot2026!")
        u.save()
        print(f"Restored {c}")
    except Exception as e:
        print(e)


