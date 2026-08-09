"""Statsionar epizodi oqimi.

Talab qilingan ketma-ketlik:
    hujjat turi → topish → eski yotqizilishlar → yangi epizod →
    dastlabki ko'rik → MKB-10 tashxislar → tekshiruvlar →
    qabulxona hamshirasiga yuborish
"""
from __future__ import annotations

from datetime import date

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, EpisodeDiagnosis, ICD10Code, ServiceCatalog,
    ServiceCategory,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


def role(code: str) -> Role:
    return Role.objects.get_or_create(code=code, defaults={"name": code.title()})[0]


class EpisodeBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.doctor = User.objects.create_user(username="ep_doc", password="x",
                                              role=role("doctor"))
        cls.nurse = User.objects.create_user(username="ep_nurse", password="x",
                                             role=role("nurse"))
        # DIQQAT: `card_number` modelda emas, servis qatlamida beriladi
        # (`patients.services`). To'g'ridan-to'g'ri `objects.create()` da
        # u bo'sh qoladi va ikkinchi bemorda unique cheklovi buziladi.
        cls.adult = Patient.objects.create(
            card_number="P-900001",
            last_name="Valiyev", first_name="Ali", birth_date=date(1990, 5, 5),
            gender=Patient.Gender.MALE, jshshir="12345678901234")
        cls.child = Patient.objects.create(
            card_number="P-900002",
            last_name="Karimova", first_name="Aziza", birth_date=date(2021, 3, 1),
            gender=Patient.Gender.FEMALE, birth_certificate="I-AB 123456")
        cls.visit = Visit.objects.create(
            patient=cls.adult, doctor=cls.doctor,
            visit_date=date(2026, 8, 1), queue_number=1)
        # Bu kodlar 0033_seed_icd10 migratsiyasida allaqachon yaratilgan —
        # shuning uchun `create` emas, `get_or_create`.
        cls.icd_main = ICD10Code.objects.get_or_create(
            code="K35.8", defaults={"name": "O'tkir appendisit"})[0]
        cls.icd_conc = ICD10Code.objects.get_or_create(
            code="I10", defaults={"name": "Arterial gipertenziya"})[0]


# ------------------------------------------------------------------ topish
class DocumentSearchTests(EpisodeBase):

    def setUp(self):
        self.client.force_login(self.doctor)

    def test_jshshir_boyicha_topiladi(self):
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "jshshir", "number": "12345678901234"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Valiyev")

    def test_jshshir_ajratgichlar_bilan_ham_topiladi(self):
        """Registrator raqamni bo'shliq bilan yozishi mumkin."""
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "jshshir", "number": "1234 5678 9012 34"})
        self.assertContains(r, "Valiyev")

    def test_notogri_uzunlikdagi_jshshir_ogohlantiradi(self):
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "jshshir", "number": "123"})
        self.assertContains(r, "14 ta raqam")

    def test_metrika_boyicha_topiladi(self):
        """Bolada JSHSHIR yo'q — metrika bo'yicha qidiriladi."""
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "metrika", "number": "I-AB 123456"})
        self.assertContains(r, "Karimova")

    def test_metrika_yozilishi_farq_qilsa_ham_topiladi(self):
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "metrika", "number": "iab123456"})
        self.assertContains(r, "Karimova")

    def test_topilmasa_xabar_beradi(self):
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "jshshir", "number": "99999999999999"})
        self.assertContains(r, "topilmadi")

    def test_eski_yotqizilishlar_korinadi(self):
        AdmissionEpisode.objects.create(
            patient=self.adult, referred_by=self.doctor, reason="Eski holat")
        r = self.client.get(reverse("clinical:episode_search"),
                            {"document_type": "jshshir", "number": "12345678901234"})
        self.assertContains(r, "Eski holat")


