"""OMBOR HISOBI FAQAT ASOSIY BIRLIKDA — blok/pachka yo'q.

«1 blok = 50 ampula» iyerarxiyasi hisobni chalkashtirardi: hamshiraga
nechta ampula borligi kerak, blokni bo'lib hisoblash emas. Ustiga-ustak
blok o'lchami keyin o'zgartirilsa, eski qoldiqlar boshqacha ko'rinib
qolardi — o'tgan oyning hisoboti bugun boshqa raqam ko'rsatardi.

Endi bitta o'lchov: dorining o'z birligi.
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.clinical.models import AnesthesiaStock
from apps.pharmacy.models import MeasurementUnit, Medicine, MedicineBatch


class QoldiqYozuviTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.birlik = MeasurementUnit.objects.create(name="Ampula", short_name="amp")
        cls.dori = Medicine.objects.create(name="Seftriakson", unit=cls.birlik)

    def test_qoldiq_faqat_birlikda_yoziladi(self):
        self.assertEqual(self.dori.format_quantity(54), "54 amp")

    def test_katta_son_ham_bolinmaydi(self):
        """Ilgari 250 → «5 blok» bo'lib ketardi."""
        matn = self.dori.format_quantity(250)
        self.assertEqual(matn, "250 amp")
        for sozi in ["blok", "Blok", "pachka", "pochka", "karobka"]:
            self.assertNotIn(sozi, matn)

    def test_nol_qoldiq(self):
        self.assertEqual(self.dori.format_quantity(0), "0 amp")
        self.assertEqual(self.dori.format_quantity(None), "0 amp")

    def test_kasr_son_toliq_chiqadi(self):
        self.assertEqual(self.dori.format_quantity(Decimal("2.5")), "2.5 amp")

    def test_eski_qadoq_yozuvi_hisobga_olinmaydi(self):
        """Eski bazalarda qadoq yozuvlari QOLGAN.

        Model o'chirilmadi (ma'lumot yo'qolmasligi uchun), lekin u
        endi hisobga ta'sir qilmasligi SHART — aks holda o'sha eski
        yozuv bor dorilarda qoldiq yana blokka bo'linib ketardi.
        """
        from apps.pharmacy.models import MedicinePackaging

        MedicinePackaging.objects.create(
            medicine=self.dori, name="Blok", quantity_in_base_unit=50)

        self.assertEqual(
            self.dori.format_quantity(250), "250 amp",
            "Eski qadoq yozuvi qoldiqni blokka bo'lib yubordi.")


class KirimTests(TestCase):
    def setUp(self):
        self.ombordor = User.objects.create_user(
            username="np_omb", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.WAREHOUSE, defaults={"name": "Ombor"})[0])
        self.birlik = MeasurementUnit.objects.create(name="Ampula", short_name="amp")
        self.dori = Medicine.objects.create(name="Analgin", unit=self.birlik)
        self.client.force_login(self.ombordor)

    def test_kirim_kiritilgan_songa_teng(self):
        """Ilgari «nechta blok» ampulaga ko'paytirilardi."""
        self.client.post(reverse("pharmacy:receive_medicine"), {
            "medicine_id": str(self.dori.pk),
            "quantity": "40", "selling_price": "1000",
        })

        partiya = MedicineBatch.objects.get(medicine=self.dori)
        self.assertEqual(
            partiya.quantity_received, 40,
            "Kiritilgan son o'zgartirildi — blokka ko'paytirish qolib ketgan.")
        self.assertEqual(partiya.quantity_available, 40)

    def test_kirim_formasida_qadoq_tanlovi_yoq(self):
        h = self.client.get(reverse("pharmacy:dashboard")).content.decode()
        self.assertNotIn('name="packaging_id"', h,
                         "Kirimda hali ham qadoq tanlanadi.")

    def test_yangi_dori_formasida_qadoq_maydonlari_yoq(self):
        h = self.client.get(reverse("pharmacy:dashboard")).content.decode()
        for maydon in ['name="pkg1_name"', 'name="pkg2_name"',
                       'name="pkg1_qty"', 'name="pkg2_qty"']:
            self.assertNotIn(maydon, h, f"{maydon} hali formada turibdi.")


class AnesteziologOmboriTests(TestCase):
    def setUp(self):
        self.anest = User.objects.create_user(
            username="np_anest", password="x", is_superuser=True,
            role=Role.objects.get_or_create(
                code=Role.Code.ANESTHESIOLOGIST,
                defaults={"name": "Anesteziolog"})[0])
        self.stock = AnesthesiaStock.objects.create(
            name="Propofol", unit="ampula", quantity=Decimal(10),
            selling_price=Decimal(5000), is_active=True)
        self.client.force_login(self.anest)

    def test_kirim_faqat_birlikda_qoshiladi(self):
        self.client.post(
            reverse("clinical:anesthesia_stock_edit", args=[self.stock.pk]),
            {"add_quantity": "15", "selling_price": "5000", "is_active": "1"})

        self.stock.refresh_from_db()
        self.assertEqual(
            self.stock.quantity, 25,
            "Qoldiq noto'g'ri — 10 + 15 = 25 bo'lishi kerak edi.")

    def test_blok_bilan_kirim_yoq(self):
        """Formaga eski maydonlar yuborilsa ham ta'sir qilmasin."""
        self.client.post(
            reverse("clinical:anesthesia_stock_edit", args=[self.stock.pk]),
            {"add_quantity": "5", "selling_price": "5000", "is_active": "1",
             "add_package_count": "100", "add_package_id": "eski"})

        self.stock.refresh_from_db()
        self.assertEqual(
            self.stock.quantity, 15,
            "Blok maydoni hali ham hisobga olinmoqda — qoldiq shishib ketdi.")

    def test_ekranda_blok_tanlovi_yoq(self):
        h = self.client.get(reverse("clinical:anesthesia_stock_page")).content.decode()
        for maydon in ['name="add_package_count"', 'name="add_package_id"',
                       'name="package_size[]"', 'name="package_name[]"']:
            self.assertNotIn(maydon, h, f"{maydon} hali ekranda turibdi.")

    def test_qadoq_boshqaruvi_url_lari_olib_tashlangan(self):
        from django.urls import NoReverseMatch

        for nom in ["anesthesia_stock_package_add",
                    "anesthesia_stock_package_delete"]:
            with self.subTest(url=nom):
                with self.assertRaises(NoReverseMatch):
                    reverse(f"clinical:{nom}", args=[self.stock.pk])
