"""Sozlamalar sahifasini DOM testi uchun yozib qo'yamiz.

Nega bu bor
-----------
`tests_js/service_settings.test.js` haqiqiy chizilgan sahifani o'qiydi:
modal ichidagi JS ni tekshirish uchun shablonni Django chizishi kerak.

Ilgari u fayl `/tmp/settings.html` da turardi. `/tmp` kompyuter
o'chganda tozalanadi va DOM testi har safar yiqilardi — xato dasturda
emas, testning o'zida edi.

Endi sahifa shu test orqali `tests_js/fixtures/` ichiga yoziladi.
"""
from pathlib import Path

from django.conf import settings
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User

FIXTURE = (Path(settings.BASE_DIR) / "tests_js" / "fixtures"
           / "settings.html")


class SettingsFixtureTest(TestCase):
    def setUp(self):
        rol, _ = Role.objects.get_or_create(
            code=Role.Code.SUPER_ADMIN, defaults={"name": "Super admin"})
        self.user = User.objects.create_user(
            username="fixture_super", password="x", role=rol,
            is_superuser=True)

    def test_sahifa_ochiladi_va_yoziladi(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse("clinical:service_settings"))
        self.assertEqual(r.status_code, 200)

        html = r.content.decode()
        # DOM testi aynan shu ikkisiga tayanadi
        self.assertIn("routingOptions", html)
        self.assertIn("routingForm", html)

        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(html, encoding="utf-8")
        self.assertTrue(FIXTURE.exists())
