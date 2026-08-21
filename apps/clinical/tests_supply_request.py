"""Operatsion blok: ombor zayavkasi, psixotroplar va epizod holati.

Nega bu testlar bor
-------------------
1. Anesteziolog ombori qat'iy hisobdagi psixotrop dorilar uchun, lekin
   tanlash ro'yxatiga oddiy sarf-material ham chiqardi. Hamshira uni
   tanlaydi, server esa «psixotrop emas» deb rad etadi — ish qilingandek
   tuyulib, hech narsa saqlanmasdi.

2. Operatsion hamshirada material so'rashning yo'li yo'q edi. U
   anesteziolog zayavkasidan yozardi va server «psixotrop emas» deb rad
   etardi — ish qilingandek tuyulardi.

3. Statsionardan javob berilganda kravat bo'shaydi, lekin epizod
   «Yotibdi» holatida qolaverardi — bemor uyiga ketgan bo'lsa ham
   ro'yxatda yotgan bo'lib turardi.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, AnesthesiaStock, Bed, InpatientStay, Room,
    SurgerySchedule, SurgerySupplyRequest, SurgeryType, Visit,
)
from apps.patients.models import Patient


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class SupplyRequestTest(TestCase):
    def setUp(self):
        self.hamshira = User.objects.create_user(
            username="opnurse", password="x",
            role=rol(Role.Code.WARD_NURSE, "Palata hamshirasi"))
        self.hamshira.extra_roles.add(
            rol(Role.Code.OPERATING_NURSE, "Operatsion hamshira"))
        # Zayavkani anesteziolog beradi — ombor uniki
        self.omborchi = User.objects.create_user(
            username="anest_ombor", password="x",
            role=rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))
        self.jarroh = User.objects.create_user(
            username="jarroh_s2", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"))

        bemor = Patient.objects.create(
            first_name="Ali", last_name="Aliyev", birth_date="1990-01-01",
            gender="male", birth_certificate="MB-3213211")
        visit = Visit.objects.create(
            patient=bemor, doctor=self.jarroh, visit_date=timezone.now(),
            queue_number=1, status=Visit.Status.IN_PROGRESS)
        self.surgery = SurgerySchedule.objects.create(
            visit=visit, surgery_type=SurgeryType.objects.create(
                name="Appendektomiya", price=100),
            surgeon=self.jarroh, scheduled_time=timezone.now())

        self.shprits = AnesthesiaStock.objects.create(
            name="Shprits 5ml", quantity=100, selling_price=1000,
            is_psychotropic=False)
        self.bint = AnesthesiaStock.objects.create(
            name="Bint", quantity=50, selling_price=500, is_psychotropic=False)
        self.psixo = AnesthesiaStock.objects.create(
            name="Ketamin", quantity=5, selling_price=9000,
            is_psychotropic=True)

        self.add_url = reverse("clinical:supply_request_add_item",
                               args=[self.surgery.pk])
        self.send_url = reverse("clinical:supply_request_send",
                                args=[self.surgery.pk])

    # ---------- hamshira ----------

    def test_hamshira_zayavkaga_qoshadi(self):
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url,
                         {"stock_id": str(self.shprits.pk), "quantity": "5"})
        z = SurgerySupplyRequest.objects.get(surgery=self.surgery)
        self.assertEqual(z.status, SurgerySupplyRequest.Status.DRAFT)
        self.assertEqual(z.items.count(), 1)
        self.assertEqual(z.items.first().quantity, Decimal("5"))

    def test_bir_mahsulot_ikki_qator_bolmaydi(self):
        """Ombor ro'yxatni o'qiydi — bitta nom ikki joyda turmasin."""
        self.client.force_login(self.hamshira)
        for _ in range(2):
            self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                            "quantity": "3"})
        z = SurgerySupplyRequest.objects.get(surgery=self.surgery)
        self.assertEqual(z.items.count(), 1)
        self.assertEqual(z.items.first().quantity, Decimal("6"))

    def test_manfiy_son_qabul_qilinmaydi(self):
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                        "quantity": "-2"})
        self.assertFalse(
            SurgerySupplyRequest.objects.filter(
                surgery=self.surgery, items__isnull=False).exists())

    def test_bosh_zayavka_yuborilmaydi(self):
        self.client.force_login(self.hamshira)
        SurgerySupplyRequest.objects.create(surgery=self.surgery)
        self.client.post(self.send_url)
        self.assertEqual(
            SurgerySupplyRequest.objects.get(surgery=self.surgery).status,
            SurgerySupplyRequest.Status.DRAFT)

    def test_yuborilgandan_keyin_ozgartirib_bolmaydi(self):
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                        "quantity": "5"})
        self.client.post(self.send_url)
        self.client.post(self.add_url, {"stock_id": str(self.bint.pk),
                                        "quantity": "2"})
        z = SurgerySupplyRequest.objects.get(surgery=self.surgery)
        self.assertEqual(z.status, SurgerySupplyRequest.Status.SENT)
        self.assertEqual(z.items.count(), 1)

    # ---------- ombor ----------

    def test_ombor_royxatda_koradi(self):
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                        "quantity": "5"})
        self.client.post(self.send_url)

        self.client.force_login(self.omborchi)
        html = self.client.get(
            reverse("clinical:supply_requests")).content.decode()
        self.assertIn("Shprits 5ml", html)

    def test_ombor_kamroq_berishi_mumkin(self):
        """Omborda so'ralganning hammasi bo'lmasligi mumkin."""
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                        "quantity": "10"})
        self.client.post(self.send_url)
        z = SurgerySupplyRequest.objects.get(surgery=self.surgery)
        qator = z.items.first()

        self.client.force_login(self.omborchi)
        self.client.post(
            reverse("clinical:supply_request_issue", args=[z.pk]),
            {f"issued_{qator.pk}": "4"})

        qator.refresh_from_db()
        z.refresh_from_db()
        self.assertEqual(qator.issued_quantity, Decimal("4"))
        self.assertEqual(z.status, SurgerySupplyRequest.Status.ISSUED)
        self.assertEqual(z.issued_by, self.omborchi)

    def test_rad_etish_sababi_saqlanadi(self):
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                        "quantity": "1"})
        self.client.post(self.send_url)
        z = SurgerySupplyRequest.objects.get(surgery=self.surgery)

        self.client.force_login(self.omborchi)
        self.client.post(reverse("clinical:supply_request_reject", args=[z.pk]),
                         {"reason": "Omborda qolmagan"})
        z.refresh_from_db()
        self.assertEqual(z.status, SurgerySupplyRequest.Status.REJECTED)
        self.assertEqual(z.notes, "Omborda qolmagan")

    def test_yuborilmagan_zayavkani_berib_bolmaydi(self):
        z = SurgerySupplyRequest.objects.create(surgery=self.surgery)
        self.client.force_login(self.omborchi)
        self.client.post(reverse("clinical:supply_request_issue", args=[z.pk]))
        z.refresh_from_db()
        self.assertEqual(z.status, SurgerySupplyRequest.Status.DRAFT)

    def test_psixotropni_hamshira_soramaydi(self):
        """Psixotrop qat'iy hisobda — faqat anesteziolog zayavka qiladi."""
        self.client.force_login(self.hamshira)
        self.client.post(self.add_url, {"stock_id": str(self.psixo.pk),
                                        "quantity": "1"})
        z = SurgerySupplyRequest.objects.filter(surgery=self.surgery).first()
        self.assertTrue(z is None or z.items.count() == 0)

    def test_psixotrop_tanlash_royxatiga_chiqmaydi(self):
        self.client.force_login(self.hamshira)
        html = self.client.get(
            reverse("clinical:surgery_process",
                    args=[self.surgery.pk])).content.decode()
        boshi = html.find('name="stock_id"', html.find("Operatsion hamshira zayavkasi"))
        select = html[boshi:html.find("</select>", boshi)]
        self.assertIn("Shprits 5ml", select)
        self.assertNotIn("Ketamin", select)

    def test_begona_rol_zayavka_qila_olmaydi(self):
        lab = User.objects.create_user(
            username="lab_x", password="x", role=rol(Role.Code.LAB, "Lab"))
        self.client.force_login(lab)
        r = self.client.post(self.add_url, {"stock_id": str(self.shprits.pk),
                                            "quantity": "1"})
        self.assertNotEqual(r.status_code, 200)
        self.assertFalse(SurgerySupplyRequest.objects.exists())


