"""OPERATSIYA BAYONNOMASI — oldingi hisobotlardan nusxa olish.

Vipiskadagi «Statsionar hisobotlari» bilan bir xil mantiq: jarroh
bayonnomani noldan yozmaydi, oldingisidan tayyor parchani oladi.
Takroriy va bir turdagi operatsiyalarda matn deyarli bir xil bo'ladi.

Qoidalar:
  · SHU operatsiyaning o'zi ro'yxatda chiqmaydi;
  · bekor qilinganlar va bayonnomasi bo'shlari chiqmaydi;
  · boshqa bemorning bayonnomasi umuman chiqmasligi shart.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    OperatingRoom, SurgeryReport, SurgerySchedule, SurgeryType,
)
from apps.clinical.views import past_surgery_reports
from apps.patients.models import Patient
from apps.registration.models import Visit


class OldingiBayonnomaTests(TestCase):
    def setUp(self):
        self.jarroh = User.objects.create_user(
            username="ob_surgeon", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SURGEON, defaults={"name": "Jarroh"})[0])
        self.turi = SurgeryType.objects.create(
            name="Appendektomiya", kind=SurgeryType.Kind.OPEN, price=Decimal(1))
        self.xona = OperatingRoom.objects.create(name="OB-1")

        self.patient = Patient.objects.create(
            card_number="P-OB1", last_name="Jarrohlikov", first_name="Bemor",
            birth_date=date(1985, 1, 1), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(), queue_number=1)

        # ESKI operatsiya — bayonnomasi bilan
        self.eski = SurgerySchedule.objects.create(
            visit=self.visit, surgery_type=self.turi, operating_room=self.xona,
            surgeon=self.jarroh, scheduled_time=timezone.now(),
            actual_price=Decimal(1), status=SurgerySchedule.Status.COMPLETED)
        SurgeryReport.objects.create(
            surgery=self.eski, filled_by=self.jarroh,
            performed_actions="ESKI JARAYON MATNI",
            anesthesia="ESKI NARKOZ MATNI")

        # YANGI operatsiya — hozir bayonnoma yozilmoqda
        self.yangi = SurgerySchedule.objects.create(
            visit=self.visit, surgery_type=self.turi, operating_room=self.xona,
            surgeon=self.jarroh, scheduled_time=timezone.now(),
            actual_price=Decimal(1))

    def test_oldingi_bayonnoma_royxatda_chiqadi(self):
        royxat = past_surgery_reports(self.yangi)
        self.assertEqual(len(royxat), 1)
        nomlar = [b[0] for b in royxat[0]["bloklar"]]
        self.assertIn("Nimalar qilindi", nomlar)
        self.assertIn("Narkoz", nomlar)

    def test_shu_operatsiya_ozi_chiqmaydi(self):
        SurgeryReport.objects.create(
            surgery=self.yangi, filled_by=self.jarroh,
            performed_actions="SHU OPERATSIYA MATNI")

        royxat = past_surgery_reports(self.yangi)
        self.assertEqual([r["surgery"].pk for r in royxat], [self.eski.pk])

    def test_matn_qaysi_maydonga_tushishi_korsatilgan(self):
        """Sarlavhadan hisoblab olish mo'rt — maydon nomi aniq berilsin."""
        blok = past_surgery_reports(self.yangi)[0]["bloklar"]
        maydonlar = {b[2] for b in blok}
        self.assertIn("performed_actions", maydonlar)
        self.assertIn("anesthesia", maydonlar)

    def test_bosh_bloklar_chiqmaydi(self):
        blok = past_surgery_reports(self.yangi)[0]["bloklar"]
        nomlar = [b[0] for b in blok]
        self.assertNotIn("Qilingan ukollar", nomlar)

    def test_bayonnomasiz_operatsiya_chiqmaydi(self):
        SurgerySchedule.objects.create(
            visit=self.visit, surgery_type=self.turi, operating_room=self.xona,
            surgeon=self.jarroh, scheduled_time=timezone.now(),
            actual_price=Decimal(1), status=SurgerySchedule.Status.COMPLETED)

        self.assertEqual(len(past_surgery_reports(self.yangi)), 1,
                         "Bayonnomasi yo'q operatsiya ro'yxatga tushdi.")

    def test_bekor_qilingan_operatsiya_chiqmaydi(self):
        self.eski.status = "cancelled"
        self.eski.save(update_fields=["status"])
        self.assertEqual(len(past_surgery_reports(self.yangi)), 0)

    def test_boshqa_bemorning_bayonnomasi_chiqmaydi(self):
        """Eng muhim chegara: begona bemorning matni kirib qolmasin."""
        boshqa = Patient.objects.create(
            card_number="P-OB9", last_name="Begona", first_name="X",
            birth_date=date(1990, 1, 1), gender="male")
        bv = Visit.objects.create(patient=boshqa, visit_date=date.today(),
                                  queue_number=9)
        bs = SurgerySchedule.objects.create(
            visit=bv, surgery_type=self.turi, operating_room=self.xona,
            surgeon=self.jarroh, scheduled_time=timezone.now(),
            actual_price=Decimal(1), status=SurgerySchedule.Status.COMPLETED)
        SurgeryReport.objects.create(
            surgery=bs, filled_by=self.jarroh,
            performed_actions="BEGONA BEMOR MATNI")

        royxat = past_surgery_reports(self.yangi)
        hamma_matn = " ".join(b[1] for r in royxat for b in r["bloklar"])
        self.assertNotIn("BEGONA BEMOR MATNI", hamma_matn)

    # ---------------- EKRAN ----------------
    def test_ekranda_oldingi_bayonnoma_korinadi(self):
        self.client.force_login(self.jarroh)
        resp = self.client.get(reverse("clinical:surgery_dashboard"))

        self.assertContains(resp, "Bemorning oldingi bayonnomalari")
        self.assertContains(resp, "ESKI JARAYON MATNI")
        self.assertContains(resp, "srep-copy")

    def test_kochirish_delegatsiya_bilan(self):
        """Tugmalarga bittalab bog'lansa, modal keyin chizilsa ishlamaydi."""
        self.client.force_login(self.jarroh)
        h = self.client.get(reverse("clinical:surgery_dashboard")).content.decode()
        self.assertIn("document.addEventListener('click'", h)
