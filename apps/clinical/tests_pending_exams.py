"""TEKSHIRUV JAVOBI KELMASDAN QABULNI YAKUNLAB BO'LMAYDI.

Shifokor tekshiruv buyurgan bo'lsa, javobini ko'rmasdan qabulni yopishi
mantiqsiz: tashxis nimaga asoslanadi? Bundan tashqari yopilgan qabulga
natija kelsa, uni hech kim ko'rmay qoladi va bemor javobini olmasdan
ketadi.

MUHIM QARSHI TALAB: shifokor kutib o'tirmasligi kerak. «Saqlab turish»
ishlashi va u SHU PAYTNING O'ZIDA boshqa bemorni qabul qila olishi shart
— aks holda butun navbat bitta tahlil javobini kutib to'xtab qoladi.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import ServiceCatalog, ServiceOrder
from apps.clinical.views import pending_exam_orders
from apps.patients.models import Patient
from apps.registration.models import Visit


class NatijasizYakunlashTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="pe_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.patient = Patient.objects.create(
            card_number="P-PE1", last_name="Kutuvchi", first_name="Bemor",
            birth_date=date(1990, 1, 1), gender="male",
            jshshir="51012037250031")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(),
            queue_number=1, doctor=self.doc, status=Visit.Status.WAITING)
        self.svc = ServiceCatalog.objects.create(name="Qon tahlili", price=1)
        self.order = ServiceOrder.objects.create(
            visit=self.visit, service=self.svc, price_snapshot=Decimal(1))

        self.url = reverse("clinical:consultation_save_modal",
                           args=[self.visit.pk])
        self.client.force_login(self.doc)

    def _yakunla(self):
        return self.client.post(self.url, {
            "report_html": "<p>Xulosa</p>", "status": "completed"})

    def _saqlab_tur(self):
        return self.client.post(self.url, {
            "report_html": "<p>Xulosa</p>", "status": "in_progress"})

    # ---------------- YAKUNLASH BLOKLANADI ----------------
    def test_natija_yoq_bolsa_yakunlab_bolmaydi(self):
        resp = self._yakunla()

        self.assertEqual(resp.status_code, 400)
        self.assertIn("javobi hali chiqmagan", resp.json()["error"])

        self.visit.refresh_from_db()
        self.assertNotEqual(
            self.visit.status, Visit.Status.COMPLETED,
            "Qabul tekshiruv javobisiz yopildi — natija kelganda uni hech "
            "kim ko'rmaydi.")

    def test_xato_xabarida_tekshiruv_nomi_boladi(self):
        """Shifokor NIMANI kutayotganini bilishi kerak."""
        self.assertIn("Qon tahlili", self._yakunla().json()["error"])

    def test_natija_kelgach_yakunlanadi(self):
        """Teskari nazorat: qoida qabulni butunlay to'sib qo'ymasin."""
        self.order.result_text = "Gemoglobin 120 g/l"
        self.order.result_at = timezone.now()
        self.order.save()

        resp = self._yakunla()
        self.assertEqual(resp.status_code, 200)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.status, Visit.Status.COMPLETED)

    def test_bekor_qilingan_tekshiruv_toqinlik_qilmaydi(self):
        """«Kerak emas» deb belgilangani kutilmaydi."""
        self.order.status = ServiceOrder.Status.CANCELLED
        self.order.save()

        resp = self._yakunla()
        self.assertEqual(resp.status_code, 200)

    def test_tekshiruv_umuman_yoq_bolsa_yakunlanadi(self):
        self.order.delete()
        self.assertEqual(self._yakunla().status_code, 200)

    # ---------------- SAQLAB TURISH ISHLAYDI ----------------
    def test_saqlab_turish_ishlaydi(self):
        """ASOSIY QARSHI TALAB: shifokor kutib qolmasin."""
        resp = self._saqlab_tur()

        self.assertEqual(resp.status_code, 200,
                         "Javob kutilayotganda xulosani saqlab ham bo'lmadi.")
        from apps.clinical.models import Consultation
        self.assertTrue(
            Consultation.objects.filter(visit=self.visit, doctor=self.doc).exists(),
            "Xulosa matni saqlanmadi — shifokor yozganini yo'qotadi.")

    def test_saqlab_turgach_boshqa_bemorni_qabul_qiladi(self):
        """Butun navbat bitta tahlil javobini kutib to'xtab qolmasin."""
        self._saqlab_tur()

        boshqa = Patient.objects.create(
            card_number="P-PE2", last_name="Keyingi", first_name="Bemor",
            birth_date=date(1992, 2, 2), gender="female",
            jshshir="51012037250032")
        v2 = Visit.objects.create(
            patient=boshqa, visit_date=date.today(), queue_number=2,
            doctor=self.doc, status=Visit.Status.WAITING)

        resp = self.client.post(
            reverse("clinical:consultation_save_modal", args=[v2.pk]),
            {"report_html": "<p>Ikkinchi xulosa</p>", "status": "completed"})

        self.assertEqual(
            resp.status_code, 200,
            "Birinchi bemorning javobi kutilayotgani ikkinchisini qabul "
            "qilishga to'sqinlik qildi.")
        v2.refresh_from_db()
        self.assertEqual(v2.status, Visit.Status.COMPLETED)

    def test_birinchi_bemor_ochiq_qoladi(self):
        """Saqlab turilgan qabul yo'qolib qolmasin — javob kelishi kerak."""
        self._saqlab_tur()
        self.visit.refresh_from_db()
        self.assertIn(self.visit.status,
                      (Visit.Status.ACCEPTED, Visit.Status.IN_PROGRESS))

    # ---------------- EKRAN ----------------
    def test_ekranda_yakunlash_tugmasi_yopiq(self):
        """Tugma ochiq turib, bosilgach xato chiqishi — yomon."""
        resp = self.client.get(
            reverse("clinical:consultation_modal", args=[self.visit.pk]))
        self.assertContains(resp, "Javob kutilmoqda")
        self.assertNotContains(resp, "Saqlash va Yakunlash")
        # «Saqlab turish» esa ochiq qolishi SHART
        self.assertContains(resp, "Saqlab turish")

    def test_natija_kelgach_tugma_ochiladi(self):
        self.order.result_text = "Natija"
        self.order.result_at = timezone.now()
        self.order.save()

        resp = self.client.get(
            reverse("clinical:consultation_modal", args=[self.visit.pk]))
        self.assertContains(resp, "Saqlash va Yakunlash")
        self.assertNotContains(resp, "Javob kutilmoqda")

    def test_ekran_va_server_bir_xil_hisoblaydi(self):
        """Ikki joyda alohida shart yozilsa, ular ajralib ketardi."""
        resp = self.client.get(
            reverse("clinical:consultation_modal", args=[self.visit.pk]))
        self.assertEqual(
            [o.pk for o in resp.context["pending_exams"]],
            [o.pk for o in pending_exam_orders(self.visit)])
