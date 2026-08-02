import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.accounts.models import User, Role

tablo_role, _ = Role.objects.get_or_create(code=Role.Code.TABLO, defaults={"name": "Navbat tablosi (Display)"})

user, created = User.objects.get_or_create(username="tablo")
user.set_password("1")
user.role = tablo_role
user.first_name = "Navbat"
user.last_name = "Tablosi"
user.save()

if created:
    print("User 'tablo' with password '1' created successfully.")
else:
    print("User 'tablo' already existed, password updated to '1' and role set to TABLO.")
