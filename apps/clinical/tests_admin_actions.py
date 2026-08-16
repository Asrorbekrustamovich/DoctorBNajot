"""VIPISKANI QAYTA OCHISH/TIKLASH VA TEKSHIRUVNI BEKOR QILISH.

Uchta talab:

1. Shifokor vipiskani xatolik bilan shakllantirib yuborishi mumkin.
   Shakllantirilgach hujjat QULFLANADI (bemor qo'liga beriladigan rasmiy
   hujjat jimgina o'zgarmasligi kerak), superadmin esa uni shifokorga
   qayta ochib beradi.

2. O'chirilgan vipiskani BIR HAFTA ichida tiklash mumkin. Muddat qat'iy:
   cheksiz tiklash imkoni bo'lsa o'chirishning ma'nosi qolmaydi va
   topshirilgan hisobotlar yillar o'tib ham o'zgarib turishi mumkin.

3. Adashib tayinlangan tekshiruvni shifokor ham, uni bajarishi kerak
   bo'lgan xodim ham bekor qila oladi va u registratorning to'lov
   ro'yxatidan tushadi. LEKIN natija yozilgan bo'lsa — bekor qilinmaydi.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.billing.selectors import pending_summary
from apps.clinical.models import (
    AdmissionEpisode, DischargeSummary, ServiceCatalog, ServiceOrder,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


class VipiskaBoshqaruvTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="vb_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.super = User.objects.create_user(
            username="vb_super", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SUPER_ADMIN, defaults={"name": "Super"})[0])
        self.patient = Patient.objects.create(
            card_number="P-VB1", last_name="Vipiskaev", first_name="Bemor",
            birth_date=date(1985, 1, 1), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(), queue_number=1)
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doc,
            reason="Sinov", status=AdmissionEpisode.Status.ADMITTED)
        self.url = reverse("clinical:episode_discharge", args=[self.episode.pk])

    def _shakllantir(self):
        """Vipiskani ATAYLAB shakllantirish.

        `action=finalize` shart: qulflash faqat aniq so'ralganda bo'ladi.
        Ilgari `action`siz yuborish ham qulflardi va vipiska tasodifan
        rasmiy holatga o'tib ketardi.
        """
        self.client.force_login(self.doc)
        self.client.post(self.url, {
            "action": "finalize",
            "outcome": DischargeSummary.Outcome.IMPROVED,
            "treatment_given": "BIRINCHI MATN",
        })
        return DischargeSummary.objects.get(episode=self.episode)

    # ---------------- QULFLASH ----------------
    def test_shakllantirilgach_qulflanadi(self):
        s = self._shakllantir()
        self.assertTrue(s.is_locked, "Vipiska qulflanmadi.")
        self.assertEqual(s.locked_by_id, self.doc.pk)

    def test_qulflangan_vipiskani_shifokor_ozgartira_olmaydi(self):
        s = self._shakllantir()
        self.client.post(self.url, {
            "action": "finalize",
            "outcome": DischargeSummary.Outcome.IMPROVED,
            "treatment_given": "O'ZGARTIRILGAN MATN",
        })
        s.refresh_from_db()
        self.assertEqual(
            s.treatment_given, "BIRINCHI MATN",
            "Qulflangan vipiska o'zgartirildi — chop etilgan nusxa bilan "
            "bazadagisi bir-biriga mos kelmay qoladi.")

    def test_superadmin_qayta_ochgach_shifokor_tahrirlaydi(self):
        s = self._shakllantir()

        self.client.force_login(self.super)
        self.client.post(reverse("clinical:discharge_unlock", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.is_locked)

        self.client.force_login(self.doc)
        self.client.post(self.url, {
            "action": "finalize",
            "outcome": DischargeSummary.Outcome.IMPROVED,
            "treatment_given": "TUZATILGAN MATN",
        })
        s.refresh_from_db()
        self.assertEqual(s.treatment_given, "TUZATILGAN MATN")

    def test_shifokor_ozi_qulfni_ocha_olmaydi(self):
        s = self._shakllantir()
        self.client.force_login(self.doc)
        self.client.post(reverse("clinical:discharge_unlock", args=[s.pk]))
        s.refresh_from_db()
        self.assertTrue(s.is_locked, "Shifokor o'zi qulfni ochib yubordi.")

    # ---------------- O'CHIRISH VA TIKLASH ----------------
    def test_ochirilgan_vipiska_bir_hafta_ichida_tiklanadi(self):
        s = self._shakllantir()
        self.client.force_login(self.super)

        self.client.post(reverse("clinical:discharge_delete", args=[s.pk]))
        s.refresh_from_db()
        self.assertTrue(s.is_deleted)

        self.client.post(reverse("clinical:discharge_restore", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.is_deleted, "Vipiska tiklanmadi.")

    def test_bir_haftadan_keyin_tiklab_bolmaydi(self):
        """ASOSIY TALAB: muddat qat'iy."""
        s = self._shakllantir()
        self.client.force_login(self.super)
        self.client.post(reverse("clinical:discharge_delete", args=[s.pk]))

        # Sakkiz kun oldin o'chirilgan holatga keltiramiz
        DischargeSummary.all_objects.filter(pk=s.pk).update(
            deleted_at=timezone.now() - timedelta(days=8))

        self.client.post(reverse("clinical:discharge_restore", args=[s.pk]))
        s.refresh_from_db()
        self.assertTrue(
            s.is_deleted,
            "Muddat o'tgan vipiska tiklandi — o'chirishning ma'nosi qolmaydi.")

    def test_yetti_kunning_ichida_hali_tiklanadi(self):
        """Chegara aniq bo'lsin: 6 kun — hali mumkin."""
        s = self._shakllantir()
        self.client.force_login(self.super)
        self.client.post(reverse("clinical:discharge_delete", args=[s.pk]))
        DischargeSummary.all_objects.filter(pk=s.pk).update(
            deleted_at=timezone.now() - timedelta(days=6))

        self.client.post(reverse("clinical:discharge_restore", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.is_deleted)

    def test_ochirilgach_epizod_yana_yotibdi_holatiga_qaytadi(self):
        s = self._shakllantir()
        self.client.force_login(self.super)
        self.client.post(reverse("clinical:discharge_delete", args=[s.pk]))

        self.episode.refresh_from_db()
        self.assertEqual(self.episode.status, AdmissionEpisode.Status.ADMITTED)

    def test_shifokor_vipiskani_ochira_olmaydi(self):
        s = self._shakllantir()
        self.client.force_login(self.doc)
        self.client.post(reverse("clinical:discharge_delete", args=[s.pk]))
        s.refresh_from_db()
        self.assertFalse(s.is_deleted)

    def test_boshqaruv_sahifasi_faqat_superadminga(self):
        self.client.force_login(self.doc)
        resp = self.client.get(reverse("clinical:discharge_admin"))
        self.assertNotEqual(resp.status_code, 200)

        self.client.force_login(self.super)
        resp = self.client.get(reverse("clinical:discharge_admin"))
        self.assertEqual(resp.status_code, 200)

    def test_muddati_otgan_vipiskada_tiklash_tugmasi_chiqmaydi(self):
        s = self._shakllantir()
        self.client.force_login(self.super)
        self.client.post(reverse("clinical:discharge_delete", args=[s.pk]))
        DischargeSummary.all_objects.filter(pk=s.pk).update(
            deleted_at=timezone.now() - timedelta(days=9))

        resp = self.client.get(reverse("clinical:discharge_admin"))
        self.assertContains(resp, "Tiklab bo'lmaydi")
        self.assertNotContains(resp, "Vipiskani tiklash")


class TekshiruvniBekorQilishTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="tb_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.lab_role = Role.objects.get_or_create(
            code=Role.Code.LAB, defaults={"name": "Laboratoriya"})[0]
        self.lab = User.objects.create_user(
            username="tb_lab", password="x", role=self.lab_role)
        self.begona = User.objects.create_user(
            username="tb_begona", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.NURSE, defaults={"name": "Hamshira"})[0])

        self.patient = Patient.objects.create(
            card_number="P-TB1", last_name="Bekorov", first_name="Test",
            birth_date=date(1990, 1, 1), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(),
            queue_number=1, doctor=self.doc)
        self.svc = ServiceCatalog.objects.create(
            name="Qon tahlili", price=30000, allowed_role=self.lab_role)
        self.order = ServiceOrder.objects.create(
            visit=self.visit, service=self.svc, price_snapshot=Decimal(30000))
        self.url = reverse("clinical:cancel_exam_order", args=[self.order.pk])

    def test_shifokor_ozi_tayinlaganini_bekor_qiladi(self):
        self.client.force_login(self.doc)
        self.assertEqual(pending_summary()["count"], 1)

        self.client.post(self.url)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.CANCELLED)
        self.assertEqual(
            pending_summary()["count"], 0,
            "Bekor qilingach registratorning to'lov ro'yxatidan chiqmadi.")

    def test_bajaruvchi_xodim_ham_bekor_qiladi(self):
        """Laborant bemorga bu kerak emasligini ko'radi."""
        self.client.force_login(self.lab)
        self.client.post(self.url)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.CANCELLED)

    def test_begona_xodim_bekor_qila_olmaydi(self):
        self.client.force_login(self.begona)
        self.client.post(self.url)

        self.order.refresh_from_db()
        self.assertNotEqual(self.order.status, ServiceOrder.Status.CANCELLED)

    def test_natija_yozilgan_bolsa_bekor_qilinmaydi(self):
        """ASOSIY HIMOYA: bajarilgan tekshiruv chekdan tushmasin."""
        self.order.result_text = "Gemoglobin 120 g/l"
        self.order.result_at = timezone.now()
        self.order.save()

        self.client.force_login(self.doc)
        self.client.post(self.url)

        self.order.refresh_from_db()
        self.assertNotEqual(
            self.order.status, ServiceOrder.Status.CANCELLED,
            "Natijasi bor tekshiruv bekor qilindi — klinika bepul ishlagan "
            "bo'lib qoladi.")

    def test_natijasiz_tekshiruvda_bekor_tugmasi_bor(self):
        """Teskari nazorat: tugma umuman chiqmasa test ma'nosiz bo'lardi."""
        self.client.force_login(self.doc)
        resp = self.client.get(
            reverse("clinical:consultation_modal", args=[self.visit.pk]))
        self.assertContains(
            resp, reverse("clinical:cancel_exam_order", args=[self.order.pk]))

    def test_natijali_tekshiruvda_bekor_tugmasi_chiqmaydi(self):
        """Tugma ko'rinib turib, bosilgach «bo'lmaydi» deyish — yomon.

        Natija kiritilgach tugma umuman chiqmasligi kerak.
        """
        self.order.result_text = "Gemoglobin 120 g/l"
        self.order.result_at = timezone.now()
        self.order.save()

        self.client.force_login(self.doc)
        resp = self.client.get(
            reverse("clinical:consultation_modal", args=[self.visit.pk]))
        self.assertNotContains(
            resp, reverse("clinical:cancel_exam_order", args=[self.order.pk]))

    def test_kim_bekor_qilgani_yoziladi(self):
        self.client.force_login(self.doc)
        self.client.post(self.url, {"reason": "Adashib tayinlandi"})

        self.order.refresh_from_db()
        self.assertIn("Bekor qilindi", self.order.result_text)
        self.assertIn("Adashib tayinlandi", self.order.result_text)

    def test_get_bilan_bekor_qilib_bolmaydi(self):
        self.client.force_login(self.doc)
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_ikki_marta_bekor_qilish_zarar_qilmaydi(self):
        self.client.force_login(self.doc)
        self.client.post(self.url)
        self.client.post(self.url)

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.CANCELLED)
