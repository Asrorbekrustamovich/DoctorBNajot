"""BEKOR QILINGAN NAVBAT VA TEKSHIRUV — qarz qolmasligi kerak.

HAQIQIY XATO: chek yaratilayotganda tashrifning O'Z HOLATI umuman
tekshirilmasdi. Registrator navbatni bekor qilsa ham qabul narxi va
tayinlangan tekshiruvlar chekda qolib ketardi: bemor kelmagan, xizmat
ko'rsatilmagan, lekin tizim undan pul talab qilib turardi va u «to'lov
kutayotganlar» ro'yxatidan tushmasdi.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.billing.models import Invoice
from apps.billing.selectors import pending_summary
from apps.clinical.models import DoctorPrice, ServiceCatalog, ServiceOrder
from apps.patients.models import Patient
from apps.registration.models import Visit
from apps.registration.services import visit_transition


class BekorQilishTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="bq_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.patient = Patient.objects.create(
            card_number="P-BQ1", last_name="Bekorov", first_name="Test",
            birth_date=date(1990, 1, 1), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(),
            queue_number=1, doctor=self.doc)
        self.svc = ServiceCatalog.objects.create(name="EKG tekshiruvi", price=30000)

    def _tekshiruv(self, narx=30000):
        return ServiceOrder.objects.create(
            visit=self.visit, service=self.svc,
            price_snapshot=Decimal(narx))

    # ---------------- NAVBAT BEKOR QILINGANDA ----------------
    def test_navbat_bekor_qilinsa_qarz_qolmaydi(self):
        self._tekshiruv()
        self.assertEqual(pending_summary()["count"], 1)

        visit_transition(visit=self.visit,
                         new_status=Visit.Status.CANCELLED, reason="Bemor ketdi")

        self.assertEqual(
            pending_summary()["count"], 0,
            "Navbat bekor qilingandan keyin ham to'lov talab qilinmoqda.")

    def test_bekor_qilingan_navbatning_cheki_yopiladi(self):
        self._tekshiruv()
        visit_transition(visit=self.visit,
                         new_status=Visit.Status.CANCELLED, reason="x")

        inv = Invoice.objects.get(visit=self.visit)
        self.assertEqual(inv.status, Invoice.Status.CANCELLED)
        self.assertEqual(inv.total_amount, 0)
        self.assertEqual(inv.debt, 0, "Bekor qilingan navbatda qarz qoldi.")

    def test_qabul_narxi_ham_yoqoladi(self):
        """Shifokor ko'rigi narxi ham chekdan chiqishi kerak."""
        DoctorPrice.objects.create(doctor=self.doc, price=Decimal(50000),
                                   is_active=True)
        # Narx chekka tushishi uchun chekni qayta hisoblaymiz
        from apps.billing.services import generate_invoice_for_visit
        generate_invoice_for_visit(self.visit)
        self.assertGreater(pending_summary()["count"], 0)

        visit_transition(visit=self.visit,
                         new_status=Visit.Status.CANCELLED, reason="x")
        self.assertEqual(pending_summary()["count"], 0)

    def test_bekor_qilinmagan_navbat_tegilmaydi(self):
        """Teskari nazorat: oddiy navbatning cheki saqlanadi."""
        self._tekshiruv()
        self.assertEqual(pending_summary()["count"], 1)

        visit_transition(visit=self.visit, new_status=Visit.Status.WAITING)
        self.assertEqual(pending_summary()["count"], 1,
                         "Oddiy navbatning to'lovi ham yo'qoldi.")

    # ---------------- TEKSHIRUV BEKOR QILINGANDA ----------------
    def test_tekshiruv_bekor_qilinsa_qarz_qolmaydi(self):
        order = self._tekshiruv()
        self.assertEqual(pending_summary()["count"], 1)

        order.status = ServiceOrder.Status.CANCELLED
        order.save()

        self.assertEqual(
            pending_summary()["count"], 0,
            "Bekor qilingan tekshiruv uchun to'lov talab qilinmoqda.")

    def test_har_qanday_tekshiruv_turi_uchun_ishlaydi(self):
        """Laboratoriya, EKG, UZI, rentgen — farqi yo'q."""
        for nom in ["Qon tahlili", "EKG", "UZI qorin", "Rentgen ko'krak"]:
            with self.subTest(tekshiruv=nom):
                svc = ServiceCatalog.objects.create(name=nom, price=20000)
                o = ServiceOrder.objects.create(
                    visit=self.visit, service=svc,
                    price_snapshot=Decimal(20000))
                oldin = pending_summary()["count"]
                self.assertGreater(oldin, 0)

                o.status = ServiceOrder.Status.CANCELLED
                o.save()
                self.assertEqual(
                    pending_summary()["count"], oldin - 1,
                    f"«{nom}» bekor qilingach chekdan chiqmadi")

    def test_bir_tekshiruv_bekor_qilinsa_boshqasi_qoladi(self):
        """Faqat bekor qilingani chiqsin — qolgani to'lanishi kerak."""
        o1 = self._tekshiruv()
        svc2 = ServiceCatalog.objects.create(name="UZI", price=40000)
        ServiceOrder.objects.create(visit=self.visit, service=svc2,
                                    price_snapshot=Decimal(40000))
        self.assertEqual(pending_summary()["count"], 2)

        o1.status = ServiceOrder.Status.CANCELLED
        o1.save()
        self.assertEqual(pending_summary()["count"], 1)


