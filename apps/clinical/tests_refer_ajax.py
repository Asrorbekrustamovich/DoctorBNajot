"""Statsionarga yo'naltirish: sahifa yangilanmasligi, bekor qilish, ikki
marta yubormaslik va hamshira ro'yxatidagi «Xona berish» tugmasi.

Nega bu testlar bor
-------------------
Shifokor xulosani yozib o'tirganda «Statsionarga yo'naltirish» tugmasi
butun sahifani qayta yuklardi — yozilgan matn yo'qolardi. Tugmani ikki
marta bosish ham hech narsa bilan to'silmagandi.

Hamshira ro'yxatida esa kutayotgan bemor yonida «Ko'rish» turardi va u
vipiskaga olib borardi — bemor hali yotmagan bo'lsa ham.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import AdmissionEpisode, Visit
from apps.patients.models import Patient


AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


class ReferAjaxTest(TestCase):
    def setUp(self):
        self.doc_role, _ = Role.objects.get_or_create(
            code=Role.Code.THERAPIST, defaults={"name": "Terapevt"})
        self.nurse_role, _ = Role.objects.get_or_create(
            code=Role.Code.NURSE, defaults={"name": "Hamshira"})

        self.doctor = User.objects.create_user(
            username="doc_ref", password="x", role=self.doc_role)
        self.nurse = User.objects.create_user(
            username="nurse_ref", password="x", role=self.nurse_role)

        self.patient = Patient.objects.create(
            first_name="Ali", last_name="Aliyev",
            birth_date="2000-01-01", gender="male",
            birth_certificate="MB-1112223")

        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=1,
            status=Visit.Status.IN_PROGRESS)

        self.url = reverse("clinical:refer_to_inpatient", args=[self.visit.pk])

    # ---------- yuborish ----------

    def test_ajax_json_qaytaradi_redirect_emas(self):
        """Sahifa yangilanmasligi shundan boshlanadi: javob JSON bo'lsin."""
        self.client.force_login(self.doctor)
        r = self.client.post(self.url, **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "application/json")
        j = r.json()
        self.assertTrue(j["ok"])
        self.assertTrue(j["yangi"])
        self.assertIn("cancel_url", j)

        epizod = AdmissionEpisode.objects.get(patient=self.patient)
        self.assertEqual(epizod.status, AdmissionEpisode.Status.SENT)
        self.assertIsNotNone(epizod.sent_at)

    def test_ajaxsiz_eski_yol_ishlaydi(self):
        """JS ishlamay qolsa ham forma yuborilishi kerak."""
        self.client.force_login(self.doctor)
        r = self.client.post(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            AdmissionEpisode.objects.get(patient=self.patient).status,
            AdmissionEpisode.Status.SENT)

    def test_ikki_marta_yuborsa_yangi_epizod_ochilmaydi(self):
        self.client.force_login(self.doctor)
        self.client.post(self.url, **AJAX)
        r = self.client.post(self.url, **AJAX)
        self.assertFalse(r.json()["yangi"])
        self.assertEqual(AdmissionEpisode.objects.count(), 1)

    # ---------- bekor qilish ----------

    def test_bekor_qilingach_qayta_yuborish_mumkin(self):
        self.client.force_login(self.doctor)
        j = self.client.post(self.url, **AJAX).json()

        r = self.client.post(j["cancel_url"], **AJAX)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])
        self.assertEqual(
            AdmissionEpisode.objects.get(pk=j["episode_id"]).status,
            AdmissionEpisode.Status.CANCELLED)

        # bekor qilingandan keyin YANGI epizod ochiladi
        j2 = self.client.post(self.url, **AJAX)
        self.assertTrue(j2.json()["yangi"])
        self.assertNotEqual(j2.json()["episode_id"], j["episode_id"])

    def test_yotqizilgach_bekor_qilib_bolmaydi(self):
        """Kravat berilgan — hujjat ochilgan. Orqaga qaytarish emas,
        statsionardan javob berish kerak."""
        self.client.force_login(self.doctor)
        j = self.client.post(self.url, **AJAX).json()

        epizod = AdmissionEpisode.objects.get(pk=j["episode_id"])
        epizod.status = AdmissionEpisode.Status.ADMITTED
        epizod.save(update_fields=["status"])

        r = self.client.post(j["cancel_url"], **AJAX)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(r.json()["ok"])
        self.assertEqual(
            AdmissionEpisode.objects.get(pk=epizod.pk).status,
            AdmissionEpisode.Status.ADMITTED)

    def test_bekor_qilish_sababi_yoziladi(self):
        self.client.force_login(self.doctor)
        j = self.client.post(self.url, **AJAX).json()
        self.client.post(j["cancel_url"], {"reason": "Adashib bosildi"}, **AJAX)
        self.assertEqual(
            AdmissionEpisode.objects.get(pk=j["episode_id"]).cancel_reason,
            "Adashib bosildi")

    def test_get_bilan_bekor_qilib_bolmaydi(self):
        self.client.force_login(self.doctor)
        j = self.client.post(self.url, **AJAX).json()
        r = self.client.get(j["cancel_url"])
        self.assertEqual(r.status_code, 405)


