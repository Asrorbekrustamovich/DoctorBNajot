"""Takroriy JSHSHIR/pasport 500 xato bermasligi kerak.

HAQIQIY XATO: `Patient` da soft delete ishlatiladi. O'chirilgan bemor
bazada qoladi va JSHSHIR ni band qilib turadi, lekin ModelForm faqat
tiriklarni ko'radi. Natijada forma «hammasi joyida» deb o'tkazib
yuborardi va baza `IntegrityError` tashlab, foydalanuvchiga 500 sahifa
ko'rsatilardi.
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.patients.forms import PatientForm
from apps.patients.models import Patient


def form_data(**kw):
    data = {
        "last_name": "Yangi", "first_name": "Bemor", "middle_name": "",
        "birth_date": "1990-01-01", "gender": "male",
        "jshshir": "", "passport": "", "phone": "", "address": "", "notes": "",
    }
    data.update(kw)
    return data


class PatientUniqueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username="pu_admin", password="x", is_superuser=True, is_staff=True,
            role=Role.objects.get_or_create(code="reception",
                                            defaults={"name": "Reg"})[0])
        cls.existing = Patient.objects.create(
            card_number="P-EX1", last_name="Mavjud", first_name="Bemor",
            birth_date=date(1985, 5, 5), gender="male",
            jshshir="12345678901234", passport="AA1234567")

    # ------------------------------------------------------- forma darajasi
    def test_tirik_bemordagi_jshshir_band(self):
        f = PatientForm(data=form_data(jshshir="12345678901234"))
        self.assertFalse(f.is_valid())
        # Django apostrofni HTML kodlaydi — solishtirishdan oldin ochamiz
        self.assertIn("allaqachon ro'yxatda",
                      str(f.errors["jshshir"]).replace("&#x27;", "'"))

    def test_ochirilgan_bemordagi_jshshir_ham_band(self):
        """Eng muhimi — aynan shu holat 500 berardi."""
        self.existing.delete()                       # soft delete
        self.assertFalse(Patient.objects.filter(jshshir="12345678901234").exists())
        self.assertTrue(Patient.all_objects.filter(jshshir="12345678901234").exists())

        f = PatientForm(data=form_data(jshshir="12345678901234"))
        self.assertFalse(f.is_valid())
        self.assertIn("tiklang", str(f.errors["jshshir"]))

    def test_pasport_ham_tekshiriladi(self):
        f = PatientForm(data=form_data(passport="AA1234567"))
        self.assertFalse(f.is_valid())

    def test_bosh_jshshir_null_boladi(self):
        """Bo'sh satr saqlansa, JSHSHIR'siz ikkinchi bemor unique'ni buzardi.

        Hujjat sifatida METRIKA beramiz: sinaladigan narsa bo'sh
        JSHSHIR/pasportning NULL ga aylanishi, hujjat qoidasi emas.
        """
        f = PatientForm(data=form_data(birth_certificate="V-XX 000111"))
        self.assertTrue(f.is_valid(), f.errors)
        self.assertIsNone(f.cleaned_data["jshshir"])
        self.assertIsNone(f.cleaned_data["passport"])

    def test_jshshirsiz_ikkita_bemor_yaratiladi(self):
        Patient.objects.create(card_number="P-N1", last_name="A", first_name="A",
                               birth_date=date(1990, 1, 1), gender="male")
        Patient.objects.create(card_number="P-N2", last_name="B", first_name="B",
                               birth_date=date(1990, 1, 1), gender="male")
        self.assertEqual(Patient.objects.filter(jshshir__isnull=True).count(), 2)

    # -------------------------------------------------------- sahifa darajasi
    def test_sahifa_500_bermaydi(self):
        self.existing.delete()
        self.client.force_login(self.admin)
        r = self.client.post(reverse("patients:create"),
                             form_data(jshshir="12345678901234"))
        self.assertEqual(r.status_code, 200, "500 yoki yo'naltirish bo'ldi")
        self.assertContains(r, "tiklang")

    def test_togri_malumot_saqlanadi(self):
        self.client.force_login(self.admin)
        r = self.client.post(reverse("patients:create"),
                             form_data(jshshir="99999999999999"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Patient.objects.filter(jshshir="99999999999999").exists())