class StatsionargaYonaltirishTests(TestCase):
    """Ambulator ko'rikdan bir bosishda statsionarga."""

    def setUp(self):
        self.doc = User.objects.create_user(
            username="sy_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.patient = Patient.objects.create(
            card_number="P-SY1", last_name="Yotquvchi", first_name="Bemor",
            birth_date=date(1980, 5, 5), gender="male",
            jshshir="51012037250024")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(),
            queue_number=1, doctor=self.doc)
        self.url = reverse("clinical:refer_to_inpatient", args=[self.visit.pk])
        self.client.force_login(self.doc)

    def test_epizod_ochiladi_va_hamshiraga_yuboriladi(self):
        from apps.clinical.models import AdmissionEpisode

        self.client.post(self.url, {"reason": "Qorin og'rig'i"})

        ep = AdmissionEpisode.objects.filter(patient=self.patient).first()
        self.assertIsNotNone(ep, "Epizod ochilmadi.")
        self.assertEqual(
            ep.status, AdmissionEpisode.Status.SENT,
            "Epizod hamshiraga yuborilmadi — u ro'yxatda ko'rinmaydi.")
        self.assertEqual(ep.visit_id, self.visit.pk)
        self.assertEqual(ep.referred_by_id, self.doc.pk)

    def test_hujjat_raqami_ozi_toladi(self):
        """Shifokor JSHSHIRni qayta terishi shart emas."""
        from apps.clinical.models import AdmissionEpisode

        self.client.post(self.url, {})
        ep = AdmissionEpisode.objects.get(patient=self.patient)
        self.assertEqual(ep.document_number, "51012037250024")

    def test_ikkinchi_marta_bosilsa_takror_epizod_ochilmaydi(self):
        """Aks holda bitta bemor ikki joyda «yotayotgan» bo'lib qoladi."""
        from apps.clinical.models import AdmissionEpisode

        self.client.post(self.url, {})
        self.client.post(self.url, {})
        self.assertEqual(
            AdmissionEpisode.objects.filter(patient=self.patient).count(), 1)

    def test_hamshira_royxatida_korinadi(self):
        self.client.post(self.url, {"reason": "SINOV SABABI"})

        hamshira = User.objects.create_user(
            username="sy_nurse", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.WARD_NURSE,
                defaults={"name": "Palata hamshirasi"})[0])
        self.client.force_login(hamshira)

        resp = self.client.get(reverse("clinical:nurse_incoming"))
        self.assertContains(resp, "Yotquvchi")
        self.assertContains(resp, "SINOV SABABI")
        # Kutayotgan bemorda birinchi ish — xona berish.
        self.assertContains(resp, "Xona berish")

    def test_oddiy_hamshira_statsionar_bolimiga_otadi(self):
        """Oddiy hamshirada kravat berish oynasi ochilmaydi.

        Lekin «Ko'rish» ham to'g'ri emas edi — u vipiskaga olib borardi,
        holbuki bemor hali yotmagan. Endi u statsionar bo'limiga o'tadi.
        """
        self.client.post(self.url, {})

        oddiy = User.objects.create_user(
            username="sy_nurse2", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.NURSE, defaults={"name": "Hamshira"})[0])
        self.client.force_login(oddiy)

        resp = self.client.get(reverse("clinical:nurse_incoming"))
        self.assertContains(resp, "Yotquvchi")
        self.assertContains(resp, "Xona berish")
        # oyna emas — havola
        self.assertNotContains(resp, "hx-target=\"#bed-modal-body\"")
        self.assertContains(resp, reverse("clinical:inpatient_dashboard"))

    def test_get_bilan_yonaltirib_bolmaydi(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_shifokor_oz_joyida_qoladi(self):
        """Shifokorni statsionar rasmiylashtirish oynasiga tashlamaydi.

        Uning ishi tugadi — qolganini qabulxona hamshirasi bajaradi.
        Ilgari epizod sahifasiga o'tkazilardi va ambulator shifokor
        o'sha yerda qolib ketardi.
        """
        keldi = reverse("registration:queue")
        resp = self.client.post(self.url, {}, HTTP_REFERER=keldi)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            resp["Location"], keldi,
            "Shifokor o'zi turgan sahifaga qaytmadi.")
        self.assertNotIn("/episode/", resp["Location"],
                         "Shifokor statsionar epizodi sahifasiga tashlandi.")

    def test_referer_bolmasa_navbatga_qaytadi(self):
        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("/episode/", resp["Location"])

    def test_hujjat_hamshirasi_ozi_biriktiriladi(self):
        """Hujjatni bemorni qabul qilgan odam yuritadi.

        Ilgari bu ro'yxatdan tanlanardi: boshqa hamshira tanlanib qolishi
        yoki bo'sh qoldirilib hujjat egasiz qolishi mumkin edi — keyin
        kim yozganini aniqlab bo'lmasdi.
        """
        from apps.clinical.models import Bed, Room
        from apps.clinical.views import _create_stay

        hamshira = User.objects.create_user(
            username="hh_nurse", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.WARD_NURSE,
                defaults={"name": "Palata hamshirasi"})[0])
        boshqa = User.objects.create_user(
            username="hh_boshqa", password="x",
            role=Role.objects.get(code=Role.Code.WARD_NURSE))

        room = Room.objects.create(name="HH-xona")
        bed = Bed.objects.create(room=room, number="1A")

        istak = self.client.request().wsgi_request
        istak.user = hamshira
        # Formaga BOSHQA hamshira yuborilsa ham e'tiborga olinmasin
        istak.POST = {"doc_nurse": str(boshqa.pk)}

        stay, err = _create_stay(istak, self.visit, bed)
        self.assertIsNone(err)
        self.assertEqual(
            stay.doc_nurse_id, hamshira.pk,
            "Hujjat hamshirasi yotqizishni rasmiylashtirgan odam "
            "bo'lishi kerak edi.")

    def test_hujjat_hamshirasi_maydoni_ozgarmas(self):
        """Ekranda ko'rinadi, lekin tanlab bo'lmaydi."""
        from apps.clinical.models import Bed, Room

        hamshira = User.objects.create_user(
            username="hh_nurse2", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.WARD_NURSE,
                defaults={"name": "Palata hamshirasi"})[0])
        room = Room.objects.create(name="HH-xona2")
        Bed.objects.create(room=room, number="2A")

        self.client.force_login(hamshira)
        resp = self.client.get(
            reverse("clinical:admit_visit", args=[self.visit.pk]))
        h = resp.content.decode()

        self.assertIn("Hujjatlashtirish hamshirasi", h)
        self.assertNotIn('name="doc_nurse"', h,
                         "Hujjat hamshirasi hali ham tanlanadigan ro'yxat.")
        self.assertIn("readonly", h)
        # Boshqa ikkitasi esa tanlanadigan bo'lib qolishi kerak
        self.assertIn('name="procedure_nurse"', h)
        self.assertIn('name="assigned_doctor"', h)

    def test_ikkala_yotqizish_oynasida_ham_ozgarmas(self):
        """Yotqizish ikki yo'ldan qilinadi: bemordan va kravatdan.

        Bittasini tuzatib, ikkinchisini unutish — eng ko'p uchraydigan
        xato. Ikkalasini ham tekshiramiz.
        """
        import pathlib

        asos = pathlib.Path(__file__).resolve().parents[2] / "templates" / "clinical"
        for nom in ["_admit_visit_form.html", "_assign_bed_form.html"]:
            with self.subTest(shablon=nom):
                matn = (asos / nom).read_text(encoding="utf-8")
                self.assertNotIn(
                    'name="doc_nurse"', matn,
                    f"{nom}: hujjat hamshirasi hali ham tanlanadi")
                self.assertIn("Hujjatlashtirish hamshirasi", matn)

    def test_yonaltirish_haqida_xabar_beriladi(self):
        """Sahifa o'zgarmagani uchun bosilganini bilish shart."""
        resp = self.client.post(self.url, {}, follow=True)
        xabarlar = [str(m) for m in resp.context["messages"]]
        self.assertTrue(
            any("statsionarga yo'naltirildi" in x for x in xabarlar),
            f"Tasdiq xabari chiqmadi: {xabarlar}")
