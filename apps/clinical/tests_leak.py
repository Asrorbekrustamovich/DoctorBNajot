"""Vipiska FAQAT O'Z EPIZODINI qamrashi kerak.

HAQIQIY XATO: `_episode_dossier` bemorning BARCHA yotishlaridagi
muolajalarni yig'ardi. Bemor mart oyida bir marta, avgustda ikkinchi
marta yotgan bo'lsa, avgustdagi vipiskaga martdagi ukollar ham tushib
qolardi — ustiga-ustak ptechkada AVTOMATIK belgilangan holatda, ya'ni
shifokor sezmasa rasmiy hujjatga chiqib ketardi.

Vipiska — bitta yotishning hisoboti.
"""
from datetime import date, timedelta
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, Bed, InpatientStay, ProcedureRecord, Room,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


class LeakTests(TestCase):
    def test_eski_yotqizilish_yangi_vipiskaga_tushmasligi_kerak(self):
        doc = User.objects.create_user(
            username="lk_doc", password="x",
            role=Role.objects.get_or_create(code="doctor", defaults={"name": "Sh"})[0])
        p = Patient.objects.create(card_number="P-LK1", last_name="Leak",
                                   first_name="Test", birth_date=date(1990, 1, 1),
                                   gender="male")
        room = Room.objects.create(name="LK-1")
        bed1 = Bed.objects.create(room=room, number="A")
        bed2 = Bed.objects.create(room=room, number="B")

        # --- 1-EPIZOD (mart oyida, allaqachon yopilgan)
        v1 = Visit.objects.create(patient=p, visit_date=date(2026, 3, 1), queue_number=1)
        s1 = InpatientStay.objects.create(visit=v1, bed=bed1,
                                          status=InpatientStay.Status.DISCHARGED)
        ProcedureRecord.objects.create(stay=s1, nurse=doc, name="ESKI UKOL (1-epizod)")
        AdmissionEpisode.objects.create(
            patient=p, visit=v1, referred_by=doc, reason="Eski holat",
            status=AdmissionEpisode.Status.DISCHARGED)

        # --- 2-EPIZOD (bugun)
        v2 = Visit.objects.create(patient=p, visit_date=date(2026, 8, 11), queue_number=2)
        s2 = InpatientStay.objects.create(visit=v2, bed=bed2)
        ProcedureRecord.objects.create(stay=s2, nurse=doc, name="YANGI UKOL (2-epizod)")
        ep2 = AdmissionEpisode.objects.create(
            patient=p, visit=v2, stay=s2, referred_by=doc, reason="Yangi holat",
            status=AdmissionEpisode.Status.ADMITTED)

        self.client.force_login(doc)
        r = self.client.get(reverse("clinical:episode_discharge", args=[ep2.pk]))

        # MUHIMI: eski ukol vipiskaga TUSHMASLIGI kerak. Uni «Oldingi
        # yotishlar» modalida KO'RSATISH aybsiz — u yerda hujjat emas,
        # nusxalash uchun ma'lumotnoma. Shuning uchun sahifadagi matnni
        # emas, ptechkali ro'yxatni tekshiramiz.
        nomlar = [p.name for p in r.context["all_procedures"]]
        self.assertIn("YANGI UKOL (2-epizod)", nomlar)
        self.assertNotIn(
            "ESKI UKOL (1-epizod)", nomlar,
            "Oldingi yotqizilish muolajasi yangi vipiskaning ro'yxatiga tushdi!")

        # Chop etiladigan hujjatda ham bo'lmasligi kerak — yakuniy dalil.
        from apps.clinical.models import DischargeSummary
        DischargeSummary.objects.create(episode=ep2, discharged_by=doc)
        blank = self.client.get(
            reverse("clinical:discharge_print", args=[ep2.pk])).content.decode()
        self.assertIn("YANGI UKOL", blank)
        self.assertNotIn("ESKI UKOL", blank,
                         "Oldingi yotqizilish muolajasi rasmiy vipiskaga chiqdi!")


