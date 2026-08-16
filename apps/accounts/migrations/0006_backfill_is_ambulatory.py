"""Mavjud shifokorlarga «ambulator» bayrog'ini ko'chirish.

Ilgari ambulatorlik `specialty` matnida «ambulator» so'zi bor-yo'qligiga
qarab aniqlanardi. Endi alohida bayroq bor — eski ma'lumotni yo'qotmaslik
uchun o'sha matnga qarab bir marta to'ldiramiz.
"""
from django.db import migrations
from django.db.models import Q


def forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.filter(
        Q(specialty__icontains="ambulator") | Q(specialty__icontains="amblator")
    ).update(is_ambulatory=True)


def backward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    User.objects.update(is_ambulatory=False)


class Migration(migrations.Migration):

    dependencies = [("accounts", "0005_user_is_ambulatory")]
    operations = [migrations.RunPython(forward, backward)]
