"""VIPISKA BLANKASI — bo'sh joylar va bir varaqqa sig'ishi.

Talab: hujjat iloji boricha bitta A4 ga sig'sin, to'ldirilmagan qismlar
umuman chiqmasin.

Bo'sh sarlavha ikki tomondan zarar: rasmiy hujjat e'tiborsiz ko'rinadi
va bekorga joy egallab, matnni ikkinchi varaqqa surib yuboradi.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.clinical.models import AdmissionEpisode, DischargeSummary
from apps.patients.models import Patient
from apps.registration.models import Visit


class VipiskaBlankTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="vp_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.patient = Patient.objects.create(
            card_number="P-VP1", last_name="Blank", first_name="Bemor",
            birth_date=date(1980, 3, 3), gender="male")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(), queue_number=1)
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doc,
            reason="Qorin og'rig'i", status=AdmissionEpisode.Status.DISCHARGED)
        self.summary = DischargeSummary.objects.create(
            episode=self.episode, discharged_by=self.doc)
        self.url = reverse("clinical:discharge_print", args=[self.episode.pk])
        self.client.force_login(self.doc)

    # ---------------- BO'SH BO'LIMLAR ----------------
    def test_bosh_bolimlar_chiqmaydi(self):
        """Hech narsa to'ldirilmagan — sarlavhalar ham bo'lmasin."""
        h = self.client.get(self.url).content.decode()

        for sarlavha in ["O'tkazilgan davolash",
                         "Jarrohlik amaliyoti va bayonnomasi",
                         "Berilgan dori-darmonlar",
                         "Statsionardagi muolajalar va ukollar",
                         "O'tkazilgan tekshiruvlar va natijalari",
                         "Tavsiyalar",
                         "Tashxislar (MKB-10)",
                         "Kelgandagi holati"]:
            self.assertNotIn(
                sarlavha, h,
                f"«{sarlavha}» bo'sh bo'lsa ham blankka chiqdi — "
                f"hujjat bekorga cho'ziladi")

    def test_toldirilgan_bolim_chiqadi(self):
        """Teskari nazorat: shart ishlayotganiga ishonch."""
        self.summary.treatment_given = "Infuzion terapiya"
        self.summary.recommendations = "Parhez"
        self.summary.save()
        self.episode.complaints = "Bosh og'rig'i"
        self.episode.save()

        h = self.client.get(self.url).content.decode()
        self.assertIn("O'tkazilgan davolash", h)
        self.assertIn("Infuzion terapiya", h)
        self.assertIn("Tavsiyalar", h)
        self.assertIn("Kelgandagi holati", h)

    def test_bosh_manzil_qatori_chiqmaydi(self):
        h = self.client.get(self.url).content.decode()
        self.assertNotIn("Manzil:", h)

    def test_manzil_bor_bolsa_chiqadi(self):
        # Apostrofsiz manzil: HTML'da u `&#x27;` bo'lib ekranlanadi va
        # tekshiruvni bekorga chalg'itadi.
        self.patient.address = "Boston shahri, 12-uy"
        self.patient.save()
        h = self.client.get(self.url).content.decode()
        self.assertIn("Manzil:", h)
        self.assertIn("Boston shahri, 12-uy", h)

    def test_mehnat_qobiliyati_tegishli_emas_bolsa_chiqmaydi(self):
        """«Tegishli emas» — tanlanmaganning boshqacha aytilishi."""
        self.summary.work_capacity = DischargeSummary.WorkCapacity.NOT_APPLICABLE
        self.summary.save()
        h = self.client.get(self.url).content.decode()
        self.assertNotIn("Mehnat qobiliyati", h)

    def test_mehnat_qobiliyati_belgilangan_bolsa_chiqadi(self):
        self.summary.work_capacity = DischargeSummary.WorkCapacity.SICK_LEAVE
        self.summary.save()
        h = self.client.get(self.url).content.decode()
        self.assertIn("Mehnat qobiliyati", h)

    def test_natija_har_doim_chiqadi(self):
        """Davolash natijasi — vipiskaning yuragi, hech qachon tushmasin."""
        h = self.client.get(self.url).content.decode()
        self.assertIn("Davolash natijasi", h)
        self.assertIn("Chiqishdagi holati va natija", h)

    def test_imzo_va_muhr_qoladi(self):
        """Rasmiy rekvizitlar bo'sh bo'lsa ham qoladi — imzo joyi kerak."""
        h = self.client.get(self.url).content.decode()
        self.assertIn("Davolovchi shifokor", h)
        self.assertIn("Bo'lim mudiri", h)

    # ---------------- SIG'DIRISH ----------------
    def test_shrift_nisbiy_olchamda(self):
        """Hamma o'lcham `em` da bo'lsa, bitta o'zgaruvchi butun hujjatni
        mutanosib kichraytiradi. Piksel qolib ketsa sarlavhalar matndan
        kattaligicha qolib, ko'rinish buziladi."""
        h = self.client.get(self.url).content.decode()
        self.assertIn("--fs", h)
        self.assertIn("font-size: var(--fs)", h)

    def test_shrift_chegarasi_bor(self):
        """Cheksiz kichraytirish o'qib bo'lmaydigan hujjat beradi."""
        h = self.client.get(self.url).content.decode()
        self.assertIn("MIN", h)
        self.assertRegex(h, r"MIN\s*=\s*10")

    def test_chop_etishdan_oldin_qayta_hisoblanadi(self):
        """Ekran va qog'oz kengligi boshqa — faqat yuklanishda
        hisoblansa, qog'ozda o'lcham noto'g'ri chiqadi."""
        h = self.client.get(self.url).content.decode()
        self.assertIn("beforeprint", h)