class VipiskaSelectionTests(TestCase):
    """Tashxis tarixi va matnni qisqartirish.

    Bemor bir necha marta yotgan bo'lsa, hamma tashxis va hamma natijani
    ko'r-ko'rona qo'shsak vipiska bir necha varaq bo'lib ketadi. Shuning
    uchun shifokor ptechka bilan tanlaydi va matnni qisqartira oladi.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.clinical.models import (
            EpisodeDiagnosis, ICD10Code, ServiceCatalog, ServiceCategory,
            ServiceOrder, ServiceResultRow,
        )
        cls.doc = User.objects.create_user(
            username="vs_doc", password="x",
            role=Role.objects.get_or_create(code="doctor", defaults={"name": "Sh"})[0])
        cls.p = Patient.objects.create(
            card_number="P-VS1", last_name="Vipiska", first_name="Test",
            birth_date=date(1980, 1, 1), gender="male")

        cls.icd_old = ICD10Code.objects.get_or_create(
            code="E11.9", defaults={"name": "Qandli diabet"})[0]
        cls.icd_new = ICD10Code.objects.get_or_create(
            code="K35.8", defaults={"name": "O'tkir appendisit"})[0]

        # 1-epizod (eski) — surunkali tashxis
        v1 = Visit.objects.create(patient=cls.p, visit_date=date(2026, 3, 1),
                                  queue_number=11)
        cls.ep_old = AdmissionEpisode.objects.create(
            patient=cls.p, visit=v1, referred_by=cls.doc, reason="Eski",
            status=AdmissionEpisode.Status.DISCHARGED)
        cls.dx_old = EpisodeDiagnosis.objects.create(
            episode=cls.ep_old, icd=cls.icd_old,
            kind=EpisodeDiagnosis.Kind.MAIN)

        # 2-epizod (joriy)
        cls.v2 = Visit.objects.create(patient=cls.p, visit_date=date(2026, 8, 11),
                                      queue_number=12)
        cls.ep = AdmissionEpisode.objects.create(
            patient=cls.p, visit=cls.v2, referred_by=cls.doc, reason="Yangi",
            status=AdmissionEpisode.Status.ADMITTED)
        cls.dx_new = EpisodeDiagnosis.objects.create(
            episode=cls.ep, icd=cls.icd_new, kind=EpisodeDiagnosis.Kind.MAIN)

        cat = ServiceCategory.objects.create(name="VS lab", button_label="+Analiz")
        svc = ServiceCatalog.objects.create(name="Qon tahlili", price=0, category=cat)
        cls.order = ServiceOrder.objects.create(
            visit=cls.v2, service=svc, status=ServiceOrder.Status.COMPLETED,
            result_at=timezone.now(),
            result_text="Juda uzun asl natija matni, hammasi kerak emas.")
        ServiceResultRow.objects.create(
            order=cls.order, name="Leykotsit", value="12.0", unit="10^9/l")

    def setUp(self):
        self.client.force_login(self.doc)
        self.url = reverse("clinical:episode_discharge", args=[self.ep.pk])

    # ---------------------------------------------------------- tashxislar
    def test_eski_tashxis_royxatda_korinadi(self):
        r = self.client.get(self.url)
        h = r.content.decode()
        self.assertIn("E11.9", h, "Oldingi yotishdagi tashxis ro'yxatda yo'q")
        self.assertIn("K35.8", h)

    def test_shu_epizod_tashxisi_avtomatik_belgilanadi(self):
        r = self.client.get(self.url)
        dx = {d.pk: d for d in r.context["all_diagnoses"]}
        self.assertTrue(dx[self.dx_new.pk].vip_checked, "Shu epizod tashxisi belgilanmagan")
        self.assertFalse(dx[self.dx_old.pk].vip_checked, "Eski tashxis o'zi belgilanib qolgan")

    def test_eski_tashxisni_qoshish_mumkin(self):
        self.client.post(self.url, {
            "outcome": "improved",
            "selected_diagnoses": [str(self.dx_new.pk), str(self.dx_old.pk)],
        })
        self.ep.refresh_from_db()
        self.assertEqual(len(self.ep.discharge.selected_diagnosis_ids), 2)

        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        h = r.content.decode()
        self.assertIn("E11.9", h, "Belgilangan eski tashxis blankka tushmadi")
        self.assertIn("K35.8", h)

    def test_belgilanmagan_tashxis_blankka_tushmaydi(self):
        self.client.post(self.url, {
            "outcome": "improved",
            "selected_diagnoses": [str(self.dx_new.pk)],   # eskisi yo'q
        })
        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        h = r.content.decode()
        self.assertNotIn("E11.9", h, "Belgilanmagan tashxis blankka tushdi")
        self.assertIn("K35.8", h)

    # ------------------------------------------------------------- matnlar
    def test_qisqartirilgan_matn_saqlanadi_va_chiqadi(self):
        self.client.post(self.url, {
            "outcome": "improved",
            "selected_orders": [str(self.order.pk)],
            "selected_diagnoses": [str(self.dx_new.pk)],
            f"text_{self.order.pk}": "Leykotsitoz aniqlandi.",
        })
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.discharge.item_texts[str(self.order.pk)],
                         "Leykotsitoz aniqlandi.")

        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        h = r.content.decode()
        self.assertIn("Leykotsitoz aniqlandi", h)
        self.assertNotIn("Juda uzun asl natija", h,
                         "Qisqartirilgan bo'lsa ham asl matn chiqdi")

    def test_matn_yozilmasa_asl_natija_chiqadi(self):
        self.client.post(self.url, {
            "outcome": "improved",
            "selected_orders": [str(self.order.pk)],
            "selected_diagnoses": [str(self.dx_new.pk)],
        })
        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        h = r.content.decode()
        self.assertIn("Juda uzun asl natija", h)
        self.assertIn("Leykotsit", h)

    def test_asl_natija_ozgarmaydi(self):
        """Laboratoriya yozgan natija tibbiy hujjat — unga tegilmaydi."""
        self.client.post(self.url, {
            "outcome": "improved",
            "selected_orders": [str(self.order.pk)],
            f"text_{self.order.pk}": "Qisqa",
        })
        self.order.refresh_from_db()
        self.assertEqual(self.order.result_text,
                         "Juda uzun asl natija matni, hammasi kerak emas.")

    def test_qayta_ochilganda_tanlov_saqlanib_qoladi(self):
        self.client.post(self.url, {
            "outcome": "improved",
            "selected_diagnoses": [str(self.dx_old.pk)],
            f"text_{self.order.pk}": "Mening matnim",
        })
        r = self.client.get(self.url)
        dx = {d.pk: d for d in r.context["all_diagnoses"]}
        self.assertTrue(dx[self.dx_old.pk].vip_checked)
        self.assertFalse(dx[self.dx_new.pk].vip_checked)
        self.assertIn("Mening matnim", r.content.decode())
