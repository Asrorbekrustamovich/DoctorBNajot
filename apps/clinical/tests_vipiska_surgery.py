"""Vipiska: operatsiya bloki, to'xtatib turish va yo'naltirish maqsadi.

Nega bu testlar bor
-------------------
1. Bemor kartasida «Operatsiya uchun» deb turardi, holbuki buni hech
   kim tanlamagan — ambulator yo'naltirishda maqsad so'ralmasdi va
   qiymat boshqa yo'ldan kelib qolardi.

2. Vipiskada operatsiya bo'yicha faqat bo'sh matn maydoni bor edi:
   qilingan operatsiya ro'yxatda ko'rinmasdi, shifokor uni jarrohlik
   bo'limidan qo'lda ko'chirardi.

3. Yagona «Shakllantirish» tugmasi vipiskani darrov QULFLARDI. Kerakli
   yozuv (ukol, operatsiya protokoli) hali kiritilmagan bo'lsa,
   shifokor yo yarim hujjat bilan yakunlashi, yo yozganini tashlab
   ketishi kerak edi.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, DischargeSummary, SurgerySchedule, SurgeryType, Visit,
)
from apps.patients.models import Patient

AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class ReferPurposeTest(TestCase):
    """Maqsad tanlanmasa — «Operatsiya uchun» deb yozilmasin."""

    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc_p", password="x", role=rol(Role.Code.THERAPIST, "Terapevt"))
        self.patient = Patient.objects.create(
            first_name="Asror", last_name="Azatbayev",
            birth_date="2004-01-01", gender="male",
            birth_certificate="MB-7776665")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=1,
            status=Visit.Status.IN_PROGRESS)
        self.url = reverse("clinical:refer_to_inpatient", args=[self.visit.pk])
        self.client.force_login(self.doctor)

    def test_maqsad_korsatilmasa_davolash(self):
        self.client.post(self.url, **AJAX)
        ep = AdmissionEpisode.objects.get(patient=self.patient)
        self.assertEqual(ep.purpose, AdmissionEpisode.Purpose.TREATMENT)
        self.assertFalse(ep.needs_anesthesiologist)

    def test_operatsiya_tanlansa_yoziladi(self):
        self.client.post(self.url, {"purpose": "surgery"}, **AJAX)
        ep = AdmissionEpisode.objects.get(patient=self.patient)
        self.assertEqual(ep.purpose, AdmissionEpisode.Purpose.SURGERY)
        self.assertTrue(ep.needs_anesthesiologist)

    def test_oynada_tanlov_bor(self):
        html = self.client.get(
            reverse("clinical:consultation_modal",
                    args=[self.visit.pk])).content.decode()
        self.assertIn('id="referPurpose"', html)
        self.assertIn("Operatsiya uchun", html)
        self.assertIn("operatsiyasiz", html)


class VipiskaHoldTest(TestCase):
    """To'xtatib turish: saqlaydi, lekin qulflamaydi."""

    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc_h", password="x", role=rol(Role.Code.THERAPIST, "Terapevt"))
        self.patient = Patient.objects.create(
            first_name="Vali", last_name="Valiyev",
            birth_date="1990-01-01", gender="male",
            birth_certificate="MB-1231231")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=2,
            status=Visit.Status.IN_PROGRESS)
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doctor,
            status=AdmissionEpisode.Status.ADMITTED)
        self.url = reverse("clinical:episode_discharge", args=[self.episode.pk])
        self.client.force_login(self.doctor)

    def test_toxtatib_turish_qulflamaydi(self):
        self.client.post(self.url, {
            "action": "hold",
            "recommendations": "Yarim yozilgan matn",
        })
        s = DischargeSummary.objects.get(episode=self.episode)
        self.assertFalse(s.is_locked)
        self.assertIsNone(s.locked_at)
        self.assertEqual(s.recommendations, "Yarim yozilgan matn")

    def test_toxtatib_turish_epizodni_yopmaydi(self):
        """Yetishmagani qo'shilgach davom ettirish kerak."""
        self.client.post(self.url, {"action": "hold"})
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.status,
                         AdmissionEpisode.Status.ADMITTED)

    def test_toxtatilgandan_keyin_davom_ettirish_mumkin(self):
        self.client.post(self.url, {"action": "hold",
                                    "recommendations": "birinchi"})
        self.client.post(self.url, {"action": "hold",
                                    "recommendations": "ikkinchi"})
        s = DischargeSummary.objects.get(episode=self.episode)
        self.assertEqual(s.recommendations, "ikkinchi")
        self.assertFalse(s.is_locked)

    def test_toxtatilganini_yakunlash_mumkin(self):
        self.client.post(self.url, {"action": "hold",
                                    "recommendations": "yarim"})
        self.client.post(self.url, {"action": "finalize",
                                    "recommendations": "tayyor"})
        s = DischargeSummary.objects.get(episode=self.episode)
        self.assertTrue(s.is_locked)
        self.assertEqual(s.recommendations, "tayyor")
        self.episode.refresh_from_db()
        self.assertEqual(self.episode.status,
                         AdmissionEpisode.Status.DISCHARGED)

    def test_yakunlash_qulflaydi(self):
        self.client.post(self.url, {"action": "finalize"})
        self.assertTrue(
            DischargeSummary.objects.get(episode=self.episode).is_locked)

    def test_tugma_formada_bor(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn('value="hold"', html)
        self.assertIn("xtatib turish", html)


class VipiskaSurgeryBlockTest(TestCase):
    """Operatsiya bo'lsa — vipiskada ro'yxat bo'lib chiqsin."""

    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc_s", password="x", role=rol(Role.Code.THERAPIST, "Terapevt"))
        self.jarroh = User.objects.create_user(
            username="jarroh_s", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"),
            last_name="Durdiyev", first_name="Xamdam")
        self.patient = Patient.objects.create(
            first_name="Gul", last_name="Gulova",
            birth_date="1985-01-01", gender="female",
            birth_certificate="MB-4564564")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=3,
            status=Visit.Status.IN_PROGRESS)
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doctor,
            status=AdmissionEpisode.Status.ADMITTED)
        self.url = reverse("clinical:episode_discharge", args=[self.episode.pk])
        self.client.force_login(self.doctor)

    def _operatsiya(self):
        tur = SurgeryType.objects.create(name="Appendektomiya", price=100)
        return SurgerySchedule.objects.create(
            visit=self.visit, surgery_type=tur, surgeon=self.jarroh,
            scheduled_time=timezone.now())

    def test_operatsiyasiz_blok_korinmaydi(self):
        html = self.client.get(self.url).content.decode()
        self.assertNotIn('name="selected_surgeries"', html)

    def test_operatsiya_bolsa_royxatda_chiqadi(self):
        self._operatsiya()
        html = self.client.get(self.url).content.decode()
        self.assertIn('name="selected_surgeries"', html)
        self.assertIn("Appendektomiya", html)

    def test_bekor_qilingan_operatsiya_chiqmaydi(self):
        sx = self._operatsiya()
        sx.status = "cancelled"
        sx.save(update_fields=["status"])
        self.assertNotIn('name="selected_surgeries"',
                         self.client.get(self.url).content.decode())

    def test_tanlangani_saqlanadi(self):
        sx = self._operatsiya()
        self.client.post(self.url, {
            "action": "hold",
            "selected_surgeries": [str(sx.pk)],
        })
        s = DischargeSummary.objects.get(episode=self.episode)
        self.assertEqual(s.selected_surgery_ids, [str(sx.pk)])

    def test_belgilanmagan_operatsiya_chop_etishga_tushmaydi(self):
        sx = self._operatsiya()
        self.client.post(self.url, {"action": "finalize"})  # hech biri tanlanmagan
        s = DischargeSummary.objects.get(episode=self.episode)
        self.assertEqual(s.selected_surgery_ids, [])

        html = self.client.get(
            reverse("clinical:discharge_print",
                    args=[self.episode.pk])).content.decode()
        self.assertNotIn("Bajarilgan operatsiyalar", html)

    def test_tanlangani_chop_etishda_chiqadi(self):
        sx = self._operatsiya()
        self.client.post(self.url, {
            "action": "finalize",
            "selected_surgeries": [str(sx.pk)],
        })
        html = self.client.get(
            reverse("clinical:discharge_print",
                    args=[self.episode.pk])).content.decode()
        self.assertIn("Bajarilgan operatsiyalar", html)
        self.assertIn("Appendektomiya", html)
