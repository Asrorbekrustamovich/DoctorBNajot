"""TO'LOV PAYTIDA NARXNI TO'G'RILASH VA SHIFOKOR ULUSHI (50/50).

Ikki holat uchun narxni to'lov paytida o'zgartirish kerak:
  · katalogdagi narx eskirib qolgan bo'lishi mumkin;
  · bemor shifokorning qarindoshi bo'lib, bepul davolanishi mumkin.

Uchta qat'iy qoida:
  1. Tuzatish FAQAT shu chekka tegadi — katalog narxi o'zgarmaydi,
     aks holda bittaga qilingan chegirma hammaga tarqalardi.
  2. Bepul (0 so'm) band ham «to'langan» hisoblanadi — aks holda u
     registrator ro'yxatida abadiy osilib qolar, laboratoriya esa
     bemorni «to'lamagan» deb qabul qilmasdi.
  3. Shifokorning 50% ulushi HAQIQATDA to'langan summadan hisoblanadi,
     katalog narxidan emas.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.billing.models import DoctorShare, Invoice
from apps.billing.selectors import pending_summary
from apps.clinical.models import DoctorPrice, ServiceCatalog, ServiceOrder
from apps.patients.models import Patient
from apps.registration.models import Visit


class NarxTahririTests(TestCase):
    def setUp(self):
        self.reg = User.objects.create_user(
            username="nt_reg", password="x",
            role=Role.objects.get_or_create(
                code=Role.Code.ADMINISTRATOR, defaults={"name": "Registrator"})[0])
        self.doc = User.objects.create_user(
            username="nt_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        DoctorPrice.objects.create(doctor=self.doc, price=Decimal(50000),
                                   is_active=True)

        self.patient = Patient.objects.create(
            card_number="P-NT1", last_name="Narxov", first_name="Bemor",
            birth_date=date(1990, 1, 1), gender="male",
            jshshir="51012037250061")
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(),
            queue_number=1, doctor=self.doc)
        self.invoice = Invoice.objects.get(visit=self.visit)
        self.band = self.invoice.items.first()
        self.url = reverse("billing:pay_invoice", args=[self.invoice.pk])
        self.client.force_login(self.reg)

    # ---------------- NARXNI TO'G'RILASH ----------------
    def test_narx_pasaytirilsa_shu_summa_olinadi(self):
        """Katalogda 50 000, lekin registrator 30 000 deb to'g'rilaydi."""
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "30000",
            "amount": "30000",
        })

        self.band.refresh_from_db()
        self.invoice.refresh_from_db()
        self.assertEqual(self.band.total_price, 30000)
        self.assertEqual(self.invoice.total_amount, 30000)
        self.assertEqual(self.invoice.debt, 0, "Qarz qolib ketdi.")

    def test_katalog_narxi_ozgarmaydi(self):
        """ASOSIY QOIDA: bittaga qilingan chegirma hammaga tarqalmasin."""
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "10000", "amount": "10000",
        })

        narx = DoctorPrice.objects.get(doctor=self.doc)
        self.assertEqual(
            narx.price, 50000,
            "Katalogdagi qabul narxi o'zgarib ketdi — keyingi bemorlar "
            "ham chegirma bilan qabul qilinadi.")

    def test_narx_oshirilishi_ham_mumkin(self):
        """Bazadagi narx eskirib qolgan bo'lishi mumkin."""
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "80000", "amount": "80000",
        })
        self.band.refresh_from_db()
        self.assertEqual(self.band.total_price, 80000)

    def test_tolangan_bandga_tegib_bolmaydi(self):
        """To'langach narx o'zgarsa, kassadagi pul bilan chek mos kelmaydi."""
        self.client.post(self.url, {"amount": "50000"})
        self.band.refresh_from_db()
        self.assertIsNotNone(self.band.paid_at)

        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "1000", "amount": "0",
        })
        self.band.refresh_from_db()
        self.assertEqual(self.band.total_price, 50000,
                         "To'langan bandning narxi o'zgartirildi.")

    def test_manfiy_narx_qabul_qilinmaydi(self):
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "-5000", "amount": "50000",
        })
        self.band.refresh_from_db()
        self.assertEqual(self.band.total_price, 50000)

    # ---------------- BEPUL DAVOLASH ----------------
    def test_bepul_rasmiylashtiriladi(self):
        """Shifokorning qarindoshi — 0 so'm."""
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "0", "amount": "0",
        })

        self.band.refresh_from_db()
        self.assertEqual(self.band.total_price, 0)
        self.assertIsNotNone(
            self.band.paid_at,
            "Bepul band «to'lanmagan» bo'lib qoldi — u registrator "
            "ro'yxatida osilib qoladi.")

    def test_bepul_bemor_tolov_royxatidan_tushadi(self):
        self.assertEqual(pending_summary()["count"], 1)
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "0", "amount": "0",
        })
        self.assertEqual(pending_summary()["count"], 0)

    def test_bepul_tekshiruv_laboratoriyada_ochiladi(self):
        """`ServiceOrder.is_paid` chek bandiga qarab ishlaydi."""
        svc = ServiceCatalog.objects.create(name="Qon tahlili",
                                            price=Decimal(30000))
        order = ServiceOrder.objects.create(
            visit=self.visit, service=svc, price_snapshot=Decimal(30000))

        self.invoice.refresh_from_db()
        bandlar = {str(i.reference_id): i for i in self.invoice.items.all()}
        tekshiruv_bandi = bandlar[str(order.pk)]

        data = {"amount": "0"}
        for i in self.invoice.items.all():
            data[f"item_price_{i.pk}"] = "0"
        self.client.post(self.url, data)

        order.refresh_from_db()
        self.assertTrue(
            order.is_paid,
            "Bepul tekshiruv «to'lanmagan» bo'lib qoldi — laborant "
            "bemorni qabul qila olmaydi.")

    # ---------------- SHIFOKOR ULUSHI 50/50 ----------------
    def test_ulush_haqiqiy_summadan_hisoblanadi(self):
        """Katalogda 50 000 bo'lsa ham, 30 000 to'langan bo'lsa — 15 000."""
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "30000", "amount": "30000",
        })

        ulush = DoctorShare.objects.filter(doctor=self.doc).first()
        self.assertIsNotNone(ulush, "Shifokor ulushi yozilmadi.")
        self.assertEqual(
            ulush.amount, 15000,
            "Ulush katalog narxidan hisoblandi — shifokorga olinmagan "
            "puldan ulush yozilmoqda.")

    def test_bepul_bolsa_ulush_yozilmaydi(self):
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "0", "amount": "0",
        })
        self.assertFalse(DoctorShare.objects.filter(doctor=self.doc).exists())

    def test_ulush_takrorlanmaydi(self):
        """HAQIQIY XATO: chek har qayta hisoblanganda ulush qayta yozilardi.

        Chek har bir tekshiruv qo'shilganda butunlay qayta tuziladi
        (bandlar o'chib, yangidan yaratiladi). Shu sababli `paid_at`
        yana bo'sh bo'lib, ulush QAYTA yozilardi — uch marta tekshiruv
        tayinlansa shifokorga 25 000 o'rniga 100 000 yozilib ketardi.
        """
        self.client.post(self.url, {"amount": "50000"})
        self.assertEqual(DoctorShare.objects.count(), 1)

        svc = ServiceCatalog.objects.create(name="UZI", price=Decimal(1))
        for _ in range(3):
            ServiceOrder.objects.create(visit=self.visit, service=svc,
                                        price_snapshot=Decimal(1))

        jami = sum(s.amount for s in DoctorShare.objects.all())
        self.assertEqual(DoctorShare.objects.count(), 1,
                         f"Ulush takrorlandi: {DoctorShare.objects.count()} ta")
        self.assertEqual(jami, 25000, f"Ulush summasi shishdi: {jami}")

    # ---------------- TUZATISH QAYTA HISOBLASHDA SAQLANADI ----------------
    def test_tuzatilgan_narx_analiz_qoshilganda_yoqolmaydi(self):
        """HAQIQIY XATO — foydalanuvchi topgan.

        50 000 lik qabul 100 000 ga to'g'rilanib to'landi. Keyin 90 000 lik
        ikkita analiz qo'shildi. Qarz 90 000 bo'lishi kerak edi, lekin
        40 000 chiqdi: chek qayta tuzilganda qabul narxi katalogdagi
        50 000 ga qaytib ketgan, ya'ni tuzatish yo'qolgan.
        """
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "100000", "amount": "100000",
        })
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.debt, 0)

        for nom in ("Analiz-1", "Analiz-2"):
            svc = ServiceCatalog.objects.create(name=nom, price=Decimal(45000))
            ServiceOrder.objects.create(visit=self.visit, service=svc,
                                        price_snapshot=Decimal(45000))

        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.debt, 90000,
            f"Qarz noto'g'ri: {self.invoice.debt}. Tuzatilgan qabul narxi "
            f"chek qayta tuzilganda yo'qolgan.")
        self.assertEqual(self.invoice.total_amount, 190000)

    def test_tuzatish_chekda_saqlanadi(self):
        self.client.post(self.url, {
            f"item_price_{self.band.pk}": "70000", "amount": "70000",
        })
        self.invoice.refresh_from_db()
        self.assertEqual(
            self.invoice.price_overrides.get(str(self.visit.pk)), "70000",
            "Tuzatish chekda saqlanmadi — qayta hisoblashda yo'qoladi.")

    # ---------------- TEKSHIRUV NARXINI TAHRIRLASH ----------------
    def test_tekshiruv_narxi_tahrirlanadi(self):
        """Ilgari tekshiruvda faqat «bekor qilish» bor edi."""
        svc = ServiceCatalog.objects.create(name="UZI", price=Decimal(60000))
        order = ServiceOrder.objects.create(
            visit=self.visit, service=svc, price_snapshot=Decimal(60000))

        self.invoice.refresh_from_db()
        band = self.invoice.items.get(reference_id=order.pk)

        self.client.post(
            reverse("billing:edit_item_price", args=[band.pk]),
            {"price": "40000", "audit_reason": "Bazadagi narx eskirgan"})

        band.refresh_from_db()
        self.assertEqual(band.total_price, 40000)

    def test_tekshiruv_tuzatishi_ham_yoqolmaydi(self):
        """Boshqa analiz qo'shilganda ham tuzatish saqlanishi kerak."""
        svc = ServiceCatalog.objects.create(name="UZI", price=Decimal(60000))
        order = ServiceOrder.objects.create(
            visit=self.visit, service=svc, price_snapshot=Decimal(60000))
        self.invoice.refresh_from_db()
        band = self.invoice.items.get(reference_id=order.pk)

        self.client.post(
            reverse("billing:edit_item_price", args=[band.pk]),
            {"price": "40000", "audit_reason": "Chegirma"})

        svc2 = ServiceCatalog.objects.create(name="EKG", price=Decimal(20000))
        ServiceOrder.objects.create(visit=self.visit, service=svc2,
                                    price_snapshot=Decimal(20000))

        self.invoice.refresh_from_db()
        yangi_band = self.invoice.items.get(reference_id=order.pk)
        self.assertEqual(
            yangi_band.total_price, 40000,
            "Tekshiruv narxi tuzatilgan edi, lekin qayta hisoblashda "
            "katalog narxiga qaytib ketdi.")
        # 50 000 (qabul) + 40 000 (tuzatilgan UZI) + 20 000 (EKG)
        self.assertEqual(self.invoice.total_amount, 110000)

    def test_tekshiruv_bepul_qilinadi(self):
        svc = ServiceCatalog.objects.create(name="Qon", price=Decimal(30000))
        order = ServiceOrder.objects.create(
            visit=self.visit, service=svc, price_snapshot=Decimal(30000))
        self.invoice.refresh_from_db()
        band = self.invoice.items.get(reference_id=order.pk)

        self.client.post(
            reverse("billing:edit_item_price", args=[band.pk]),
            {"price": "0", "audit_reason": "Shifokorning qarindoshi"})

        order.refresh_from_db()
        self.assertTrue(order.is_paid,
                        "Bepul tekshiruv laboratoriyada ochilmadi.")

    def test_sababsiz_tahrirlab_bolmaydi(self):
        """Pul o'zgarishi izsiz qolmasligi kerak."""
        svc = ServiceCatalog.objects.create(name="Rentgen", price=Decimal(50000))
        order = ServiceOrder.objects.create(
            visit=self.visit, service=svc, price_snapshot=Decimal(50000))
        self.invoice.refresh_from_db()
        band = self.invoice.items.get(reference_id=order.pk)

        self.client.post(reverse("billing:edit_item_price", args=[band.pk]),
                         {"price": "10000"})
        band.refresh_from_db()
        self.assertEqual(band.total_price, 50000)

    def test_tolangan_bandni_tahrirlab_bolmaydi(self):
        self.client.post(self.url, {"amount": "50000"})
        self.band.refresh_from_db()

        self.client.post(reverse("billing:edit_item_price", args=[self.band.pk]),
                         {"price": "1", "audit_reason": "sinov"})
        self.band.refresh_from_db()
        self.assertEqual(self.band.total_price, 50000)

    def test_eski_takroriy_ulushlar_tizimni_toxtatmaydi(self):
        """HAQIQIY XATO: eski buzuq ma'lumot butun tizimni to'xtatib qo'ydi.

        Avvalgi kod bir xil tavsifli bir nechta ulush yozgan edi. Yangi
        kod `update_or_create` ishlatganda ular `MultipleObjectsReturned`
        bilan yiqilardi — natijada TEKSHIRUV TAYINLASH ham ishlamay
        qolgan edi: AJAX so'rov JSON o'rniga HTML xato sahifasini
        qaytarardi («Unexpected token '<'»).

        Eski ma'lumot o'z-o'zidan tuzalishi kerak.
        """
        from apps.billing.services import settle_prepaid_items

        # Eski xato natijasini takrorlaymiz: ikkita bir xil ulush
        for _ in range(2):
            DoctorShare.objects.create(
                doctor=self.doc, invoice=self.invoice, amount=Decimal(99999),
                description=f"{self.band.name} uchun 50% ulush")
        self.assertEqual(DoctorShare.objects.count(), 2)

        self.invoice.paid_amount = Decimal(50000)
        self.invoice.save(update_fields=["paid_amount"])
        settle_prepaid_items(self.invoice)      # yiqilmasligi SHART

        self.assertEqual(DoctorShare.objects.count(), 1,
                         "Ortiqcha ulushlar o'chirilmadi.")
        self.assertEqual(DoctorShare.objects.first().amount, 25000,
                         "Qolgan ulush summasi to'g'rilanmadi.")

    def test_eski_takroriy_ulushda_tekshiruv_tayinlanadi(self):
        """Uchidan-uchiga: buzuq ma'lumot bo'lsa ham tayinlash ishlasin."""
        for _ in range(2):
            DoctorShare.objects.create(
                doctor=self.doc, invoice=self.invoice, amount=Decimal(1),
                description=f"{self.band.name} uchun 50% ulush")

        self.invoice.paid_amount = Decimal(50000)
        self.invoice.save(update_fields=["paid_amount"])

        svc = ServiceCatalog.objects.create(name="EKG", price=Decimal(20000))
        # Chek signal orqali qayta hisoblanadi — shu yerda yiqilardi
        ServiceOrder.objects.create(visit=self.visit, service=svc,
                                    price_snapshot=Decimal(20000))

        self.assertTrue(
            ServiceOrder.objects.filter(visit=self.visit).exists(),
            "Tekshiruv tayinlanmadi — eski buzuq ulush to'sib qo'ydi.")

    def test_pul_qaytarilsa_ulush_ham_ochadi(self):
        """Pul qaytarilsa shifokorga ulush qolib ketmasin."""
        from apps.billing.services import settle_prepaid_items

        self.client.post(self.url, {"amount": "50000"})
        self.assertEqual(DoctorShare.objects.count(), 1)

        self.invoice.refresh_from_db()
        self.invoice.refunded_amount = Decimal(50000)
        self.invoice.save(update_fields=["refunded_amount"])
        settle_prepaid_items(self.invoice)

        self.assertEqual(
            DoctorShare.objects.count(), 0,
            "Pul qaytarildi, lekin shifokor ulushi qolib ketdi.")
        self.band.refresh_from_db()
        self.assertIsNone(self.band.paid_at)