class ReferButtonStateTest(TestCase):
    """Modal qayta ochilganda tugma to'g'ri holatda chiqishi."""

    def setUp(self):
        role, _ = Role.objects.get_or_create(
            code=Role.Code.THERAPIST, defaults={"name": "Terapevt"})
        self.doctor = User.objects.create_user(
            username="doc_state", password="x", role=role)
        self.patient = Patient.objects.create(
            first_name="Vali", last_name="Valiyev",
            birth_date="1990-05-05", gender="male",
            birth_certificate="MB-9998887")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=1,
            status=Visit.Status.IN_PROGRESS)

    def _modal(self):
        self.client.force_login(self.doctor)
        r = self.client.get(
            reverse("clinical:consultation_modal", args=[self.visit.pk]))
        return r.content.decode()

    def test_yuborilmagan_bolsa_tugma_ochiq(self):
        html = self._modal()
        self.assertIn('data-sent="0"', html)
        self.assertIn("naltirish", html)

    def test_yuborilgan_bolsa_tugma_kulrang(self):
        AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit,
            referred_by=self.doctor,
            status=AdmissionEpisode.Status.SENT,
            sent_at=timezone.now())
        html = self._modal()
        self.assertIn('data-sent="1"', html)
        self.assertIn("Statsionarga yuborildi", html)
        self.assertIn("btn-secondary", html)

    def test_bekor_qilingan_epizod_tugmani_yopmaydi(self):
        AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit,
            referred_by=self.doctor,
            status=AdmissionEpisode.Status.CANCELLED)
        html = self._modal()
        self.assertIn('data-sent="0"', html)


class NurseIncomingButtonTest(TestCase):
    """Hamshira ro'yxati: kutayotgan bemorda «Xona berish» chiqsin,
    vipiskaga olib boradigan «Ko'rish» emas."""

    def setUp(self):
        doc_role, _ = Role.objects.get_or_create(
            code=Role.Code.THERAPIST, defaults={"name": "Terapevt"})
        nurse_role, _ = Role.objects.get_or_create(
            code=Role.Code.NURSE, defaults={"name": "Hamshira"})
        self.doctor = User.objects.create_user(
            username="doc_inc", password="x", role=doc_role)
        self.nurse = User.objects.create_user(
            username="nurse_inc", password="x", role=nurse_role)

        self.patient = Patient.objects.create(
            first_name="Gul", last_name="Gulova",
            birth_date="1995-03-03", gender="female",
            birth_certificate="MB-5554443")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=1,
            status=Visit.Status.IN_PROGRESS)
        self.epizod = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit,
            referred_by=self.doctor,
            status=AdmissionEpisode.Status.SENT,
            sent_at=timezone.now())

    def _sahifa(self):
        self.client.force_login(self.nurse)
        return self.client.get(
            reverse("clinical:nurse_incoming")).content.decode()

    def test_kutayotganda_xona_berish_chiqadi(self):
        html = self._sahifa()
        self.assertIn("Xona berish", html)

    def test_kutayotganda_vipiskaga_havola_yoq(self):
        vipiska = reverse("clinical:episode_detail", args=[self.epizod.pk])
        # izohdagi matn emas, aynan havola tekshiriladi
        self.assertNotIn(f'href="{vipiska}"', self._sahifa())

    def test_xona_berish_statsionar_bolimga_olib_boradi(self):
        html = self._sahifa()
        self.assertIn(reverse("clinical:inpatient_dashboard"), html)

    def test_yotqizilgandan_keyin_korish_qaytadi(self):
        self.epizod.status = AdmissionEpisode.Status.ADMITTED
        self.epizod.save(update_fields=["status"])
        vipiska = reverse("clinical:episode_detail", args=[self.epizod.pk])
        self.assertIn(f'href="{vipiska}"', self._sahifa())
