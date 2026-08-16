"""TO'LOV KUTAYOTGAN TAYINLOVLAR — hisoblagich va bildirishnoma.

Shifokor tekshiruv yoki qabul tayinlaganda registrator buni bilishi
kerak. Ilgari u faqat to'lov sahifasini o'zi ochib ko'rgandagina
bilardi — boshqa bo'limda turgan bo'lsa, bemor kassada kutib qolardi.

Ikki talab:
  · to'lov sahifasida nechta tayinlov kutayotgani ko'rinsin;
  · to'lov qabul qilingach o'sha son kamaysin (yo'qolsin).

Hisoblagich va bildirishnoma BITTA funksiyadan oziqlanadi — aks holda
bildirishnomada bir son, sahifada boshqa son turardi.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.billing.models import Invoice, InvoiceItem
from apps.billing.selectors import pending_summary
from apps.patients.models import Patient
from apps.registration.models import Visit


class KutayotganTolovTests(TestCase):
    def setUp(self):
        self.reg = User.objects.create_user(
            username="pd_reg", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.ADMINISTRATOR,
                defaults={"name": "Registrator"})[0])
        self.patient = Patient.objects.create(
            card_number="P-PD1", last_name="Tolovchi", first_name="Bemor",
            birth_date=date(1990, 1, 1), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(), queue_number=1)
        # Chek tashrif yaratilganda signal orqali O'ZI ochiladi —
        # qo'lda yaratsak `visit_id` bo'yicha unikal cheklovga urilamiz.
        self.invoice = Invoice.objects.get(visit=self.visit)
        self.client.force_login(self.reg)

    def _tayinlov(self, nom="Xizmat: UZI", narx=50000):
        it = InvoiceItem.objects.create(
            invoice=self.invoice, item_type=InvoiceItem.ItemType.SERVICE,
            name=nom, quantity=Decimal(1),
            price=Decimal(narx), total_price=Decimal(narx))
        # Oldindan to'lanadigan turga majburlaymiz (xizmat — shunaqa)
        it.payment_mode = InvoiceItem.PaymentMode.PREPAID
        it._mode_locked = True
        it.save(update_fields=["payment_mode"])
        return it

    # ---------------- HISOBLAGICH ----------------
    def test_tayinlov_yoq_bolsa_nol(self):
        self.assertEqual(pending_summary()["count"], 0)

    def test_tayinlanganda_hisoblagich_osadi(self):
        self._tayinlov()
        self._tayinlov(nom="Xizmat: EKG", narx=30000)

        x = pending_summary()
        self.assertEqual(x["count"], 2, "Tayinlovlar hisobga olinmadi.")
        self.assertEqual(x["patients"], 1)
        self.assertEqual(x["total"], 80000)

    def test_tolangandan_keyin_yoqoladi(self):
        """ASOSIY TALAB: to'lov qabul qilingach son kamayadi."""
        it = self._tayinlov()
        self.assertEqual(pending_summary()["count"], 1)

        it.paid_at = timezone.now()
        it._mode_locked = True
        it.save(update_fields=["paid_at"])

        self.assertEqual(
            pending_summary()["count"], 0,
            "To'lov qabul qilingandan keyin ham tayinlov ro'yxatda qoldi.")

    def test_bekor_qilingan_chek_hisoblanmaydi(self):
        self._tayinlov()
        self.invoice.status = Invoice.Status.CANCELLED
        self.invoice.save(update_fields=["status"])

        self.assertEqual(pending_summary()["count"], 0,
                         "Bekor qilingan chek to'lov kutayotgan deb sanaldi.")

    def test_narxsiz_band_hisoblanmaydi(self):
        """0 so'mlik band uchun kassaga chaqirishning ma'nosi yo'q."""
        self._tayinlov(narx=0)
        self.assertEqual(pending_summary()["count"], 0)

    def test_ikki_bemor_alohida_sanaladi(self):
        self._tayinlov()
        boshqa = Patient.objects.create(
            card_number="P-PD2", last_name="Ikkinchi", first_name="Bemor",
            birth_date=date(1991, 2, 2), gender="female")
        v2 = Visit.objects.create(patient=boshqa, visit_date=date.today(),
                                  queue_number=2)
        inv2 = Invoice.objects.get(visit=v2)
        it = InvoiceItem.objects.create(
            invoice=inv2, item_type=InvoiceItem.ItemType.SERVICE,
            name="Xizmat: Rentgen", quantity=Decimal(1),
            price=Decimal(40000), total_price=Decimal(40000))
        it.payment_mode = InvoiceItem.PaymentMode.PREPAID
        it._mode_locked = True
        it.save(update_fields=["payment_mode"])

        x = pending_summary()
        self.assertEqual(x["count"], 2)
        self.assertEqual(x["patients"], 2)

    def test_belgi_ozgaradi(self):
        """Yangi tayinlov kelganini bilish uchun belgi o'zgarishi shart.

        Bildirishnoma shu belgiga qarab chiqadi — o'zgarmasa, registrator
        yangi tayinlovdan bexabar qoladi.
        """
        oldin = pending_summary()["signature"]
        self._tayinlov()
        self.assertNotEqual(pending_summary()["signature"], oldin)

    # ---------------- EKRAN VA API ----------------
    def test_sahifada_hisoblagich_korinadi(self):
        self._tayinlov()
        resp = self.client.get(reverse("billing:registrator_payments"))
        self.assertContains(resp, "To'lov kutayotgan tayinlov")
        self.assertEqual(resp.context["kutayotgan"]["count"], 1)

    def test_qidiruv_hisoblagichni_ozgartirmaydi(self):
        """Registrator qidirib turganda ham JAMI son ko'rinishi kerak."""
        self._tayinlov()
        resp = self.client.get(reverse("billing:registrator_payments"),
                               {"q": "ZZZZZZZZ"})
        self.assertEqual(resp.context["kutayotgan"]["count"], 1)

    def test_api_json_qaytaradi(self):
        self._tayinlov()
        resp = self.client.get(reverse("billing:pending_payments_json"))
        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        self.assertEqual(d["count"], 1)
        self.assertEqual(d["patients"], 1)
        self.assertTrue(d["signature"])

    def test_shifokorga_api_yopiq(self):
        """Shifokorga bu ma'lumot kerak emas va uni chalg'itadi."""
        doc = User.objects.create_user(
            username="pd_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.client.force_login(doc)
        resp = self.client.get(reverse("billing:pending_payments_json"))
        self.assertNotEqual(resp.status_code, 200)
