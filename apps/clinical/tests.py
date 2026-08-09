"""Tekshiruvlar (analiz, EKG, UZI…) oqimi uchun testlar.

Qamrab olinadi:
  · guruhlar daraxti va «+Analiz» modalining tarkibi
  · tekshiruv tayinlash va narx snapshot'i (katalog narxi o'zgarsa
    eski buyurtma o'zgarmasligi)
  · kim bajarishi: xizmat > guruh > hamma (Python va SQL mantig'i bir xilmi)
  · natija kiritish (jadval + matn) va bo'sh qatorlar tashlanishi
  · natijani chop etish — shifokor ham, registratura ham
"""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    ResultTemplateRow, ServiceCatalog, ServiceCategory, ServiceOrder,
    ServiceResultRow,
)
from apps.clinical.selectors import exam_picker_groups
from apps.clinical.views import _my_orders_filter
from apps.patients.models import Patient
from apps.registration.models import Visit


def role(code: str) -> Role:
    return Role.objects.get_or_create(code=code, defaults={"name": code.title()})[0]


def user(username: str, code: str | None = None, **kw) -> User:
    u = User.objects.create_user(username=username, password="x", **kw)
    if code:
        u.role = role(code)
        u.save(update_fields=["role"])
    return u


class Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lab_root = ServiceCategory.objects.create(
            name="Sinov laboratoriyasi", button_label="+Analiz", icon="🧪", sort_order=10)
        cls.clinic = ServiceCategory.objects.create(
            name="Sinov klinik tahlillari", parent=cls.lab_root, sort_order=10)
        cls.uzi = ServiceCategory.objects.create(
            name="Sinov UZI", button_label="+UZI", icon="🔊",
            kind=ServiceCategory.Kind.DIAGNOSTIC, sort_order=30)

        cls.kla = ServiceCatalog.objects.create(
            name="Umumiy qon tahlili", price=Decimal("40000"), category=cls.clinic)
        cls.uzi_abdomen = ServiceCatalog.objects.create(
            name="UZI — Qorin", price=Decimal("90000"), category=cls.uzi)
        # Guruhsiz xizmat — modalda ko'rinmasligi kerak
        cls.consult = ServiceCatalog.objects.create(
            name="Terapevt qabuli", price=Decimal("50000"))

        cls.doctor = user("doc", "doctor")
        cls.laborant = user("lab", "nurse")
        cls.reception = user("reg", "reception")
        cls.admin = user("sa", None, is_superuser=True, is_staff=True)

        cls.patient = Patient.objects.create(
            first_name="Ali", last_name="Valiyev", card_number="P-000001",
            birth_date="1990-01-01", gender="male")
        cls.visit = Visit.objects.create(
            patient=cls.patient, doctor=cls.doctor,
            visit_date=timezone.localdate(), queue_number=1,
            status=Visit.Status.ACCEPTED)


# ---------------------------------------------------------------- daraxt
class ExamPickerTests(Base):

    def test_guruhlar_daraxt_bolib_chiqadi(self):
        # DIQQAT: bazada migratsiya bilan kelgan guruhlar ham bor
        # (Laboratoriya, EKG, UZI, Endoskopiya…). Shuning uchun to'liq
        # ro'yxatni emas, FAQAT shu test yaratgan guruhlarni tekshiramiz —
        # aks holda katalogga yangi xizmat qo'shilishi testni yiqitadi.
        groups = {g["id"]: g for g in exam_picker_groups()}
        self.assertIn(str(self.lab_root.id), groups)
        self.assertIn(str(self.uzi.id), groups)

        analiz = groups[str(self.lab_root.id)]
        self.assertEqual(analiz["services"], [])          # bevosita yo'q
        self.assertEqual(len(analiz["children"]), 1)
        self.assertEqual(analiz["children"][0]["name"], "Sinov klinik tahlillari")
        self.assertEqual(analiz["count"], 1)

    def test_guruhsiz_xizmat_modalda_korinmaydi(self):
        names = []
        for g in exam_picker_groups():
            names += [s["name"] for s in g["services"]]
            for c in g["children"]:
                names += [s["name"] for s in c["services"]]
        self.assertNotIn("Terapevt qabuli", names)

    def test_narx_va_manzil_birga_keladi(self):
        self.uzi.default_role = role("nurse")
        self.uzi.save()
        svc = exam_picker_groups()[1]["services"][0]
        self.assertEqual(svc["price"], Decimal("90000"))
        self.assertIn("Nurse", svc["owner"])

    def test_tayinlangan_xizmat_belgilanadi(self):
        ServiceOrder.objects.create(visit=self.visit, service=self.kla)
        groups = exam_picker_groups({str(self.kla.id)})
        svc = groups[0]["children"][0]["services"][0]
        self.assertTrue(svc["assigned"])

    def test_bosh_guruh_royxatga_tushmaydi(self):
        ServiceCategory.objects.create(name="Bo'sh sinov guruhi", sort_order=99)
        self.assertNotIn("Bo'sh sinov guruhi", [g["name"] for g in exam_picker_groups()])


