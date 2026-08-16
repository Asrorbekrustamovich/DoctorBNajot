"""BEMOR QIDIRUVI — hamma joyda bir xil ishlashi kerak.

HAQIQIY XATO: metrika (tug'ilganlik guvohnomasi) bo'yicha qidiruv faqat
statsionar epizodida bor edi. Kartotekada, kassada va registraturada esa
yo'q — bolani topib bo'lmasdi, chunki ularda pasport bo'lmaydi va metrika
yagona hujjat hisoblanadi.

Ikkinchi muammo: metrika turlicha yoziladi — «I-AB 123456», «I AB123456»,
«IAB123456». Oddiy `icontains` bunda ishlamaydi.

Qidiruv har joyda alohida yozilgani uchun ular bir-biridan uzilib
ketgan edi. Endi bitta funksiya — shuning uchun testlar UCHALA ekranni
ham tekshiradi.
"""
from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.patients.models import Patient
from apps.patients.selectors import patient_list
from apps.registration.models import Visit


class MetrikaQidiruvTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.bola = Patient.objects.create(
            card_number="P-Q001", last_name="Bolaev", first_name="Kichik",
            birth_date=date(2021, 4, 4), gender="male",
            birth_certificate="I-AB 123456")
        cls.katta = Patient.objects.create(
            card_number="P-Q002", last_name="Kattaev", first_name="Ulug'bek",
            birth_date=date(1985, 1, 1), gender="male",
            passport="AA1234567", jshshir="51012037250024")

    # ---------------- SELEKTOR ----------------
    def test_metrika_bilan_topiladi(self):
        topildi = patient_list(search="I-AB 123456")
        self.assertIn(self.bola, topildi,
                      "Metrika bo'yicha bemor topilmadi.")

    def test_metrika_boshliqsiz_yozilsa_ham_topiladi(self):
        for variant in ["IAB123456", "I AB123456", "i-ab123456", "IAB 123456"]:
            with self.subTest(variant=variant):
                self.assertIn(
                    self.bola, patient_list(search=variant),
                    f"«{variant}» ko'rinishida yozilganda topilmadi — "
                    f"metrika turlicha yoziladi")

    def test_metrikaning_bir_qismi_bilan_topiladi(self):
        self.assertIn(self.bola, patient_list(search="123456"))

    def test_jshshir_boshliq_bilan_terilsa_ham_topiladi(self):
        """Registrator raqamni bo'shliq bilan terishi odatiy hol."""
        self.assertIn(self.katta, patient_list(search="5101 2037 2500 24"))

    def test_pasport_bilan_topiladi(self):
        self.assertIn(self.katta, patient_list(search="AA1234567"))

    def test_fio_va_karta_avvalgidek_ishlaydi(self):
        self.assertIn(self.bola, patient_list(search="Bolaev"))
        self.assertIn(self.katta, patient_list(search="P-Q002"))

    def test_begona_soz_hech_kimni_topmaydi(self):
        """Teskari nazorat: filtr haqiqatan cheklayotganiga ishonch."""
        self.assertEqual(patient_list(search="ZZZZZZZZ").count(), 0)

    def test_metrika_boshqa_bemorni_tortib_kelmaydi(self):
        self.assertNotIn(self.katta, patient_list(search="I-AB 123456"))

    def test_bosh_sorov_hammasini_qaytaradi(self):
        self.assertEqual(patient_list(search="").count(), 2)


