"""OSILIB QOLGAN KRAVATNI BO'SHATISH.

HAQIQIY XATO: `Bed.is_occupied` — yotishlardan alohida saqlanadigan
bayroq, va u butun tizimda FAQAT BITTA joyda o'chadi: bemorga javob
berilganda (`discharge_bed`). Agar shu zanjir uzilsa — baza tozalandi,
yozuv qo'lda o'chirildi, server yarim yo'lda to'xtadi — kravat abadiy
«band» bo'lib qoladi.

Oqibati og'ir: bemor yo'q, lekin yangi bemorni ham yotqizib bo'lmaydi,
chunki `assign_bed` faqat `is_occupied=False` kravatlarni ko'radi.
Statsionar butunlay to'siladi va bundan chiqishning yagona yo'li
bazaga qo'lda kirish edi.

Shu sababli administratorga bo'shatish amali berildi. Lekin u KO'R
bo'lmasligi kerak: kravatda haqiqatdan bemor yotgan bo'lsa,
bo'shatishga ruxsat berilmaydi — aks holda ikki bemor bitta kravatda
ko'rinib qoladi.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.clinical.models import Bed, InpatientStay, Room
from apps.patients.models import Patient
from apps.registration.models import Visit


class BedReleaseTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="kr_admin", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.ADMINISTRATOR, defaults={"name": "Administrator"})[0])
        self.nurse = User.objects.create_user(
            username="kr_nurse", password="x",
            role=Role.objects.get_or_create(
                code="nurse", defaults={"name": "Hamshira"})[0])
        self.room = Room.objects.create(name="KR-1")
        self.bed = Bed.objects.create(room=self.room, number="1A", is_occupied=True)
        self.url = reverse("clinical:release_bed", args=[self.bed.id])

    # ------------------------------------------------------------------
    def test_bemorsiz_band_kravat_boshatiladi(self):
        """Asosiy holat: bayroq «band», lekin hech kim yotmagan."""
        self.client.force_login(self.admin)
        self.client.post(self.url)

        self.bed.refresh_from_db()
        self.assertFalse(
            self.bed.is_occupied,
            "Bemori yo'q kravat bo'shatilishi kerak edi — aks holda "
            "statsionar to'silib qoladi.")

    def test_bemor_yotgan_kravat_boshatilmaydi(self):
        """XAVFSIZLIK TO'SIG'I — eng muhim test."""
        p = Patient.objects.create(card_number="P-KR1", last_name="Test",
                                   first_name="Bemor", birth_date=date(1990, 1, 1),
                                   gender="male")
        v = Visit.objects.create(patient=p, visit_date=date.today(), queue_number=1)
        InpatientStay.objects.create(visit=v, bed=self.bed,
                                     status=InpatientStay.Status.ACTIVE)

        self.client.force_login(self.admin)
        resp = self.client.post(self.url, follow=True)

        self.bed.refresh_from_db()
        self.assertTrue(
            self.bed.is_occupied,
            "Bemor yotgan kravat bo'shatilib ketdi — endi uning o'rniga "
            "boshqa bemor yotqiziladi va ikkalasi bitta kravatda ko'rinadi.")
        self.assertContains(resp, "javob bering")

    def test_hamroh_yotgan_kravat_ham_boshatilmaydi(self):
        """Hamroh ham odam — u yotgan kravat ham himoyalangan bo'lishi shart."""
        p = Patient.objects.create(card_number="P-KR2", last_name="Test",
                                   first_name="Hamroh", birth_date=date(1990, 1, 1),
                                   gender="male")
        v = Visit.objects.create(patient=p, visit_date=date.today(), queue_number=2)
        other = Bed.objects.create(room=self.room, number="1B")
        InpatientStay.objects.create(visit=v, bed=other, companion_bed=self.bed,
                                     is_companion=True,
                                     status=InpatientStay.Status.ACTIVE)

        self.client.force_login(self.admin)
        self.client.post(self.url)

        self.bed.refresh_from_db()
        self.assertTrue(self.bed.is_occupied,
                        "Hamroh yotgan kravat bo'shatilib ketdi.")

    def test_javob_berilgan_yotish_toqinlik_qilmaydi(self):
        """Eski (yopilgan) yotish bo'shatishga to'sqinlik qilmasligi kerak."""
        p = Patient.objects.create(card_number="P-KR3", last_name="Test",
                                   first_name="Eski", birth_date=date(1990, 1, 1),
                                   gender="male")
        v = Visit.objects.create(patient=p, visit_date=date.today(), queue_number=3)
        InpatientStay.objects.create(visit=v, bed=self.bed,
                                     status=InpatientStay.Status.DISCHARGED)

        self.client.force_login(self.admin)
        self.client.post(self.url)

        self.bed.refresh_from_db()
        self.assertFalse(self.bed.is_occupied)

    # ------------------------------------------------------------------
    def test_hamshira_boshata_olmaydi(self):
        """Ruxsat faqat administratorda."""
        self.client.force_login(self.nurse)
        self.client.post(self.url)

        self.bed.refresh_from_db()
        self.assertTrue(self.bed.is_occupied,
                        "Hamshira kravatni bo'shatib yubordi — ruxsat yo'q edi.")

    def test_get_soravi_ozgartirmaydi(self):
        """Havolani bosish yoki sahifa yangilanishi kravatni bo'shatmasin."""
        self.client.force_login(self.admin)
        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 405)
        self.bed.refresh_from_db()
        self.assertTrue(self.bed.is_occupied)


class ClearDataResetsBedsTests(TestCase):
    """Baza tozalanganda kravatlar ham bo'shatilishi shart.

    Aynan shu qoldirilgani uchun tozalashdan keyin statsionar ishlamay
    qolgan edi: yotishlar o'chdi, kravatlar «band» bo'lib qoldi.
    """

    def test_tozalash_kravatlarni_boshatadi(self):
        from django.core.management import call_command

        room = Room.objects.create(name="TZ-1")
        bed = Bed.objects.create(room=room, number="X", is_occupied=True)

        call_command("clear_all_data", "--yes", "--no-backup",
                     "--keep-audit", verbosity=0)

        bed.refresh_from_db()
        self.assertFalse(
            bed.is_occupied,
            "Tozalashdan keyin kravat «band» bo'lib qoldi — statsionarga "
            "hech kimni yotqizib bo'lmaydi.")