class PsychotropicOnlyTest(TestCase):
    """Anesteziolog zayavkasida faqat psixotroplar chiqsin."""

    def setUp(self):
        self.anest = User.objects.create_user(
            username="anest_p", password="x",
            role=rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))
        jarroh = User.objects.create_user(
            username="jarroh_p", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"))
        bemor = Patient.objects.create(
            first_name="Gul", last_name="Gulova", birth_date="1990-01-01",
            gender="female", birth_certificate="MB-9879871")
        visit = Visit.objects.create(
            patient=bemor, doctor=jarroh, visit_date=timezone.now(),
            queue_number=2, status=Visit.Status.IN_PROGRESS)
        self.surgery = SurgerySchedule.objects.create(
            visit=visit, surgery_type=SurgeryType.objects.create(
                name="Churra", price=100),
            surgeon=jarroh, scheduled_time=timezone.now())

        self.psixo = AnesthesiaStock.objects.create(
            name="Ketamin", quantity=10, selling_price=1000,
            is_psychotropic=True)
        self.oddiy = AnesthesiaStock.objects.create(
            name="Doka salfetka", quantity=50, selling_price=500,
            is_psychotropic=False)

    def _sahifa(self):
        self.client.force_login(self.anest)
        return self.client.get(
            reverse("clinical:surgery_process",
                    args=[self.surgery.pk])).content.decode()

    def test_psixotrop_royxatda_bor(self):
        self.assertIn("Ketamin", self._sahifa())

    def test_tanlash_royxati_faqat_psixotrop(self):
        html = self._sahifa()
        boshi = html.find('name="stock_id"')
        oxiri = html.find("</select>", boshi)
        select = html[boshi:oxiri]
        self.assertIn("Ketamin", select)
        self.assertNotIn("Doka salfetka", select)

    def test_oddiy_material_server_darajasida_ham_rad_etiladi(self):
        self.client.force_login(self.anest)
        self.client.post(
            reverse("clinical:anesthesia_request_add_item",
                    args=[self.surgery.pk]),
            {"stock_id": str(self.oddiy.pk), "quantity": "1"})
        req = getattr(self.surgery, "anesthesia_request", None)
        self.assertTrue(req is None or req.items.count() == 0)


class EpisodePatientLeftTest(TestCase):
    """Javob berilgach «Yotibdi» deb ko'rsatilmasin."""

    def setUp(self):
        self.doctor = User.objects.create_user(
            username="doc_left", password="x",
            role=rol(Role.Code.THERAPIST, "Terapevt"))
        self.patient = Patient.objects.create(
            first_name="Asror", last_name="Azatbayev",
            birth_date="2004-01-01", gender="male",
            birth_certificate="MB-1010101")
        self.visit = Visit.objects.create(
            patient=self.patient, doctor=self.doctor,
            visit_date=timezone.now(), queue_number=3,
            status=Visit.Status.IN_PROGRESS)

        xona = Room.objects.create(name="1xona")
        self.bed = Bed.objects.create(room=xona, number="1A")
        self.stay = InpatientStay.objects.create(
            visit=self.visit, bed=self.bed,
            admission_date=timezone.now())
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doctor,
            status=AdmissionEpisode.Status.ADMITTED, stay=self.stay)

    def test_yotayotgan_bemor_yotibdi(self):
        self.assertFalse(self.episode.patient_left)
        self.assertEqual(self.episode.display_status, "Yotqizildi")

    def test_javob_berilgach_yotibdi_emas(self):
        self.stay.status = InpatientStay.Status.DISCHARGED
        self.stay.discharge_date = timezone.now()
        self.stay.save(update_fields=["status", "discharge_date"])

        ep = AdmissionEpisode.objects.get(pk=self.episode.pk)
        self.assertTrue(ep.patient_left)
        self.assertIn("vipiska kutilmoqda", ep.display_status)

    def test_yotishsiz_epizod_yiqilmaydi(self):
        ep = AdmissionEpisode.objects.create(
            patient=self.patient, referred_by=self.doctor,
            status=AdmissionEpisode.Status.SENT)
        self.assertFalse(ep.patient_left)

    def test_royxatda_ham_togri_chiqadi(self):
        self.stay.status = InpatientStay.Status.DISCHARGED
        self.stay.save(update_fields=["status"])

        hamshira = User.objects.create_user(
            username="nurse_left", password="x",
            role=rol(Role.Code.WARD_NURSE, "Palata hamshirasi"))
        self.client.force_login(hamshira)
        html = self.client.get(
            reverse("clinical:nurse_incoming")).content.decode()
        self.assertIn("vipiska kutilmoqda", html)


