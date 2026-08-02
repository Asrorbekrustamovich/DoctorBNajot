"""Operatsiya moduli uchun boshlang'ich ma'lumotlarni to'ldirish (idempotent).

Ishlatilishi: python manage.py seed_operation_data

Qo'shadi:
  - Operatsion xonalar
  - Anesteziolog foydalanuvchisi (login: anesteziolog / Najot2026!)
  - Operatsiya turlari (agar bo'lmasa)
  - Anesteziolog ombori mahsulotlari (sotish narxi bilan)
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role, User
from apps.clinical.models import AnesthesiaStock, OperatingRoom, SurgeryType, SurgicalItem

DEMO_PASSWORD = "Najot2026!"

ROOMS = [
    ("Operatsiya xonasi №1", "Umumiy jarrohlik"),
    ("Operatsiya xonasi №2", "Laparoskopiya"),
    ("Operatsiya xonasi №3", "Jonli/shoshilinch"),
]

SURGERY_TYPES = [
    ("Appendektomiya (ko'richak)", Decimal("1500000")),
    ("Churra (gerniya) operatsiyasi", Decimal("2000000")),
    ("Xoletsistektomiya (o't pufagi)", Decimal("3500000")),
    ("Kesar kesish", Decimal("4000000")),
]

# (nomi, birlik, soni, sotish narxi) — anesteziolog ombori operatsiya materiallari
STOCK = [
    ("Lidokain 2% (ampula)", "dona", Decimal("100"), Decimal("8000")),
    ("Propofol (ampula)", "dona", Decimal("40"), Decimal("45000")),
    ("Ketamin (ampula)", "dona", Decimal("30"), Decimal("38000")),
    ("Sevofluran (flakon)", "dona", Decimal("15"), Decimal("320000")),
    ("Fentanil (ampula)", "dona", Decimal("25"), Decimal("52000")),
    ("Shpris 10 ml", "dona", Decimal("200"), Decimal("3000")),
    ("Shpris 5 ml", "dona", Decimal("250"), Decimal("2000")),
    ("Sistema (kapelnitsa)", "dona", Decimal("50"), Decimal("12000")),
    ("Intubatsion trubka", "dona", Decimal("40"), Decimal("35000")),
    ("Steril perchatka (juft)", "juft", Decimal("300"), Decimal("2500")),
    ("Steril bint", "dona", Decimal("150"), Decimal("4000")),
    ("Fiziologik eritma 0.9% (flakon)", "dona", Decimal("80"), Decimal("9000")),
    ("Kislorod maskasi", "dona", Decimal("60"), Decimal("15000")),
    ("Venoz kateter", "dona", Decimal("70"), Decimal("18000")),
]

# Operatsion asistentlar (dropdownда tanlash uchun) — (login, familiya, ism)
ASSISTANTS = [
    ("asistent1", "Yo'ldoshev", "Sardor"),
    ("asistent2", "Qodirova", "Malika"),
    ("asistent3", "Ergashev", "Bekzod"),
]


class Command(BaseCommand):
    help = "Operatsiya moduli uchun demo ma'lumotlar (xona, anesteziolog, turlar, ombor)."

    @transaction.atomic
    def handle(self, *args: Any, **options: Any) -> None:
        # 1) Operatsion xonalar
        rooms = 0
        for name, desc in ROOMS:
            _, created = OperatingRoom.all_objects.get_or_create(
                name=name, defaults={"description": desc, "is_active": True}
            )
            rooms += int(created)
        self.stdout.write(f"Operatsion xonalar: +{rooms} (jami {OperatingRoom.objects.count()})")

        # 2) Anesteziolog foydalanuvchisi
        anest_role = Role.all_objects.filter(code=Role.Code.ANESTHESIOLOGIST).first()
        if anest_role and not User.all_objects.filter(username="anesteziolog").exists():
            u = User(username="anesteziolog", first_name="Anvar", last_name="Anesteziolog",
                     role=anest_role, is_active=True)
            u.set_password(DEMO_PASSWORD)
            u.save()
            self.stdout.write(self.style.SUCCESS(f"Anesteziolog yaratildi: anesteziolog / {DEMO_PASSWORD}"))
        else:
            self.stdout.write("Anesteziolog allaqachon mavjud yoki rol topilmadi.")

        # 2.5) Operatsion asistentlar (jarrohlik jamoasi — surgeon roli bilan)
        surgeon_role = Role.all_objects.filter(code=Role.Code.SURGEON).first()
        made = 0
        if surgeon_role:
            for username, last, first in ASSISTANTS:
                if User.all_objects.filter(username=username).exists():
                    continue
                u = User(username=username, first_name=first, last_name=last,
                         role=surgeon_role, is_active=True, specialty="Operatsion asistent")
                u.set_password(DEMO_PASSWORD)
                u.save()
                made += 1
        self.stdout.write(f"Operatsion asistentlar: +{made} (parol: {DEMO_PASSWORD})")

        # 3) Operatsiya turlari (faqat bo'sh bo'lsa qo'shamiz)
        if SurgeryType.objects.count() == 0:
            for name, price in SURGERY_TYPES:
                SurgeryType.all_objects.get_or_create(
                    name=name, defaults={"price": price, "is_active": True}
                )
            self.stdout.write(f"Operatsiya turlari: +{len(SURGERY_TYPES)}")
        else:
            self.stdout.write(f"Operatsiya turlari mavjud ({SurgeryType.objects.count()} ta) — o'zgartirilmadi.")

        # 4) Anesteziolog ombori
        stock = 0
        for name, unit, qty, price in STOCK:
            _, created = AnesthesiaStock.all_objects.get_or_create(
                name=name,
                defaults={"unit": unit, "quantity": qty, "selling_price": price, "is_active": True},
            )
            stock += int(created)
        self.stdout.write(f"Anesteziolog ombori: +{stock} (jami {AnesthesiaStock.objects.count()})")

        # 5) Sterilizatsiyadan o'tgan (TAYYOR) belyo va anjomlar —
        #    tayyorlash qadamida ko'p tanlovli ro'yxatда chiqadi.
        #    Belyo (linen) -> avtoklav; ochiq nabor -> avtoklav; endoskopik -> rastvor.
        ITEMS = [
            # (nom, turi, seriya)
            ("Belyo to'plami (biks) #1", SurgicalItem.Type.LINEN, "BLY-001"),
            ("Belyo to'plami (biks) #2", SurgicalItem.Type.LINEN, "BLY-002"),
            ("Belyo to'plami (biks) #3", SurgicalItem.Type.LINEN, "BLY-003"),
            ("Steril choyshab to'plami", SurgicalItem.Type.LINEN, "BLY-004"),
            ("Umumiy jarrohlik nabori #1", SurgicalItem.Type.NABOR, "NBR-001"),
            ("Umumiy jarrohlik nabori #2", SurgicalItem.Type.NABOR, "NBR-002"),
            ("Laparotomiya nabori", SurgicalItem.Type.NABOR, "NBR-003"),
            ("Appendektomiya nabori", SurgicalItem.Type.NABOR, "NBR-004"),
            ("Laparoskop kamerasi", SurgicalItem.Type.ENDO_INSTRUMENT, "END-001"),
            ("Laparoskopik troakarlar to'plami", SurgicalItem.Type.ENDO_INSTRUMENT, "END-002"),
            ("Endoskopik qaychi-tutqich nabori", SurgicalItem.Type.ENDO_INSTRUMENT, "END-003"),
        ]
        items = 0
        for name, itype, serial in ITEMS:
            obj, created = SurgicalItem.all_objects.get_or_create(
                serial_number=serial,
                defaults={"name": name, "item_type": itype,
                          "status": SurgicalItem.Status.READY, "current_room": None},
            )
            if not created and obj.status != SurgicalItem.Status.READY:
                # allaqachon bor bo'lsa — tayyor holatga qaytaramiz (demo uchun)
                obj.status = SurgicalItem.Status.READY
                obj.current_room = None
                obj.save(update_fields=["status", "current_room", "steril_method"])
            items += int(created)
        self.stdout.write(
            f"Steril belyo/anjomlar: +{items} (jami tayyor: "
            f"{SurgicalItem.objects.filter(status=SurgicalItem.Status.READY).count()})"
        )

        self.stdout.write(self.style.SUCCESS("Operatsiya demo ma'lumotlari tayyor."))
