"""Patients moduli unit testlari."""
from __future__ import annotations

import datetime

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Role
from apps.accounts.services import seed_default_roles, user_create
from apps.core.exceptions import DomainError
from apps.patients.models import Patient
from apps.patients.selectors import find_duplicates, patient_list
from apps.patients.services import patient_create, patient_delete, patient_update

STRONG_PASSWORD = "Xk9#mPl2$vQz"


def make_patient(**overrides) -> Patient:
    data = dict(
        last_name="Karimov", first_name="Aziz", birth_date=datetime.date(1990, 5, 20),
        gender=Patient.Gender.MALE, phone="+998901234567",
        jshshir="12345678901234", passport="AA1234567",
    )
    data.update(overrides)
    return patient_create(**data)


class PatientServiceTests(TestCase):
    def test_create_assigns_sequential_card_number(self) -> None:
        p1 = make_patient()
        p2 = make_patient(
            last_name="Aliyeva", first_name="Nilufar", gender=Patient.Gender.FEMALE,
            jshshir="98765432109876", passport="AB7654321", phone="+998907654321",
            birth_date=datetime.date(1985, 3, 10),
        )
        self.assertEqual(p1.card_number, "P-000001")
        self.assertEqual(p2.card_number, "P-000002")

    def test_duplicate_jshshir_rejected(self) -> None:
        make_patient()
        with self.assertRaises(DomainError) as ctx:
            make_patient(passport="AC1111111", phone="+998900000000")
        self.assertEqual(ctx.exception.code, "patient_exists")

    def test_suspected_duplicate_requires_confirmation(self) -> None:
        make_patient()
        # Bir xil FIO+tug'ilgan sana, boshqa hujjatlar
        with self.assertRaises(DomainError) as ctx:
            patient_create(
                last_name="Karimov", first_name="Aziz",
                birth_date=datetime.date(1990, 5, 20), gender=Patient.Gender.MALE,
            )
        self.assertEqual(ctx.exception.code, "duplicate_suspected")
        # allow_duplicate bilan o'tadi
        p = patient_create(
            last_name="Karimov", first_name="Aziz",
            birth_date=datetime.date(1990, 5, 20), gender=Patient.Gender.MALE,
            allow_duplicate=True,
        )
        self.assertTrue(p.card_number)

    def test_empty_documents_do_not_conflict(self) -> None:
        # JSHSHIR/pasportsiz ikki bemor (None unique'ga tegmaydi)
        patient_create(last_name="A", first_name="B", birth_date=datetime.date(2000, 1, 1),
                       gender=Patient.Gender.MALE)
        patient_create(last_name="C", first_name="D", birth_date=datetime.date(2001, 2, 2),
                       gender=Patient.Gender.FEMALE)
        self.assertEqual(Patient.objects.count(), 2)

    def test_update_and_audit(self) -> None:
        from apps.audit.models import AuditLog

        patient = make_patient()
        patient_update(patient=patient, phone="+998911119999")
        patient.refresh_from_db()
        self.assertEqual(patient.phone, "+998911119999")
        self.assertTrue(
            AuditLog.objects.filter(
                model_name="patients.patient", object_id=str(patient.pk),
                action=AuditLog.Action.UPDATE,
            ).exists()
        )

    def test_delete_is_soft(self) -> None:
        patient = make_patient()
        patient_delete(patient=patient)
        self.assertFalse(Patient.objects.filter(pk=patient.pk).exists())
        self.assertTrue(Patient.all_objects.filter(pk=patient.pk).exists())

    def test_age_calculation(self) -> None:
        from django.utils import timezone

        today = timezone.localdate()
        patient = make_patient(birth_date=today.replace(year=today.year - 30))
        self.assertEqual(patient.age, 30)

    def test_search_selector(self) -> None:
        make_patient()
        self.assertEqual(patient_list(search="Karimov").count(), 1)
        self.assertEqual(patient_list(search="P-000001").count(), 1)
        self.assertEqual(patient_list(search="yo'q-odam").count(), 0)

    def test_find_duplicates_by_phone_and_lastname(self) -> None:
        make_patient()
        dups = find_duplicates(
            jshshir=None, passport=None, phone="+998901234567",
            last_name="Karimov", first_name="Boshqa",
            birth_date=datetime.date(1999, 1, 1),
        )
        self.assertEqual(dups.count(), 1)


class PatientAPITests(TestCase):
    def setUp(self) -> None:
        seed_default_roles()
        self.client = APIClient()

    def _login_as(self, role_code: str) -> None:
        user = user_create(
            username=f"u_{role_code}", password=STRONG_PASSWORD,
            role=Role.objects.get(code=role_code),
        )
        self.client.force_authenticate(user)

    def test_reception_can_create_patient(self) -> None:
        self._login_as("reception")
        response = self.client.post("/api/v1/patients/", {
            "last_name": "Tosheva", "first_name": "Madina",
            "birth_date": "1995-07-15", "gender": "female",
            "phone": "+998935554433",
        })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["card_number"], "P-000001")

    def test_viewer_cannot_create_but_can_read(self) -> None:
        make_patient()
        self._login_as("viewer")
        self.assertEqual(self.client.get("/api/v1/patients/").status_code, 200)
        response = self.client.post("/api/v1/patients/", {
            "last_name": "X", "first_name": "Y",
            "birth_date": "1990-01-01", "gender": "male",
        })
        self.assertEqual(response.status_code, 403)

    def test_doctor_can_read_patients(self) -> None:
        make_patient()
        self._login_as("doctor")
        response = self.client.get("/api/v1/patients/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)

    def test_duplicate_returns_400_with_code(self) -> None:
        make_patient()
        self._login_as("reception")
        response = self.client.post("/api/v1/patients/", {
            "last_name": "Karimov", "first_name": "Aziz",
            "birth_date": "1990-05-20", "gender": "male",
        })
        self.assertEqual(response.status_code, 400)
