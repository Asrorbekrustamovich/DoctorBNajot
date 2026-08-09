"""Endoskopiya guruhini to'g'rilash.

IKKI MUAMMO:

1. «Rektoromanoskopiya» katalogda umuman yo'q edi, holbuki u eng ko'p
   qilinadigan endoskopik tekshiruvlardan biri.

2. «Kolonoskopiya» va «Kolposkopiya» yonma-yon turganda bir xil so'zdek
   o'qiladi va foydalanuvchi ularni nusxa deb o'yladi. Aslida ular
   butunlay boshqa tekshiruv: biri yo'g'on ichak, ikkinchisi ginekologik.
   Nomga izoh qo'shamiz — chalkashlik yo'qoladi.

Narxlar taxminiy; superadmin ularni o'zgartiradi va bu eski
buyurtmalarga ta'sir qilmaydi (`ServiceOrder.price_snapshot`).
"""
from decimal import Decimal

from django.db import migrations

RENAME = [
    ("Kolonoskopiya", "Kolonoskopiya (yo'g'on ichak)"),
    ("Kolposkopiya", "Kolposkopiya (ginekologik)"),
]

ADD = [
    ("Rektoromanoskopiya (to'g'ri ichak)", Decimal("120000")),
]


def fix(apps, schema_editor):
    ServiceCatalog = apps.get_model("clinical", "ServiceCatalog")
    ServiceCategory = apps.get_model("clinical", "ServiceCategory")

    endo = ServiceCategory.objects.filter(name="Endoskopiya").first()

    for old, new in RENAME:
        svc = ServiceCatalog.objects.filter(name=old).first()
        # Yangi nom band bo'lsa tegmaymiz (nom `unique`)
        if svc and not ServiceCatalog.objects.filter(name=new).exists():
            svc.name = new
            svc.save(update_fields=["name"])

    if endo is None:
        return
    for name, price in ADD:
        ServiceCatalog.objects.get_or_create(
            name=name,
            defaults={"price": price, "category": endo, "is_active": True},
        )


def unfix(apps, schema_editor):
    ServiceCatalog = apps.get_model("clinical", "ServiceCatalog")
    for old, new in RENAME:
        svc = ServiceCatalog.objects.filter(name=new).first()
        if svc and not ServiceCatalog.objects.filter(name=old).exists():
            svc.name = old
            svc.save(update_fields=["name"])
    # Yangi qo'shilganini faqat ishlatilmagan bo'lsa o'chiramiz
    for name, _ in ADD:
        svc = ServiceCatalog.objects.filter(name=name).first()
        if svc and not svc.orders.exists():
            svc.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0033_seed_icd10"),
    ]

    operations = [migrations.RunPython(fix, unfix)]
