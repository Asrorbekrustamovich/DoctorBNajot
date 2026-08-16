"""Havolalarni kuzatib chiqamiz — real ma'lumot bilan.

Nega bu test bor
----------------
`tests_smoke` parametrsiz sahifalarni tekshiradi. Ammo xatolarning
ko'pchiligi aynan ma'lumotli sahifalarda chiqadi: bemor kartasi, epizod,
vipiska, operatsiya jarayoni. Ular `<uuid>` bilan ochiladi va qo'lda
ro'yxat yozib chiqish — eskirib qoladigan ish.

Shuning uchun: bitta to'liq bemor yo'li quriladi (qabul → tekshiruv →
statsionar → operatsiya), keyin bosh sahifadan boshlab HAVOLALAR
kuzatiladi. Ekranda ko'rinib turgan har bir havola ochilib ko'riladi.

Talab bitta: hech qaysi sahifa yiqilmasin.
"""
import re

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, Bed, InpatientStay, ProcedureRecord, Room,
    SurgerySchedule, SurgeryType, Visit,
)
from apps.patients.models import Patient

HAVOLA = re.compile(r'href="(/[^"#?]*)"')
# HTMX manzillari ham ochiladi: ular bo'lak (partial) qaytaradi va
# odatiy kuzatuvda ko'rinmay qolardi — xatolari esa aynan o'sha
# bo'laklarda chiqadi (oyna «Yuklanmoqda…» da qotib qoladi).
HTMX = re.compile(r'hx-get="(/[^"#?]*)"')

# Yuklab olish, tashqi tizim va chiqish — kuzatuvga kirmaydi
TASHLANADI = ("/admin", "/static", "/media", "/api", "/accounts/logout",
              "/logout")


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class CrawlTest(TestCase):
    def setUp(self):
        self.super = User.objects.create_user(
            username="crawl_super", password="x",
            role=rol(Role.Code.SUPER_ADMIN, "Super admin"),
            is_superuser=True)
        doctor = User.objects.create_user(
            username="crawl_doc", password="x",
            role=rol(Role.Code.DOCTOR, "Shifokor"))
        jarroh = User.objects.create_user(
            username="crawl_surg", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"))

        bemor = Patient.objects.create(
            first_name="Test", last_name="Bemorov",
            birth_date="1990-01-01", gender="male",
            birth_certificate="MB-9999999")
        visit = Visit.objects.create(
            patient=bemor, doctor=doctor, visit_date=timezone.now(),
            queue_number=1, status=Visit.Status.IN_PROGRESS)

        xona = Room.objects.create(name="Sinov xonasi")
        stay = InpatientStay.objects.create(
            visit=visit, bed=Bed.objects.create(room=xona, number="1A"),
            admission_date=timezone.now())
        ProcedureRecord.objects.create(
            stay=stay, name="Ukol", nurse=doctor,
            category=ProcedureRecord.Category.PROCEDURE,
            performed_at=timezone.now())
        AdmissionEpisode.objects.create(
            patient=bemor, visit=visit, referred_by=doctor, stay=stay,
            status=AdmissionEpisode.Status.ADMITTED, reason="Sinov")

        SurgerySchedule.objects.create(
            visit=visit, surgeon=jarroh, scheduled_time=timezone.now(),
            surgery_type=SurgeryType.objects.create(name="Sinov operatsiya",
                                                    price=1000))

    def _kuzat(self, user):
        """Shu foydalanuvchi ko'radigan havolalarni ochib chiqamiz."""
        self.client.force_login(user)

        korilgan = set()
        navbat = ["/"]
        xatolar = []
        # Cheklov: cheksiz aylanib qolmaslik uchun
        while navbat and len(korilgan) < 220:
            u = navbat.pop(0)
            if u in korilgan or u.startswith(TASHLANADI):
                continue
            korilgan.add(u)

            try:
                r = self.client.get(u, follow=True)
            except Exception as e:  # noqa: BLE001
                xatolar.append(f"{u} -> {type(e).__name__}: {e}")
                continue

            if r.status_code >= 500:
                xatolar.append(f"{u} -> {r.status_code}")
                continue

            gavda = r.content.decode(errors="ignore")
            for naqsh in (HAVOLA, HTMX):
                for m in naqsh.finditer(gavda):
                    keyingi = m.group(1)
                    if keyingi not in korilgan:
                        navbat.append(keyingi)

        self.client.logout()
        return korilgan, xatolar

    def test_superadmin_havolalari_yiqilmaydi(self):
        korilgan, xatolar = self._kuzat(self.super)
        self.assertGreater(len(korilgan), 20,
                           "Havolalar kuzatilmadi — bosh sahifa bo'shmi?")
        self.assertEqual(xatolar, [],
                         f"{len(korilgan)} sahifa ko'rildi. Yiqilganlari:\n"
                         + "\n".join(xatolar[:40]))

    def test_boshqa_rollar_havolalari_yiqilmaydi(self):
        """Har rol boshqa menyuni ko'radi — xato ham boshqa joyda chiqadi."""
        rollar = [
            (Role.Code.DOCTOR, "Shifokor"),
            (Role.Code.RECEPTION, "Registratura"),
            (Role.Code.WARD_NURSE, "Palata hamshirasi"),
            (Role.Code.SURGEON, "Jarroh"),
            (Role.Code.ANESTHESIOLOGIST, "Anesteziolog"),
            (Role.Code.CASHIER, "Kassir"),
            (Role.Code.WAREHOUSE, "Ombor mudiri"),
            (Role.Code.LAB, "Laboratoriya"),
            (Role.Code.STERILIZATION, "Avtoklav"),
        ]
        hammasi = []
        for kod, nom in rollar:
            u = User.objects.create_user(
                username=f"crawl_{kod}", password="x", role=rol(kod, nom))
            _, xatolar = self._kuzat(u)
            hammasi += [f"[{kod}] {x}" for x in xatolar]
        self.assertEqual(hammasi, [],
                         "Yiqilgan sahifalar:\n" + "\n".join(hammasi[:40]))
