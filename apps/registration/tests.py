"""Registration moduli unit testlari."""
from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.accounts.services import seed_default_roles, user_create
from apps.core.exceptions import DomainError, InvalidTransitionError
from apps.patients.models import Patient
from apps.patients.services import patient_create
from apps.registration.models import Appointment, Visit
from apps.registration.services import (
    appointment_create,
    visit_create,
    visit_from_appointment,
    visit_transition,
)

STRONG_PASSWORD = "Xk9#mPl2$vQz"


class RegistrationTestBase(TestCase):
    def setUp(self) -> None:
        seed_default_roles()
        self.doctor = user_create(
            username="doc", password=STRONG_PASSWORD,
            role=Role.objects.get(code="doctor"),
            first_name="Olim", last_name="Sattorov",
        )
        # Registraturada bemor faqat AMBULATOR shifokorga yozdiriladi.
        # Bu bayroqsiz shifokor ro'yxatga tushmaydi va API «bunday
        # shifokor yo'q» deb 400 qaytaradi.
        self.doctor.is_ambulatory = True
        self.doctor.save(update_fields=["is_ambulatory"])
        self.patient = patient_create(
            last_name="Karimov", first_name="Aziz",
            birth_date=datetime.date(1990, 5, 20), gender=Patient.Gender.MALE,
            phone="+998901234567",
        )
        self.patient2 = patient_create(
            last_name="Aliyeva", first_name="Nilufar",
            birth_date=datetime.date(1985, 3, 10), gender=Patient.Gender.FEMALE,
            phone="+998907654321",
        )


class VisitServiceTests(RegistrationTestBase):
    def test_queue_number_increments_per_day(self) -> None:
        v1 = visit_create(patient=self.patient, doctor=self.doctor)
        v2 = visit_create(patient=self.patient2, doctor=self.doctor)
        self.assertEqual(v1.queue_number, 1)
        self.assertEqual(v2.queue_number, 2)
        self.assertEqual(v1.status, Visit.Status.WAITING)

    def test_duplicate_open_visit_rejected(self) -> None:
        visit_create(patient=self.patient)
        with self.assertRaises(DomainError) as ctx:
            visit_create(patient=self.patient)
        self.assertEqual(ctx.exception.code, "visit_already_open")

    def test_full_status_flow(self) -> None:
        visit = visit_create(patient=self.patient, doctor=self.doctor)
        visit = visit_transition(visit=visit, new_status=Visit.Status.ACCEPTED)
        self.assertIsNotNone(visit.accepted_at)
        visit = visit_transition(visit=visit, new_status=Visit.Status.IN_PROGRESS)
        visit = visit_transition(visit=visit, new_status=Visit.Status.COMPLETED)
        self.assertIsNotNone(visit.completed_at)
        visit = visit_transition(visit=visit, new_status=Visit.Status.ARCHIVED)
        self.assertEqual(visit.status, Visit.Status.ARCHIVED)

    def test_invalid_transition_rejected(self) -> None:
        visit = visit_create(patient=self.patient)
        with self.assertRaises(InvalidTransitionError):
            visit_transition(visit=visit, new_status=Visit.Status.COMPLETED)

    def test_cancel_stores_reason(self) -> None:
        visit = visit_create(patient=self.patient)
        visit = visit_transition(
            visit=visit, new_status=Visit.Status.CANCELLED, reason="Bemor ketib qoldi"
        )
        self.assertEqual(visit.cancel_reason, "Bemor ketib qoldi")

    def test_archived_is_terminal(self) -> None:
        visit = visit_create(patient=self.patient)
        visit_transition(visit=visit, new_status=Visit.Status.CANCELLED)
        visit_transition(visit=visit, new_status=Visit.Status.ARCHIVED)
        with self.assertRaises(InvalidTransitionError):
            visit_transition(visit=visit, new_status=Visit.Status.WAITING)


