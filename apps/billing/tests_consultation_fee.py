"""Qabul narxi bemor shifokorga KIRISHIDAN OLDIN chekka tushishi kerak.

HAQIQIY XATO: narx chekka faqat shifokor xulosa yozgandan keyin
tushardi (`Consultation.fee` orqali). Klinika qoidasi esa teskari:
avval to'lov, keyin ko'rik. Natijada registrator ekranida to'lanadigan
hech narsa ko'rinmasdi va pul yig'ilmay qolardi.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Role, User
from apps.billing.models import Invoice, InvoiceItem
from apps.clinical.models import Consultation, DoctorPrice
from apps.patients.models import Patient
from apps.registration.models import Visit


class ConsultationFeeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.doc = User.objects.create_user(
            username="cf_doc", password="x", first_name="Olim", last_name="Sattorov",
            role=Role.objects.get_or_create(code="doctor", defaults={"name": "Sh"})[0])
        cls.doc2 = User.objects.create_user(
            username="cf_doc2", password="x", first_name="Aziz", last_name="Karimov",
            role=Role.objects.get(code="doctor"))
        DoctorPrice.objects.create(doctor=cls.doc, price=Decimal("100000"))
        DoctorPrice.objects.create(doctor=cls.doc2, price=Decimal("150000"))
        cls.patient = Patient.objects.create(
            card_number="P-CF1", last_name="Bemor", first_name="Test",
            birth_date=date(1990, 1, 1), gender="male")

    def _invoice(self, visit):
        return Invoice.objects.get(visit=visit)

    def test_qabul_yozdirilganda_narx_chekka_tushadi(self):
        v = Visit.objects.create(patient=self.patient, doctor=self.doc,
                                 visit_date=date(2026, 8, 11), queue_number=1)
        inv = self._invoice(v)
        self.assertEqual(inv.total_amount, Decimal("100000"))
        item = inv.items.get()
        self.assertIn("Sattorov", item.name)
        self.assertEqual(item.payment_mode, InvoiceItem.PaymentMode.PREPAID)
        self.assertFalse(item.is_paid)

    def test_shifokorsiz_qabulda_narx_yoq(self):
        v = Visit.objects.create(patient=self.patient, visit_date=date(2026, 8, 11),
                                 queue_number=2)
        self.assertEqual(self._invoice(v).total_amount, Decimal("0"))

    def test_boshqa_shifokorga_yonaltirilsa_narx_almashadi(self):
        v = Visit.objects.create(patient=self.patient, doctor=self.doc,
                                 visit_date=date(2026, 8, 11), queue_number=3)
        self.assertEqual(self._invoice(v).total_amount, Decimal("100000"))

        v.doctor = self.doc2
        v.save()
        inv = self._invoice(v)
        self.assertEqual(inv.total_amount, Decimal("150000"))
        self.assertEqual(inv.items.count(), 1, "Ikkita qabul narxi qo'shilib ketdi")
        self.assertIn("Karimov", inv.items.get().name)

    def test_xulosa_yozilgach_narx_ikkilanmaydi(self):
        """Shifokor xulosa yozgach, `Consultation.fee` ishlatiladi."""
        v = Visit.objects.create(patient=self.patient, doctor=self.doc,
                                 visit_date=date(2026, 8, 11), queue_number=4)
        Consultation.objects.create(visit=v, doctor=self.doc, fee=Decimal("100000"))
        inv = self._invoice(v)
        self.assertEqual(inv.items.count(), 1, "Qabul narxi ikki marta yozildi")
        self.assertEqual(inv.total_amount, Decimal("100000"))

    def test_narx_belgilanmagan_shifokorda_chek_bosh(self):
        doc3 = User.objects.create_user(username="cf_doc3", password="x",
                                        role=Role.objects.get(code="doctor"))
        v = Visit.objects.create(patient=self.patient, doctor=doc3,
                                 visit_date=date(2026, 8, 11), queue_number=5)
        self.assertEqual(self._invoice(v).total_amount, Decimal("0"))

    def test_narx_ochirilgan_bolsa_hisoblanmaydi(self):
        DoctorPrice.objects.filter(doctor=self.doc).update(is_active=False)
        v = Visit.objects.create(patient=self.patient, doctor=self.doc,
                                 visit_date=date(2026, 8, 11), queue_number=6)
        self.assertEqual(self._invoice(v).total_amount, Decimal("0"))
