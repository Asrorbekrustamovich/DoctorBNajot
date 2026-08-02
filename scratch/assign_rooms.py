import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.accounts.models import User, Role
from apps.clinical.models import Room

doctors = User.objects.filter(role__code__in=[Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR])

for i, doc in enumerate(doctors, start=1):
    room_name = f"{i}-Xona"
    room, created = Room.objects.get_or_create(
        name=room_name,
        defaults={
            "floor": 1
        }
    )
    room.assigned_doctor = doc
    room.save()
    print(f"Assigned {doc.get_full_name() or doc.username} to {room.name}")