# ------------------------------------------------------------------ epizod
class EpisodeCreateTests(EpisodeBase):

    def setUp(self):
        self.client.force_login(self.doctor)

    def _create(self, **extra):
        data = {"document_type": "jshshir", "number": "12345678901234",
                "reason": "Qorin og'rig'i", "purpose": "treatment",
                "with_primary_exam": "1"}
        data.update(extra)
        return self.client.post(
            reverse("clinical:episode_create", args=[self.adult.pk]), data)

    def test_epizod_ochiladi_va_shifokor_yoziladi(self):
        self._create()
        e = AdmissionEpisode.objects.get(patient=self.adult)
        self.assertEqual(e.referred_by, self.doctor)
        self.assertEqual(e.status, AdmissionEpisode.Status.DRAFT)
        self.assertTrue(e.with_primary_exam)

    def test_kravatsiz_yaratiladi(self):
        """Shifokor yo'llaganda kravat hali tanlanmagan."""
        self._create()
        self.assertIsNone(AdmissionEpisode.objects.get(patient=self.adult).stay)

    def test_operatsiya_uchun_anesteziolog_kerak(self):
        self._create(purpose="surgery")
        self.assertTrue(AdmissionEpisode.objects.get(patient=self.adult).needs_anesthesiologist)

    def test_davolash_uchun_anesteziolog_kerak_emas(self):
        self._create(purpose="treatment")
        self.assertFalse(AdmissionEpisode.objects.get(patient=self.adult).needs_anesthesiologist)

    def test_birlamchi_koriksiz_yotqizish(self):
        self._create(with_primary_exam="")
        self.assertFalse(AdmissionEpisode.objects.get(patient=self.adult).with_primary_exam)

    def test_ikkinchi_ochiq_epizod_yaratilmaydi(self):
        """Aks holda bitta bemor ikki joyda «yotayotgan» bo'lib qoladi."""
        self._create()
        self._create()
        self.assertEqual(AdmissionEpisode.objects.filter(patient=self.adult).count(), 1)

    def test_yopilgandan_keyin_yangisi_ochiladi(self):
        self._create()
        AdmissionEpisode.objects.update(status=AdmissionEpisode.Status.DISCHARGED)
        self._create()
        self.assertEqual(AdmissionEpisode.objects.filter(patient=self.adult).count(), 2)


