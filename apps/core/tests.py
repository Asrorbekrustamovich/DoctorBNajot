"""Core moduli testlari: soft delete, BaseModel, healthcheck."""
from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import Role
from apps.accounts.services import seed_default_roles


class SoftDeleteTests(TestCase):
    """Role (BaseModel meros oluvchi) misolida soft delete xatti-harakati."""

    def setUp(self) -> None:
        seed_default_roles()

    def test_delete_is_soft(self) -> None:
        role = Role.objects.get(code="viewer")
        role.delete()
        self.assertFalse(Role.objects.filter(code="viewer").exists())
        self.assertTrue(Role.all_objects.filter(code="viewer").exists())
        deleted = Role.all_objects.get(code="viewer")
        self.assertTrue(deleted.is_deleted)
        self.assertIsNotNone(deleted.deleted_at)

    def test_restore(self) -> None:
        role = Role.objects.get(code="viewer")
        role.delete()
        deleted = Role.all_objects.get(code="viewer")
        deleted.restore()
        self.assertTrue(Role.objects.filter(code="viewer").exists())

    def test_queryset_delete_is_soft(self) -> None:
        Role.objects.filter(code="viewer").delete()
        self.assertTrue(Role.all_objects.filter(code="viewer", is_deleted=True).exists())

    def test_uuid_primary_key(self) -> None:
        import uuid

        role = Role.objects.get(code="doctor")
        self.assertIsInstance(role.pk, uuid.UUID)


class HealthCheckTests(TestCase):
    def test_healthz_returns_ok(self) -> None:
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["database"])


# ==========================================================================
#  TO'LIQ TOZALASH buyrug'i — o'chirilmasligi kerak narsalar o'chib ketmasin
# ==========================================================================

class ClearAllDataTests(TestCase):
    """`clear_all_data` bemorlarni o'chirib, sozlamalarni saqlashi kerak."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date
        from decimal import Decimal
        from apps.accounts.models import Role, User
        from apps.clinical.models import (
            AnesthesiaStock, Consultation, OperatingRoom, Room, ServiceCatalog,
            ServiceOrder, SurgeryType, SurgicalItem, SurgicalItemHistory,
        )
        from apps.patients.models import Patient
        from apps.pharmacy.models import MeasurementUnit, Medicine
        from apps.registration.models import Visit

        cls.rol = Role.objects.get_or_create(
            code=Role.Code.DOCTOR, defaults={"name": "Shifokor"})[0]
        cls.doctor = User.objects.create_user(
            username="shifokor_t", password="x", first_name="Test",
            last_name="Shifokorov", role=cls.rol,
        )
        # --- Saqlanishi kerak ---
        cls.xizmat = ServiceCatalog.objects.create(name="UZI — Test", price=50000)
        cls.palata = Room.objects.create(name="101")
        cls.op_xona = OperatingRoom.objects.create(name="Op-1")
        cls.op_turi = SurgeryType.objects.create(name="Test operatsiya", price=100)
        cls.anjom = SurgicalItem.objects.create(
            name="Test nabor", item_type=SurgicalItem.Type.NABOR,
            status=SurgicalItem.Status.USED, current_room=cls.op_xona,
        )
        cls.birlik = MeasurementUnit.objects.create(name="dona", short_name="dona")

        # --- O'chishi kerak ---
        cls.bemor = Patient.objects.create(
            last_name="Testov", first_name="Test",
            birth_date=date(1990, 1, 1), gender=Patient.Gender.MALE,
        )
        cls.visit = Visit.objects.create(
            patient=cls.bemor, visit_date=date(2026, 8, 1), queue_number=1,
        )
        Consultation.objects.create(visit=cls.visit, doctor=cls.doctor)
        ServiceOrder.objects.create(visit=cls.visit, service=cls.xizmat)
        SurgicalItemHistory.objects.create(item=cls.anjom, action="Test")
        Medicine.objects.create(name="Analgin", unit=cls.birlik)
        AnesthesiaStock.objects.create(name="Propofol", quantity=Decimal("10"))

    def _run(self, *args):
        from io import StringIO
        from django.core.management import call_command
        out = StringIO()
        call_command("clear_all_data", "--yes", "--no-backup", *args, stdout=out)
        return out.getvalue()

    def test_dry_run_changes_nothing(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.patients.models import Patient
        call_command("clear_all_data", "--dry-run", stdout=StringIO())
        self.assertEqual(Patient.all_objects.count(), 1)

    def test_patient_data_is_removed(self):
        from apps.billing.models import Invoice
        from apps.clinical.models import Consultation, ServiceOrder, SurgicalItemHistory
        from apps.patients.models import Patient
        from apps.registration.models import Visit
        self._run()
        for model in (Patient, Visit, Consultation, ServiceOrder,
                      SurgicalItemHistory, Invoice):
            self.assertEqual(model.all_objects.count(), 0,
                             f"{model.__name__} o'chmadi")

    def test_pharmacy_and_anesthesia_stock_removed(self):
        from apps.clinical.models import AnesthesiaStock
        from apps.pharmacy.models import Medicine
        self._run()
        self.assertEqual(Medicine.all_objects.count(), 0, "Dorilar o'chmadi")
        self.assertEqual(AnesthesiaStock.all_objects.count(), 0,
                         "Anesteziolog ombori o'chmadi")

    def test_settings_are_kept(self):
        """Eng muhimi: sozlamalar o'chib ketmasligi kerak."""
        from apps.accounts.models import Role, User
        from apps.clinical.models import (
            OperatingRoom, Room, ServiceCatalog, SurgeryType, SurgicalItem,
        )
        from apps.pharmacy.models import MeasurementUnit
        self._run()
        self.assertEqual(User.objects.count(), 1, "Xodimlar o'chib ketdi!")
        self.assertTrue(Role.objects.exists(), "Rollar o'chib ketdi!")
        self.assertEqual(ServiceCatalog.objects.count(), 1, "Xizmatlar katalogi o'chdi!")
        self.assertEqual(Room.objects.count(), 1, "Palatalar o'chdi!")
        self.assertEqual(OperatingRoom.objects.count(), 1, "Operatsion xonalar o'chdi!")
        self.assertEqual(SurgeryType.objects.count(), 1, "Operatsiya turlari o'chdi!")
        self.assertEqual(SurgicalItem.objects.count(), 1, "Jarrohlik anjomlari o'chdi!")
        self.assertEqual(MeasurementUnit.objects.count(), 1, "O'lchov birliklari o'chdi!")

    def test_instruments_reset_to_ready(self):
        from apps.clinical.models import SurgicalItem
        self._run()
        self.anjom.refresh_from_db()
        self.assertEqual(self.anjom.status, SurgicalItem.Status.READY)
        self.assertIsNone(self.anjom.current_room)

    def test_with_storage_flag_removes_units(self):
        from apps.pharmacy.models import MeasurementUnit
        self._run("--with-storage")
        self.assertEqual(MeasurementUnit.objects.count(), 0)

    def test_second_run_is_safe(self):
        """Ikkinchi marta ishga tushirilsa xato bermasligi kerak."""
        self._run()
        chiqish = self._run()
        self.assertIn("toza", chiqish.lower())
