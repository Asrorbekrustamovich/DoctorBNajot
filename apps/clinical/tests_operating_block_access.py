"""Operatsion blokka kim kiradi.

Nega bu testlar bor
-------------------
Operatsion blok klinikadagi HAMMA hamshiraga ochiq edi — `nurse` roli
ham kirardi, ya'ni laboratoriya yonidagi kabinet hamshirasi ham.

Endi ruxsat aniq: palata hamshiralari kiradi (bemorni operatsiyaga
tayyorlash, olib borish va qaytarib olish ularning ishi), oddiy
hamshira esa faqat «operatsion hamshira» roli qo'shimcha qilib
biriktirilganda — anestiziska va operatsion hamshira shu tarzda
kiritiladi.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class OperatingBlockAccessTest(TestCase):
    def setUp(self):
        self.ward = rol(Role.Code.WARD_NURSE, "Palata hamshirasi")
        self.opn = rol(Role.Code.OPERATING_NURSE, "Operatsion hamshira")

        # Palata hamshirasi — bemorni operatsiyaga tayyorlaydi
        self.bolim = User.objects.create_user(
            username="meretova", password="x", role=self.ward,
            last_name="Meretova", first_name="Ayqibat",
            specialty="Bo'lim hamshirasi")

        # Oddiy hamshira — biriktirilmagan, blokka kirmaydi
        self.oddiy = User.objects.create_user(
            username="oddiy_hamshira", password="x",
            role=rol(Role.Code.NURSE, "Hamshira"))

        # Operatsion hamshira — o'sha yerda ishlaydi
        self.operatsion = User.objects.create_user(
            username="avezmatova", password="x", role=self.ward,
            last_name="Avezmatova", first_name="Mexrijamol",
            specialty="Operatsion hamshira")
        self.operatsion.extra_roles.add(self.opn)

    # ---------- huquq ----------

    def test_palata_hamshirasiga_ochiq(self):
        self.assertTrue(
            User.objects.get(pk=self.bolim.pk).can_operating_block)

    def test_oddiy_hamshiraga_yopiq(self):
        """Biriktirilmagan hamshira — blokka aloqasi yo'q."""
        self.assertFalse(
            User.objects.get(pk=self.oddiy.pk).can_operating_block)

    def test_biriktirilgan_oddiy_hamshiraga_ochiq(self):
        """Anestiziska — asosiy roli hamshira, blok qo'shimcha rol bilan."""
        self.oddiy.extra_roles.add(self.opn)
        self.assertTrue(
            User.objects.get(pk=self.oddiy.pk).can_operating_block)

    def test_operatsion_hamshiraga_ochiq(self):
        self.assertTrue(
            User.objects.get(pk=self.operatsion.pk).can_operating_block)

    def test_jarrohga_ochiq(self):
        j = User.objects.create_user(
            username="jarroh_a", password="x",
            role=rol(Role.Code.SURGEON, "Jarroh"))
        self.assertTrue(j.can_operating_block)

    def test_anesteziologga_ochiq(self):
        a = User.objects.create_user(
            username="anest_a", password="x",
            role=rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))
        self.assertTrue(a.can_operating_block)

    # ---------- sahifalar ----------

    def test_palata_hamshirasi_operatsion_xonalarga_kiradi(self):
        self.client.force_login(self.bolim)
        r = self.client.get(reverse("clinical:operating_rooms_overview"))
        self.assertEqual(r.status_code, 200)

    def test_oddiy_hamshira_operatsion_xonalarga_kira_olmaydi(self):
        self.client.force_login(self.oddiy)
        r = self.client.get(reverse("clinical:operating_rooms_overview"))
        self.assertNotEqual(r.status_code, 200)

    def test_operatsion_hamshira_kira_oladi(self):
        self.client.force_login(self.operatsion)
        r = self.client.get(reverse("clinical:operating_rooms_overview"))
        self.assertEqual(r.status_code, 200)

    def test_palata_hamshirasi_jarrohlik_blokiga_kiradi(self):
        self.client.force_login(self.bolim)
        r = self.client.get(reverse("clinical:surgery_dashboard"))
        self.assertEqual(r.status_code, 200)

    def test_oddiy_hamshira_jarrohlik_blokiga_kira_olmaydi(self):
        self.client.force_login(self.oddiy)
        r = self.client.get(reverse("clinical:surgery_dashboard"))
        self.assertNotEqual(r.status_code, 200)

    # ---------- menyu ----------

    def test_menyuda_palata_hamshirasiga_korinadi(self):
        self.client.force_login(self.bolim)
        html = self.client.get(
            reverse("clinical:nurse_incoming")).content.decode()
        self.assertIn(
            reverse("clinical:operating_rooms_overview"), html)

    def test_menyuda_oddiy_hamshiraga_korinmaydi(self):
        self.client.force_login(self.oddiy)
        html = self.client.get(
            reverse("clinical:nurse_incoming")).content.decode()
        self.assertNotIn(
            reverse("clinical:operating_rooms_overview"), html)

    def test_menyuda_operatsion_hamshiraga_korinadi(self):
        self.client.force_login(self.operatsion)
        html = self.client.get(
            reverse("clinical:operating_rooms_overview")).content.decode()
        self.assertIn(
            reverse("clinical:operating_rooms_overview"), html)
