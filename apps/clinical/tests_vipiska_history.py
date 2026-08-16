"""VIPISKA: BEMOR TARIXI VA SHABLON YIG'ISH.

Ikki talab:

1. TEKSHIRUVLAR — bemorning butun tarixidan chiqishi kerak, nafaqat shu
   tashrifdan. Statsionarda yotganda tayinlangan analiz ham, oldingi
   ambulator tashrifda topshirilgani ham ro'yxatda ko'rinsin.

   LEKIN eskilari AVTOMATIK BELGILANMASLIGI shart. Aks holda uch yil
   oldingi analiz shifokor sezmagan holda rasmiy hujjatga chiqib ketadi
   — bu tashxislardagi bilan bir xil xato edi.

2. OLDINGI YOTISHLAR — bemor bir necha marta yotgan bo'lsa, har birining
   hisoboti modalda ochilib, kerakli qismi shablonga yig'ilsin. Shu
   epizodning o'zi ro'yxatda chiqmasligi kerak: o'zidan nusxa olishning
   ma'nosi yo'q.
"""
from datetime import date, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import Role, User
from apps.clinical.models import (
    AdmissionEpisode, DischargeSummary, DischargeTemplate, ServiceCatalog,
    ServiceOrder,
)
from apps.patients.models import Patient
from apps.registration.models import Visit


