"""Qo'shimcha rollar: bitta xodim ikki bo'limda ishlashi.

Nega kerak
----------
Kichik klinikada qabulxona hamshirasi ayni paytda omborni ham yuritadi.
Asosiy rolni «ombor mudiri» ga o'zgartirsak, hamshiralik ekranlari
yopilib qoladi — shuning uchun asosiy rol qoladi, qo'shimchasi ustiga
biriktiriladi.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User


class ExtraRoleTest(TestCase):
    def setUp(self):
        self.nurse_role, _ = Role.objects.get_or_create(
            code=Role.Code.NURSE, defaults={"name": "Hamshira"})
        self.wh_role, _ = Role.objects.get_or_create(
            code=Role.Code.WAREHOUSE, defaults={"name": "Ombor mudiri"})
        self.user = User.objects.create_user(
            username="farida", password="x", role=self.nurse_role)

    def test_qoshimcha_rolsiz_omborga_kira_olmaydi(self):
        self.assertFalse(self.user.has_role(Role.Code.WAREHOUSE))
        self.assertFalse(self.user.can_warehouse)

    def test_qoshimcha_rol_biriktirilsa_ochiladi(self):
        self.user.extra_roles.add(self.wh_role)
        u = User.objects.get(pk=self.user.pk)
        self.assertTrue(u.has_role(Role.Code.WAREHOUSE))
        self.assertTrue(u.can_warehouse)

    def test_asosiy_rol_saqlanib_qoladi(self):
        """Ombor qo'shildi deb hamshiralik yo'qolmasligi kerak."""
        self.user.extra_roles.add(self.wh_role)
        u = User.objects.get(pk=self.user.pk)
        self.assertTrue(u.has_role(Role.Code.NURSE))
        self.assertEqual(u.role_codes, {"nurse", "warehouse"})

    def test_ombor_sahifasi_ochiladi(self):
        self.user.extra_roles.add(self.wh_role)
        self.client.force_login(self.user)
        r = self.client.get(reverse("pharmacy:dashboard"))
        self.assertEqual(r.status_code, 200)

    def test_qoshimcha_rolsiz_ombor_sahifasi_yopiq(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("pharmacy:dashboard"))
        self.assertNotEqual(r.status_code, 200)

    def test_menyuda_ombor_korinadi(self):
        self.user.extra_roles.add(self.wh_role)
        self.client.force_login(self.user)
        html = self.client.get(reverse("pharmacy:dashboard")).content.decode()
        self.assertIn(reverse("pharmacy:dashboard"), html)
        self.assertIn("Ombor", html)

    def test_rol_keshi_bir_marta_oqiydi(self):
        """Har tekshiruvda bazaga bormasin.

        Ikki so'rov kutiladi: asosiy rol (FK) va qo'shimcha rollar.
        Uchtadan oshsa — kesh ishlamayapti."""
        self.user.extra_roles.add(self.wh_role)
        u = User.objects.get(pk=self.user.pk)
        with self.assertNumQueries(2):
            u.has_role(Role.Code.WAREHOUSE)
            u.has_role(Role.Code.NURSE)
            u.can_warehouse

    def test_rolsiz_foydalanuvchi_yiqilmaydi(self):
        bosh = User.objects.create_user(username="bosh", password="x")
        self.assertEqual(bosh.role_codes, set())
        self.assertFalse(bosh.has_role(Role.Code.NURSE))
