"""Menyu qo'shimcha rollarni ham ko'rsin.

Nega bu testlar bor
-------------------
Qabulov Kamaraddin — anesteziolog, lekin ambulator qabul ham qiladi,
shuning uchun asosiy roli «shifokor». Menyu esa `user.role.code` deb
faqat ASOSIY rolni tekshirardi va unga «Anesteziolog ombori» bo'limi
ko'rinmasdi — sahifaning o'zi ochiq bo'lsa ham.

Bu jim turadigan xato: xatolik chiqmaydi, bo'lim shunchaki yo'q.
Shuning uchun har bo'limni alohida tekshiramiz.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class MenuExtraRolesTest(TestCase):
    def setUp(self):
        self.doctor = rol(Role.Code.DOCTOR, "Shifokor")
        self.user = User.objects.create_user(
            username="qabulov", password="x", role=self.doctor,
            last_name="Qabulov", first_name="Kamaraddin",
            specialty="Anestezolog / reanimatolog")

    def _menyu(self):
        self.client.force_login(self.user)
        return self.client.get(reverse("core:home")).content.decode()

    def test_anesteziolog_ombori_qoshimcha_rol_bilan_korinadi(self):
        self.user.extra_roles.add(
            rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))
        self.assertIn(reverse("clinical:anesthesia_stock_page"), self._menyu())

    def test_qoshimcha_rolsiz_korinmaydi(self):
        self.assertNotIn(
            reverse("clinical:anesthesia_stock_page"), self._menyu())

    def test_anesteziolog_ombori_sahifasi_ochiladi(self):
        self.user.extra_roles.add(
            rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))
        self.client.force_login(self.user)
        r = self.client.get(reverse("clinical:anesthesia_stock_page"))
        self.assertEqual(r.status_code, 200)

    def test_ombor_qoshimcha_rol_bilan_korinadi(self):
        self.user.extra_roles.add(rol(Role.Code.WAREHOUSE, "Ombor mudiri"))
        self.assertIn(reverse("pharmacy:dashboard"), self._menyu())

    def test_jarrohlik_bloki_qoshimcha_rol_bilan_korinadi(self):
        hamshira = User.objects.create_user(
            username="opnurse_m", password="x",
            role=rol(Role.Code.WARD_NURSE, "Palata hamshirasi"))
        hamshira.extra_roles.add(
            rol(Role.Code.OPERATING_NURSE, "Operatsion hamshira"))
        self.client.force_login(hamshira)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(reverse("clinical:surgery_dashboard"), html)

    def test_asosiy_rol_ham_ishlaydi(self):
        """Qo'shimcha rol qo'shildi deb asosiysi buzilmasin."""
        anest = User.objects.create_user(
            username="anest_m", password="x",
            role=rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))
        self.client.force_login(anest)
        html = self.client.get(reverse("core:home")).content.decode()
        self.assertIn(reverse("clinical:anesthesia_stock_page"), html)
