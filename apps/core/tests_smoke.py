"""Barcha sahifalarni har bir rol ostida ochib ko'ramiz.

Nega bu test bor
----------------
Tizimda 300 dan ortiq manzil bor. Ularning ko'pchiligi biror rol uchun
yozilgan va boshqa rol kirganda nima bo'lishi hech qachon sinalmagan.
Amalda esa xodim menyudagi bandni bosadi va oq ekran (500) ko'radi.

Bu test har bir sahifani har bir rol nomidan ochadi va faqat BITTA
narsani talab qiladi: server yiqilmasin. Ruxsat yo'qligi (302, 403)
normal — bu ham javob.

Argumentli manzillar (masalan `/visit/<uuid>/`) tashlab ketiladi:
ularni ochish uchun tayyor ma'lumot kerak, u alohida testlarda bor.
"""
from django.test import TestCase
from django.urls import get_resolver

from apps.accounts.models import Role, User


def _argumentsiz_manzillar():
    """Faqat parametrsiz GET manzillar."""
    natija = []

    def yur(resolver, prefiks=""):
        for p in resolver.url_patterns:
            if hasattr(p, "url_patterns"):
                yur(p, prefiks + str(p.pattern))
                continue
            yol = prefiks + str(p.pattern)
            if "<" in yol or "(" in yol or "?P" in yol:
                continue
            natija.append("/" + yol.lstrip("/"))

    yur(get_resolver())
    return sorted(set(natija))


class SmokeTest(TestCase):
    """Har rol × har sahifa — 500 chiqmasin."""

    ROLLAR = [
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.DIRECTOR,
        Role.Code.CHIEF_DOCTOR, Role.Code.RECEPTION, *Role.DOCTOR_ROLES,
        Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.OPERATING_NURSE,
        Role.Code.LAB, Role.Code.RADIOLOGY, Role.Code.WAREHOUSE,
        Role.Code.CASHIER, Role.Code.ACCOUNTANT, Role.Code.SURGERY_ADMIN,
        Role.Code.SURGEON, Role.Code.ANESTHESIOLOGIST,
        Role.Code.STERILIZATION, Role.Code.AUDITOR, Role.Code.VIEWER,
    ]

    # Bular yuklab olish/tashqi ta'sirga ega — smoke uchun tashlanadi
    TASHLANADI = ("/admin", "/static", "/media", "/api")

    def _user(self, kod):
        rol, _ = Role.objects.get_or_create(code=kod, defaults={"name": kod})
        return User.objects.create_user(
            username=f"smoke_{kod}", password="x", role=rol)

    def test_hech_bir_sahifa_yiqilmaydi(self):
        manzillar = [u for u in _argumentsiz_manzillar()
                     if not u.startswith(self.TASHLANADI)]
        self.assertGreater(len(manzillar), 30, "Manzillar topilmadi.")

        xatolar = []
        for kod in self.ROLLAR:
            user = self._user(kod)
            self.client.force_login(user)
            for u in manzillar:
                try:
                    r = self.client.get(u, follow=False)
                except Exception as e:  # noqa: BLE001
                    xatolar.append(f"{kod} {u} -> {type(e).__name__}: {e}")
                    continue
                if r.status_code >= 500:
                    xatolar.append(f"{kod} {u} -> {r.status_code}")
            self.client.logout()

        self.assertEqual(xatolar, [], "Yiqilgan sahifalar:\n" +
                         "\n".join(xatolar[:40]))

    def test_kirmagan_odam_yiqitmaydi(self):
        """Login qilmagan mehmon ham 500 chiqarmasin."""
        xatolar = []
        for u in _argumentsiz_manzillar():
            if u.startswith(self.TASHLANADI):
                continue
            try:
                r = self.client.get(u)
            except Exception as e:  # noqa: BLE001
                xatolar.append(f"{u} -> {type(e).__name__}: {e}")
                continue
            if r.status_code >= 500:
                xatolar.append(f"{u} -> {r.status_code}")
        self.assertEqual(xatolar, [], "Mehmon uchun yiqilgan sahifalar:\n" +
                         "\n".join(xatolar[:40]))
