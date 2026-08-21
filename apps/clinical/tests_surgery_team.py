"""Operatsiyaga yozish oynasidagi jamoa ro'yxatlari.

Nega bu testlar bor
-------------------
«Jarroh» va «Anesteziolog» ro'yxatlari bo'm-bo'sh chiqardi. Sabab:
ro'yxat `role__code=surgeon` deb faqat ASOSIY rolni qidirardi, klinikadagi
xirurglarning asosiy roli esa «shifokor» — ular ambulator qabul ham
qiladi, jarrohlik ularning qo'shimcha roli.

Bo'sh ro'yxat jim turadi: xatolik chiqmaydi, shunchaki tanlash mumkin
bo'lmaydi. Shuning uchun buni test ushlab turishi kerak.
"""
from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User, users_with_role
from apps.clinical.views import surgery_team_context


def rol(kod, nom):
    return Role.objects.get_or_create(code=kod, defaults={"name": nom})[0]


class UsersWithRoleTest(TestCase):
    def setUp(self):
        self.doctor = rol(Role.Code.THERAPIST, "Terapevt")
        self.surgeon = rol(Role.Code.SURGEON, "Jarroh")
        self.anest = rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog")

    def test_asosiy_rol_topiladi(self):
        u = User.objects.create_user(username="j1", password="x",
                                     role=self.surgeon)
        self.assertIn(u, users_with_role(Role.Code.SURGEON))

    def test_qoshimcha_rol_ham_topiladi(self):
        """Asosiy roli «shifokor», jarrohlik qo'shimcha."""
        u = User.objects.create_user(username="j2", password="x",
                                     role=self.doctor)
        u.extra_roles.add(self.surgeon)
        self.assertIn(u, users_with_role(Role.Code.SURGEON))

    def test_begona_rol_tushmaydi(self):
        u = User.objects.create_user(username="j3", password="x",
                                     role=self.doctor)
        self.assertNotIn(u, users_with_role(Role.Code.SURGEON))

    def test_ikki_marta_chiqmaydi(self):
        """Bir nechta rol mos kelsa ham — ro'yxatda bitta qator.

        `assistants` ro'yxati bir necha rolni birdan so'raydi. Ikki
        qo'shimcha roli bo'lgan xodim JOIN sababli ikki marta chiqib
        qolardi — tanlash ro'yxatida ismi takrorlanib turardi.
        """
        u = User.objects.create_user(username="j4", password="x",
                                     role=self.surgeon)
        u.extra_roles.add(self.surgeon, self.doctor)
        royxat = list(users_with_role(Role.Code.SURGEON, *Role.DOCTOR_ROLES))
        self.assertEqual(royxat.count(u), 1)

    def test_faolsiz_xodim_chiqmaydi(self):
        u = User.objects.create_user(username="j5", password="x",
                                     role=self.surgeon)
        u.is_active = False
        u.save(update_fields=["is_active"])
        self.assertNotIn(u, users_with_role(Role.Code.SURGEON))

    def test_ochirilgan_xodim_chiqmaydi(self):
        u = User.objects.create_user(username="j6", password="x",
                                     role=self.surgeon)
        u.delete()  # soft delete
        self.assertNotIn(u, users_with_role(Role.Code.SURGEON))


class SurgeryTeamContextTest(TestCase):
    """Oynaga uzatiladigan ro'yxatlar bo'sh qolmasin."""

    def setUp(self):
        doctor = rol(Role.Code.THERAPIST, "Terapevt")
        self.xirurg = User.objects.create_user(
            username="xirurg", password="x", role=doctor,
            last_name="Durdiyev", first_name="Xamdam",
            specialty="Xirurg / amblator")
        self.xirurg.extra_roles.add(rol(Role.Code.SURGEON, "Jarroh"))

        self.anesteziolog = User.objects.create_user(
            username="anest", password="x", role=doctor,
            last_name="Qabulov", first_name="Kamaraddin",
            specialty="Anestezolog / reanimatolog")
        self.anesteziolog.extra_roles.add(
            rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))

        self.anestiziska = User.objects.create_user(
            username="anestiziska", password="x",
            role=rol(Role.Code.NURSE, "Hamshira"),
            last_name="Maxmurdova", first_name="Shaxnoza",
            specialty="Anestiziska")

    def test_jarrohlar_royxati_bosh_emas(self):
        self.assertIn(self.xirurg, surgery_team_context()["surgeons"])

    def test_anesteziologlar_royxati_bosh_emas(self):
        self.assertIn(self.anesteziolog,
                      surgery_team_context()["anesthesiologists"])

    def test_anestiziska_operatsion_hamshiralar_orasida(self):
        """Anestiziska alohida maydonga ega emas — operatsion
        hamshiralar ichidan tanlanadi."""
        self.assertIn(self.anestiziska,
                      surgery_team_context()["operating_nurses"])

    def test_anestiziska_maydonida_hamshiralar(self):
        """«Anestiziska» maydoni — hamshiralar uchun.

        Ilgari bu maydon «Operatsion asistent» deb atalardi va unga
        shifokorlar ham aralash chiqardi. Amalda u yerda anestiziska
        turadi, shuning uchun shifokorlar ro'yxatdan olib tashlandi.
        """
        assistentlar = surgery_team_context()["assistants"]
        self.assertIn(self.anestiziska, assistentlar)
        self.assertNotIn(self.xirurg, assistentlar)


class SurgeryModalRenderTest(TestCase):
    """Oyna chindan ham ismlarni chiqarayaptimi."""

    def setUp(self):
        doctor = rol(Role.Code.THERAPIST, "Terapevt")
        self.xirurg = User.objects.create_user(
            username="xirurg2", password="x", role=doctor,
            last_name="Zaripboev", first_name="Jasur",
            specialty="Xirurg / Endoskopist")
        self.xirurg.extra_roles.add(rol(Role.Code.SURGEON, "Jarroh"))

        self.anesteziolog = User.objects.create_user(
            username="anest2", password="x", role=doctor,
            last_name="Qabulov", first_name="Kamaraddin",
            specialty="Anestezolog")
        self.anesteziolog.extra_roles.add(
            rol(Role.Code.ANESTHESIOLOGIST, "Anesteziolog"))

        self.admin = User.objects.create_user(
            username="jadmin", password="x",
            role=rol(Role.Code.SURGERY_ADMIN, "Jarrohlik admin"))

    def _sahifa(self):
        self.client.force_login(self.admin)
        return self.client.get(
            reverse("clinical:surgery_dashboard")).content.decode()

    def test_jarroh_ismi_chiqadi(self):
        self.assertIn("Zaripboev Jasur", self._sahifa())

    def test_anesteziolog_ismi_chiqadi(self):
        self.assertIn("Qabulov Kamaraddin", self._sahifa())

    def test_mutaxassislik_ham_korsatiladi(self):
        """13 ta hamshira faqat ism bilan chiqsa, kimligi bilinmaydi."""
        self.assertIn("Xirurg / Endoskopist", self._sahifa())