# ------------------------------------------------------ ko'rik va tashxislar
class EpisodeContentTests(EpisodeBase):

    def setUp(self):
        self.client.force_login(self.doctor)
        self.ep = AdmissionEpisode.objects.create(
            patient=self.adult, visit=self.visit,
            referred_by=self.doctor, reason="Qorin og'rig'i")

    def test_dastlabki_korik_bolimlari_bor(self):
        r = self.client.get(reverse("clinical:episode_detail", args=[self.ep.pk]))
        for bolim in ["Shikoyatlar", "Anamnesis morbi", "Anamnesis vitae",
                      "Status localis", "Epidemiologik anamnez",
                      "Status praesens", "Allergoanamnez", "Nevrologik holati",
                      "Klinik tashxis"]:
            self.assertContains(r, bolim, msg_prefix=f"«{bolim}» yo'q")

    def test_korik_saqlanadi(self):
        self.client.post(reverse("clinical:episode_save_exam", args=[self.ep.pk]), {
            "complaints": "Qorinda og'riq", "anamnesis_morbi": "1 kun",
            "status_praesens": "Qoniqarli", "clinical_diagnosis": "O'tkir appendisit",
            "department": "Xirurgiya", "purpose": "surgery",
        })
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.complaints, "Qorinda og'riq")
        self.assertEqual(self.ep.department, "Xirurgiya")
        self.assertEqual(self.ep.purpose, AdmissionEpisode.Purpose.SURGERY)

    def test_bir_nechta_tashxis_qoshiladi(self):
        url = reverse("clinical:episode_add_diagnosis", args=[self.ep.pk])
        self.client.post(url, {"icd": str(self.icd_main.id), "kind": "main",
                               "stage": "preliminary", "course": "acute"})
        self.client.post(url, {"icd": str(self.icd_conc.id), "kind": "concomitant",
                               "stage": "final", "course": "chronic"})
        self.assertEqual(self.ep.diagnoses.count(), 2)
        self.assertEqual(self.ep.main_diagnosis.icd, self.icd_main)

    def test_tashxis_atributlari_saqlanadi(self):
        self.client.post(reverse("clinical:episode_add_diagnosis", args=[self.ep.pk]),
                         {"icd": str(self.icd_main.id), "stage": "final",
                          "kind": "complication", "course": "subacute"})
        d = self.ep.diagnoses.first()
        self.assertEqual(d.stage, EpisodeDiagnosis.Stage.FINAL)
        self.assertEqual(d.kind, EpisodeDiagnosis.Kind.COMPLICATION)
        self.assertEqual(d.course, EpisodeDiagnosis.Course.SUBACUTE)

    def test_royxatda_yoq_tashxis_matn_bilan(self):
        self.client.post(reverse("clinical:episode_add_diagnosis", args=[self.ep.pk]),
                         {"free_text": "Noyob holat", "kind": "main"})
        self.assertEqual(self.ep.diagnoses.first().label, "Noyob holat")

    def test_bosh_tashxis_qoshilmaydi(self):
        self.client.post(reverse("clinical:episode_add_diagnosis", args=[self.ep.pk]), {})
        self.assertEqual(self.ep.diagnoses.count(), 0)

    def test_tashxis_ochiriladi(self):
        self.client.post(reverse("clinical:episode_add_diagnosis", args=[self.ep.pk]),
                         {"icd": str(self.icd_main.id)})
        d = self.ep.diagnoses.first()
        self.client.post(reverse("clinical:episode_delete_diagnosis",
                                 args=[self.ep.pk, d.pk]))
        self.assertEqual(self.ep.diagnoses.count(), 0)

    def test_icd_qidiruv_ishlaydi(self):
        r = self.client.get(reverse("clinical:icd_search"), {"q": "appendis"})
        self.assertEqual(r.json()["results"][0]["code"], "K35.8")

    def test_tekshiruv_pikeri_epizodda_bor(self):
        """«+Analiz» statsionar rasmiylashtirishda ham bo'lishi kerak."""
        cat = ServiceCategory.objects.create(name="Laboratoriya", button_label="+Analiz")
        ServiceCatalog.objects.create(name="Umumiy qon tahlili", price=40000, category=cat)
        r = self.client.get(reverse("clinical:episode_detail", args=[self.ep.pk]))
        self.assertContains(r, "examPicker")
        self.assertContains(r, "+Analiz")
        self.assertContains(r, "Umumiy qon tahlili")


