"""Shablonlar sog'ligi — butun loyiha bo'yicha.

Alohida fayl: `apps/core/tests.py` da soft-delete va healthcheck testlari
turadi, ularning ustiga yozib yubormaslik uchun.
Django `manage.py test` bilan bu faylni ham topadi.
"""
from __future__ import annotations

import glob
import os
import re

from django.conf import settings
from django.template.loader import get_template
from django.test import TestCase

TEMPLATE_DIR = os.path.join(settings.BASE_DIR, "templates")


def all_templates() -> list[str]:
    return sorted(glob.glob(os.path.join(TEMPLATE_DIR, "**", "*.html"), recursive=True))


class TemplateHygieneTests(TestCase):

    def test_kop_qatorli_izoh_yoq(self):
        """`{# … #}` FAQAT bitta qatorda ishlaydi.

        HAQIQIY XATO: ko'p qatorli `{# … #}` Django tomonidan izoh deb
        tanilmaydi va sahifada oddiy MATN bo'lib chiqadi. Foydalanuvchi
        ekranning pastida «{# Tekshiruv tayinlash pikeri… #}» yozuvini
        ko'rdi. Ko'p qatorli izoh uchun `{% comment %}` ishlatiladi.
        """
        bad = []
        for path in all_templates():
            with open(path, encoding="utf-8") as f:
                for lineno, line in enumerate(f, start=1):
                    idx = line.find("{#")
                    if idx >= 0 and "#}" not in line[idx + 2:]:
                        rel = os.path.relpath(path, TEMPLATE_DIR)
                        bad.append(f"{rel}:{lineno}  {line.strip()[:60]}")
        self.assertEqual(
            bad, [],
            "Ko'p qatorli {# #} izohlar sahifada matn bo'lib chiqadi. "
            "{% comment %} ishlating:\n  " + "\n  ".join(bad),
        )

    def test_hamma_shablon_kompilyatsiya_boladi(self):
        """Sintaksis xatosi bo'lgan shablon 500 xato beradi.

        Bu sahifa ochilgunga qadar bilinmaydi — shuning uchun hammasini
        oldindan kompilyatsiya qilib ko'ramiz.
        """
        skipped, failed = 0, []
        for path in all_templates():
            rel = os.path.relpath(path, TEMPLATE_DIR).replace(os.sep, "/")
            try:
                get_template(rel)
            except Exception as exc:  # noqa: BLE001
                # `{% extends %}` da o'zgaruvchi ishlatilgan bo'lsa yuklab
                # bo'lmaydi — bu xato emas.
                if "extends" in str(exc).lower():
                    skipped += 1
                    continue
                failed.append(f"{rel}: {exc}")
        self.assertEqual(failed, [], "Shablon kompilyatsiya qilinmadi:\n  "
                                     + "\n  ".join(failed))

    def test_izohlar_muvozanatda(self):
        """Har bir `{% comment %}` yopilgan bo'lsin.

        DIQQAT: shunchaki sanab bo'lmaydi. Django `{% comment %}` ni
        `{% endcomment %}` gacha yutadi, shuning uchun izoh MATNI ichida
        yozilgan `{% comment %}` so'zi oddiy matn — xato emas. Avvalgi
        variantim shu sababli bexosdan «xato» topgan edi. To'g'ri usul:
        avval yopilgan bloklarni olib tashlab, keyin qolganini qarash.
        """
        bad = []
        for path in all_templates():
            s = open(path, encoding="utf-8").read()
            stripped = re.sub(
                r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", s,
                flags=re.DOTALL,
            )
            rel = os.path.relpath(path, TEMPLATE_DIR)
            if re.search(r"\{%\s*comment\s*%\}", stripped):
                bad.append(f"{rel}: yopilmagan {{% comment %}}")
            if re.search(r"\{%\s*endcomment\s*%\}", stripped):
                bad.append(f"{rel}: ortiqcha {{% endcomment %}}")
        self.assertEqual(bad, [], "\n  ".join(bad))


class ViewSmokeTests(TestCase):
    """Har bir sahifa ochiladimi — 500 bermaydimi.

    NEGA KERAK: `assign_bed_htmx` va `admit_visit_htmx` da aniqlanmagan
    `ward_nurses` o'zgaruvchisi bor edi. Django testlari ularni chaqirmagani
    uchun xato yashiringan, foydalanuvchi esa «Bemorni joylashtirish»
    oynasida abadiy «Yuklanmoqda…» ni ko'rgan (HTMX 500 ni ekranga
    chiqarmaydi).

    Bu test barcha GET yo'nalishlarini superadmin sifatida ochib ko'radi.
    Yangi sahifa qo'shilganda u ham avtomatik qamrab olinadi.
    """

    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from apps.accounts.models import Role, User
        from apps.clinical.models import Bed, Room
        from apps.patients.models import Patient
        from apps.registration.models import Visit

        cls.admin = User.objects.create_user(
            username="smoke_admin", password="x",
            is_superuser=True, is_staff=True)
        cls.patient = Patient.objects.create(
            last_name="Smoke", first_name="Test",
            birth_date=date(1990, 1, 1), gender=Patient.Gender.MALE)
        cls.visit = Visit.objects.create(
            patient=cls.patient, visit_date=date(2026, 8, 1), queue_number=1)
        cls.room = Room.objects.create(name="Smoke-1")
        cls.bed = Bed.objects.create(room=cls.room, number="1A")

    def _urls(self):
        """URL naqshlarini namuna qiymatlar bilan to'ldiramiz."""
        import re
        from django.urls import get_resolver

        sample = {
            "pk": self.visit.pk, "visit_id": self.visit.pk,
            "patient_id": self.patient.pk, "bed_id": self.bed.pk,
            "room_id": self.room.pk,
        }

        def walk(resolver, prefix=""):
            out = []
            for p in resolver.url_patterns:
                if hasattr(p, "url_patterns"):
                    out += walk(p, prefix + str(p.pattern))
                else:
                    out.append(prefix + str(p.pattern))
            return out

        urls = []
        for route in walk(get_resolver()):
            if route.startswith(("api/", "admin/")):
                continue
            if "<" in route:
                missing = False

                def sub(m):
                    nonlocal missing
                    name = m.group(2)
                    if name not in sample:
                        missing = True
                        return ""
                    return str(sample[name])

                url = "/" + re.sub(r"<([^:>]+:)?([^>]+)>", sub, route)
                if missing:
                    continue
            else:
                url = "/" + route
            urls.append(url)
        return urls

    def test_hech_bir_sahifa_500_bermaydi(self):
        self.client.force_login(self.admin)
        broken = []
        for url in self._urls():
            try:
                r = self.client.get(url)
            except Exception as exc:  # noqa: BLE001
                broken.append(f"{url} -> {type(exc).__name__}: {exc}")
                continue
            if r.status_code >= 500:
                broken.append(f"{url} -> HTTP {r.status_code}")
        self.assertEqual(broken, [], "Sahifalar ochilmadi:\n  " + "\n  ".join(broken))