# ------------------------------------------------------------- tayinlash
class AssignTests(Base):

    def test_tayinlash_narx_snapshotini_oladi(self):
        self.client.force_login(self.doctor)
        r = self.client.post(
            reverse("clinical:consultation_assign_services", args=[self.visit.pk]),
            {"services": [str(self.kla.id), str(self.uzi_abdomen.id)]},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(ServiceOrder.objects.count(), 2)
        o = ServiceOrder.objects.get(service=self.kla)
        self.assertEqual(o.price_snapshot, Decimal("40000"))
        self.assertEqual(o.status, ServiceOrder.Status.WAITING)
        self.assertFalse(o.is_paid)

    def test_katalog_narxi_ozgarsa_eski_buyurtma_ozgarmaydi(self):
        o = ServiceOrder.objects.create(visit=self.visit, service=self.kla)
        self.kla.price = Decimal("999999")
        self.kla.save()
        o.refresh_from_db()
        self.assertEqual(o.price_snapshot, Decimal("40000"))

    def test_takroriy_tayinlash_ikkilantirmaydi(self):
        self.client.force_login(self.doctor)
        url = reverse("clinical:consultation_assign_services", args=[self.visit.pk])
        self.client.post(url, {"services": [str(self.kla.id)]})
        self.client.post(url, {"services": [str(self.kla.id)]})
        self.assertEqual(ServiceOrder.objects.filter(service=self.kla).count(), 1)

    def test_yopiq_qabulga_tayinlab_bolmaydi(self):
        self.visit.status = Visit.Status.COMPLETED
        self.visit.save()
        self.client.force_login(self.doctor)
        r = self.client.post(
            reverse("clinical:consultation_assign_services", args=[self.visit.pk]),
            {"services": [str(self.kla.id)]},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(ServiceOrder.objects.count(), 0)


# ------------------------------------------------------------ kim bajaradi
class RoutingTests(Base):
    """Xizmat > guruh > hamma. Python va SQL mantig'i BIR XIL bo'lishi shart.

    Aks holda xodim ro'yxatda ko'rmagan tekshiruvni ocha oladi yoki
    aksincha — ro'yxatda ko'rgan narsasini ocholmaydi.
    """

    def _sql_sees(self, u) -> set[str]:
        qs = ServiceOrder.objects.filter(_my_orders_filter(u))
        return {str(o.service_id) for o in qs}

    def setUp(self):
        self.o_kla = ServiceOrder.objects.create(visit=self.visit, service=self.kla)
        self.o_uzi = ServiceOrder.objects.create(visit=self.visit, service=self.uzi_abdomen)

    def test_hech_narsa_biriktirilmagan_hammaga_ochiq(self):
        self.assertTrue(self.kla.can_be_performed_by(self.laborant))
        self.assertIn(str(self.kla.id), self._sql_sees(self.laborant))

    def test_guruh_roli_meros_boladi(self):
        self.clinic.default_role = self.laborant.role
        self.clinic.save()
        self.kla.refresh_from_db()
        self.assertTrue(self.kla.can_be_performed_by(self.laborant))
        self.assertFalse(self.kla.can_be_performed_by(self.doctor))
        self.assertIn(str(self.kla.id), self._sql_sees(self.laborant))
        self.assertNotIn(str(self.kla.id), self._sql_sees(self.doctor))

    def test_guruh_xodimi_meros_boladi(self):
        self.clinic.default_staff = self.laborant
        self.clinic.save()
        self.kla.refresh_from_db()
        self.assertTrue(self.kla.can_be_performed_by(self.laborant))
        self.assertFalse(self.kla.can_be_performed_by(self.doctor))
        self.assertEqual(self._sql_sees(self.laborant),
                         {str(self.kla.id), str(self.uzi_abdomen.id)})

    def test_xizmat_xodimi_guruhdan_ustun(self):
        self.clinic.default_staff = self.laborant
        self.clinic.save()
        self.kla.responsible_staff = self.doctor
        self.kla.save()
        self.assertTrue(self.kla.can_be_performed_by(self.doctor))
        self.assertFalse(self.kla.can_be_performed_by(self.laborant))
        self.assertIn(str(self.kla.id), self._sql_sees(self.doctor))
        self.assertNotIn(str(self.kla.id), self._sql_sees(self.laborant))

    def test_python_va_sql_bir_xil_javob_beradi(self):
        """Har bir sozlanma uchun ikkala mantiq mos kelishi kerak."""
        combos = [
            {},
            {"allowed_role": self.laborant.role},
            {"responsible_staff": self.laborant},
            {"responsible_staff": self.doctor},
        ]
        group_combos = [
            {},
            {"default_role": self.laborant.role},
            {"default_staff": self.laborant},
        ]
        for gc in group_combos:
            for f in ("default_role", "default_staff"):
                setattr(self.clinic, f, gc.get(f))
            self.clinic.save()
            for sc in combos:
                for f in ("allowed_role", "responsible_staff"):
                    setattr(self.kla, f, sc.get(f))
                self.kla.save()
                self.kla.refresh_from_db()
                for u in (self.laborant, self.doctor):
                    with self.subTest(group=gc, svc=sc, user=u.username):
                        self.assertEqual(
                            self.kla.can_be_performed_by(u),
                            str(self.kla.id) in self._sql_sees(u),
                        )

    def test_superadmin_hammasini_koradi(self):
        self.kla.responsible_staff = self.doctor
        self.kla.save()
        self.assertTrue(self.kla.can_be_performed_by(self.admin))
        self.assertIn(str(self.kla.id), self._sql_sees(self.admin))


# --------------------------------------------------------------- natijalar
class ResultTests(Base):

    def setUp(self):
        self.order = ServiceOrder.objects.create(visit=self.visit, service=self.kla)
        ResultTemplateRow.objects.create(
            service=self.kla, name="Gemoglobin", unit="g/l", reference="120-160")
        # OLDINDAN TO'LOV: tekshiruv puli xizmatdan oldin to'lanadi.
        # Bu testlar natija kiritishni sinaydi, to'lov to'sig'ini emas —
        # shuning uchun avval to'lovni yopamiz. To'lov to'sig'ining o'zi
        # `tests_prepay.py` da alohida tekshiriladi.
        self._settle()

    def _settle(self):
        from apps.billing.models import Invoice
        from apps.billing.services import settle_prepaid_items
        inv = Invoice.objects.filter(visit=self.visit).first()
        if inv is None:
            return
        inv.paid_amount = inv.total_amount
        inv.save()
        settle_prepaid_items(inv)

    def _perform(self, **extra):
        self.client.force_login(self.admin)
        data = {
            "row_name": ["Gemoglobin", "Leykotsit", ""],
            "row_value": ["105", "7.1", ""],
            "row_unit": ["g/l", "10^9/l", ""],
            "row_ref": ["120-160", "4.0-9.0", ""],
            "row_abnormal": ["0"],
            "result_text": "Kamqonlik.",
        }
        data.update(extra)
        return self.client.post(
            reverse("clinical:examiner_order_perform", args=[self.order.id]),
            data, follow=True)

    def test_natija_saqlanadi_va_yakunlanadi(self):
        self._perform()
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.COMPLETED)
        self.assertIsNotNone(self.order.result_at)
        self.assertTrue(self.order.has_result)
        self.assertEqual(self.order.result_rows.count(), 2)

    def test_bosh_qatorlar_saqlanmaydi(self):
        self._perform()
        self.assertEqual(
            list(self.order.result_rows.values_list("name", flat=True)),
            ["Gemoglobin", "Leykotsit"])

    def test_normadan_chetlanish_belgilanadi(self):
        self._perform()
        rows = {r.name: r.is_abnormal for r in self.order.result_rows.all()}
        self.assertTrue(rows["Gemoglobin"])
        self.assertFalse(rows["Leykotsit"])

    def test_faqat_matn_ham_yetarli(self):
        """UZI/EKG da jadval bo'lmaydi — faqat tavsif yoziladi."""
        self._perform(row_name=[""], row_value=[""], row_unit=[""], row_ref=[""],
                      result_text="Patologiya aniqlanmadi.")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.COMPLETED)
        self.assertEqual(self.order.result_rows.count(), 0)
        self.assertTrue(self.order.has_result)

    def test_faqat_jadval_ham_yetarli(self):
        self._perform(result_text="")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.COMPLETED)
        self.assertEqual(self.order.result_rows.count(), 2)

    def test_butunlay_bosh_natija_qabul_qilinmaydi(self):
        self._perform(row_name=[""], row_value=[""], row_unit=[""], row_ref=[""],
                      result_text="")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, ServiceOrder.Status.WAITING)
        self.assertFalse(self.order.has_result)

    def test_qayta_saqlashda_eski_qatorlar_qolmaydi(self):
        self._perform()
        self.order.status = ServiceOrder.Status.IN_PROGRESS
        self.order.save(update_fields=["status"])
        self._settle()   # status o'zgarishi chekni qayta quradi
        self._perform(row_name=["Trombotsit"], row_value=["250"],
                      row_unit=["10^9/l"], row_ref=["150-400"], row_abnormal=[])
        self.assertEqual(
            list(self.order.result_rows.values_list("name", flat=True)),
            ["Trombotsit"])


