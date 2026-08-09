"""OLDINDAN TO'LOV qoidasi.

Klinika qoidasi:
  · ambulator qabul va TEKSHIRUVLAR — xizmatdan OLDIN to'lanadi
  · statsionar (palata) — kassaga yoziladi, yakunda hisoblanadi

Tekshiruvga bu qoida qayerdan buyurilganidan qat'i nazar tegishli:
ambulator qabulda ham, statsionarda yotgan bemorda ham.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.billing.models import Invoice, InvoiceItem
from apps.billing.services import prepaid_debt, settle_prepaid_items
from apps.clinical.models import ServiceCatalog, ServiceCategory, ServiceOrder
from apps.patients.models import Patient
from apps.registration.models import Visit


def role(code):
    return Role.objects.get_or_create(code=code, defaults={"name": code.title()})[0]


class PrepayBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        # DIQQAT: rol EXAMINER_ROLES ichida bo'lishi SHART. Aks holda
        # foydalanuvchi rol tekshiruvida to'siladi va «to'lovsiz
        # bajarilmadi» degan testlar NOTO'G'RI SABABDAN o'tib ketadi —
        # ya'ni to'lov to'sig'ini umuman sinamaydi.
        cls.lab = User.objects.create_user(username="pp_lab", password="x",
                                           role=role("lab"))
        cls.cashier = User.objects.create_user(username="pp_kassir", password="x",
                                               role=role("reception"))
        cls.patient = Patient.objects.create(
            card_number="P-800001", last_name="Toshev", first_name="Olim",
            birth_date=date(1985, 1, 1), gender=Patient.Gender.MALE)
        cls.visit = Visit.objects.create(
            patient=cls.patient, visit_date=date(2026, 8, 1), queue_number=7)
        cat = ServiceCategory.objects.create(name="Sinov lab", button_label="+Analiz")
        cls.svc = ServiceCatalog.objects.create(
            name="Sinov qon tahlili", price=Decimal("40000"), category=cat)
        cls.free_svc = ServiceCatalog.objects.create(
            name="Bepul ko'rik", price=Decimal("0"), category=cat)

    def _invoice(self):
        return Invoice.objects.get_or_create(
            visit=self.visit, defaults={"patient": self.patient})[0]


# ------------------------------------------------------- to'lov tartibi
class PaymentModeTests(PrepayBase):

    def test_tekshiruv_oldindan_tolanadi(self):
        inv = self._invoice()
        item = InvoiceItem.objects.create(
            invoice=inv, item_type=InvoiceItem.ItemType.SERVICE,
            name="Analiz", price=Decimal("40000"), quantity=1)
        self.assertEqual(item.payment_mode, InvoiceItem.PaymentMode.PREPAID)
        self.assertTrue(item.is_prepaid_required)

    def test_statsionar_kassaga_yoziladi(self):
        inv = self._invoice()
        item = InvoiceItem.objects.create(
            invoice=inv, item_type=InvoiceItem.ItemType.INPATIENT,
            name="Palata 3 kun", price=Decimal("300000"), quantity=1)
        self.assertEqual(item.payment_mode, InvoiceItem.PaymentMode.POSTPAID)
        self.assertFalse(item.is_prepaid_required)

    def test_dori_va_operatsiya_kassaga(self):
        inv = self._invoice()
        for t in (InvoiceItem.ItemType.MEDICINE, InvoiceItem.ItemType.SURGERY):
            i = InvoiceItem.objects.create(
                invoice=inv, item_type=t, name=str(t), price=Decimal("1000"), quantity=1)
            self.assertEqual(i.payment_mode, InvoiceItem.PaymentMode.POSTPAID, t)


# ------------------------------------------------------- pul taqsimlash
class SettleTests(PrepayBase):

    def setUp(self):
        self.inv = self._invoice()
        self.exam = InvoiceItem.objects.create(
            invoice=self.inv, item_type=InvoiceItem.ItemType.SERVICE,
            name="Analiz", price=Decimal("40000"), quantity=1)
        self.bed = InvoiceItem.objects.create(
            invoice=self.inv, item_type=InvoiceItem.ItemType.INPATIENT,
            name="Palata", price=Decimal("300000"), quantity=1)
        self.inv.total_amount = Decimal("340000")
        self.inv.save()

    def test_tolovsiz_hech_narsa_tolangan_emas(self):
        settle_prepaid_items(self.inv)
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.is_paid)
        self.assertEqual(prepaid_debt(self.inv), Decimal("40000"))

    def test_pul_avval_oldindan_tolanadiganga_ketadi(self):
        """40 000 to'lansa — palata emas, ANALIZ yopiladi."""
        self.inv.paid_amount = Decimal("40000")
        self.inv.save()
        settle_prepaid_items(self.inv, cashier=self.cashier)
        self.exam.refresh_from_db(); self.bed.refresh_from_db()
        self.assertTrue(self.exam.is_paid, "Analiz to'langan bo'lishi kerak")
        self.assertFalse(self.bed.is_paid, "Palata hali to'lanmagan")
        self.assertEqual(prepaid_debt(self.inv), Decimal("0"))

    def test_kassir_yoziladi(self):
        self.inv.paid_amount = Decimal("40000")
        self.inv.save()
        settle_prepaid_items(self.inv, cashier=self.cashier)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.paid_by, self.cashier)

    def test_yetmasa_tolanmagan_boladi(self):
        self.inv.paid_amount = Decimal("10000")
        self.inv.save()
        settle_prepaid_items(self.inv)
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.is_paid)

    def test_pul_qaytarilsa_tolov_bekor_boladi(self):
        """Qaytarilgandan keyin tekshiruv yana to'lanmagan bo'lishi kerak."""
        self.inv.paid_amount = Decimal("40000")
        self.inv.save()
        settle_prepaid_items(self.inv)
        self.exam.refresh_from_db()
        self.assertTrue(self.exam.is_paid)

        self.inv.refunded_amount = Decimal("40000")
        self.inv.save()
        settle_prepaid_items(self.inv)
        self.exam.refresh_from_db()
        self.assertFalse(self.exam.is_paid, "Pul qaytarilgach to'lov bekor bo'lishi kerak")


