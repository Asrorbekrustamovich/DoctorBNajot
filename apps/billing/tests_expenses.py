"""Klinika xarajatlari va shifokor ulushi.

Nega bu testlar bor
-------------------
1. Operatsiya summasi shifokorning 50% ulushiga qo'shilardi. Ammo
   operatsiya klinikaning ishi: xonasi, anjomi, jamoasi, sarf-materiali
   klinikadan chiqadi. Uni ham ikkiga bo'lish klinikani zararga olib
   borardi.

2. Klinika xarajatlari hech qayerda jamlanmagan edi: statsionar dorisi
   dorixona omborida, operatsiya materiali anesteziolog omborida yotardi.
   «Bu oy doriga qancha ketdi?» degan savolga javob yo'q edi.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.billing.expenses import xarajat_hisoboti
from apps.billing.reports import build_report
from apps.clinical.models import (
    AnesthesiaRequest, AnesthesiaRequestItem, AnesthesiaStock, Bed,
    Consultation, InpatientStay, NurseUsageItem, Room, SurgerySchedule,
    SurgeryType, Visit,
)
from apps.patients.models import Patient
from apps.pharmacy.models import (
    MeasurementUnit, Medicine, MedicineBatch, MedicineDispense,
)


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class DoctorShareTest(TestCase):
    """Ulush faqat QABUL summasidan hisoblansin."""

    def setUp(self):
        self.doctor = User.objects.create_user(
            username="ul_doc", password="x",
            role=rol(Role.Code.DOCTOR, "Shifokor"),
            last_name="Durdiyev", first_name="Xamdam")
        bemor = Patient.objects.create(
            first_name="Ali", last_name="Aliyev", birth_date="1990-01-01",
            gender="male", birth_certificate="MB-1111000")
        self.visit = Visit.objects.create(
            patient=bemor, doctor=self.doctor, visit_date=timezone.now(),
            queue_number=1, status=Visit.Status.IN_PROGRESS)

        Consultation.objects.create(
            visit=self.visit, doctor=self.doctor, fee=Decimal("100000"))

        SurgerySchedule.objects.create(
            visit=self.visit, surgeon=self.doctor,
            scheduled_time=timezone.now(),
            actual_price=Decimal("2500000"),
            surgery_type=SurgeryType.objects.create(
                name="Appendektomiya", price=Decimal("2500000")))

    def _qator(self):
        h = build_report(date.today(), date.today())
        return next(d for d in h["doctors"] if d["doctor__id"] == self.doctor.pk)

    def test_ulush_faqat_qabuldan(self):
        d = self._qator()
        self.assertEqual(d["income"], Decimal("100000"))
        self.assertEqual(d["surgery_income"], Decimal("2500000"))
        # 100 000 / 2 = 50 000. Operatsiya kirmaydi.
        self.assertEqual(d["doctor_share"], Decimal("50000.00"))

    def test_operatsiya_klinikaga_qoladi(self):
        d = self._qator()
        # 2 600 000 - 50 000
        self.assertEqual(d["clinic_share"], Decimal("2550000.00"))

    def test_operatsiya_soni_korinadi(self):
        """Ulushga kirmasa ham, ish hajmi jadvalda ko'rinsin."""
        d = self._qator()
        self.assertEqual(d["surgeries"], 1)
        self.assertEqual(d["total_income"], Decimal("2600000"))

    def test_faqat_jarrohda_ulush_yoq(self):
        jarroh = User.objects.create_user(
            username="ul_surg", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"),
            last_name="Zaripboev", first_name="Jasur")
        SurgerySchedule.objects.create(
            visit=self.visit, surgeon=jarroh, scheduled_time=timezone.now(),
            actual_price=Decimal("900000"),
            surgery_type=SurgeryType.objects.create(name="Churra",
                                                    price=Decimal("900000")))
        h = build_report(date.today(), date.today())
        d = next(x for x in h["doctors"] if x["doctor__id"] == jarroh.pk)
        self.assertEqual(d["doctor_share"], Decimal("0.00"))
        self.assertEqual(d["clinic_share"], Decimal("900000"))


