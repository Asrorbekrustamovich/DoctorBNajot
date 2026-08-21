"""Statsionar hisobotlari: javob berilgach shu yotish ham chiqsin.

Nega bu testlar bor
-------------------
«Statsionar hisobotlari» ro'yxati joriy epizodni HAR DOIM chetlab
o'tardi — «o'zidan nusxa olishning ma'nosi yo'q» degan mantiq bilan.

Bemor palatada yotganda bu to'g'ri: yotish tugamagan, hisobot ham yo'q.
Lekin javob berilgach hisobot to'liq bo'ladi — muolajalar, ukollar,
dorilar, tekshiruv natijalari. Shifokor vipiskani aynan shulardan
yig'adi. Chetlab o'tilgani uchun ro'yxat bo'sh chiqar va «Bu bemor
ilgari statsionarda yotmagan» deb yozardi — bemor endigina chiqib
ketgan bo'lsa ham.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.episode_views import _past_episode_reports
from apps.clinical.models import (
    AdmissionEpisode, Bed, InpatientStay, ProcedureRecord, Room, Visit,
)
from apps.patients.models import Patient


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class CurrentStayReportTest(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc_rep", password="x",
            role=rol(Role.Code.THERAPIST, "Terapevt"))
        self.patient = Patient.objects.create(
            first_name="Asror", last_name="Azatbayev",
            birth_date="2004-01-01", gender="male",
            birth_certificate="MB-5050505")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=1,
            status=Visit.Status.IN_PROGRESS)

        xona = Room.objects.create(name="2xona")
        self.stay = InpatientStay.objects.create(
            visit=self.visit,
            bed=Bed.objects.create(room=xona, number="2A"),
            admission_date=timezone.now())
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doctor,
            status=AdmissionEpisode.Status.ADMITTED, stay=self.stay,
            reason="Yonbosh og'rig'i")

        ProcedureRecord.objects.create(
            stay=self.stay, name="Ampitsilin", nurse=self.doctor,
            category=ProcedureRecord.Category.PROCEDURE,
            performed_at=timezone.now(), notes="bir ampula")

    def _javob_ber(self):
        self.stay.status = InpatientStay.Status.DISCHARGED
        self.stay.discharge_date = timezone.now()
        self.stay.save(update_fields=["status", "discharge_date"])

    # ---------- ro'yxat ----------

    def test_yotayotganda_royxat_bosh(self):
        """Yotish tugamagan — hisobot ham yo'q."""
        self.assertEqual(_past_episode_reports(self.episode), [])

    def test_javob_berilgach_royxatda_chiqadi(self):
        self._javob_ber()
        r = _past_episode_reports(
            AdmissionEpisode.objects.get(pk=self.episode.pk))
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["joriy"])

    def test_muolajalar_hisobotga_tushadi(self):
        self._javob_ber()
        r = _past_episode_reports(
            AdmissionEpisode.objects.get(pk=self.episode.pk))
        matnlar = dict(r[0]["bloklar"])
        self.assertIn("Muolajalar va ukollar", matnlar)
        self.assertIn("Ampitsilin", matnlar["Muolajalar va ukollar"])

    def test_korik_matni_ham_bor(self):
        self._javob_ber()
        r = _past_episode_reports(
            AdmissionEpisode.objects.get(pk=self.episode.pk))
        matnlar = dict(r[0]["bloklar"])
        self.assertEqual(matnlar.get("Murojaat sababi"), "Yonbosh og'rig'i")

    def test_ikki_marta_chiqmaydi(self):
        """Epizod ham, yotish ham bitta satr bo'lsin."""
        self._javob_ber()
        r = _past_episode_reports(
            AdmissionEpisode.objects.get(pk=self.episode.pk))
        self.assertEqual(len(r), 1)

    def test_bekor_qilingan_epizod_chiqmaydi(self):
        self._javob_ber()
        self.episode.status = AdmissionEpisode.Status.CANCELLED
        self.episode.save(update_fields=["status"])
        self.assertEqual(
            _past_episode_reports(
                AdmissionEpisode.objects.get(pk=self.episode.pk)), [])

    # ---------- ekran ----------

    def _sahifa(self):
        self.client.force_login(self.doctor)
        return self.client.get(
            reverse("clinical:episode_detail",
                    args=[self.episode.pk])).content.decode()

    def test_yotmagan_degan_yozuv_yoq(self):
        self._javob_ber()
        html = self._sahifa()
        self.assertNotIn("ilgari statsionarda yotmagan", html)
        self.assertIn("Shu yotish", html)

    def test_yotayotganda_tushunarli_yozuv(self):
        html = self._sahifa()
        self.assertIn("hozir yotibdi", html)
        self.assertNotIn("ilgari statsionarda yotmagan", html)