# --------------------------------------------- tekshiruvni to'sish
class ExamGateTests(PrepayBase):

    def setUp(self):
        # DIQQAT: chek bandini QO'LDA yaratmaymiz. `ServiceOrder` saqlanganda
        # signal `generate_invoice_for_visit` ni chaqiradi va u chekni
        # butunlay qayta quradi (eski bandlarni o'chirib tashlaydi).
        # Qo'lda qo'shsak, ikkita band paydo bo'lib, summa ikki barobar
        # bo'lib ketadi — testning o'zi haqiqatni buzadi.
        self.order = ServiceOrder.objects.create(visit=self.visit, service=self.svc)
        self.inv = Invoice.objects.get(visit=self.visit)
        self.item = self.inv.items.get(reference_id=self.order.id)
        self.client.force_login(self.lab)

    def _pay(self):
        self.inv.refresh_from_db()
        self.inv.paid_amount = self.inv.total_amount
        self.inv.save()
        settle_prepaid_items(self.inv, cashier=self.cashier)

    def test_tolanmagan_tekshiruv_tosiladi(self):
        self.assertFalse(self.order.is_paid)
        self.assertIn("to'lov", self.order.payment_blocked_reason.lower())

    def test_tolangach_tosiq_yoq(self):
        self._pay()
        self.assertTrue(self.order.is_paid)
        self.assertEqual(self.order.payment_blocked_reason, "")

    def test_narxsiz_tekshiruv_tosilmaydi(self):
        """Narxi 0 bo'lsa to'lov talab qilinmaydi."""
        o = ServiceOrder.objects.create(visit=self.visit, service=self.free_svc)
        self.assertEqual(o.payment_blocked_reason, "")

    def test_rol_togri_ekanini_avval_tekshiramiz(self):
        """Nazorat: to'lansa chaqiruv ISHLAYDI.

        Busiz «chaqirilmadi» testlari rol tufayli ham o'tib ketardi va
        to'lov to'sig'ini umuman sinamagan bo'lardi.
        """
        self._pay()
        self.client.post(reverse("clinical:examiner_order_call", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.called_at, "Rol to'sib qo'ydi, to'lov emas")

    def test_tolanmagan_bemor_chaqirilmaydi(self):
        self.client.post(reverse("clinical:examiner_order_call", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertIsNone(self.order.called_at, "To'lovsiz chaqirildi!")

    def test_tolanmagan_tekshiruv_qabul_qilinmaydi(self):
        self.client.post(reverse("clinical:examiner_order_accept", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, ServiceOrder.Status.IN_PROGRESS)

    def test_tolanmagan_tekshiruvga_natija_yozilmaydi(self):
        """Eng muhimi: xizmat ko'rsatilib bo'lmaydi."""
        self.client.post(reverse("clinical:examiner_order_perform", args=[self.order.id]),
                         {"result_text": "Natija", "row_name": [""], "row_value": [""],
                          "row_unit": [""], "row_ref": [""]})
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, ServiceOrder.Status.COMPLETED)
        self.assertEqual(self.order.result_text, "")

    def test_tolangandan_keyin_hammasi_ishlaydi(self):
        self._pay()
        self.client.post(reverse("clinical:examiner_order_call", args=[self.order.id]))
        self.order.refresh_from_db()
        self.assertIsNotNone(self.order.called_at)

        self.client.post(reverse("clinical:examiner_order_perform", args=[self.order.id]),
                         {"result_text": "Norma", "row_name": [""], "row_value": [""],
                          "row_unit": [""], "row_ref": [""]})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.COMPLETED)

    def test_status_ozgartirish_tolovni_aldamaydi(self):
        """Status qo'lda `paid` qilinsa ham, chek to'lanmagan bo'lsa to'siq qoladi."""
        self.order.status = ServiceOrder.Status.PAID
        self.order.save()
        self.assertFalse(self.order.is_paid, "Status pul o'rnini bosmasligi kerak")
        self.assertNotEqual(self.order.payment_blocked_reason, "")