class ExpenseReportTest(TestCase):
    """Statsionar dorisi va operatsiya materiali."""

    def setUp(self):
        self.doctor = User.objects.create_user(
            username="xar_doc", password="x",
            role=rol(Role.Code.DOCTOR, "Shifokor"))
        bemor = Patient.objects.create(
            first_name="Gul", last_name="Gulova", birth_date="1990-01-01",
            gender="female", birth_certificate="MB-2222000")
        self.visit = Visit.objects.create(
            patient=bemor, doctor=self.doctor, visit_date=timezone.now(),
            queue_number=1, status=Visit.Status.IN_PROGRESS)

        xona = Room.objects.create(name="Sinov")
        self.stay = InpatientStay.objects.create(
            visit=self.visit, bed=Bed.objects.create(room=xona, number="1A"),
            admission_date=timezone.now())

        dona = MeasurementUnit.objects.create(name="dona")
        dori = Medicine.objects.create(name="Ampitsilin", unit=dona)
        self.batch = MedicineBatch.objects.create(
            medicine=dori, quantity_received=100, quantity_available=100,
            selling_price=Decimal("5000"), purchase_price=Decimal("3000"))

    def _hisobot(self):
        return xarajat_hisoboti(date.today(), date.today())

    # ---------- statsionar dorisi ----------

    def test_dori_kelish_narxi_bilan_hisoblanadi(self):
        MedicineDispense.objects.create(
            visit=self.visit, batch=self.batch, quantity=Decimal("4"),
            price_at_dispense=Decimal("5000"))
        h = self._hisobot()
        # 4 × 3000 (kelish narxi), sotish narxi 5000 emas
        self.assertEqual(h["dori"]["jami"], Decimal("12000"))

    def test_qaytarilgan_dori_xarajat_emas(self):
        MedicineDispense.objects.create(
            visit=self.visit, batch=self.batch, quantity=Decimal("4"),
            price_at_dispense=Decimal("5000"), is_returned=True)
        self.assertEqual(self._hisobot()["dori"]["jami"], Decimal("0.00"))

    def test_ambulator_dori_xarajatga_kirmaydi(self):
        """Ambulator bemorga sotilgan dori — savdo, xarajat emas."""
        bemor2 = Patient.objects.create(
            first_name="Vali", last_name="Valiyev", birth_date="1990-01-01",
            gender="male", birth_certificate="MB-3333000",
            card_number="P-TEST-002")
        visit2 = Visit.objects.create(
            patient=bemor2, doctor=self.doctor, visit_date=timezone.now(),
            queue_number=2, status=Visit.Status.IN_PROGRESS)
        MedicineDispense.objects.create(
            visit=visit2, batch=self.batch, quantity=Decimal("10"),
            price_at_dispense=Decimal("5000"))
        self.assertEqual(self._hisobot()["dori"]["jami"], Decimal("0.00"))

    def test_dorilar_nom_boyicha_yigiladi(self):
        for _ in range(3):
            MedicineDispense.objects.create(
                visit=self.visit, batch=self.batch, quantity=Decimal("2"),
                price_at_dispense=Decimal("5000"))
        h = self._hisobot()
        self.assertEqual(len(h["dori"]["qatorlar"]), 1)
        self.assertEqual(h["dori"]["qatorlar"][0]["soni"], Decimal("6"))

    # ---------- operatsiya ----------

    def _operatsiya(self):
        return SurgerySchedule.objects.create(
            visit=self.visit, surgeon=self.doctor,
            scheduled_time=timezone.now(), actual_price=Decimal("2000000"),
            surgery_type=SurgeryType.objects.create(name="Churra",
                                                    price=Decimal("2000000")))

    def test_anesteziolog_materiali_hisoblanadi(self):
        sx = self._operatsiya()
        stock = AnesthesiaStock.objects.create(
            name="Ketamin", quantity=10, selling_price=Decimal("9000"))
        req = AnesthesiaRequest.objects.create(surgery=sx)
        AnesthesiaRequestItem.objects.create(
            request=req, stock=stock, quantity=Decimal("2"),
            price_snapshot=Decimal("9000"))
        h = self._hisobot()
        self.assertEqual(h["operatsiya"]["anest"], Decimal("18000"))

    def test_hamshira_anjomi_hisoblanadi(self):
        sx = self._operatsiya()
        stock = AnesthesiaStock.objects.create(
            name="Bint", quantity=50, selling_price=Decimal("500"))
        NurseUsageItem.objects.create(
            surgery=sx, stock=stock, quantity=Decimal("3"),
            price=Decimal("500"))
        h = self._hisobot()
        self.assertEqual(h["operatsiya"]["hamshira"], Decimal("1500"))

    def test_bekor_qilingan_operatsiya_chiqmaydi(self):
        sx = self._operatsiya()
        stock = AnesthesiaStock.objects.create(
            name="Bint", quantity=50, selling_price=Decimal("500"))
        NurseUsageItem.objects.create(
            surgery=sx, stock=stock, quantity=Decimal("3"),
            price=Decimal("500"))
        sx.status = "cancelled"
        sx.save(update_fields=["status"])
        self.assertEqual(self._hisobot()["operatsiya"]["jami"], Decimal("0.00"))

    def test_materialsiz_operatsiya_royxatga_tushmaydi(self):
        self._operatsiya()
        self.assertEqual(self._hisobot()["operatsiya"]["qatorlar"], [])

    # ---------- jami ----------

    def test_jami_ikkisining_yigindisi(self):
        MedicineDispense.objects.create(
            visit=self.visit, batch=self.batch, quantity=Decimal("4"),
            price_at_dispense=Decimal("5000"))
        sx = self._operatsiya()
        stock = AnesthesiaStock.objects.create(
            name="Bint", quantity=50, selling_price=Decimal("500"))
        NurseUsageItem.objects.create(
            surgery=sx, stock=stock, quantity=Decimal("3"),
            price=Decimal("500"))
        h = self._hisobot()
        self.assertEqual(h["jami_xarajat"], Decimal("13500"))

    def test_hisobot_sahifasida_korinadi(self):
        MedicineDispense.objects.create(
            visit=self.visit, batch=self.batch, quantity=Decimal("4"),
            price_at_dispense=Decimal("5000"))
        direktor = User.objects.create_user(
            username="xar_dir", password="x",
            role=rol(Role.Code.DIRECTOR, "Direktor"))
        self.client.force_login(direktor)
        from django.urls import reverse
        html = self.client.get(
            reverse("billing:revenue_report")).content.decode()
        self.assertIn("Statsionar DORI xarajati", html)
        self.assertIn("OPERATSIYA xarajati", html)
        self.assertIn("Ampitsilin", html)
