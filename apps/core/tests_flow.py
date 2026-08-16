"""UCHIDAN-UCHIGA OQIM — bemor eshikdan kirib, vipiska bilan chiqadi.

Alohida testlar har bir bo'lakni tekshiradi, lekin ular ORASIDAGI
bog'lanish tekshirilmay qoladi: registratura chekni to'g'ri ochdimi,
to'lov tekshiruvni ochdimi, yotqizish epizodga ulandimi, vipiskaga
hamma narsa tushdimi.

Bu test butun zanjirni bitta bemor bilan bosib o'tadi. Bo'laklar orasida
biror bog'lanish uzilsa — shu yerda ko'rinadi.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.billing.models import Invoice, InvoiceItem
from apps.billing.selectors import pending_summary
from apps.clinical.models import (
    AdmissionEpisode, Bed, DischargeSummary, DoctorPrice, InpatientStay,
    Room, ServiceCatalog, ServiceOrder,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


def _rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class ToliqOqimTests(TestCase):
    """Registratura → to'lov → shifokor → tekshiruv → statsionar → vipiska."""

    def setUp(self):
        self.reg = User.objects.create_user(
            username="fl_reg", password="x",
            role=_rol(Role.Code.ADMINISTRATOR, "Registrator"))
        self.doc = User.objects.create_user(
            username="fl_doc", password="x", first_name="Shifokor",
            role=_rol("doctor", "Shifokor"))
        self.lab = User.objects.create_user(
            username="fl_lab", password="x",
            role=_rol(Role.Code.LAB, "Laboratoriya"))
        self.hamshira = User.objects.create_user(
            username="fl_nurse", password="x",
            role=_rol(Role.Code.WARD_NURSE, "Palata hamshirasi"))
        self.super = User.objects.create_user(
            username="fl_super", password="x", is_superuser=True,
            role=_rol(Role.Code.SUPER_ADMIN, "Super"))

        DoctorPrice.objects.create(doctor=self.doc, price=Decimal(50000),
                                   is_active=True)
        self.svc = ServiceCatalog.objects.create(
            name="Umumiy qon tahlili", price=Decimal(30000))
        self.room = Room.objects.create(name="Oqim-1")
        self.bed = Bed.objects.create(room=self.room, number="1A",
                                      price_per_day=Decimal(100000))

    def test_toliq_zanjir(self):
        # ---------- 1. REGISTRATURA: bemor va navbat ----------
        self.client.force_login(self.reg)
        self.client.post(reverse("patients:create"), {
            "last_name": "Oqimov", "first_name": "Bemor",
            "birth_date": "1985-05-05", "gender": "male",
            "jshshir": "51012037250044",
        })
        bemor = Patient.objects.get(last_name="Oqimov")

        visit = Visit.objects.create(
            patient=bemor, visit_date=date.today(), queue_number=1,
            doctor=self.doc, status=Visit.Status.WAITING)

        # Qabul narxi chekka DARROV tushishi kerak — bemor kirishdan oldin
        chek = Invoice.objects.get(visit=visit)
        self.assertEqual(chek.total_amount, 50000,
                         "Shifokor qabuli narxi chekka tushmadi.")
        self.assertEqual(pending_summary()["count"], 1,
                         "To'lov registrator ro'yxatida ko'rinmadi.")

        # ---------- 2. TO'LOV ----------
        bandlar = list(chek.items.all())
        self.assertTrue(all(i.payment_mode == InvoiceItem.PaymentMode.PREPAID
                            for i in bandlar),
                        "Ambulator qabul oldindan to'lanadigan emas.")

        chek.paid_amount = Decimal(50000)
        chek.save(update_fields=["paid_amount"])
        from apps.billing.services import settle_prepaid_items
        settle_prepaid_items(chek)

        self.assertEqual(pending_summary()["count"], 0,
                         "To'langach ro'yxatdan tushmadi.")

        # ---------- 3. SHIFOKOR: tekshiruv tayinlaydi ----------
        self.client.force_login(self.doc)
        order = ServiceOrder.objects.create(
            visit=visit, service=self.svc, price_snapshot=Decimal(30000))

        # Tekshiruv ham to'lov kutadi
        self.assertEqual(pending_summary()["count"], 1,
                         "Tayinlangan tekshiruv to'lovga chiqmadi.")

        # Javob kelmasdan qabulni yakunlab bo'lmaydi
        javob = self.client.post(
            reverse("clinical:consultation_save_modal", args=[visit.pk]),
            {"report_html": "<p>Ko'rik</p>", "status": "completed"})
        self.assertEqual(javob.status_code, 400,
                         "Tekshiruv javobisiz qabul yakunlandi.")

        # ---------- 4. LABORATORIYA: natija ----------
        order.result_text = "Gemoglobin 120 g/l"
        order.result_at = timezone.now()
        order.performed_by = self.lab
        order.save()

        # Endi yakunlash mumkin
        javob = self.client.post(
            reverse("clinical:consultation_save_modal", args=[visit.pk]),
            {"report_html": "<p>Ko'rik</p>", "status": "in_progress"})
        self.assertEqual(javob.status_code, 200)

        # ---------- 5. STATSIONARGA YO'NALTIRISH ----------
        self.client.post(
            reverse("clinical:refer_to_inpatient", args=[visit.pk]),
            {"reason": "Kuzatuv uchun"})

        epizod = AdmissionEpisode.objects.get(patient=bemor)
        self.assertEqual(epizod.status, AdmissionEpisode.Status.SENT,
                         "Epizod hamshiraga yuborilmadi.")

        # ---------- 6. HAMSHIRA: kravat beradi ----------
        self.client.force_login(self.hamshira)
        javob = self.client.post(
            reverse("clinical:admit_visit", args=[visit.pk]),
            {"bed_id": str(self.bed.pk), "stay_type": "standard",
             "assigned_doctor": str(self.doc.pk)})

        stay = InpatientStay.objects.get(visit=visit)
        self.assertEqual(stay.status, InpatientStay.Status.ACTIVE)
        self.bed.refresh_from_db()
        self.assertTrue(self.bed.is_occupied, "Kravat band bo'lmadi.")

        # Yotish epizodga BOG'LANISHI shart
        epizod.refresh_from_db()
        self.assertEqual(
            epizod.stay_id, stay.pk,
            "Yotish epizodga bog'lanmadi — statsionar hisobotlari bo'sh "
            "chiqadi.")
        self.assertEqual(epizod.status, AdmissionEpisode.Status.ADMITTED)

        # Hujjat hamshirasi — yotqizgan odam
        self.assertEqual(stay.doc_nurse_id, self.hamshira.pk)

        # ---------- 7. STATSIONAR HUJJATLARI ----------
        h = self.client.get(
            reverse("clinical:stay_documentation", args=[stay.pk])
        ).content.decode()
        self.assertIn("Umumiy qon tahlili", h,
                      "Qabulda tayinlangan tahlil hujjatda ko'rinmadi.")
        self.assertIn("Kuzatuv uchun", h,
                      "Murojaat sababi hujjatda ko'rinmadi.")

        # ---------- 8. VIPISKA ----------
        self.client.force_login(self.doc)
        javob = self.client.post(
            reverse("clinical:episode_discharge", args=[epizod.pk]), {
                # Qulflash faqat ataylab so'ralganda
                "action": "finalize",
                "outcome": DischargeSummary.Outcome.RECOVERED,
                "treatment_given": "Infuzion terapiya",
                "recommendations": "Parhez",
            })
        self.assertEqual(javob.status_code, 302)

        vipiska = DischargeSummary.objects.get(episode=epizod)
        self.assertTrue(vipiska.is_locked,
                        "Vipiska shakllantirilgach qulflanmadi.")

        # Blankada hamma narsa bo'lishi kerak
        blank = self.client.get(
            reverse("clinical:discharge_print", args=[epizod.pk])
        ).content.decode()
        self.assertIn("Oqimov", blank)
        self.assertIn("Infuzion terapiya", blank)
        self.assertIn("Umumiy qon tahlili", blank)
        self.assertIn("Gemoglobin 120 g/l", blank)

        # ---------- 9. SUPERADMIN: qayta ochish ----------
        self.client.force_login(self.super)
        self.client.post(reverse("clinical:discharge_unlock", args=[vipiska.pk]))
        vipiska.refresh_from_db()
        self.assertFalse(vipiska.is_locked)

    def test_navbat_bekor_qilinsa_zanjir_tozalanadi(self):
        """Bekor qilingan navbatdan qarz ham, to'lov talabi ham qolmaydi."""
        bemor = Patient.objects.create(
            card_number="P-FL2", last_name="Bekorov", first_name="Test",
            birth_date=date(1990, 1, 1), gender="male",
            jshshir="51012037250045")
        visit = Visit.objects.create(
            patient=bemor, visit_date=date.today(), queue_number=2,
            doctor=self.doc, status=Visit.Status.WAITING)
        ServiceOrder.objects.create(
            visit=visit, service=self.svc, price_snapshot=Decimal(30000))

        self.assertGreater(pending_summary()["count"], 0)

        from apps.registration.services import visit_transition
        visit_transition(visit=visit, new_status=Visit.Status.CANCELLED,
                         reason="Bemor kelmadi")

        self.assertEqual(pending_summary()["count"], 0,
                         "Bekor qilingan navbatdan to'lov talabi qoldi.")
        chek = Invoice.objects.get(visit=visit)
        self.assertEqual(chek.debt, 0, "Bekor qilingan navbatda qarz qoldi.")
