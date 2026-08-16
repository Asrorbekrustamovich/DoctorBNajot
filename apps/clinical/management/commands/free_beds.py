"""Osilib qolgan kravatlarni bo'shatadi.

NIMA UCHUN: `Bed.is_occupied` — yotishlardan alohida saqlanadigan bayroq.
U butun tizimda faqat bitta joyda o'chadi — bemorga javob berilganda.
Agar shu zanjir uzilsa (baza tozalandi, yozuv qo'lda o'chirildi, server
yarim yo'lda to'xtadi), kravat abadiy «band» bo'lib qoladi va statsionar
to'silib qoladi: bemor yo'q, lekin yangi bemorni ham yotqizib bo'lmaydi.

Ishlatish:
    python manage.py free_beds              # ko'rsatadi, tegmaydi
    python manage.py free_beds --yes        # bo'shatadi
    python manage.py free_beds --yes --force  # yotgan bemor bo'lsa ham

XAVFSIZLIK: bemor yotgan kravatga tegilmaydi. Aks holda uning o'rniga
boshqa bemor yotqiziladi va ikkalasi bitta kravatda ko'rinadi. Bunday
holatda to'g'ri yo'l — dasturdan javob berish.
"""
from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "«Band» bo'lib osilib qolgan kravatlarni bo'shatadi."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--yes", action="store_true",
                            help="Haqiqatdan bo'shatish")
        parser.add_argument("--force", action="store_true",
                            help="Bemor yotgan bo'lsa ham bo'shatish (xavfli)")

    def handle(self, *args: Any, **opts: Any) -> None:
        from apps.clinical.models import Bed, InpatientStay

        band = Bed.all_objects.filter(is_occupied=True).select_related("room")
        if not band.exists():
            self.stdout.write(self.style.SUCCESS(
                "\n  Band kravat yo'q — hammasi bo'sh.\n"))
            return

        boshatiladi, tegilmaydi = [], []
        for bed in band:
            stay = (bed.stays.filter(status=InpatientStay.Status.ACTIVE).first()
                    or bed.companion_stays.filter(
                        status=InpatientStay.Status.ACTIVE).first())
            if stay is not None and not opts["force"]:
                tegilmaydi.append((bed, stay))
            else:
                boshatiladi.append(bed)

        self.stdout.write(self.style.MIGRATE_HEADING("\n  BAND KRAVATLAR"))

        for bed in boshatiladi:
            self.stdout.write(f"    · {bed}  — bemori yo'q, bo'shatiladi")
        for bed, stay in tegilmaydi:
            self.stdout.write(self.style.WARNING(
                f"    · {bed}  — {stay.visit.patient.full_name} yotibdi, TEGILMAYDI"))

        if not opts["yes"]:
            self.stdout.write(self.style.WARNING(
                "\n  Hech narsa o'zgartirilmadi. Bo'shatish uchun: "
                "python manage.py free_beds --yes\n"))
            return

        n = Bed.all_objects.filter(
            id__in=[b.id for b in boshatiladi]).update(is_occupied=False)

        self.stdout.write(self.style.SUCCESS(
            f"\n  {n} ta kravat bo'shatildi — endi bemor yotqizish mumkin.\n"))

        if tegilmaydi:
            self.stdout.write(self.style.WARNING(
                f"  {len(tegilmaydi)} ta kravatda bemor yotibdi — ularga "
                "tegilmadi.\n  To'g'ri yo'l: dasturdan javob berish.\n"))