class VipiskaTarixTests(TestCase):
    def setUp(self):
        self.doc = User.objects.create_user(
            username="vt_doc", password="x",
            role=Role.objects.get_or_create(
                code="doctor", defaults={"name": "Shifokor"})[0])
        self.patient = Patient.objects.create(
            card_number="P-VT1", last_name="Tarix", first_name="Bemor",
            birth_date=date(1985, 5, 5), gender="male")

        self.svc_eski = ServiceCatalog.objects.create(name="Umumiy qon (eski)", price=10000)
        self.svc_yangi = ServiceCatalog.objects.create(name="Biokimyo (statsionar)", price=20000)

        # --- ESKI TASHRIF (o'tgan yil, ambulator)
        self.eski_visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today() - timedelta(days=400),
            queue_number=1)
        self.eski_order = ServiceOrder.objects.create(
            visit=self.eski_visit, service=self.svc_eski,
            status=ServiceOrder.Status.COMPLETED,
            result_text="Gemoglobin 120 g/l", result_at=timezone.now())

        # --- HOZIRGI TASHRIF + EPIZOD (statsionar)
        self.visit = Visit.objects.create(
            patient=self.patient, visit_date=date.today(), queue_number=2)
        self.yangi_order = ServiceOrder.objects.create(
            visit=self.visit, service=self.svc_yangi,
            status=ServiceOrder.Status.COMPLETED,
            result_text="ALT 30 U/l", result_at=timezone.now())
        self.episode = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.visit, referred_by=self.doc,
            reason="Qorin og'rig'i", status=AdmissionEpisode.Status.ADMITTED)

        self.url = reverse("clinical:episode_discharge", args=[self.episode.pk])
        self.client.force_login(self.doc)

    # ---------------- TEKSHIRUVLAR ----------------
    def test_statsionarda_tayinlangan_tekshiruv_chiqadi(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Biokimyo (statsionar)")

    def test_oldingi_tashrifdagi_tekshiruv_ham_chiqadi(self):
        """Asosiy talab: ro'yxat bemorning BUTUN tarixidan."""
        resp = self.client.get(self.url)
        self.assertContains(
            resp, "Umumiy qon (eski)",
            msg_prefix="Oldingi tashrifdagi tekshiruv ro'yxatga tushmadi — "
                       "shifokor uni vipiskaga qo'sha olmaydi")

    def test_shu_epizodniki_belgilangan_eskisi_belgilanmagan(self):
        """Eng muhim test: eskisi O'ZI hujjatga tushib ketmasin."""
        orders = {o.pk: o for o in self.client.get(self.url).context["orders"]}

        self.assertTrue(orders[self.yangi_order.pk].vip_checked,
                        "Shu epizodning tekshiruvi belgilanmagan.")
        self.assertFalse(
            orders[self.eski_order.pk].vip_checked,
            "O'tgan yilgi tekshiruv AVTOMATIK belgilangan — shifokor "
            "sezmasa rasmiy hujjatga chiqib ketadi.")

    def test_natijasiz_tekshiruv_royxatga_tushmaydi(self):
        ServiceOrder.objects.create(
            visit=self.visit, service=self.svc_eski,
            status=ServiceOrder.Status.WAITING)
        orders = self.client.get(self.url).context["orders"]
        self.assertTrue(all(o.has_result for o in orders),
                        "Natijasi yo'q tekshiruv vipiska ro'yxatiga tushdi.")

    def test_boshqa_bemor_tekshiruvi_qoshilmaydi(self):
        """Tarixni kengaytirganda begona bemor kirib qolmasin."""
        boshqa = Patient.objects.create(
            card_number="P-VT2", last_name="Begona", first_name="Bemor",
            birth_date=date(1990, 1, 1), gender="female")
        bv = Visit.objects.create(patient=boshqa, visit_date=date.today(),
                                  queue_number=3)
        ServiceOrder.objects.create(
            visit=bv, service=self.svc_eski,
            status=ServiceOrder.Status.COMPLETED,
            result_text="BEGONA NATIJA", result_at=timezone.now())

        resp = self.client.get(self.url)
        self.assertNotContains(resp, "BEGONA NATIJA")

    # ---------------- OLDINGI YOTISHLAR ----------------
    def test_oldingi_epizod_modalda_chiqadi(self):
        eski_ep = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.eski_visit, referred_by=self.doc,
            reason="ESKI SABAB", status=AdmissionEpisode.Status.DISCHARGED)
        DischargeSummary.objects.create(
            episode=eski_ep, discharged_by=self.doc,
            treatment_given="ESKI DAVOLASH MATNI",
            recommendations="ESKI TAVSIYA")

        resp = self.client.get(self.url)
        self.assertContains(resp, "ESKI DAVOLASH MATNI")
        self.assertContains(resp, "ESKI TAVSIYA")
        self.assertContains(resp, "ESKI SABAB")

    def test_shu_epizod_oldingilar_royxatida_chiqmaydi(self):
        """O'zidan nusxa olish ma'nosiz — va chalkashtiradi."""
        resp = self.client.get(self.url)
        past = resp.context["past_episodes"]
        self.assertNotIn(self.episode.pk, [p["episode"].pk for p in past])

    def test_bekor_qilingan_epizod_chiqmaydi(self):
        AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.eski_visit, referred_by=self.doc,
            reason="BEKOR QILINGAN EPIZOD",
            status=AdmissionEpisode.Status.CANCELLED)
        resp = self.client.get(self.url)
        self.assertNotContains(resp, "BEKOR QILINGAN EPIZOD")

    def test_bosh_bloklar_royxatga_tushmaydi(self):
        """Bo'm-bo'sh sarlavhalar keraklisini topishni qiyinlashtiradi."""
        eski_ep = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.eski_visit, referred_by=self.doc,
            reason="Sabab bor", complaints="",
            status=AdmissionEpisode.Status.DISCHARGED)

        past = self.client.get(self.url).context["past_episodes"]
        pe = next(p for p in past if p["episode"].pk == eski_ep.pk)
        bosh = [nom for nom, matn in pe["bloklar"] if not matn]
        self.assertTrue(bosh, "Sinov noto'g'ri qurildi — bo'sh blok yo'q")
        # Shablonda `{% if blok.1 %}` bilan yashiriladi
        resp = self.client.get(self.url)
        self.assertNotContains(resp, ">Shikoyatlar<")

    # ---------------- SHABLON ----------------
    def test_shablon_saqlanadi_va_royxatda_chiqadi(self):
        self.client.post(self.url, {
            "save_template": "1",
            "template_name": "Appendektomiya standart",
            "template_content": "O'tkazilgan davolash (01.01.2025):\nInfuzion terapiya",
        })
        tpl = DischargeTemplate.objects.filter(doctor=self.doc).first()
        self.assertIsNotNone(tpl, "Shablon saqlanmadi.")
        self.assertEqual(tpl.name, "Appendektomiya standart")

        resp = self.client.get(self.url)
        self.assertContains(resp, "Appendektomiya standart")

    # ---------------- EPIZOD SAHIFASIDA BELGILASH ----------------
    def test_epizod_sahifasida_butun_tarix_ptechka_bilan(self):
        """Shifokor bemor yotgan paytda belgilaydi — vipiskani kutmasdan."""
        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))

        nomlar = {o.service.name for o in resp.context["exam_orders"]}
        self.assertIn("Umumiy qon (eski)", nomlar,
                      "Epizod sahifasida bemorning eski tekshiruvi ko'rinmadi")
        self.assertIn("Biokimyo (statsionar)", nomlar)
        self.assertContains(resp, "vip-chk")

    def test_belgilash_saqlanadi_va_vipiskaga_otadi(self):
        """Belgilash → saqlash → vipiskada aynan o'sha chiqishi.

        Ikki sahifa alohida hisoblasa, shifokor epizodda belgilaydi-yu
        vipiskada boshqa narsa chiqadi. Shuning uchun uchidan-uchiga
        tekshiramiz.
        """
        url = reverse("clinical:episode_select_orders", args=[self.episode.pk])
        resp = self.client.post(url, {"selected_orders": [str(self.eski_order.pk)]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["count"], 1)

        orders = {o.pk: o for o in self.client.get(self.url).context["orders"]}
        self.assertTrue(orders[self.eski_order.pk].vip_checked,
                        "Belgilangan eski tekshiruv vipiskada belgilanmagan.")
        self.assertFalse(
            orders[self.yangi_order.pk].vip_checked,
            "Olib tashlangan tekshiruv vipiskada yana belgilanib qolgan.")

    def test_hech_biri_tanlanmagani_saqlanadi(self):
        """None (hali tanlanmagan) va [] (ataylab bo'sh) — boshqa-boshqa.

        Ikkalasini bir xil qilsak, «hech biri» bosilganda belgilar
        o'z-o'zidan qaytib kelaverardi.
        """
        url = reverse("clinical:episode_select_orders", args=[self.episode.pk])
        self.client.post(url, {})

        self.episode.refresh_from_db()
        self.assertEqual(self.episode.selected_order_ids, [])

        orders = self.client.get(self.url).context["orders"]
        self.assertFalse(any(o.vip_checked for o in orders),
                         "«Hech biri» saqlanmadi — belgilar qaytib keldi.")

    def test_begona_tekshiruv_id_si_saqlanmaydi(self):
        """Formaga qo'lda ID yozib, boshqa bemorning natijasini
        vipiskaga qo'shtirib bo'lmasin."""
        boshqa = Patient.objects.create(
            card_number="P-VT9", last_name="Begona", first_name="X",
            birth_date=date(1990, 1, 1), gender="male")
        bv = Visit.objects.create(patient=boshqa, visit_date=date.today(),
                                  queue_number=9)
        begona = ServiceOrder.objects.create(
            visit=bv, service=self.svc_eski,
            status=ServiceOrder.Status.COMPLETED,
            result_text="BEGONA", result_at=timezone.now())

        url = reverse("clinical:episode_select_orders", args=[self.episode.pk])
        self.client.post(url, {"selected_orders": [str(begona.pk)]})

        self.episode.refresh_from_db()
        self.assertNotIn(str(begona.pk), self.episode.selected_order_ids or [],
                         "Boshqa bemorning tekshiruvi epizodga saqlanib qoldi.")

    def test_get_bilan_belgilab_bolmaydi(self):
        url = reverse("clinical:episode_select_orders", args=[self.episode.pk])
        self.assertEqual(self.client.get(url).status_code, 405)

    # ---------------- EPIZOD SAHIFASI: HISOBOTLAR VA SHABLON ----------------
    def _eski_epizod(self):
        ep = AdmissionEpisode.objects.create(
            patient=self.patient, visit=self.eski_visit, referred_by=self.doc,
            reason="ESKI SABAB", department="Xirurgiya",
            status=AdmissionEpisode.Status.DISCHARGED)
        DischargeSummary.objects.create(
            episode=ep, discharged_by=self.doc,
            treatment_given="ESKI DAVOLASH MATNI",
            recommendations="ESKI TAVSIYA")
        return ep

    def test_epizod_sahifasida_statsionar_hisobotlari_chiqadi(self):
        self._eski_epizod()
        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))

        self.assertContains(resp, "Statsionar hisobotlari")
        self.assertContains(resp, "ESKI SABAB")
        self.assertContains(resp, "ESKI DAVOLASH MATNI")
        self.assertContains(resp, "ESKI TAVSIYA")

    def test_tekshiruv_tayinlash_pikeri_olib_tashlangan(self):
        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))
        self.assertNotContains(resp, "Tekshiruvlar tayinlash")
        self.assertNotContains(resp, "Bemorga tayinlash")

    def test_palata_maydoni_olib_tashlangan(self):
        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))
        self.assertNotContains(resp, 'name="room"')

    def test_korik_saqlanganda_palata_ochib_ketmaydi(self):
        """Maydon formada yo'q — POST'da ham kelmaydi.

        Agar view `room` ni baribir POST'dan o'qiganida, har «Saqlash»
        bosilganda hamshira bergan palata o'chib ketardi.
        """
        from apps.clinical.models import Room
        xona = Room.objects.create(name="Nazorat xonasi")
        self.episode.room = xona
        self.episode.save(update_fields=["room"])

        self.client.post(
            reverse("clinical:episode_save_exam", args=[self.episode.pk]),
            {"complaints": "Bosh og'rig'i", "department": "Nevrologiya"})

        self.episode.refresh_from_db()
        self.assertEqual(self.episode.room_id, xona.id,
                         "Ko'rik saqlanganda palata o'chib ketdi.")
        self.assertEqual(self.episode.complaints, "Bosh og'rig'i")

    def test_shablon_epizod_sahifasidan_saqlanadi(self):
        resp = self.client.post(
            reverse("clinical:episode_save_template", args=[self.episode.pk]),
            {"template_name": "Xirurgiya tavsiyalari",
             "template_content": "Tavsiyalar (01.01.2025):\nParhez"},
            follow=True)

        tpl = DischargeTemplate.objects.filter(doctor=self.doc).first()
        self.assertIsNotNone(tpl, "Shablon epizod sahifasidan saqlanmadi.")
        self.assertEqual(tpl.name, "Xirurgiya tavsiyalari")
        self.assertContains(resp, "Xirurgiya tavsiyalari")

    def test_shablon_ajax_bilan_saqlanadi(self):
        """Sahifa yangilanmasligi uchun JSON qaytishi shart.

        HAQIQIY XATO: shablon oddiy forma bilan saqlanardi va sahifa
        qayta yuklanardi. Shifokor yuqorida to'ldirgan, hali saqlanmagan
        ko'rik matnlari (shikoyatlar, anamnez) yo'qolib ketardi.
        """
        resp = self.client.post(
            reverse("clinical:episode_save_template", args=[self.episode.pk]),
            {"template_name": "AJAX shablon", "template_content": "Matn"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        self.assertTrue(d["ok"])
        self.assertEqual(d["name"], "AJAX shablon")
        self.assertEqual(d["content"], "Matn")

    def test_ajax_bosh_shablonda_xato_qaytaradi(self):
        resp = self.client.post(
            reverse("clinical:episode_save_template", args=[self.episode.pk]),
            {"template_name": "", "template_content": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])
        self.assertFalse(DischargeTemplate.objects.exists())

    def test_shablon_ochiriladi(self):
        tpl = DischargeTemplate.objects.create(
            doctor=self.doc, name="O'chiriladigan", content="matn")

        resp = self.client.post(
            reverse("clinical:episode_delete_template",
                    args=[self.episode.pk, tpl.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(DischargeTemplate.objects.filter(pk=tpl.pk).exists())

    def test_begona_shablon_ochirilmaydi(self):
        """ID topib, boshqa shifokorning shablonini o'chirib bo'lmasin."""
        boshqa = User.objects.create_user(
            username="vt_doc3", password="x", role=Role.objects.get(code="doctor"))
        tpl = DischargeTemplate.objects.create(
            doctor=boshqa, name="BEGONA", content="matn")

        resp = self.client.post(
            reverse("clinical:episode_delete_template",
                    args=[self.episode.pk, tpl.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(resp.status_code, 404)
        self.assertTrue(
            DischargeTemplate.objects.filter(pk=tpl.pk).exists(),
            "Boshqa shifokorning shabloni o'chirib yuborildi.")

    def test_shablon_matni_sahifada_beriladi(self):
        """Chip ichida matn bo'lishi kerak — aks holda tanlab bo'lmaydi."""
        DischargeTemplate.objects.create(
            doctor=self.doc, name="Tavsiyalar", content="PARHEZ MATNI")

        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))
        self.assertContains(resp, "tpl-use")
        self.assertContains(resp, "PARHEZ MATNI")

    def test_bosh_shablon_saqlanmaydi(self):
        self.client.post(
            reverse("clinical:episode_save_template", args=[self.episode.pk]),
            {"template_name": "", "template_content": ""})
        self.assertFalse(DischargeTemplate.objects.exists())

    # ---------------- YOTISH ↔ EPIZOD BOG'LANISHI ----------------
    def test_epizodsiz_yotish_ham_hisobotda_chiqadi(self):
        """HAQIQIY XATO: «Statsionar tarixi» da bemor turibdi, lekin
        «Statsionar hisobotlari» «ilgari yotmagan» deb yozardi.

        Sabab: ro'yxat faqat `AdmissionEpisode` dan qurilgan edi, hamshira
        kravat berganda esa epizod bilan yotish bog'lanmasdi.
        """
        from apps.clinical.models import Bed, InpatientStay, Room

        room = Room.objects.create(name="VT-xona")
        bed = Bed.objects.create(room=room, number="7A")
        InpatientStay.objects.create(
            visit=self.eski_visit, bed=bed,
            status=InpatientStay.Status.DISCHARGED, total_days=5)

        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))

        self.assertEqual(
            len(resp.context["past_episodes"]), 1,
            "Epizodga bog'lanmagan yotish hisobotlar ro'yxatiga tushmadi.")
        self.assertNotContains(resp, "ilgari statsionarda yotmagan")
        self.assertContains(resp, "VT-xona")

    def test_hisobotda_ukol_va_amaliy_malumot_chiqadi(self):
        """Shifokorga «nima qilingan edi?» degan savolga javob kerak.

        Ko'rik matnlari — shifokor YOZGANI. Ukol, kapelnitsa, berilgan
        dori, tekshiruv natijasi esa BAJARILGANI. Vipiska yozayotganda
        aynan shular kerak bo'ladi, shuning uchun hisobotda bo'lishi shart.
        """
        from apps.clinical.models import (
            Bed, InpatientStay, ProcedureRecord, Room,
        )

        room = Room.objects.create(name="VT-ukol")
        bed = Bed.objects.create(room=room, number="5A")
        stay = InpatientStay.objects.create(
            visit=self.eski_visit, bed=bed,
            status=InpatientStay.Status.DISCHARGED, total_days=2)
        ProcedureRecord.objects.create(
            stay=stay, nurse=self.doc, name="Seftriakson 1g v/i",
            notes="kuniga 2 mahal")

        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))

        pe = resp.context["past_episodes"][0]
        nomlar = [nom for nom, _ in pe["bloklar"]]
        self.assertIn("Muolajalar va ukollar", nomlar,
                      "Yotishda qilingan ukollar hisobotga tushmadi.")
        self.assertContains(resp, "Seftriakson 1g v/i")

        # Eski tekshiruv natijasi ham shu yotishning tashrifidan
        self.assertIn("Tekshiruv natijalari", nomlar)
        self.assertContains(resp, "Gemoglobin 120 g/l")

    def test_epizodli_yotish_ikki_marta_chiqmaydi(self):
        """Bog'langan bo'lsa BITTA satr — dublikat bo'lmasin."""
        from apps.clinical.models import Bed, InpatientStay, Room

        room = Room.objects.create(name="VT-xona2")
        bed = Bed.objects.create(room=room, number="8A")
        stay = InpatientStay.objects.create(
            visit=self.eski_visit, bed=bed,
            status=InpatientStay.Status.DISCHARGED, total_days=3)
        ep = self._eski_epizod()
        ep.stay = stay
        ep.save(update_fields=["stay"])

        resp = self.client.get(
            reverse("clinical:episode_detail", args=[self.episode.pk]))
        self.assertEqual(len(resp.context["past_episodes"]), 1,
                         "Bitta yotish ikki marta ko'rindi.")

    def test_kravat_berilganda_epizodga_boglanadi(self):
        """Ildiz sabab: `_create_stay` epizodni biriktirmasdi."""
        from apps.clinical.models import Bed, Room
        from apps.clinical.views import _create_stay

        room = Room.objects.create(name="VT-xona3")
        bed = Bed.objects.create(room=room, number="9A")

        istak = self.client.request().wsgi_request
        istak.user = self.doc
        istak.POST = {}

        stay, err = _create_stay(istak, self.visit, bed)
        self.assertIsNone(err)

        self.episode.refresh_from_db()
        self.assertEqual(
            self.episode.stay_id, stay.pk,
            "Kravat berilgach epizod yotish bilan bog'lanmadi — "
            "statsionar hisobotlari bo'sh chiqadi.")
        self.assertEqual(self.episode.status,
                         AdmissionEpisode.Status.ADMITTED)

    def test_boshqa_shifokor_shabloni_korinmaydi(self):
        boshqa = User.objects.create_user(
            username="vt_doc2", password="x",
            role=Role.objects.get(code="doctor"))
        DischargeTemplate.objects.create(
            doctor=boshqa, name="BEGONA SHABLON", content="matn")

        resp = self.client.get(self.url)
        self.assertNotContains(resp, "BEGONA SHABLON")
