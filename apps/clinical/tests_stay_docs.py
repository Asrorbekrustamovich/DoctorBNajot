"""STATSIONAR HUJJATLARI — bemorning hamma yozuvi shu yerda bo'lishi kerak.

Ikki HAQIQIY XATO topildi:

1. Tekshiruvlar `created_at >= admission_date` bo'yicha filtrlanardi, ya'ni
   faqat YOTQIZILGANDAN KEYIN tayinlanganlari ko'rinardi. Amalda oqim
   teskari: shifokor ambulator ko'rikda tahlil buyuradi, natija keladi va
   SHUNDAN KEYIN bemor yotqiziladi. Ya'ni aynan yotqizishga asos bo'lgan
   tahlillar hujjatda ko'rinmasdi.

2. Shifokorning klinik yozuvlari (shikoyat, anamnez, klinik tashxis,
   MKB-10) epizodda saqlanadi va bu sahifaga UMUMAN chiqmasdi. Hujjatda
   faqat hamshira yozuvlari — checklist, ukollar, dorilar — bor edi va u
   tibbiy asossiz ko'rinardi.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, Bed, EpisodeDiagnosis, ICD10Code, InpatientStay,
    ProcedureRecord, Room, ServiceCatalog, ServiceOrder,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


class StatsionarHujjatlariTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="sh_doc", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.SUPER_ADMIN, defaults={"name": "Super"})[0])
        self.patient = Patient.objects.create(
            card_number="P-SH1", last_name="Hujjatov", first_name="Bemor",
            birth_date=date(1990, 1, 1), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(), queue_number=1)

        # 1) AMBULATOR ko'rikda tayinlangan tekshiruv — yotishdan OLDIN
        self.eski_svc = ServiceCatalog.objects.create(
            name="QABULDA TAYINLANGAN UZI", price=1)
        self.eski_order = ServiceOrder.objects.create(
            visit=self.visit, service=self.eski_svc,
            price_snapshot=Decimal(1),
            result_text="Natija bor", result_at=timezone.now())

        room = Room.objects.create(name="SH-xona")
        bed = Bed.objects.create(room=room, number="1A")
        self.stay = InpatientStay.objects.create(
            visit=self.visit, bed=bed, status=InpatientStay.Status.ACTIVE,
            admission_date=timezone.now())

        # 2) Yotgandan KEYIN tayinlangan
        self.yangi_svc = ServiceCatalog.objects.create(
            name="YOTGANDA TAYINLANGAN QON", price=1)
        ServiceOrder.objects.create(
            visit=self.visit, service=self.yangi_svc, price_snapshot=Decimal(1))

        ProcedureRecord.objects.create(
            stay=self.stay, nurse=self.doc, name="UKOL YOZUVI")

        self.icd = ICD10Code.objects.get_or_create(
            code="K35.8", defaults={"name": "O'tkir appendisit"})[0]
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, stay=self.stay,
            referred_by=self.doc,
            reason="MUROJAAT SABABI", complaints="SHIKOYAT MATNI",
            anamnesis_morbi="ANAMNEZ MATNI",
            clinical_diagnosis="KLINIK TASHXIS MATNI",
            status=AdmissionEpisode.Status.ADMITTED)
        EpisodeDiagnosis.objects.create(
            episode=self.episode, icd=self.icd,
            kind=EpisodeDiagnosis.Kind.MAIN)

        self.url = reverse("clinical:stay_documentation", args=[self.stay.id])
        self.client.force_login(self.doc)

    # ---------------- TEKSHIRUVLAR ----------------
    def test_yotishdan_oldin_tayinlangan_tekshiruv_ham_chiqadi(self):
        h = self.client.get(self.url).content.decode()
        self.assertIn(
            "QABULDA TAYINLANGAN UZI", h,
            "Yotqizishga asos bo'lgan tahlil hujjatda ko'rinmadi.")

    def test_yotgandan_keyingisi_ham_chiqadi(self):
        h = self.client.get(self.url).content.decode()
        self.assertIn("YOTGANDA TAYINLANGAN QON", h)

    def test_bekor_qilingan_tekshiruv_chiqmaydi(self):
        self.eski_order.status = ServiceOrder.Status.CANCELLED
        self.eski_order.save()
        h = self.client.get(self.url).content.decode()
        self.assertNotIn("QABULDA TAYINLANGAN UZI", h)

    def test_boshqa_bemorning_tekshiruvi_qoshilmaydi(self):
        """Filtrni kengaytirganda begona yozuv kirib qolmasin."""
        boshqa = Patient.objects.create(
            card_number="P-SH9", last_name="Begona", first_name="X",
            birth_date=date(1990, 1, 1), gender="male")
        bv = Visit.objects.create(patient=boshqa, visit_date=date.today(),
                                  queue_number=9)
        svc = ServiceCatalog.objects.create(name="BEGONA TEKSHIRUV", price=1)
        ServiceOrder.objects.create(visit=bv, service=svc,
                                    price_snapshot=Decimal(1))

        h = self.client.get(self.url).content.decode()
        self.assertNotIn("BEGONA TEKSHIRUV", h)

    # ---------------- KLINIK YOZUVLAR ----------------
    def test_korik_yozuvlari_chiqadi(self):
        h = self.client.get(self.url).content.decode()
        for matn in ["MUROJAAT SABABI", "SHIKOYAT MATNI",
                     "ANAMNEZ MATNI", "KLINIK TASHXIS MATNI"]:
            with self.subTest(matn=matn):
                self.assertIn(matn, h,
                              "Shifokorning klinik yozuvi hujjatda yo'q — "
                              "hujjat tibbiy asossiz ko'rinadi.")

    def test_mkb10_tashxis_chiqadi(self):
        h = self.client.get(self.url).content.decode()
        self.assertIn("K35.8", h)

    def test_bosh_bloklar_chiqmaydi(self):
        """To'ldirilmagan bo'limlar hujjatni bekorga cho'zmasin."""
        resp = self.client.get(self.url)
        nomlar = [n for n, _ in resp.context["episode_bloklar"]]
        self.assertNotIn("Nevrologik holati", nomlar)
        self.assertIn("Shikoyatlar", nomlar)

    def test_epizod_yotishga_boglanmagan_bolsa_ham_topiladi(self):
        """Eski ma'lumotlarda `stay` bog'lanmagan bo'lishi mumkin.

        Bunday holatda ham tashrif orqali topilishi kerak, aks holda
        eski yotishlarda hujjat bo'sh chiqadi.
        """
        AdmissionEpisode.objects.filter(pk=self.episode.pk).update(stay=None)
        self.stay.refresh_from_db()

        h = self.client.get(self.url).content.decode()
        self.assertIn("SHIKOYAT MATNI", h)

    def test_epizodsiz_yotishda_sahifa_ochiladi(self):
        """Teskari nazorat: epizod bo'lmasa ham sahifa yiqilmasin."""
        self.episode.delete()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["episode_bloklar"], [])

    # ---------------- RASMIY BLANK ----------------
    def test_rasmiy_blankda_ham_klinik_yozuvlar_bor(self):
        """Chop etiladigan varaqa shikoyat va tashxisdan boshlanadi."""
        h = self.client.get(self.url, {"official": "1"}).content.decode()
        self.assertIn("Klinik yozuvlar va tashxis", h)
        self.assertIn("SHIKOYAT MATNI", h)
        self.assertIn("K35.8", h)
        self.assertIn("QABULDA TAYINLANGAN UZI", h)