# ------------------------------------------------------- yuborish va rollar
class EpisodeFlowTests(EpisodeBase):

    def setUp(self):
        self.ep = AdmissionEpisode.objects.create(
            patient=self.adult, referred_by=self.doctor, reason="Qorin og'rig'i")

    def test_qabulxonaga_yuboriladi(self):
        self.client.force_login(self.doctor)
        self.client.post(reverse("clinical:episode_send", args=[self.ep.pk]))
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, AdmissionEpisode.Status.SENT)
        self.assertIsNotNone(self.ep.sent_at)

    def test_sababsiz_yuborilmaydi(self):
        self.ep.reason = ""
        self.ep.save()
        self.client.force_login(self.doctor)
        self.client.post(reverse("clinical:episode_send", args=[self.ep.pk]))
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, AdmissionEpisode.Status.DRAFT)

    def test_hamshira_royxatda_koradi(self):
        self.ep.status = AdmissionEpisode.Status.SENT
        self.ep.save()
        self.client.force_login(self.nurse)
        r = self.client.get(reverse("clinical:nurse_incoming"))
        self.assertContains(r, "Valiyev")
        self.assertContains(r, self.doctor.username)

    def test_hamshira_tahrir_qila_olmaydi(self):
        """«Bo'lim hamshirasiga FAQAT KO'RINSIN» — talab shu."""
        self.client.force_login(self.nurse)
        r = self.client.get(reverse("clinical:episode_detail", args=[self.ep.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "faqat")

        self.client.post(reverse("clinical:episode_save_exam", args=[self.ep.pk]),
                         {"complaints": "HAMSHIRA YOZDI"})
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.complaints, "")

    def test_qabul_yozuvi_bekor_qilinadi(self):
        self.client.force_login(self.doctor)
        self.client.post(reverse("clinical:episode_cancel", args=[self.ep.pk]),
                         {"cancel_reason": "Bemor rozi bo'lmadi"})
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, AdmissionEpisode.Status.CANCELLED)
        self.assertEqual(self.ep.cancel_reason, "Bemor rozi bo'lmadi")

    def test_yotqizilgan_epizod_bekor_qilinmaydi(self):
        self.ep.status = AdmissionEpisode.Status.ADMITTED
        self.ep.save()
        self.client.force_login(self.doctor)
        self.client.post(reverse("clinical:episode_cancel", args=[self.ep.pk]))
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, AdmissionEpisode.Status.ADMITTED)

    def test_yopilgan_epizod_tahrirlanmaydi(self):
        self.ep.status = AdmissionEpisode.Status.DISCHARGED
        self.ep.save()
        self.client.force_login(self.doctor)
        self.client.post(reverse("clinical:episode_save_exam", args=[self.ep.pk]),
                         {"complaints": "KECH"})
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.complaints, "")