class AppointmentServiceTests(RegistrationTestBase):
    def _tomorrow_at(self, hour: int, minute: int = 0) -> datetime.datetime:
        tomorrow = timezone.localdate() + datetime.timedelta(days=1)
        return timezone.make_aware(
            datetime.datetime.combine(tomorrow, datetime.time(hour, minute))
        )

    def test_appointment_create(self) -> None:
        appt = appointment_create(
            patient=self.patient, doctor=self.doctor,
            scheduled_at=self._tomorrow_at(10), duration_minutes=30,
        )
        self.assertEqual(appt.status, Appointment.Status.SCHEDULED)

    def test_past_datetime_rejected(self) -> None:
        with self.assertRaises(DomainError) as ctx:
            appointment_create(
                patient=self.patient, doctor=self.doctor,
                scheduled_at=timezone.now() - datetime.timedelta(hours=1),
            )
        self.assertEqual(ctx.exception.code, "past_datetime")

    def test_non_doctor_rejected(self) -> None:
        cashier = user_create(
            username="kassir", password=STRONG_PASSWORD,
            role=Role.objects.get(code="cashier"),
        )
        with self.assertRaises(DomainError) as ctx:
            appointment_create(
                patient=self.patient, doctor=cashier,
                scheduled_at=self._tomorrow_at(11),
            )
        self.assertEqual(ctx.exception.code, "not_a_doctor")

    def test_overlapping_slot_rejected(self) -> None:
        appointment_create(
            patient=self.patient, doctor=self.doctor,
            scheduled_at=self._tomorrow_at(10), duration_minutes=30,
        )
        with self.assertRaises(DomainError) as ctx:
            appointment_create(
                patient=self.patient2, doctor=self.doctor,
                scheduled_at=self._tomorrow_at(10, 15), duration_minutes=30,
            )
        self.assertEqual(ctx.exception.code, "slot_taken")

    def test_adjacent_slot_allowed(self) -> None:
        appointment_create(
            patient=self.patient, doctor=self.doctor,
            scheduled_at=self._tomorrow_at(10), duration_minutes=30,
        )
        appt2 = appointment_create(
            patient=self.patient2, doctor=self.doctor,
            scheduled_at=self._tomorrow_at(10, 30), duration_minutes=30,
        )
        self.assertIsNotNone(appt2.pk)

    def test_visit_from_appointment(self) -> None:
        appt = appointment_create(
            patient=self.patient, doctor=self.doctor,
            scheduled_at=self._tomorrow_at(9), reason="Bosh og'rig'i",
        )
        visit = visit_from_appointment(appointment=appt)
        appt.refresh_from_db()
        self.assertEqual(appt.status, Appointment.Status.ARRIVED)
        self.assertEqual(visit.patient, self.patient)
        self.assertEqual(visit.appointment, appt)
        self.assertEqual(visit.complaint, "Bosh og'rig'i")
        # Ikkinchi marta ochib bo'lmaydi
        with self.assertRaises(InvalidTransitionError):
            visit_from_appointment(appointment=appt)


class RegistrationAPITests(RegistrationTestBase):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        self.reception = user_create(
            username="reg1", password=STRONG_PASSWORD,
            role=Role.objects.get(code="reception"),
        )

    def test_reception_creates_visit_via_api(self) -> None:
        self.client.force_authenticate(self.reception)
        response = self.client.post("/api/v1/visits/", {
            "patient_id": str(self.patient.pk),
            "doctor_id": str(self.doctor.pk),
            "complaint": "Isitma",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["queue_number"], 1)
        self.assertEqual(response.data["status"], "waiting")

    def test_transition_via_api(self) -> None:
        visit = visit_create(patient=self.patient)
        self.client.force_authenticate(self.reception)
        response = self.client.post(
            f"/api/v1/visits/{visit.pk}/transition/", {"status": "accepted"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["status"], "accepted")

    def test_invalid_transition_returns_400(self) -> None:
        visit = visit_create(patient=self.patient)
        self.client.force_authenticate(self.reception)
        response = self.client.post(
            f"/api/v1/visits/{visit.pk}/transition/", {"status": "completed"}
        )
        self.assertEqual(response.status_code, 400)

    def test_viewer_cannot_create_visit(self) -> None:
        viewer = user_create(
            username="v1", password=STRONG_PASSWORD,
            role=Role.objects.get(code="viewer"),
        )
        self.client.force_authenticate(viewer)
        response = self.client.post("/api/v1/visits/", {
            "patient_id": str(self.patient.pk),
        })
        self.assertEqual(response.status_code, 403)

    def test_today_endpoint(self) -> None:
        visit_create(patient=self.patient)
        self.client.force_authenticate(self.reception)
        response = self.client.get("/api/v1/visits/today/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