class QidiruvEkranlarTests(TestCase):
    """Uchala ekran ham bir xil topishi shart."""

    def setUp(self):
        self.admin = User.objects.create_user(
            username="q_admin", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.ADMINISTRATOR,
                defaults={"name": "Administrator"})[0])
        self.bola = Patient.objects.create(
            card_number="P-Q010", last_name="Metrikaev", first_name="Bola",
            birth_date=date(2020, 2, 2), gender="female",
            birth_certificate="II-CD 998877")
        Visit.objects.create(patient=self.bola, visit_date=date.today(),
                             queue_number=1)
        self.client.force_login(self.admin)

    def test_kartotekada_metrika_bilan_topiladi(self):
        resp = self.client.get(reverse("patients:list"), {"q": "II-CD 998877"})
        self.assertContains(resp, "Metrikaev")

    def test_registrator_tolov_ekranida_metrika_bilan_topiladi(self):
        """Registrator to'lov qabul qilayotganda ham topa olishi kerak.

        Bu ekranda ilgari qidiruv UMUMAN yo'q edi.
        """
        url = reverse("billing:registrator_payments")
        resp = self.client.get(url, {"q": "IICD998877"})
        self.assertContains(resp, "Metrikaev")

    def test_registrator_ekranida_jshshir_bilan_topiladi(self):
        self.bola.jshshir = "32002027250011"
        self.bola.save()
        resp = self.client.get(reverse("billing:registrator_payments"),
                               {"q": "32002027250011"})
        self.assertContains(resp, "Metrikaev")

    def test_registrator_ekranida_begona_sorov_bosh_qaytaradi(self):
        """Teskari nazorat: filtr haqiqatan cheklayaptimi."""
        resp = self.client.get(reverse("billing:registrator_payments"),
                               {"q": "ZZZZZZZZ"})
        self.assertNotContains(resp, "Metrikaev")

    def test_kassa_royxatida_metrika_bilan_topiladi(self):
        resp = self.client.get(reverse("billing:dashboard"), {"q": "IICD998877"},
                               follow=True)
        self.assertContains(resp, "Metrikaev")

    def test_yangi_bemor_formasida_metrika_maydoni_bor(self):
        """HAQIQIY XATO: formada faqat JSHSHIR va pasport bor edi.

        Bolalarda pasport bo'lmaydi va metrika yagona hujjat — ya'ni
        bolani hujjatsiz ro'yxatga olishga to'g'ri kelardi. Qidiruv
        metrikani qo'llab-quvvatlagani bilan, kiritish joyi bo'lmagach
        undan foyda yo'q edi.
        """
        from apps.patients.forms import PatientForm

        self.assertIn("birth_certificate", PatientForm().fields)

        resp = self.client.get(reverse("patients:create"))
        self.assertContains(resp, 'name="birth_certificate"')
        self.assertContains(resp, "Metrika")

    def test_metrikali_bemor_saqlanadi(self):
        resp = self.client.post(reverse("patients:create"), {
            "last_name": "Yangibolaev", "first_name": "Kichkina",
            "birth_date": "2022-03-03", "gender": "male",
            "birth_certificate": "III-EF 445566",
        }, follow=True)

        yangi = Patient.objects.filter(last_name="Yangibolaev").first()
        self.assertIsNotNone(yangi, f"Bemor saqlanmadi: {resp.status_code}")
        self.assertEqual(yangi.birth_certificate, "III-EF 445566")
        # Va darrov qidiruvda topilishi kerak
        self.assertIn(yangi, patient_list(search="IIIEF445566"))

    def test_metrikasiz_ikki_bemor_ziddiyat_bermaydi(self):
        """Bo'sh metrika NULL bo'lishi shart.

        Bo'sh satr saqlansa, metrikasiz IKKINCHI bemor ham `""` olib,
        unikal cheklov buziladi va foydalanuvchi 500 sahifani ko'radi.
        """
        # Hujjat sifatida JSHSHIR beramiz — sinaladigan narsa metrikaning
        # BO'SH qolishi, hujjat qoidasi emas.
        for i, jshshir in enumerate(["51012037250071", "51012037250072"], 1):
            self.client.post(reverse("patients:create"), {
                "last_name": f"Metrikasiz{i}", "first_name": "Bemor",
                "birth_date": "1990-01-01", "gender": "male",
                "jshshir": jshshir,
                "birth_certificate": "",
            })

        self.assertEqual(
            Patient.objects.filter(last_name__startswith="Metrikasiz").count(), 2)

    def test_faqat_metrika_bilan_saqlanadi_jshshir_talab_qilinmaydi(self):
        """ASOSIY TALAB: bolada JSHSHIR ham, pasport ham bo'lmaydi.

        Ularni talab qilish — bolani umuman ro'yxatga ololmaslik demak.
        """
        self.client.post(reverse("patients:create"), {
            "last_name": "Faqatmetrika", "first_name": "Bola",
            "birth_date": "2023-05-05", "gender": "female",
            "jshshir": "", "passport": "",
            "birth_certificate": "IV-GH 111222",
        })

        yangi = Patient.objects.filter(last_name="Faqatmetrika").first()
        self.assertIsNotNone(yangi, "Faqat metrika bilan bemor saqlanmadi.")
        self.assertIsNone(yangi.jshshir)
        self.assertIsNone(yangi.passport)

    def test_hujjatsiz_bemor_saqlanmaydi(self):
        """Hech qanday hujjatsiz bemorni keyin na topib, na ajratib bo'ladi."""
        resp = self.client.post(reverse("patients:create"), {
            "last_name": "Hujjatsiz", "first_name": "Bemor",
            "birth_date": "1990-01-01", "gender": "male",
            "jshshir": "", "passport": "", "birth_certificate": "",
        })

        self.assertFalse(Patient.objects.filter(last_name="Hujjatsiz").exists())
        self.assertContains(resp, "Kamida bitta hujjat")

    def test_faqat_jshshir_bilan_ham_saqlanadi(self):
        """Teskari nazorat: kattalarda metrika talab qilinmasin."""
        self.client.post(reverse("patients:create"), {
            "last_name": "Faqatjshshir", "first_name": "Katta",
            "birth_date": "1980-01-01", "gender": "male",
            "jshshir": "51012037250099",
        })
        self.assertTrue(Patient.objects.filter(last_name="Faqatjshshir").exists())

    def test_api_metrika_bilan_bemor_yaratadi(self):
        """API'da metrika maydoni umuman yo'q edi."""
        from apps.patients.serializers import PatientWriteSerializer

        self.assertIn("birth_certificate", PatientWriteSerializer().fields)

    def test_band_metrika_tushunarli_xato_beradi(self):
        resp = self.client.post(reverse("patients:create"), {
            "last_name": "Takroriy", "first_name": "Bemor",
            "birth_date": "1990-01-01", "gender": "male",
            "birth_certificate": "II-CD 998877",      # allaqachon band
        })
        self.assertEqual(resp.status_code, 200, "500 sahifa chiqdi")
        # Apostrof HTML'da `&#x27;` bo'lib ekranlanadi — tekshiruvni
        # apostrofsiz qismga qo'yamiz.
        self.assertContains(resp, "Bu metrika allaqachon")
        self.assertContains(resp, "Metrikaev")

    def test_registratura_royxatida_metrika_korinadi(self):
        """Tezkor qidiruv shu matn ustidan ishlaydi — bo'lmasa topilmaydi."""
        from apps.registration.forms import VisitForm

        yorliq = VisitForm().fields["patient"].label_from_instance(self.bola)
        self.assertIn("Metrika", yorliq)
        self.assertIn("II-CD 998877", yorliq)