# ------------------------------------------------------------- chop etish
class PrintTests(Base):

    def setUp(self):
        self.order = ServiceOrder.objects.create(
            visit=self.visit, service=self.kla,
            status=ServiceOrder.Status.COMPLETED,
            performed_by=self.laborant, result_at=timezone.now(),
            result_text="Kamqonlik.")
        ServiceResultRow.objects.create(
            order=self.order, name="Gemoglobin", value="105",
            unit="g/l", reference="120-160", is_abnormal=True)

    def test_shifokor_chop_eta_oladi(self):
        self.client.force_login(self.doctor)
        r = self.client.get(reverse("clinical:service_result_print", args=[self.order.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Gemoglobin")
        self.assertContains(r, 'class="abn"')

    def test_registratura_ham_chop_eta_oladi(self):
        """Bemor «natijamni bering» deb registraturaga keladi."""
        self.client.force_login(self.reception)
        r = self.client.get(reverse("clinical:service_result_print", args=[self.order.id]))
        self.assertEqual(r.status_code, 200)

    def test_umumiy_blankda_faqat_tayyorlari_chiqadi(self):
        ServiceOrder.objects.create(visit=self.visit, service=self.uzi_abdomen)
        self.client.force_login(self.doctor)
        r = self.client.get(reverse("clinical:visit_results_print", args=[self.visit.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Umumiy qon tahlili")
        self.assertNotContains(r, "UZI — Qorin")

    def test_bemor_malumotlari_blankda_bor(self):
        self.client.force_login(self.doctor)
        r = self.client.get(reverse("clinical:service_result_print", args=[self.order.id]))
        self.assertContains(r, self.patient.full_name)
        self.assertContains(r, "P-000001")
