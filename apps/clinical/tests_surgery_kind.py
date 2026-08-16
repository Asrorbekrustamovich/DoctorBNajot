"""OPERATSIYA USULI (ochiq / endoskopik) VA AVTOKLAV AYLANMASI.

HAQIQIY XATO: `SurgeryType.kind` modelda bor edi va izohida «Ochiq:
avtoklav anjomlar + belyo. Endoskopik: rastvor anjomlar + belyo» deb
yozilgan edi — lekin bu qoida HECH QAYERDA tekshirilmasdi. Endoskopik
operatsiyani ochiq jarrohlik nabori bilan boshlab yuborish mumkin edi,
endoskopik anjom umuman tanlanmasa ham.

Ikkinchi qism — anjom aylanmasi: tanlangach «Operatsiyada», operatsiya
tugagach «Ishlatilgan / Ifloslangan» bo'lib avtoklavga qaytishi kerak.
Aks holda ifloslangan anjom keyingi bemorga steril deb beriladi.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    OperatingRoom, SurgerySchedule, SurgeryType, SurgicalItem,
)
from apps.clinical.views import _surgery_items_error
from apps.patients.models import Patient
from apps.registration.models import Visit


class OperatsiyaUsuliTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ochiq = SurgeryType.objects.create(
            name="Appendektomiya (ochiq)", kind=SurgeryType.Kind.OPEN,
            price=Decimal(100))
        cls.endo = SurgeryType.objects.create(
            name="Laparoskopiya", kind=SurgeryType.Kind.ENDOSCOPIC,
            price=Decimal(200))

        cls.nabor = SurgicalItem.objects.create(
            name="Jarrohlik nabori-1", item_type=SurgicalItem.Type.NABOR,
            status=SurgicalItem.Status.READY)
        cls.belyo = SurgicalItem.objects.create(
            name="Belyo biks-1", item_type=SurgicalItem.Type.LINEN,
            status=SurgicalItem.Status.READY)
        cls.endo_anjom = SurgicalItem.objects.create(
            name="Laparoskop", item_type=SurgicalItem.Type.ENDO_INSTRUMENT,
            status=SurgicalItem.Status.READY)

    def _tanlov(self, *items):
        return SurgicalItem.objects.filter(id__in=[i.pk for i in items])

    def _reja(self, turi):
        return SurgerySchedule(surgery_type=turi)

    # ---------------- OCHIQ ----------------
    def test_ochiq_nabor_va_belyo_bilan_boshlanadi(self):
        xato = _surgery_items_error(
            self._reja(self.ochiq), self._tanlov(self.nabor, self.belyo))
        self.assertEqual(xato, "")

    def test_ochiq_naborsiz_boshlanmaydi(self):
        xato = _surgery_items_error(
            self._reja(self.ochiq), self._tanlov(self.belyo))
        self.assertIn("nabori", xato)

    def test_ochiq_faqat_nabor_bilan_boshlanmaydi(self):
        xato = _surgery_items_error(
            self._reja(self.ochiq), self._tanlov(self.nabor))
        self.assertNotEqual(xato, "")

    # ---------------- ENDOSKOPIK ----------------
    def test_endoskopik_endo_anjom_va_belyo_bilan_boshlanadi(self):
        xato = _surgery_items_error(
            self._reja(self.endo), self._tanlov(self.endo_anjom, self.belyo))
        self.assertEqual(xato, "")

    def test_endoskopikni_ochiq_nabor_bilan_boshlab_bolmaydi(self):
        """ASOSIY XATO: ilgari bunga ruxsat berilardi."""
        xato = _surgery_items_error(
            self._reja(self.endo), self._tanlov(self.nabor, self.belyo))
        self.assertIn(
            "ENDOSKOPIK ANJOM", xato,
            "Endoskopik operatsiya ochiq nabor bilan boshlanib ketdi.")

    def test_endoskopikda_faqat_endo_anjom_yetmaydi(self):
        xato = _surgery_items_error(
            self._reja(self.endo), self._tanlov(self.endo_anjom))
        self.assertIn("belyo", xato)

    # ---------------- STERILIZATSIYA USULI ----------------
    def test_endoskopik_anjom_rastvorda_tozalanadi(self):
        """Avtoklav endoskopik anjomni buzadi — model majburlaydi."""
        self.endo_anjom.steril_method = SurgicalItem.SterilMethod.AUTOCLAVE
        self.endo_anjom.save()
        self.endo_anjom.refresh_from_db()
        self.assertEqual(self.endo_anjom.steril_method,
                         SurgicalItem.SterilMethod.SOLUTION)

    def test_belyo_faqat_avtoklavda(self):
        self.belyo.steril_method = SurgicalItem.SterilMethod.SOLUTION
        self.belyo.save()
        self.belyo.refresh_from_db()
        self.assertEqual(self.belyo.steril_method,
                         SurgicalItem.SterilMethod.AUTOCLAVE)


class AnjomAylanmasiTests(TestCase):
    """Tayyor → Operatsiyada → Ifloslangan → (tozalash) → Tayyor."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="ak_admin", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SUPER_ADMIN, defaults={"name": "Super"})[0])
        self.turi = SurgeryType.objects.create(
            name="Test operatsiya", kind=SurgeryType.Kind.OPEN, price=Decimal(1))
        self.xona = OperatingRoom.objects.create(name="Op-1")
        self.jarroh = User.objects.create_user(
            username="ak_surgeon", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.SURGEON, defaults={"name": "Jarroh"})[0])
        self.nabor = SurgicalItem.objects.create(
            name="Nabor-A", item_type=SurgicalItem.Type.NABOR,
            status=SurgicalItem.Status.READY)
        self.belyo = SurgicalItem.objects.create(
            name="Belyo-A", item_type=SurgicalItem.Type.LINEN,
            status=SurgicalItem.Status.READY)

        p = Patient.objects.create(
            card_number="P-AK1", last_name="Operatsiyaev", first_name="B",
            birth_date=date(1990, 1, 1), gender="male")
        v = Visit.objects.create(patient=p, visit_date=date.today(),
                                 queue_number=1)
        self.reja = SurgerySchedule.objects.create(
            visit=v, surgery_type=self.turi, operating_room=self.xona,
            surgeon=self.jarroh,
            scheduled_time=timezone.now(), actual_price=Decimal(1))
        self.client.force_login(self.admin)
        self.url = reverse("clinical:update_surgery_status", args=[self.reja.id])

    def test_boshlanganda_anjom_operatsiyada_boladi(self):
        self.client.post(self.url, {
            "status": SurgerySchedule.Status.IN_PROGRESS,
            "items": [str(self.nabor.pk), str(self.belyo.pk)],
        })

        self.nabor.refresh_from_db()
        self.assertEqual(self.nabor.status, SurgicalItem.Status.IN_USE)
        self.assertEqual(self.nabor.current_room_id, self.xona.pk)

    def test_yakunlanganda_anjom_ifloslangan_boladi(self):
        """ASOSIY TALAB: ishlatilgan anjom steril deb qolib ketmasin."""
        self.client.post(self.url, {
            "status": SurgerySchedule.Status.IN_PROGRESS,
            "items": [str(self.nabor.pk), str(self.belyo.pk)],
        })
        self.client.post(self.url, {"status": SurgerySchedule.Status.COMPLETED})

        self.nabor.refresh_from_db()
        self.belyo.refresh_from_db()
        self.assertEqual(
            self.nabor.status, SurgicalItem.Status.USED,
            "Ishlatilgan nabor «tayyor» bo'lib qoldi — keyingi bemorga "
            "ifloslangan holda beriladi.")
        self.assertEqual(self.belyo.status, SurgicalItem.Status.USED)

    def test_bekor_qilinsa_anjom_ozod_boladi(self):
        self.client.post(self.url, {
            "status": SurgerySchedule.Status.IN_PROGRESS,
            "items": [str(self.nabor.pk), str(self.belyo.pk)],
        })
        self.client.post(self.url, {"status": SurgerySchedule.Status.SCHEDULED})

        self.nabor.refresh_from_db()
        self.assertEqual(self.nabor.status, SurgicalItem.Status.READY,
                         "Bekor qilingan operatsiyaning anjomi band qoldi.")
        self.assertIsNone(self.nabor.current_room_id)

    def test_naborsiz_boshlab_bolmaydi_va_anjom_tegilmaydi(self):
        self.client.post(self.url, {
            "status": SurgerySchedule.Status.IN_PROGRESS,
            "items": [str(self.belyo.pk)],          # nabor yo'q
        })

        self.reja.refresh_from_db()
        self.belyo.refresh_from_db()
        self.assertEqual(self.reja.status, SurgerySchedule.Status.SCHEDULED)
        self.assertEqual(self.belyo.status, SurgicalItem.Status.READY,
                         "Operatsiya boshlanmadi, lekin anjom band qilindi.")

    def test_anjom_tarixi_yoziladi(self):
        self.client.post(self.url, {
            "status": SurgerySchedule.Status.IN_PROGRESS,
            "items": [str(self.nabor.pk), str(self.belyo.pk)],
        })
        self.assertTrue(
            self.nabor.history.exists(),
            "Anjom tarixi yozilmadi — kim, qachon, qaysi operatsiyada "
            "ishlatgani aniqlanmaydi.")