class ItemMarkFormTest(TestCase):
    """«Ishlatildi / Ishlatilmadi» tugmalari ishlashi.

    Tugmalar tayyorlash formasi ICHIDA turadi. Ilgari ular o'z <form>
    iga o'ralgan edi — brauzer ichma-ich formani tashlab yuboradi va
    bosilganda tashqi forma («Tayyorlashni saqlash») yuborilardi:
    belgi hech qachon saqlanmasdi va hech qanday xato ham chiqmasdi.
    """

    def setUp(self):
        from apps.clinical.models import SurgicalItem

        self.hamshira = User.objects.create_user(
            username="opn_mark", password="x",
            role=rol(Role.Code.WARD_NURSE, "Palata hamshirasi"))
        self.hamshira.extra_roles.add(
            rol(Role.Code.OPERATING_NURSE, "Operatsion hamshira"))
        jarroh = User.objects.create_user(
            username="jarroh_mark", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"))
        bemor = Patient.objects.create(
            first_name="Nur", last_name="Nurova", birth_date="1990-01-01",
            gender="female", birth_certificate="MB-2222222")
        visit = Visit.objects.create(
            patient=bemor, doctor=jarroh, visit_date=timezone.now(),
            queue_number=9, status=Visit.Status.IN_PROGRESS)
        self.surgery = SurgerySchedule.objects.create(
            visit=visit, surgery_type=SurgeryType.objects.create(
                name="Churra", price=100),
            surgeon=jarroh, scheduled_time=timezone.now())

        self.item = SurgicalItem.objects.create(
            name="Belyo to'plami (biks) #1",
            item_type=SurgicalItem.Type.LINEN,
            steril_method=SurgicalItem.SterilMethod.AUTOCLAVE,
            status=SurgicalItem.Status.IN_USE)
        self.surgery.items_used.add(self.item)

    def _sahifa(self):
        self.client.force_login(self.hamshira)
        return self.client.get(
            reverse("clinical:surgery_process",
                    args=[self.surgery.pk])).content.decode()

    def test_belgilash_formasi_tayyorlash_formasidan_tashqarida(self):
        html = self._sahifa()
        tayyorlash_oxiri = html.find("Tayyorlashni saqlash")
        mark_forma = html.find(f'id="markForm{self.item.pk}"')
        self.assertGreater(mark_forma, -1, "belgilash formasi topilmadi")
        self.assertGreater(
            mark_forma, tayyorlash_oxiri,
            "belgilash formasi tayyorlash formasi ichida qolib ketgan")

    def test_tugma_formaga_ulangan(self):
        self.assertIn(f'form="markForm{self.item.pk}"', self._sahifa())

    def test_ishlatildi_saqlanadi(self):
        from apps.clinical.models import SurgicalItem

        self.client.force_login(self.hamshira)
        self.client.post(
            reverse("clinical:surgery_item_mark", args=[self.item.pk]),
            {"surgery_id": str(self.surgery.pk), "action": "used"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, SurgicalItem.Status.USED)

    def test_ishlatilmadi_saqlanadi(self):
        from apps.clinical.models import SurgicalItem

        self.client.force_login(self.hamshira)
        self.client.post(
            reverse("clinical:surgery_item_mark", args=[self.item.pk]),
            {"surgery_id": str(self.surgery.pk), "action": "unused"})
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, SurgicalItem.Status.READY)
        self.assertNotIn(self.item, self.surgery.items_used.all())
