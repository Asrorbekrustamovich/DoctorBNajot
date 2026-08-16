"""Vipiska tasodifan qulflanmasin.

Nega bu testlar bor
-------------------
Vipiska — bemor qo'liga beriladigan rasmiy hujjat. Shakllantirilgach
qulflanadi va keyin faqat superadmin ocha oladi.

Ilgari `action` maydoni bo'lmagan HAR QANDAY yuborish uni qulflardi:
matn maydonida Enter bosilsa ham, forma boshqa yo'l bilan yuborilib
qolsa ham. Shifokor rasmiy ko'rinishni ochib, keyin epizodga qaytganida
vipiska allaqachon shakllangan bo'lib chiqardi.

Endi qulflash faqat aniq so'ralganda bo'ladi; qolgan hamma holatda
matn saqlanadi, lekin hujjat ochiq qoladi.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import AdmissionEpisode, DischargeSummary, Visit
from apps.patients.models import Patient


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class VipiskaLockTest(TestCase):
    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc_lock", password="x",
            role=rol(Role.Code.DOCTOR, "Shifokor"))
        patient = Patient.objects.create(
            first_name="Ali", last_name="Aliyev", birth_date="1990-01-01",
            gender="male", birth_certificate="MB-7070707")
        visit = Visit.objects.create(
            patient=patient, doctor=self.doctor, visit_date=timezone.now(),
            queue_number=1, status=Visit.Status.IN_PROGRESS)
        self.episode = AdmissionEpisode.objects.create(
            patient=patient, visit=visit, referred_by=self.doctor,
            status=AdmissionEpisode.Status.ADMITTED)
        self.url = reverse("clinical:episode_discharge", args=[self.episode.pk])
        self.client.force_login(self.doctor)

    def _summary(self):
        return DischargeSummary.objects.get(episode=self.episode)

    def _epizod(self):
        return AdmissionEpisode.objects.get(pk=self.episode.pk)

    # ---------- tasodifiy yuborish ----------

    def test_actionsiz_yuborish_qulflamaydi(self):
        """Enter bosilib forma ketib qolsa ham hujjat ochiq qolsin."""
        self.client.post(self.url, {"recommendations": "yarim yozilgan"})
        self.assertFalse(self._summary().is_locked)
        self.assertEqual(self._epizod().status,
                         AdmissionEpisode.Status.ADMITTED)

    def test_actionsiz_yuborishda_matn_saqlanadi(self):
        """Qulflamaslik — yozilganini tashlab yuborish degani emas."""
        self.client.post(self.url, {"recommendations": "yarim yozilgan"})
        self.assertEqual(self._summary().recommendations, "yarim yozilgan")

    def test_notogri_action_ham_qulflamaydi(self):
        self.client.post(self.url, {"action": "allaqanday"})
        self.assertFalse(self._summary().is_locked)

    # ---------- rasmiy ko'rinish va qaytish ----------

    def test_rasmiy_korinish_qulflamaydi(self):
        self.client.post(self.url, {"action": "hold"})
        self.client.get(
            reverse("clinical:discharge_print", args=[self.episode.pk]))
        self.assertFalse(self._summary().is_locked)
        self.assertEqual(self._epizod().status,
                         AdmissionEpisode.Status.ADMITTED)

    def test_epizodga_qaytish_qulflamaydi(self):
        self.client.post(self.url, {"action": "hold"})
        self.client.get(
            reverse("clinical:discharge_print", args=[self.episode.pk]))
        self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))
        self.assertFalse(self._summary().is_locked)
        self.assertEqual(self._epizod().status,
                         AdmissionEpisode.Status.ADMITTED)

    def test_qaytish_havolasi_oddiy_link(self):
        """Qaytish tugmasi forma yubormasin — oddiy havola bo'lsin."""
        self.client.post(self.url, {"action": "hold"})
        html = self.client.get(
            reverse("clinical:discharge_print",
                    args=[self.episode.pk])).content.decode()
        qaytish = reverse("clinical:episode_detail", args=[self.episode.pk])
        self.assertIn(f'href="{qaytish}"', html)
        self.assertNotIn("<form", html)

    # ---------- ataylab qulflash ----------

    def test_finalize_qulflaydi(self):
        self.client.post(self.url, {"action": "finalize"})
        self.assertTrue(self._summary().is_locked)
        self.assertEqual(self._epizod().status,
                         AdmissionEpisode.Status.DISCHARGED)

    def test_finalize_tugmasi_tasdiq_soraydi(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("confirm(", html)
        self.assertIn('value="finalize"', html)
