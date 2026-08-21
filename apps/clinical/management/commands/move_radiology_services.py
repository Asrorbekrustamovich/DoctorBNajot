"""Radiologiya rolidagi xizmatlarni shifokorlarga o'tkazadi.

Klinikada alohida radiolog bo'lmasa, UZI/Rentgen/EKG kabi tekshiruvlarni
shifokorlarning o'zi bajaradi. Bu buyruq shu xizmatlarni «Radiologiya»
rolidan «Shifokor» roliga ko'chiradi — keyin ularning har birini
Xizmatlar katalogida aniq shifokorga biriktirasiz.

Ishlatilishi:
    python manage.py move_radiology_services --dry-run   # faqat ko'rsatadi
    python manage.py move_radiology_services             # ko'chiradi
    python manage.py move_radiology_services --to lab    # boshqa rolga
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Role
from apps.clinical.models import ServiceCatalog


class Command(BaseCommand):
    help = "Radiologiya xizmatlarini boshqa rolga (odatda Shifokor) ko'chiradi"

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="src", default=Role.Code.RADIOLOGY,
                            help="Manba rol kodi (default: radiology)")
        parser.add_argument("--to", dest="dst", default=Role.Code.THERAPIST,
                            help="Maqsad rol kodi (default: doctor)")
        parser.add_argument("--dry-run", action="store_true",
                            help="Hech narsa o'zgartirmasdan faqat ko'rsatadi")

    def handle(self, *args, **opts):
        src = Role.objects.filter(code=opts["src"]).first()
        dst = Role.objects.filter(code=opts["dst"]).first()

        if not src:
            self.stdout.write(self.style.WARNING(
                f"«{opts['src']}» rolidagi xizmat yo'q — hech narsa qilinmadi."))
            return
        if not dst:
            self.stdout.write(self.style.ERROR(
                f"«{opts['dst']}» roli topilmadi. Avval: python manage.py seed_roles"))
            return

        qs = ServiceCatalog.objects.filter(allowed_role=src).order_by("name")
        n = qs.count()
        if not n:
            self.stdout.write(self.style.SUCCESS(
                f"«{src.name}» rolida xizmat yo'q — ko'chirishga hojat yo'q."))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n«{src.name}» → «{dst.name}»  ({n} ta xizmat)\n"))
        for s in qs:
            xodim = s.responsible_staff.get_full_name() if s.responsible_staff_id else "—"
            self.stdout.write(f"  · {s.name:<55} mas'ul: {xodim}")

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(
                "\n--dry-run: hech narsa o'zgartirilmadi.\n"))
            return

        with transaction.atomic():
            # DIQQAT: `update()` Auditable.save() ni chaqirmaydi, lekin bu yerda
            # ataylab shunday — 22 ta yozuv uchun 22 ta audit yozuvi kerak emas.
            qs.update(allowed_role=dst)

        self.stdout.write(self.style.SUCCESS(
            f"\n✓ {n} ta xizmat «{dst.name}» roliga o'tkazildi.\n"))
        self.stdout.write(
            "  Keyingi qadam: Sozlamalar → Xizmatlar katalogi → har biriga\n"
            "  «Mas'ul xodim» tanlang (masalan EKG → kardiolog).\n"
            "  Mas'ul xodim tanlanmaguncha xizmat BARCHA shifokorlar\n"
            "  navbatida ko'rinadi.\n"
        )
