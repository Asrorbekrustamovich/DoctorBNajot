"""Sterilizatsiya (avtoklav) anjomlari — regression testlar.

Har bir test tuzatilgan aniq bugni qamrab oladi: tuzatishdan OLDIN yiqiladi,
tuzatishdan KEYIN o'tadi.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    OperatingRoom, SurgerySchedule, SurgeryType, SurgicalItem,
    SurgicalItemHistory,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


def _role(code, name=None):
    return Role.objects.get_or_create(code=code, defaults={"name": name or code})[0]


class SterilizationTestBase(TestCase):
    """Bitta bemor + bitta jarroh + bitta operatsiya bilan umumiy tayyorgarlik."""

    @classmethod
    def setUpTestData(cls):
        cls.surgeon = User.objects.create_user(
            username="jarroh", password="x", first_name="Alisher",
            last_name="Jarrohov", role=_role(Role.Code.SURGEON, "Jarroh"),
        )
        cls.nurse = User.objects.create_user(
            username="hamshira", password="x", first_name="Nodira",
            last_name="Hamshirayeva",
            role=_role(Role.Code.NURSE, "Hamshira"),
        )
        cls.steril = User.objects.create_user(
            username="avtoklav", password="x", first_name="Bekzod",
            last_name="Sterilov",
            role=_role(Role.Code.STERILIZATION, "Sterilizatsiya"),
        )
        cls.patient = Patient.objects.create(
            last_name="Rustamov", first_name="Asror", middle_name="Rustamovich",
            birth_date=date(1990, 5, 1), gender=Patient.Gender.MALE,
        )
        cls.visit = Visit.objects.create(
            patient=cls.patient, visit_date=date(2026, 7, 1), queue_number=1,
        )
        cls.room = OperatingRoom.objects.create(name="1-operatsion")
        cls.stype = SurgeryType.objects.create(name="Appendektomiya", price=100)
        cls.surgery = SurgerySchedule.objects.create(
            visit=cls.visit, surgery_type=cls.stype, surgeon=cls.surgeon,
            operating_room=cls.room, operating_nurse=cls.nurse,
            scheduled_time=timezone.now(),
        )

    def make_item(self, name="Nabor-1", item_type=SurgicalItem.Type.NABOR,
                  status=SurgicalItem.Status.READY, **kw):
        return SurgicalItem.objects.create(
            name=name, item_type=item_type, status=status, **kw
        )


class ItemHistoryContextTests(SterilizationTestBase):
    """Tarix yozuvi KIMGA va KIM boshchiligida ekanini saqlashi kerak."""

    def test_log_fills_patient_and_surgeon(self):
        item = self.make_item()
        h = SurgicalItemHistory.log(
            item, "Operatsiyaga biriktirildi", user=self.nurse, surgery=self.surgery,
        )
        self.assertEqual(h.patient, self.patient)
        self.assertEqual(h.surgeon, self.surgeon)
        self.assertIn("Rustamov", h.patient_snapshot)
        self.assertIn("Jarrohov", h.surgeon_snapshot)
        self.assertEqual(h.surgery_snapshot, "Appendektomiya")
        self.assertEqual(h.room_snapshot, "1-operatsion")
        self.assertEqual(h.changed_by, self.nurse)

    def test_snapshot_survives_surgery_deletion(self):
        """Operatsiya butunlay o'chsa ham epidemiologik iz yo'qolmasligi kerak."""
        item = self.make_item()
        SurgicalItemHistory.log(item, "Ishlatildi", surgery=self.surgery)
        SurgerySchedule.objects.filter(id=self.surgery.id).hard_delete()
        h = item.history.first()
        self.assertIsNone(h.surgery)          # FK SET_NULL bo'ldi
        self.assertIn("Rustamov", h.patient_snapshot)   # matn nusxasi qoldi
        self.assertIn("Jarrohov", h.surgeon_snapshot)

    def test_last_use_returns_latest_surgery_record(self):
        item = self.make_item()
        SurgicalItemHistory.log(item, "Biriktirildi", surgery=self.surgery)
        SurgicalItemHistory.log(item, "Qo'lda o'zgartirildi")  # operatsiyasiz
        self.assertIsNotNone(item.last_use)
        self.assertIn("Rustamov", item.last_use.patient_snapshot)

    def test_log_without_surgery_leaves_context_empty(self):
        item = self.make_item()
        h = SurgicalItemHistory.log(item, "Qo'lda o'zgartirildi", user=self.steril)
        self.assertEqual(h.patient_snapshot, "")
        self.assertFalse(h.has_surgery_context)


class SurgeryFlowLogsHistoryTests(SterilizationTestBase):
    """Operatsiya oqimining har bir qadami tarix yozishi kerak (avval yozmasdi)."""

    def test_preparation_step_logs_attachment(self):
        item = self.make_item("Belyo", SurgicalItem.Type.LINEN)
        self.client.force_login(self.nurse)
        self.client.post(
            reverse("clinical:surgery_step_preparation", args=[self.surgery.id]),
            {"room_prepared": "1", "items": [str(item.id)]},
        )
        item.refresh_from_db()
        self.assertEqual(item.status, SurgicalItem.Status.IN_USE)
        self.assertEqual(item.current_room, self.room)
        h = item.history.first()
        self.assertIsNotNone(h, "Biriktirishda tarix yozuvi yaratilmadi")
        self.assertIn("Rustamov", h.patient_snapshot)
        self.assertIn("Jarrohov", h.surgeon_snapshot)

    def test_finish_operation_logs_usage(self):
        item = self.make_item("Belyo", SurgicalItem.Type.LINEN,
                              status=SurgicalItem.Status.IN_USE)
        self.surgery.items_used.add(item)
        self.surgery.patient_prepared = True
        self.surgery.room_prepared = True
        self.surgery.anesthesia_exam_at = timezone.now()
        self.surgery.save()
        self.surgery.vitals.create(recorded_by=self.nurse, recorded_at=timezone.now())

        self.client.force_login(self.surgeon)
        self.client.post(
            reverse("clinical:surgery_finish_operation", args=[self.surgery.id])
        )
        item.refresh_from_db()
        self.assertEqual(item.status, SurgicalItem.Status.USED)
        h = item.history.filter(action__icontains="ishlatildi").first()
        self.assertIsNotNone(h, "Yakunlashda tarix yozuvi yaratilmadi")
        self.assertIn("Rustamov", h.patient_snapshot)

    def test_mark_unused_removes_from_items_used(self):
        """Ishlatilmagan anjom operatsiya hisobotida ko'rinmasligi kerak."""
        item = self.make_item(status=SurgicalItem.Status.IN_USE)
        self.surgery.items_used.add(item)
        self.client.force_login(self.nurse)
        self.client.post(
            reverse("clinical:surgery_item_mark", args=[item.id]),
            {"surgery_id": str(self.surgery.id), "action": "unused"},
        )
        item.refresh_from_db()
        self.assertEqual(item.status, SurgicalItem.Status.READY)
        self.assertFalse(self.surgery.items_used.filter(id=item.id).exists())
        self.assertTrue(item.history.filter(action__icontains="Ishlatilmadi").exists())


