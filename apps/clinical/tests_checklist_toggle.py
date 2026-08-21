"""Statsionar ro'yxatida belgilash (ptechka) ishlashi.

Nega bu testlar bor
-------------------
`stay_checklist_toggle` da chekinish buzilib ketgan edi va bu ikki xato
tug'dirgan:

1. Qulf tekshiruvi `else` dan tashqarida turardi — «tekshiruv» va
   «operatsiya» tarmoqlarida ham ishga tushardi. U yerda `item` degan
   o'zgaruvchi umuman yo'q: NameError va oq ekran.

2. Belgilash satrlari `return` dan keyin yozilgan edi, ya'ni hech
   qachon bajarilmasdi. Hamshira ptechkani bosadi, sahifa yangilanadi,
   belgi esa o'zgarmaydi — va hech qanday xato chiqmaydi.
"""
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    Bed, InpatientStay, Room, StayChecklistItem, SurgerySchedule,
    SurgeryType, Visit,
)
from apps.patients.models import Patient


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class ChecklistToggleTest(TestCase):
    def setUp(self):
        self.hamshira = User.objects.create_user(
            username="tog_nurse", password="x",
            role=rol(Role.Code.WARD_NURSE, "Palata hamshirasi"))
        self.doctor = User.objects.create_user(
            username="tog_doc", password="x",
            role=rol(Role.Code.THERAPIST, "Terapevt"))

        bemor = Patient.objects.create(
            first_name="Nur", last_name="Nurov", birth_date="1990-01-01",
            gender="male", birth_certificate="MB-6161616")
        self.visit = Visit.objects.create(
            patient=bemor, doctor=self.doctor, visit_date=timezone.now(),
            queue_number=1, status=Visit.Status.IN_PROGRESS)
        xona = Room.objects.create(name="Sinov")
        self.stay = InpatientStay.objects.create(
            visit=self.visit, bed=Bed.objects.create(room=xona, number="1A"),
            admission_date=timezone.now())

        self.item = StayChecklistItem.objects.create(
            stay=self.stay, title="Tomir yo'li ochildi",
            category=StayChecklistItem.Category.PROCEDURE)

        self.client.force_login(self.hamshira)

    def _url(self, pk):
        return reverse("clinical:stay_checklist_toggle", args=[pk])

    # ---------- oddiy ptechka ----------

    def test_belgilash_saqlanadi(self):
        self.client.post(self._url(self.item.pk), {"type": "checklist"})
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_done)
        self.assertEqual(self.item.done_by, self.hamshira)
        self.assertIsNotNone(self.item.done_at)

    def test_qayta_bosilsa_belgi_olinadi(self):
        self.client.post(self._url(self.item.pk), {"type": "checklist"})
        self.client.post(self._url(self.item.pk), {"type": "checklist"})
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_done)
        self.assertIsNone(self.item.done_at)

    def test_turi_korsatilmasa_ham_ishlaydi(self):
        """Standart qiymat — `checklist`."""
        self.client.post(self._url(self.item.pk))
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_done)

    # ---------- operatsiya ptechkasi ----------

    def test_operatsiya_belgilanganda_yiqilmaydi(self):
        surgery = SurgerySchedule.objects.create(
            visit=self.visit, surgeon=self.doctor,
            scheduled_time=timezone.now(),
            surgery_type=SurgeryType.objects.create(name="Sinov", price=1))
        r = self.client.post(self._url(surgery.pk), {"type": "surgery"})
        self.assertLess(r.status_code, 500)
        surgery.refresh_from_db()
        self.assertEqual(surgery.status, SurgerySchedule.Status.COMPLETED)

    # ---------- qulf ----------

    def test_imzolangan_hujjat_qulflangan(self):
        self.stay.patient_signature = "data:image/png;base64,xxx"
        self.stay.save(update_fields=["patient_signature"])

        self.client.post(self._url(self.item.pk), {"type": "checklist"})
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_done,
                         "Qulflangan hujjatda belgi o'zgardi.")

    # ---------- metod ----------

    def test_get_bilan_ozgartirib_bolmaydi(self):
        r = self.client.get(self._url(self.item.pk))
        self.assertEqual(r.status_code, 405)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_done)
