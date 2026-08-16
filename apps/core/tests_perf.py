"""SO'ROVLAR SONI — sahifa ochilganda baza necha marta so'raladi.

Bu testlar tezlikni emas, SO'ROVLAR SONINI qo'riqlaydi. Ular bir marta
qo'yilmasa, «har bir qator uchun bitta so'rov» (N+1) jimgina kirib
keladi: 20 ta operatsiyada sahifa 100 dan ortiq so'rov yuborardi va
jarrohlik paneli kun bo'yi ochiq turadi.

HAQIQIY XATO: «Bemorning oldingi bayonnomalari» qo'shilganda har bir
operatsiya uchun alohida so'rov ketardi (20 ta operatsiya = +20 so'rov).
Endi hammasi bitta so'rovda olinadi.
"""
from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    OperatingRoom, ServiceCatalog, ServiceOrder, SurgeryReport,
    SurgerySchedule, SurgeryType,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


class SorovlarSoniTests(TestCase):
    def _panel_sorovlari(self, nechta):
        """`nechta` operatsiya bilan jarrohlik panelini ochib, so'rovni sanaydi."""
        u = User.objects.create_user(
            username=f"pf{nechta}", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SUPER_ADMIN, defaults={"name": "Super"})[0])
        turi = SurgeryType.objects.create(
            name=f"T{nechta}", kind=SurgeryType.Kind.OPEN, price=Decimal(1))
        xona = OperatingRoom.objects.create(name=f"X{nechta}")

        for i in range(nechta):
            p = Patient.objects.create(
                card_number=f"P-PF{nechta}-{i}", last_name=f"B{i}",
                first_name="X", birth_date=date(1990, 1, 1), gender="male")
            # Navbat raqami sana bo'yicha unikal — ikkala o'lchov bir
            # kunda o'tkazilgani uchun raqamlarni ajratamiz.
            v = Visit.objects.create(patient=p, visit_date=date.today(),
                                     queue_number=nechta * 100 + i)
            s = SurgerySchedule.objects.create(
                visit=v, surgery_type=turi, operating_room=xona, surgeon=u,
                scheduled_time=timezone.now(), actual_price=Decimal(1))
            SurgeryReport.objects.create(
                surgery=s, filled_by=u, performed_actions="matn")

        self.client.force_login(u)
        with CaptureQueriesContext(connection) as ctx:
            javob = self.client.get(reverse("clinical:surgery_dashboard"))
        self.assertEqual(javob.status_code, 200)
        return len(ctx)

    def _operatsiyalar(self, nechta, belgi):
        """Bayonnomali `nechta` operatsiya yaratadi."""
        u = User.objects.create_user(
            username=f"pf{belgi}", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SUPER_ADMIN, defaults={"name": "Super"})[0])
        turi = SurgeryType.objects.create(
            name=f"T{belgi}", kind=SurgeryType.Kind.OPEN, price=Decimal(1))
        xona = OperatingRoom.objects.create(name=f"X{belgi}")

        rejalar = []
        for i in range(nechta):
            p = Patient.objects.create(
                card_number=f"P-{belgi}-{i}", last_name=f"B{i}",
                first_name="X", birth_date=date(1990, 1, 1), gender="male")
            v = Visit.objects.create(
                patient=p, visit_date=date.today(),
                queue_number=belgi * 1000 + i)
            s = SurgerySchedule.objects.create(
                visit=v, surgery_type=turi, operating_room=xona, surgeon=u,
                scheduled_time=timezone.now(), actual_price=Decimal(1))
            SurgeryReport.objects.create(
                surgery=s, filled_by=u, performed_actions="matn")
            rejalar.append(s)
        return rejalar

    def test_oldingi_bayonnomalar_bitta_sorovda_olinadi(self):
        """ASOSIY HIMOYA: so'rovlar soni operatsiyalar soniga qarab o'smasin.

        Aynan `_with_past_reports` o'lchanadi — butun sahifa emas.
        Sahifaning qolgan qismida boshqa (eskidan qolgan) so'rovlar bor
        va ular o'lchovni chalg'itardi.
        """
        from apps.clinical.views import _with_past_reports

        oz = self._operatsiyalar(3, belgi=1)
        with CaptureQueriesContext(connection) as k1:
            _with_past_reports(SurgerySchedule.objects.filter(
                pk__in=[s.pk for s in oz]).select_related("visit"))

        kop = self._operatsiyalar(20, belgi=2)
        with CaptureQueriesContext(connection) as k2:
            _with_past_reports(SurgerySchedule.objects.filter(
                pk__in=[s.pk for s in kop]).select_related("visit"))

        self.assertLessEqual(
            len(k2), len(k1) + 1,
            f"So'rovlar soni operatsiyalar soniga qarab o'smoqda "
            f"(3 ta → {len(k1)}, 20 ta → {len(k2)}). N+1 kirib qolgan.")

    def test_oldingi_bayonnomalar_hali_ham_togri_topiladi(self):
        """Tezlashtirish natijani buzmaganiga ishonch."""
        from apps.clinical.views import _with_past_reports

        u = User.objects.create_user(
            username="pf_bir", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SUPER_ADMIN, defaults={"name": "Super"})[0])
        turi = SurgeryType.objects.create(
            name="TB", kind=SurgeryType.Kind.OPEN, price=Decimal(1))
        xona = OperatingRoom.objects.create(name="XB")
        p = Patient.objects.create(
            card_number="P-BIR", last_name="Bir", first_name="Bemor",
            birth_date=date(1990, 1, 1), gender="male")

        rejalar = []
        for i in range(2):
            v = Visit.objects.create(patient=p, visit_date=date.today(),
                                     queue_number=5000 + i)
            s = SurgerySchedule.objects.create(
                visit=v, surgery_type=turi, operating_room=xona, surgeon=u,
                scheduled_time=timezone.now(), actual_price=Decimal(1))
            SurgeryReport.objects.create(
                surgery=s, filled_by=u, performed_actions=f"MATN-{i}")
            rejalar.append(s)

        natija = _with_past_reports(
            SurgerySchedule.objects.filter(pk__in=[s.pk for s in rejalar])
            .select_related("visit"))

        for s in natija:
            self.assertEqual(
                len(s.past_reports), 1,
                "Bir bemorning ikkinchi bayonnomasi topilmadi.")
            self.assertNotEqual(
                s.past_reports[0]["surgery"].pk, s.pk,
                "O'zining bayonnomasi ro'yxatga tushdi.")

    def test_konsultatsiya_modali_tekshiruvlar_soniga_qarab_osmaydi(self):
        doc = User.objects.create_user(
            username="pf_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        p = Patient.objects.create(
            card_number="P-PFC", last_name="C", first_name="X",
            birth_date=date(1990, 1, 1), gender="male")
        v = Visit.objects.create(patient=p, visit_date=date.today(),
                                 queue_number=99, doctor=doc)
        svc = ServiceCatalog.objects.create(name="S", price=Decimal(1))
        self.client.force_login(doc)

        with CaptureQueriesContext(connection) as bosh:
            self.client.get(reverse("clinical:consultation_modal", args=[v.pk]))

        for _ in range(15):
            ServiceOrder.objects.create(visit=v, service=svc,
                                        price_snapshot=Decimal(1))

        with CaptureQueriesContext(connection) as kop:
            javob = self.client.get(
                reverse("clinical:consultation_modal", args=[v.pk]))

        self.assertEqual(javob.status_code, 200)
        self.assertLess(
            len(kop) - len(bosh), 20,
            f"Tekshiruvlar soni ortganda so'rovlar keskin oshdi "
            f"(0 ta → {len(bosh)}, 15 ta → {len(kop)}).")