# ------------------------------------------------------------- VIPISKA
class DischargeTests(EpisodeBase):
    """5 kun yotgan bemorga chiqishda to'liq hujjat shakllanishi kerak."""

    def setUp(self):
        from django.utils import timezone
        from datetime import timedelta
        from apps.clinical.models import (
            Bed, InpatientStay, Room, ServiceCatalog, ServiceCategory,
            ServiceOrder, ServiceResultRow,
        )

        self.ep = AdmissionEpisode.objects.create(
            patient=self.adult, visit=self.visit, referred_by=self.doctor,
            reason="Qorin og'rig'i", department="Xirurgiya",
            complaints="Qorinda kuchli og'riq",
            status=AdmissionEpisode.Status.ADMITTED,
        )
        EpisodeDiagnosis.objects.create(
            episode=self.ep, icd=self.icd_main, kind=EpisodeDiagnosis.Kind.MAIN,
            stage=EpisodeDiagnosis.Stage.FINAL, course=EpisodeDiagnosis.Course.ACUTE)
        EpisodeDiagnosis.objects.create(
            episode=self.ep, icd=self.icd_conc,
            kind=EpisodeDiagnosis.Kind.CONCOMITANT)

        # 5 kun oldin yotqizilgan
        room = Room.objects.create(name="Sinov-1")
        bed = Bed.objects.create(room=room, number="1A")
        stay = InpatientStay.objects.create(visit=self.visit, bed=bed)
        InpatientStay.objects.filter(pk=stay.pk).update(
            admission_date=timezone.now() - timedelta(days=5))
        self.ep.stay = InpatientStay.objects.get(pk=stay.pk)
        self.ep.save()

        # Tayyor natijali tekshiruv
        cat = ServiceCategory.objects.create(name="Vip lab", button_label="+Analiz")
        svc = ServiceCatalog.objects.create(name="Qon tahlili", price=0, category=cat)
        self.order = ServiceOrder.objects.create(
            visit=self.visit, service=svc,
            status=ServiceOrder.Status.COMPLETED,
            result_at=timezone.now(), result_text="Leykotsitoz")
        ServiceResultRow.objects.create(
            order=self.order, name="Leykotsit", value="14.2",
            unit="10^9/l", reference="4.0-9.0", is_abnormal=True)

        self.client.force_login(self.doctor)

    def _write(self, **extra):
        data = {"outcome": "recovered", "work_capacity": "sick_leave",
                "treatment_given": "Appendektomiya, antibiotiklar",
                "condition_at_discharge": "Qoniqarli",
                "recommendations": "2 hafta og'ir yuk ko'tarmaslik",
                "follow_up": "10 kundan keyin oilaviy shifokorga"}
        data.update(extra)
        return self.client.post(
            reverse("clinical:episode_discharge", args=[self.ep.pk]), data)

    def test_vipiska_shakllanadi(self):
        from apps.clinical.models import DischargeSummary
        r = self._write()
        self.assertEqual(r.status_code, 302)
        s = DischargeSummary.objects.get(episode=self.ep)
        self.assertEqual(s.outcome, DischargeSummary.Outcome.RECOVERED)
        self.assertEqual(s.discharged_by, self.doctor)

    def test_epizod_yopiladi(self):
        self._write()
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, AdmissionEpisode.Status.DISCHARGED)
        self.assertFalse(self.ep.is_open)

    def test_yotgan_kunlar_hisoblanadi(self):
        self._write()
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.discharge.bed_days, 5)

    def test_blank_hamma_malumotni_yigadi(self):
        """Shifokor qo'lda ko'chirib yozmasligi kerak."""
        self._write()
        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        self.assertEqual(r.status_code, 200)
        # Django apostrofni `&#x27;` deb kodlaydi — solishtirishdan oldin
        # ikkala tomonni bir ko'rinishga keltiramiz.
        h = r.content.decode().replace("&#x27;", "'")

        self.assertIn(self.adult.last_name, h)          # bemor
        self.assertIn("Xirurgiya", h)                    # bo'lim
        self.assertIn("5 kun", h)                        # yotgan kunlar
        self.assertIn("K35.8", h)                        # asosiy tashxis
        self.assertIn("I10", h)                          # hamroh tashxis
        self.assertIn("Qon tahlili", h)                  # tekshiruv
        self.assertIn("Leykotsit", h)                    # natija ko'rsatkichi
        self.assertIn("Appendektomiya", h)               # davolash
        self.assertIn("Sog'aydi", h)                     # natija
        self.assertIn("2 hafta", h)                      # tavsiya
        self.assertIn("Qorinda kuchli og'riq", h)        # kelgandagi shikoyat

    def test_normadan_chetlanish_ajratiladi(self):
        self._write()
        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        self.assertContains(r, "#b3261e")   # qizil rang bilan

    def test_vipiskasiz_chop_etib_bolmaydi(self):
        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        self.assertEqual(r.status_code, 302)

    def test_qayta_yozilsa_ikkilanmaydi(self):
        from apps.clinical.models import DischargeSummary
        self._write()
        self._write(outcome="improved")
        self.assertEqual(DischargeSummary.objects.filter(episode=self.ep).count(), 1)
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.discharge.outcome, DischargeSummary.Outcome.IMPROVED)

    def test_hamshira_vipiska_yoza_olmaydi(self):
        """Ruxsat bo'lmasa ham 302 qaytadi (rad etish sahifasiga).

        Shuning uchun status kodiga emas, NATIJAGA qaraymiz: vipiska
        yaratilmagan va epizod ochiq qolgan bo'lishi kerak.
        """
        from apps.clinical.models import DischargeSummary
        self.client.force_login(self.nurse)
        self._write()
        self.assertFalse(DischargeSummary.objects.filter(episode=self.ep).exists())
        self.ep.refresh_from_db()
        self.assertEqual(self.ep.status, AdmissionEpisode.Status.ADMITTED)

    def test_hamshira_vipiskani_kora_oladi(self):
        self._write()
        self.client.force_login(self.nurse)
        r = self.client.get(reverse("clinical:discharge_print", args=[self.ep.pk]))
        self.assertEqual(r.status_code, 200)