class AutoclaveViewTests(SterilizationTestBase):
    """Avtoklav paneli buglari."""

    def test_cleaning_writes_history(self):
        """Ilgari tozalash umuman tarixga yozilmasdi."""
        item = self.make_item(status=SurgicalItem.Status.USED, current_room=self.room)
        SurgicalItemHistory.log(item, "Bemorga ishlatildi", surgery=self.surgery)
        self.client.force_login(self.steril)
        self.client.post(reverse("clinical:clean_surgical_item", args=[item.id]))
        item.refresh_from_db()
        self.assertEqual(item.status, SurgicalItem.Status.READY)
        self.assertIsNone(item.current_room, "Sterillangan anjom xonada qolib ketdi")
        self.assertTrue(
            item.history.filter(action__icontains="Sterilizatsiyadan").exists(),
            "Tozalash tarixga yozilmadi",
        )

    def test_update_status_ready_clears_room(self):
        item = self.make_item(status=SurgicalItem.Status.USED, current_room=self.room)
        self.client.force_login(self.steril)
        self.client.post(
            reverse("clinical:update_item_status", args=[item.id]), {"status": "ready"}
        )
        item.refresh_from_db()
        self.assertEqual(item.status, SurgicalItem.Status.READY)
        self.assertIsNone(item.current_room)

    def test_cannot_free_item_locked_in_active_surgery(self):
        """Davom etayotgan operatsiyadagi anjomni bo'shatib bo'lmaydi."""
        item = self.make_item(status=SurgicalItem.Status.IN_USE, current_room=self.room)
        self.surgery.status = SurgerySchedule.Status.IN_PROGRESS
        self.surgery.save(update_fields=["status"])
        self.surgery.items_used.add(item)

        self.client.force_login(self.steril)
        self.client.post(
            reverse("clinical:update_item_status", args=[item.id]), {"status": "ready"}
        )
        item.refresh_from_db()
        self.assertEqual(
            item.status, SurgicalItem.Status.IN_USE,
            "Operatsiyada band anjom bo'shatib yuborildi",
        )

    def test_dashboard_separates_dirty_and_ready(self):
        self.make_item("Toza", status=SurgicalItem.Status.READY)
        self.make_item("Iflos", status=SurgicalItem.Status.USED)
        self.client.force_login(self.steril)
        resp = self.client.get(reverse("clinical:autoclave_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([i.name for i in resp.context["dirty_items"]], ["Iflos"])
        self.assertEqual([i.name for i in resp.context["ready_items"]], ["Toza"])


class SterilizationPagesRenderTests(SterilizationTestBase):
    """Sahifalar bemor/jarroh ma'lumotini haqiqatan ham chiqarishi kerak."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin2", password="x", is_superuser=True,
            role=_role(Role.Code.SUPER_ADMIN, "Super admin"),
        )
        self.item = self.make_item("Nabor-A", status=SurgicalItem.Status.USED)
        SurgicalItemHistory.log(
            self.item, "Bemorga ishlatildi", user=self.nurse, surgery=self.surgery,
        )

    def _assert_shows_context(self, url_name):
        resp = self.client.get(reverse(url_name))
        self.assertEqual(resp.status_code, 200, url_name)
        html = resp.content.decode()
        self.assertIn("Rustamov", html, f"{url_name}: bemor ko'rinmadi")
        self.assertIn("Jarrohov", html, f"{url_name}: jarroh ko'rinmadi")
        self.assertIn("Appendektomiya", html, f"{url_name}: operatsiya ko'rinmadi")

    def test_sterilization_dashboard_shows_patient_and_surgeon(self):
        self.client.force_login(self.steril)
        self._assert_shows_context("clinical:sterilization_dashboard")

    def test_autoclave_dashboard_shows_patient_and_surgeon(self):
        self.client.force_login(self.steril)
        self._assert_shows_context("clinical:autoclave_dashboard")

    def test_autoclave_settings_shows_patient_and_surgeon(self):
        self.client.force_login(self.admin)
        self._assert_shows_context("clinical:autoclave_settings")

    def test_history_is_prefetched_without_n_plus_1(self):
        """Anjomlar soni oshsa ham so'rovlar soni ortmasligi kerak."""
        for i in range(5):
            it = self.make_item(f"Qo'shimcha-{i}", status=SurgicalItem.Status.USED)
            SurgicalItemHistory.log(it, "Ishlatildi", surgery=self.surgery)
        self.client.force_login(self.steril)
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # 6 ta anjom bilan
        with CaptureQueriesContext(connection) as ctx_many:
            self.client.get(reverse("clinical:sterilization_dashboard"))
        many = len(ctx_many.captured_queries)

        # 1 ta anjom bilan — so'rovlar soni bir xil bo'lishi kerak
        SurgicalItem.objects.exclude(name="Nabor-A").hard_delete()
        with CaptureQueriesContext(connection) as ctx_few:
            self.client.get(reverse("clinical:sterilization_dashboard"))
        few = len(ctx_few.captured_queries)

        self.assertEqual(many, few, "Anjom soniga qarab so'rovlar oshmoqda (N+1)")


class VitalsRegressionTests(SterilizationTestBase):
    """Protokol yozuvi vaqtsiz saqlanganda 500 bermasligi kerak."""

    def test_vitals_without_time_does_not_crash(self):
        v = self.surgery.vitals.create(recorded_by=self.nurse)  # recorded_at=None
        self.assertIn("—", str(v))  # __str__ yiqilmaydi

    def test_vitals_add_view_sets_time(self):
        """Faqat anesteziolog roli yoza oladi va vaqt avtomatik qo'yiladi."""
        anesth = User.objects.create_user(
            username="anest", password="x", first_name="Bahodir",
            last_name="Anesteziolog",
            role=_role(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"),
        )
        self.client.force_login(anesth)
        self.client.post(
            reverse("clinical:surgery_vitals_add", args=[self.surgery.id]),
            {"blood_pressure": "120/80", "pulse": "72"},
        )
        v = self.surgery.vitals.first()
        self.assertIsNotNone(v, "Protokol yozuvi yaratilmadi")
        self.assertIsNotNone(v.recorded_at, "Protokol yozuvi vaqtsiz saqlandi")

    def test_no_duplicate_view_definition(self):
        """`surgery_vitals_add` bir marta aniqlangan bo'lishi kerak."""
        import inspect
        from apps.clinical import views
        src = inspect.getsource(views)
        self.assertEqual(
            src.count("\ndef surgery_vitals_add("), 1,
            "surgery_vitals_add takrorlanmoqda — biri hech qachon ishlamaydi",
        )


class DeleteProtectionTests(SterilizationTestBase):
    """Tarixi bor anjom o'chirilmasligi kerak (audit izi CASCADE bilan yo'q bo'lardi)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin1", password="x", is_superuser=True,
            role=_role(Role.Code.SUPER_ADMIN, "Super admin"),
        )

    def test_item_with_history_is_not_deleted(self):
        item = self.make_item()
        SurgicalItemHistory.log(item, "Ishlatildi", surgery=self.surgery)
        self.client.force_login(self.admin)
        self.client.post(reverse("clinical:delete_surgical_item", args=[item.id]))
        self.assertTrue(SurgicalItem.objects.filter(id=item.id).exists())
        self.assertTrue(SurgicalItemHistory.objects.filter(item_id=item.id).exists())

    def test_clean_item_without_history_is_deleted(self):
        item = self.make_item("Yangi nabor")
        self.client.force_login(self.admin)
        self.client.post(reverse("clinical:delete_surgical_item", args=[item.id]))
        self.assertFalse(SurgicalItem.objects.filter(id=item.id).exists())


# ==========================================================================
#  XIZMATLAR: "qayerga borish" + Qabul qilish / Kechiktirish oqimi
# ==========================================================================

class ServiceFlowTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from apps.clinical.models import AmbulatoryRoom, ServiceCatalog, ServiceOrder
        cls.ServiceOrder = ServiceOrder

        cls.radiolog_role = _role(Role.Code.RADIOLOGY, "Radiologiya")
        cls.lab_role = _role(Role.Code.LAB, "Laboratoriya")

        cls.radiolog = User.objects.create_user(
            username="radiolog", password="x", first_name="Aziz",
            last_name="Karimov", role=cls.radiolog_role, specialty="UZI mutaxassisi",
        )
        cls.radiolog2 = User.objects.create_user(
            username="radiolog2", password="x", first_name="Zilola",
            last_name="Tosheva", role=cls.radiolog_role,
        )
        cls.laborant = User.objects.create_user(
            username="laborant", password="x", first_name="Dilnoza",
            last_name="Yusupova", role=cls.lab_role,
        )
        cls.doctor = User.objects.create_user(
            username="shifokor2", password="x", first_name="Sardor",
            last_name="Aliyev", role=_role(Role.Code.DOCTOR, "Shifokor"),
        )

        cls.room = AmbulatoryRoom.objects.create(name="3-Xona")
        cls.uzi = ServiceCatalog.objects.create(
            name="UZI — Jigar", price=60000, allowed_role=cls.radiolog_role,
            room=cls.room, responsible_staff=cls.radiolog,
        )
        cls.lab_service = ServiceCatalog.objects.create(
            name="Umumiy qon tahlili", price=30000, allowed_role=cls.lab_role,
        )
        cls.free_service = ServiceCatalog.objects.create(
            name="Spirometriya", price=60000,  # allowed_role yo'q
        )

        cls.patient = Patient.objects.create(
            last_name="Olimov", first_name="Bobur",
            birth_date=date(1985, 3, 3), gender=Patient.Gender.MALE,
        )
        cls.visit = Visit.objects.create(
            patient=cls.patient, visit_date=date(2026, 7, 2), queue_number=7,
            doctor=cls.doctor,
        )

    def make_order(self, service=None):
        return self.ServiceOrder.objects.create(
            visit=self.visit, service=service or self.uzi,
            status=self.ServiceOrder.Status.WAITING,
        )


class ServiceDestinationTests(ServiceFlowTestBase):
    """Bemor qayerga / kimning oldiga borishi ko'rsatilishi kerak."""

    def test_destination_includes_room_and_staff(self):
        self.assertEqual(self.uzi.destination, "3-Xona — Karimov Aziz")

    def test_destination_falls_back_to_role(self):
        self.assertEqual(self.lab_service.destination, "Laboratoriya")

    def test_destination_empty_when_nothing_set(self):
        self.assertEqual(self.free_service.destination, "")

    def test_referral_page_shows_where_to_go(self):
        self.make_order(self.uzi)
        self.client.force_login(self.doctor)
        resp = self.client.get(reverse("clinical:service_referral", args=[self.visit.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("3-Xona", html)
        self.assertIn("Karimov Aziz", html)
        self.assertIn("TEKSHIRUVGA YO'LLANMA", html)


class ExaminerAcceptDeferTests(ServiceFlowTestBase):
    """«Qabul qildim» va «Kechiktirish» tugmalari haqiqatan ishlashi kerak."""

    def test_accept_sets_in_progress(self):
        order = self.make_order()
        self.client.force_login(self.radiolog)
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, self.ServiceOrder.Status.IN_PROGRESS)
        self.assertEqual(order.accepted_by, self.radiolog)
        self.assertIsNotNone(order.accepted_at)

    def test_second_examiner_cannot_steal_accepted_order(self):
        """Ikki xodim bir bemorni chaqirib qolmasligi kerak."""
        order = self.make_order()
        self.client.force_login(self.radiolog)
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        self.client.force_login(self.radiolog2)
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.accepted_by, self.radiolog)

    def test_defer_returns_to_queue_with_reason(self):
        order = self.make_order()
        self.client.force_login(self.radiolog)
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        self.client.post(
            reverse("clinical:examiner_order_defer", args=[order.id]),
            {"reason": "Bemor kelmadi"},
        )
        order.refresh_from_db()
        self.assertEqual(order.status, self.ServiceOrder.Status.WAITING)
        self.assertEqual(order.deferred_reason, "Bemor kelmadi")
        self.assertEqual(order.deferred_by, self.radiolog)
        self.assertEqual(order.defer_count, 1)
        self.assertIsNone(order.accepted_by, "Kechiktirilganda qabul bekor bo'lishi kerak")

    def test_defer_requires_reason(self):
        order = self.make_order()
        self.client.force_login(self.radiolog)
        self.client.post(reverse("clinical:examiner_order_defer", args=[order.id]), {"reason": "  "})
        order.refresh_from_db()
        self.assertEqual(order.defer_count, 0)
        self.assertEqual(order.status, self.ServiceOrder.Status.WAITING)

    def test_defer_counter_increments(self):
        order = self.make_order()
        self.client.force_login(self.radiolog)
        for i in range(3):
            self.client.post(
                reverse("clinical:examiner_order_defer", args=[order.id]),
                {"reason": f"Sabab {i}"},
            )
        order.refresh_from_db()
        self.assertEqual(order.defer_count, 3)
        self.assertEqual(order.deferred_reason, "Sabab 2")

    def test_deferred_order_stays_in_queue(self):
        order = self.make_order()
        self.client.force_login(self.radiolog)
        self.client.post(
            reverse("clinical:examiner_order_defer", args=[order.id]),
            {"reason": "Uskuna band"},
        )
        resp = self.client.get(reverse("clinical:examiner_dashboard"))
        ids = [o.id for o in resp.context["pending_orders"]]
        self.assertIn(order.id, ids, "Kechiktirilgan tekshiruv navbatdan yo'qoldi")

    def test_accepted_order_moves_to_in_progress_section(self):
        order = self.make_order()
        self.client.force_login(self.radiolog)
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        resp = self.client.get(reverse("clinical:examiner_dashboard"))
        self.assertIn(order.id, [o.id for o in resp.context["in_progress_orders"]])
        self.assertNotIn(order.id, [o.id for o in resp.context["pending_orders"]])


class ExaminerRoleGuardTests(ServiceFlowTestBase):
    """Xodim faqat o'z rolidagi tekshiruvga tegishi mumkin."""

    def test_lab_cannot_accept_radiology_order(self):
        order = self.make_order(self.uzi)
        self.client.force_login(self.laborant)
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, self.ServiceOrder.Status.WAITING)
        self.assertIsNone(order.accepted_by)

    def test_lab_cannot_perform_radiology_order(self):
        order = self.make_order(self.uzi)
        self.client.force_login(self.laborant)
        self.client.post(
            reverse("clinical:examiner_order_perform", args=[order.id]),
            {"result_text": "Soxta xulosa"},
        )
        order.refresh_from_db()
        self.assertNotEqual(order.status, self.ServiceOrder.Status.COMPLETED)
        self.assertEqual(order.result_text, "")

    def test_unassigned_service_can_be_done_by_anyone(self):
        order = self.make_order(self.free_service)
        self.client.force_login(self.laborant)
        self.client.post(
            reverse("clinical:examiner_order_perform", args=[order.id]),
            {"result_text": "Norma"},
        )
        order.refresh_from_db()
        self.assertEqual(order.status, self.ServiceOrder.Status.COMPLETED)

    def test_completed_order_cannot_be_reopened(self):
        order = self.make_order(self.uzi)
        self.client.force_login(self.radiolog)
        self.client.post(
            reverse("clinical:examiner_order_perform", args=[order.id]),
            {"result_text": "Norma"},
        )
        self.client.post(reverse("clinical:examiner_order_accept", args=[order.id]))
        order.refresh_from_db()
        self.assertEqual(order.status, self.ServiceOrder.Status.COMPLETED)


class ServiceFormValidationTests(ServiceFlowTestBase):
    """Mas'ul xodim xizmatning roliga mos bo'lishi kerak."""

    def test_mismatched_staff_role_is_rejected(self):
        from apps.accounts.forms import ServiceForm
        form = ServiceForm(data={
            "name": "Yangi UZI", "price": "50000",
            "allowed_role": self.radiolog_role.id,
            "responsible_staff": self.laborant.id,   # laborant ≠ radiolog
            "is_active": True,
        })
        self.assertFalse(form.is_valid())
        self.assertIn("responsible_staff", form.errors)

    def test_matching_staff_role_is_accepted(self):
        from apps.accounts.forms import ServiceForm
        form = ServiceForm(data={
            "name": "Yangi UZI 2", "price": "50000",
            "allowed_role": self.radiolog_role.id,
            "responsible_staff": self.radiolog.id,
            "room": self.room.id,
            "is_active": True,
        })
        self.assertTrue(form.is_valid(), form.errors)


class ScheduleSurgeryModalTests(TestCase):
    """«Operatsiyaga yozish» oynasi qayerdan ochilsa ham bir xil bo'lishi kerak."""

    @classmethod
    def setUpTestData(cls):
        from apps.clinical.models import OperatingRoom, SurgeryType
        cls.admin = User.objects.create_user(
            username="adm", password="x", is_superuser=True,
            role=_role(Role.Code.SUPER_ADMIN, "Super admin"),
        )
        cls.surgeon = User.objects.create_user(
            username="jarroh9", password="x", first_name="Alisher", last_name="Jarrohov",
            role=_role(Role.Code.SURGEON, "Jarroh"),
        )
        cls.anesth = User.objects.create_user(
            username="anest9", password="x", first_name="Bahodir", last_name="Anesteziolog",
            role=_role(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"),
        )
        cls.nurse = User.objects.create_user(
            username="hamshira9", password="x", first_name="Nodira", last_name="Hamshirayeva",
            role=_role(Role.Code.NURSE, "Hamshira"),
        )
        cls.ward_nurse = User.objects.create_user(
            username="palata9", password="x", first_name="Gulnora", last_name="Palatova",
            role=_role(Role.Code.WARD_NURSE, "Palata hamshirasi"),
        )
        cls.room = OperatingRoom.objects.create(name="2-operatsion blok")
        cls.stype = SurgeryType.objects.create(name="Gerniotomiya", price=500000)
        cls.patient = Patient.objects.create(
            last_name="Sobirov", first_name="Jasur",
            birth_date=date(1979, 1, 1), gender=Patient.Gender.MALE,
        )
        cls.visit = Visit.objects.create(
            patient=cls.patient, visit_date=date(2026, 7, 3), queue_number=11,
        )

    def test_patient_card_modal_has_full_team_fields(self):
        """Bemor kartasidagi oyna ham anesteziolog va boshqa maydonlarni ko'rsatsin."""
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for field in ("assistant_id", "anesthesiologist_id", "operating_nurse_id",
                      "ward_nurse_id", "operating_room_id"):
            self.assertIn(field, html, f"Bemor kartasi oynasida «{field}» maydoni yo'q")
        self.assertIn("Anesteziolog Bahodir", html)
        self.assertIn("2-operatsion blok", html)

    def test_context_lists_are_populated(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("patients:detail", args=[self.patient.pk]))
        for key in ("surgery_types", "surgeons", "assistants", "anesthesiologists",
                    "operating_nurses", "ward_nurses", "operating_rooms"):
            self.assertIn(key, resp.context, f"«{key}» kontekstda yo'q")
        self.assertIn(self.anesth, list(resp.context["anesthesiologists"]))
        self.assertIn(self.ward_nurse, list(resp.context["ward_nurses"]))

    def test_scheduling_from_patient_card_saves_team(self):
        """Bemor kartasidan yozilganda ham butun jamoa saqlanishi kerak."""
        self.client.force_login(self.admin)
        self.client.post(reverse("clinical:schedule_surgery"), {
            "visit_id": str(self.visit.id),
            "surgery_type_id": str(self.stype.id),
            "surgeon_id": str(self.surgeon.id),
            "assistant_id": str(self.nurse.id),
            "anesthesiologist_id": str(self.anesth.id),
            "operating_nurse_id": str(self.nurse.id),
            "ward_nurse_id": str(self.ward_nurse.id),
            "operating_room_id": str(self.room.id),
            "scheduled_time": "2026-08-10T09:30",
            "notes": "Ertalabki operatsiya",
        })
        s = SurgerySchedule.objects.filter(visit=self.visit).first()
        self.assertIsNotNone(s, "Operatsiya yaratilmadi")
        self.assertEqual(s.surgeon, self.surgeon)
        self.assertEqual(s.anesthesiologist, self.anesth)
        self.assertEqual(s.operating_nurse, self.nurse)
        self.assertEqual(s.ward_nurse, self.ward_nurse)
        self.assertEqual(s.operating_room, self.room)

    def test_stay_page_uses_same_modal(self):
        """Statsionar sahifasidagi tugma va oyna id'si mos bo'lishi kerak."""
        from apps.clinical.models import Bed, InpatientStay, Room
        room = Room.objects.create(name="101-palata")
        bed = Bed.objects.create(room=room, number=1)
        stay = InpatientStay.objects.create(visit=self.visit, bed=bed)
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("clinical:stay_documentation", args=[stay.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('data-bs-target="#surgeryModalStay"', html)
        self.assertIn('id="surgeryModalStay"', html)
        self.assertIn("anesthesiologist_id", html)

    def test_scheduled_time_is_timezone_aware(self):
        """<input type="datetime-local"> vaqti mintaqasiz keladi — aware bo'lishi kerak."""
        self.client.force_login(self.admin)
        self.client.post(reverse("clinical:schedule_surgery"), {
            "visit_id": str(self.visit.id),
            "surgery_type_id": str(self.stype.id),
            "surgeon_id": str(self.surgeon.id),
            "scheduled_time": "2026-08-10T09:30",
        })
        s = SurgerySchedule.objects.filter(visit=self.visit).first()
        self.assertIsNotNone(s)
        self.assertFalse(timezone.is_naive(s.scheduled_time),
                         "Vaqt naive saqlandi — soat siljib ketadi")
        self.assertEqual(timezone.localtime(s.scheduled_time).strftime("%H:%M"), "09:30")


# ==========================================================================
#  MARSHRUTLASH: tekshiruv o'z shifokorining navbatida chiqishi
# ==========================================================================

class ServiceRoutingTests(TestCase):
    """Mas'ul xodim tanlangan bo'lsa — faqat o'sha xodim ko'radi."""

    @classmethod
    def setUpTestData(cls):
        from apps.clinical.models import AmbulatoryRoom, ServiceCatalog
        cls.doctor_role = _role(Role.Code.DOCTOR, "Shifokor")
        cls.lab_role = _role(Role.Code.LAB, "Laboratoriya")

        cls.kardiolog = User.objects.create_user(
            username="kardio", password="x", first_name="Aziz", last_name="Karimov",
            role=cls.doctor_role, specialty="Kardiolog",
        )
        cls.nevrolog = User.objects.create_user(
            username="nevro", password="x", first_name="Sardor", last_name="Aliyev",
            role=cls.doctor_role, specialty="Nevropatolog",
        )
        cls.laborant = User.objects.create_user(
            username="lab2", password="x", first_name="Dilnoza", last_name="Yusupova",
            role=cls.lab_role,
        )
        cls.xona = AmbulatoryRoom.objects.create(name="5-Xona")

        # EKG -> kardiologga biriktirilgan
        cls.ekg = ServiceCatalog.objects.create(
            name="EKG — Elektrokardiogramma", price=40000,
            allowed_role=cls.doctor_role, responsible_staff=cls.kardiolog, room=cls.xona,
        )
        # Qon tahlili -> faqat rol bo'yicha (laboratoriya)
        cls.qon = ServiceCatalog.objects.create(
            name="Umumiy qon tahlili", price=30000, allowed_role=cls.lab_role,
        )
        # Spirometriya -> umuman biriktirilmagan
        cls.spiro = ServiceCatalog.objects.create(name="Spirometriya", price=60000)

        cls.patient = Patient.objects.create(
            last_name="Olimov", first_name="Bobur",
            birth_date=date(1980, 2, 2), gender=Patient.Gender.MALE,
        )
        cls.visit = Visit.objects.create(
            patient=cls.patient, visit_date=date(2026, 7, 5), queue_number=3,
        )

    def order(self, service):
        from apps.clinical.models import ServiceOrder
        return ServiceOrder.objects.create(
            visit=self.visit, service=service, status=ServiceOrder.Status.WAITING
        )

    def pending_for(self, user):
        self.client.force_login(user)
        resp = self.client.get(reverse("clinical:examiner_dashboard"))
        self.assertEqual(resp.status_code, 200)
        return [o.service.name for o in resp.context["pending_orders"]]

    # --- Model qoidasi ---

    def test_assigned_service_only_for_that_staff(self):
        self.assertTrue(self.ekg.can_be_performed_by(self.kardiolog))
        self.assertFalse(self.ekg.can_be_performed_by(self.nevrolog))
        self.assertFalse(self.ekg.can_be_performed_by(self.laborant))

    def test_role_only_service_for_whole_role(self):
        self.assertTrue(self.qon.can_be_performed_by(self.laborant))
        self.assertFalse(self.qon.can_be_performed_by(self.kardiolog))

    def test_unassigned_service_for_everyone(self):
        self.assertTrue(self.spiro.can_be_performed_by(self.kardiolog))
        self.assertTrue(self.spiro.can_be_performed_by(self.laborant))

    # --- Panel ro'yxati ---

    def test_ekg_appears_only_in_cardiologists_queue(self):
        self.order(self.ekg)
        self.assertIn("EKG — Elektrokardiogramma", self.pending_for(self.kardiolog))
        self.assertNotIn("EKG — Elektrokardiogramma", self.pending_for(self.nevrolog))
        self.assertNotIn("EKG — Elektrokardiogramma", self.pending_for(self.laborant))

    def test_lab_test_goes_to_lab_only(self):
        self.order(self.qon)
        self.assertIn("Umumiy qon tahlili", self.pending_for(self.laborant))
        self.assertNotIn("Umumiy qon tahlili", self.pending_for(self.kardiolog))

    def test_unassigned_service_visible_to_all(self):
        self.order(self.spiro)
        self.assertIn("Spirometriya", self.pending_for(self.kardiolog))
        self.assertIn("Spirometriya", self.pending_for(self.laborant))

    def test_other_doctor_cannot_perform_assigned_service(self):
        o = self.order(self.ekg)
        self.client.force_login(self.nevrolog)
        self.client.post(reverse("clinical:examiner_order_perform", args=[o.id]),
                         {"result_text": "Soxta"})
        o.refresh_from_db()
        self.assertEqual(o.result_text, "")


# ==========================================================================
#  CHAQIRISH va TABLO
# ==========================================================================

class BoardCallTests(ServiceRoutingTests):
    """Tekshiruv faqat CHAQIRILGANDA tabloda chiqishi kerak."""

    def _board(self, user):
        self.client.force_login(user)
        resp = self.client.get(reverse("registration:board_feed"))
        self.assertEqual(resp.status_code, 200)
        return resp.json()["calls"]

    def setUp(self):
        self.tablo = User.objects.create_user(
            username="tablo1", password="x",
            role=_role(Role.Code.TABLO, "Tablo"),
        )

    def test_assigned_order_not_on_board_until_called(self):
        self.order(self.ekg)
        nomlar = [c.get("service") for c in self._board(self.tablo)]
        self.assertNotIn("EKG — Elektrokardiogramma", nomlar)

    def test_call_puts_patient_on_board(self):
        o = self.order(self.ekg)
        self.client.force_login(self.kardiolog)
        self.client.post(reverse("clinical:examiner_order_call", args=[o.id]))
        o.refresh_from_db()
        self.assertIsNotNone(o.called_at)
        self.assertEqual(o.called_by, self.kardiolog)

        calls = self._board(self.tablo)
        mine = [c for c in calls if c["service"] == "EKG — Elektrokardiogramma"]
        self.assertEqual(len(mine), 1, "Tabloda chiqmadi")
        c = mine[0]
        self.assertEqual(c["n"], self.visit.queue_number)
        self.assertEqual(c["patient"], "Olimov Bobur")
        self.assertEqual(c["room"], "5-Xona")
        self.assertEqual(c["doctor"], "Karimov Aziz")
        self.assertEqual(c["kind"], "service")

    def test_other_doctor_cannot_call(self):
        o = self.order(self.ekg)
        self.client.force_login(self.nevrolog)
        self.client.post(reverse("clinical:examiner_order_call", args=[o.id]))
        o.refresh_from_db()
        self.assertIsNone(o.called_at)

    def test_repeat_call_increments_counter(self):
        o = self.order(self.ekg)
        self.client.force_login(self.kardiolog)
        for _ in range(3):
            self.client.post(reverse("clinical:examiner_order_call", args=[o.id]))
        o.refresh_from_db()
        self.assertEqual(o.call_count, 3)

    def test_completed_order_leaves_board(self):
        o = self.order(self.ekg)
        self.client.force_login(self.kardiolog)
        self.client.post(reverse("clinical:examiner_order_call", args=[o.id]))
        self.client.post(reverse("clinical:examiner_order_perform", args=[o.id]),
                         {"result_text": "Norma"})
        nomlar = [c.get("service") for c in self._board(self.tablo)]
        self.assertNotIn("EKG — Elektrokardiogramma", nomlar)

    def test_board_ids_are_unique_between_visit_and_service(self):
        """Bir bemorning qabuli va tekshiruvi bir xil navbat raqamida bo'ladi —
        tablo ikkalasini alohida e'lon qila olishi kerak."""
        from django.utils import timezone as tz
        self.visit.accepted_at = tz.now()
        self.visit.status = Visit.Status.ACCEPTED
        self.visit.doctor = self.kardiolog
        self.visit.visit_date = tz.localdate()
        self.visit.save()

        o = self.order(self.ekg)
        self.client.force_login(self.kardiolog)
        self.client.post(reverse("clinical:examiner_order_call", args=[o.id]))

        calls = self._board(self.tablo)
        ids = [c["id"] for c in calls]
        self.assertEqual(len(ids), len(set(ids)), "Tablo id'lari takrorlanmoqda")
        self.assertEqual(len({c["kind"] for c in calls}), 2, "Ikkala tur ham chiqishi kerak")

    def test_inactive_room_not_announced(self):
        """Nofaol kabinet tabloda e'lon qilinmasligi kerak."""
        self.xona.is_active = False
        self.xona.save(update_fields=["is_active"])
        o = self.order(self.ekg)
        self.client.force_login(self.kardiolog)
        self.client.post(reverse("clinical:examiner_order_call", args=[o.id]))
        c = [x for x in self._board(self.tablo) if x["kind"] == "service"][0]
        self.assertEqual(c["room"], "", "Nofaol xona e'lon qilindi")


class MoveRadiologyCommandTests(TestCase):
    """Radiologiya xizmatlarini shifokorlarga o'tkazish buyrug'i."""

    def test_command_moves_services(self):
        from io import StringIO
        from django.core.management import call_command
        from apps.clinical.models import ServiceCatalog

        rad = _role(Role.Code.RADIOLOGY, "Radiologiya")
        doc = _role(Role.Code.DOCTOR, "Shifokor")
        for nom in ["UZI — Jigar", "Rentgen — Ko'krak", "EKG"]:
            ServiceCatalog.objects.create(name=nom, price=1000, allowed_role=rad)

        out = StringIO()
        call_command("move_radiology_services", "--dry-run", stdout=out)
        self.assertEqual(ServiceCatalog.objects.filter(allowed_role=rad).count(), 3,
                         "--dry-run o'zgartirmasligi kerak")

        call_command("move_radiology_services", stdout=StringIO())
        self.assertEqual(ServiceCatalog.objects.filter(allowed_role=rad).count(), 0)
        self.assertEqual(ServiceCatalog.objects.filter(allowed_role=doc).count(), 3)


class BulkAssignTests(ServiceRoutingTests):
    """Ommaviy biriktirish oynasi."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin9", password="x", is_superuser=True,
            role=_role(Role.Code.SUPER_ADMIN, "Super admin"),
        )

    def test_bulk_assign_sets_staff_and_role(self):
        from apps.clinical.models import ServiceCatalog
        self.client.force_login(self.admin)
        self.client.post(reverse("staff:services_bulk_assign"), {
            "services": [str(self.spiro.id), str(self.qon.id)],
            "responsible_staff": str(self.kardiolog.id),
            "room": str(self.xona.id),
        })
        for s in ServiceCatalog.objects.filter(id__in=[self.spiro.id, self.qon.id]):
            self.assertEqual(s.responsible_staff, self.kardiolog)
            self.assertEqual(s.allowed_role_id, self.kardiolog.role_id,
                             "Rol xodim roliga moslanmadi")
            self.assertEqual(s.room, self.xona)

    def test_bulk_clear_staff(self):
        from apps.clinical.models import ServiceCatalog
        self.client.force_login(self.admin)
        self.client.post(reverse("staff:services_bulk_assign"), {
            "services": [str(self.ekg.id)],
            "clear_staff": "1",
        })
        self.ekg.refresh_from_db()
        self.assertIsNone(self.ekg.responsible_staff)
