"""Statsionar epizodi — ambulator shifokor rasmiylashtiradi.

OQIM (talab qilingan ketma-ketlik):

    1. Hujjat turi tanlanadi: JSHSHIR yoki Metrika
    2. Raqam kiritiladi → «Topish»
    3. Bemor ma'lumotlari va ESKI YOTQIZILISHLARI chiqadi
    4. «Yangi epizod» → murojaat sababi so'raladi
    5. Dastlabki ko'rik yoziladi (yoki «ko'riksiz» belgilanadi)
    6. MKB-10 bo'yicha tashxislar qo'shiladi
    7. Shu yerda tekshiruvlar tayinlanadi (+Analiz, +EKG, +UZI…)
    8. Qabulxona hamshirasiga yuboriladi

Epizod kravatdan MUSTAQIL: shifokor yo'llaganda kravat hali tanlanmagan.
Kravatni hamshira beradi va shunda `InpatientStay` yaratiladi.
"""
from __future__ import annotations

import re
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.models import Role
from apps.accounts.permissions import role_required
from apps.clinical.models import (
    AdmissionEpisode, EpisodeDiagnosis, ICD10Code, Room,
)
from apps.patients.models import Patient

# Kim epizod ocha oladi — ambulator shifokor va boshqaruv
EPISODE_ROLES = (
    Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
)
# Kim ko'ra oladi — yuqoridagilar + qabulxona hamshirasi va registratura
EPISODE_VIEW_ROLES = EPISODE_ROLES + (
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.RECEPTION, Role.Code.DIRECTOR,
)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def episode_exam_history(episode, chosen_override=None):
    """Bemorning BUTUN tekshiruv tarixi — vipiska belgilari bilan.

    BITTA MANBA: epizod sahifasidagi ptechka ham, vipiska sahifasidagi
    ro'yxat ham shu funksiyadan oziqlanadi. Ikki joyda alohida hisoblansa
    ular albatta bir-biridan uzilib ketadi — shifokor epizodda belgilaydi,
    vipiskada boshqa narsa chiqadi.

    Belgilash qoidasi:
        episode.selected_order_ids is None  → shu epizodникilar avtomatik
        ro'yxat berilgan                    → aynan o'shalar
    """
    from apps.clinical.models import ServiceOrder

    visit = episode.visit
    own_visit_ids = {str(visit.pk)} if visit is not None else set()

    orders = []
    for o in (ServiceOrder.objects
              .filter(visit__patient=episode.patient)
              .exclude(status=ServiceOrder.Status.CANCELLED)
              .select_related("service", "service__category", "performed_by", "visit")
              .prefetch_related("result_rows")
              .order_by("-created_at")):
        if not o.has_result:
            continue          # natijasi yo'q tekshiruv hujjatga kirmaydi
        o.vip_is_own = str(o.visit_id) in own_visit_ids
        orders.append(o)

    if chosen_override is not None:
        chosen = {str(x) for x in chosen_override}
    elif episode.selected_order_ids is None:
        chosen = {str(o.pk) for o in orders if o.vip_is_own}
    else:
        chosen = {str(x) for x in episode.selected_order_ids}

    for o in orders:
        o.vip_checked = str(o.pk) in chosen

    return orders


def _past_episode_reports(episode):
    """Bemorning OLDINGI statsionar hisobotlari — nusxalash uchun.

    IKKI MANBADAN yig'iladi va bu shart:

      · AdmissionEpisode — shifokor rasmiylashtirgan epizod (ko'rik
        yozuvlari, tashxislar, vipiska matni);
      · InpatientStay — hamshira ochgan yotish (kravat, sanalar, kunlar).

    HAQIQIY XATO: ro'yxat faqat epizodlardan qurilgan edi. Kravat
    berilganda `AdmissionEpisode.stay` bo'sh qolar edi va panelda
    yotishlar umuman ko'rinmasdi: «Statsionar tarixi» da bemor turibdi,
    «Statsionar hisobotlari» esa «ilgari yotmagan» deb yozardi.

    Ikkalasi bog'langan bo'lsa BITTA satr chiqadi — dublikat bo'lmaydi.

    SHU epizodning o'zi va uning yotishi chiqmaydi: o'zidan nusxa
    olishning ma'nosi yo'q. Bekor qilinganlar ham chiqmaydi.
    """
    from apps.clinical.models import InpatientStay

    def bloklarni_yig(ep, vip):
        """Nusxalanadigan matnli bo'laklar."""
        if ep is None:
            bloklar = []
        else:
            bloklar = [
                ("Murojaat sababi", ep.reason),
                ("Shikoyatlar", ep.complaints),
                ("Anamnesis morbi", ep.anamnesis_morbi),
                ("Anamnesis vitae", ep.anamnesis_vitae),
                ("Status praesens", ep.status_praesens),
                ("Status localis", ep.status_localis),
                ("Allergoanamnez", ep.allergo_anamnesis),
                ("Klinik tashxis", ep.clinical_diagnosis),
            ]
        # Joriy epizodning vipiskasi bloklarga qo'shilmaydi (chunki u yozilmoqda)
        if vip is not None and (ep is None or ep.pk != episode.pk):
            bloklar += [
                ("O'tkazilgan davolash", vip.treatment_given),
                ("Operatsiya bayoni", vip.surgery_text),
                ("Chiqishdagi holati", vip.condition_at_discharge),
                ("Tavsiyalar", vip.recommendations),
                ("Nazorat ko'rigi", vip.follow_up),
            ]
        return [(nom, (matn or "").strip()) for nom, matn in bloklar]

    def amaliy_bloklar(stay, visit):
        """Yotish davomida HAQIQATDA qilingan ishlar.

        Ko'rik matnlari — shifokor yozgani, bular esa bajarilgani:
        ukollar, kapelnitsalar, berilgan dorilar, tekshiruv natijalari,
        shifokor xulosalari. Vipiska yozayotgan shifokorga aynan shular
        kerak bo'ladi — «nima qilingan edi?» degan savolga javob.
        """
        chiqish = []

        if stay is not None:
            qatorlar = []
            for p in (stay.procedure_records
                      .select_related("nurse").order_by("performed_at")):
                qatorlar.append(
                    f"{p.performed_at:%d.%m.%Y %H:%M} · {p.get_category_display()} · "
                    f"{p.name}"
                    + (f" — {p.notes}" if p.notes else "")
                )
            if qatorlar:
                chiqish.append(("Muolajalar va ukollar", "\n".join(qatorlar)))

        if visit is not None:
            qatorlar = []
            for m in (visit.dispensed_medicines.filter(is_returned=False)
                      .select_related("batch__medicine")):
                nom = getattr(getattr(m.batch, "medicine", None), "name", "—")
                qatorlar.append(f"{nom} × {m.quantity}")
            if qatorlar:
                chiqish.append(("Berilgan dorilar", "\n".join(qatorlar)))

            qatorlar = []
            for o in (visit.service_orders
                      .exclude(status="cancelled")
                      .select_related("service")
                      .prefetch_related("result_rows")
                      .order_by("created_at")):
                if not o.has_result:
                    continue
                satr = [f"{o.service.name}:"]
                for r in o.result_rows.all():
                    satr.append(f"  {r.name}: {r.value} {r.unit}"
                                + (f" (norma {r.reference})" if r.reference else ""))
                if o.result_text:
                    satr.append(f"  {o.result_text}")
                qatorlar.append("\n".join(satr))
            if qatorlar:
                chiqish.append(("Tekshiruv natijalari", "\n".join(qatorlar)))

            qatorlar = []
            for c in visit.consultations.select_related("doctor").order_by("created_at"):
                bolaklar = [
                    ("Shikoyat", c.complaint), ("Anamnez", c.anamnesis),
                    ("Obyektiv holat", c.objective_status),
                    ("Tashxis", c.diagnosis), ("Retsept", c.prescription),
                    ("Tavsiyalar", c.recommendations),
                ]
                matn = "\n".join(f"  {k}: {v.strip()}"
                                 for k, v in bolaklar if (v or "").strip())
                if matn:
                    kim = c.doctor.get_full_name() or c.doctor.username
                    qatorlar.append(f"{kim} ({c.created_at:%d.%m.%Y}):\n{matn}")
            if qatorlar:
                chiqish.append(("Shifokor xulosalari", "\n\n".join(qatorlar)))

        return chiqish

    natija = []
    korilgan_stay = set()

    # SHU YOTISH TUGAGAN BO'LSA — U HAM RO'YXATGA TUSHADI.
    #
    # Ilgari joriy epizod har doim chetlab o'tilardi: «o'zidan nusxa
    # olishning ma'nosi yo'q» deb. Bu bemor palatada YOTGANDA to'g'ri —
    # yotish hali tugamagan, hisobot ham yo'q.
    #
    # Lekin javob berilgach hisobot to'liq bo'ladi: muolajalar,
    # ukollar, dorilar, tekshiruv natijalari. Shifokor vipiskani aynan
    # shulardan yig'adi. Chetlab o'tilgani uchun «Bu bemor ilgari
    # statsionarda yotmagan» degan yozuv chiqardi — bemor endigina
    # chiqib ketgan bo'lsa ham.
    # Bekor qilingan epizod hisobot emas — u ham, yotishi ham chiqmaydi.
    shu_ham_qoshiladi = (
        episode.patient_left
        and episode.status != AdmissionEpisode.Status.CANCELLED
    )
    if episode.stay_id and not shu_ham_qoshiladi:
        korilgan_stay.add(episode.stay_id)

    epizodlar = (AdmissionEpisode.objects
                 .filter(patient=episode.patient)
                 .exclude(status=AdmissionEpisode.Status.CANCELLED))
    if not shu_ham_qoshiladi:
        epizodlar = epizodlar.exclude(pk=episode.pk)

    # --- 1) EPIZODLAR
    for ep in (epizodlar
               .select_related("discharge", "referred_by", "stay__bed__room", "stay__doc_nurse", "stay__procedure_nurse")
               .prefetch_related("diagnoses__icd")
               .order_by("-created_at")):
        vip = getattr(ep, "discharge", None)
        stay = ep.stay
        if stay is not None:
            korilgan_stay.add(stay.pk)

        # Oldingi epizodning operatsiyalari (vipiska templateda ko'rsatish uchun)
        ep_surgeries = []
        if ep.visit_id and hasattr(ep.visit, 'surgeries'):
            ep_surgeries = list(
                ep.visit.surgeries
                .select_related('surgery_type', 'surgeon', 'report')
                .exclude(status='cancelled')
                .order_by('scheduled_time')
            )

        natija.append({
            "episode": ep,
            "stay": stay,
            "summary": vip,
            "sana": ep.created_at,
            "bolim": ep.department or (stay.bed.room.name if stay else ""),
            "kravat": str(stay.bed) if stay else "",
            "shifokor": ep.referred_by,
            "doc_nurse": stay.doc_nurse if stay else None,
            "procedure_nurse": stay.procedure_nurse if stay else None,
            "sabab": ep.reason,
            "maqsad": ep.get_purpose_display(),
            "kunlar": vip.bed_days if vip else (stay.total_days if stay else None),
            "diagnoses": list(ep.diagnoses.all()),
            "bloklar": (bloklarni_yig(ep, vip)
                        + amaliy_bloklar(stay, ep.visit)),
            "print_pk": ep.pk if vip else None,
            # Shu yotishning o'zi — ro'yxatda ajratib ko'rsatiladi
            "joriy": ep.pk == episode.pk,
            "past_surgeries": ep_surgeries,
        })

    # --- 2) EPIZODSIZ YOTISHLAR
    #
    # Hamshira kravat berganda epizod bo'lmasligi mumkin (yoki eski
    # ma'lumot). Bunday yotishda ko'rik matni yo'q, lekin sanasi,
    # kravati, davolovchi shifokori va muolajalari bor — bular ham
    # hisobot va ko'rsatilishi kerak.
    for stay in (InpatientStay.objects
                 .filter(visit__patient=episode.patient)
                 .exclude(pk__in=korilgan_stay)
                 .exclude(status=InpatientStay.Status.CANCELLED)
                 .select_related("bed__room", "assigned_doctor", "doc_nurse", "procedure_nurse", "visit")
                 .order_by("-admission_date")):
        # Epizodsiz yotishning operatsiyalari
        stay_surgeries = []
        if stay.visit_id and hasattr(stay.visit, 'surgeries'):
            stay_surgeries = list(
                stay.visit.surgeries
                .select_related('surgery_type', 'surgeon', 'report')
                .exclude(status='cancelled')
                .order_by('scheduled_time')
            )

        natija.append({
            "episode": None,
            "stay": stay,
            "summary": None,
            "sana": stay.admission_date,
            "bolim": stay.bed.room.name if stay.bed_id else "",
            "kravat": str(stay.bed) if stay.bed_id else "",
            "shifokor": stay.assigned_doctor,
            "doc_nurse": stay.doc_nurse,
            "procedure_nurse": stay.procedure_nurse,
            "sabab": "",
            "maqsad": stay.get_stay_type_display() if hasattr(stay, "get_stay_type_display") else "",
            "kunlar": stay.total_days or None,
            "diagnoses": [],
            "bloklar": amaliy_bloklar(stay, stay.visit),
            "print_pk": None,
            "joriy": False,
            "past_surgeries": stay_surgeries,
        })

    natija.sort(key=lambda r: r["sana"], reverse=True)
    return natija


def _pick(model, raw):
    """UUID bo'yicha xavfsiz tanlash.

    `Model.objects.filter(pk="")` Django'da ValidationError tashlaydi
    («"" to'g'ri UUID emas») va sahifa 500 beradi. Formadan bo'sh qiymat
    kelishi esa odatiy hol — «tanlanmagan» degani.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return model.objects.filter(pk=raw).first()
    except (ValueError, ValidationError):
        return None


# --------------------------------------------------------------------------
#  1–3. HUJJAT BO'YICHA TOPISH
# --------------------------------------------------------------------------

@role_required(*EPISODE_VIEW_ROLES)
def episode_search(request):
    """Hujjat turi + raqam bo'yicha bemorni topish sahifasi."""
    doc_type = request.GET.get("document_type", AdmissionEpisode.DocumentType.JSHSHIR)
    number = (request.GET.get("number") or "").strip()

    patient = None
    episodes = []
    searched = bool(number)
    error = ""

    if searched:
        if doc_type == AdmissionEpisode.DocumentType.JSHSHIR:
            digits = _digits(number)
            if len(digits) != 14:
                error = "JSHSHIR 14 ta raqamdan iborat bo'lishi kerak."
            else:
                patient = Patient.objects.filter(jshshir=digits).first()
        else:
            # Metrika turlicha yoziladi: «I-AB 123456», «I AB123456».
            # Solishtirishda bo'shliq va tirelarni hisobga olmaymiz.
            # DB darajasida normalizatsiya — hammani xotiraga yuklamaymiz.
            from django.db.models.functions import Replace, Upper
            from django.db.models import Value
            norm = re.sub(r"[\s\-]", "", number).upper()
            patient = (
                Patient.objects
                .exclude(Q(birth_certificate__isnull=True) | Q(birth_certificate=""))
                .annotate(
                    norm_bc=Upper(Replace(Replace(
                        "birth_certificate",
                        Value(" "), Value("")
                    ), Value("-"), Value("")))
                )
                .filter(norm_bc=norm)
                .first()
            )

        if patient is None and not error:
            error = "Bunday hujjat bo'yicha bemor topilmadi."

        if patient is not None:
            # Eski yotqizilishlari — yangi epizod ochishdan oldin ko'rinishi
            # kerak, aks holda shifokor takroriy epizod yaratadi.
            episodes = list(
                patient.episodes.select_related("referred_by", "room", "stay")
                .exclude(status=AdmissionEpisode.Status.CANCELLED)
                .prefetch_related("diagnoses__icd")
                .order_by("-created_at")[:20]
            )

    can_create_episode = not request.user.has_role(Role.Code.RECEPTION, Role.Code.ADMINISTRATOR)

    return render(request, "clinical/episode_search.html", {
        "doc_types": AdmissionEpisode.DocumentType.choices,
        "doc_type": doc_type,
        "number": number,
        "patient": patient,
        "episodes": episodes,
        "can_create_episode": can_create_episode,
        "searched": searched,
        "error": error,
        "purposes": AdmissionEpisode.Purpose.choices,
    })


@role_required(*EPISODE_ROLES)
@require_POST
@transaction.atomic
def episode_create(request, patient_id):
    """«Yangi epizod» — murojaat sababi va maqsadi bilan."""
    patient = get_object_or_404(Patient, pk=patient_id)

    # Ochiq epizod bo'lsa ikkinchisini yaratmaymiz — aks holda bitta bemor
    # ikki joyda «yotayotgan» bo'lib qoladi.
    open_one = patient.episodes.filter(
        status__in=[AdmissionEpisode.Status.DRAFT,
                    AdmissionEpisode.Status.SENT,
                    AdmissionEpisode.Status.ADMITTED]
    ).first()
    if open_one:
        messages.warning(
            request,
            "Bu bemorda yopilmagan epizod bor. Avval uni yakunlang yoki bekor qiling.")
        return redirect("clinical:episode_detail", pk=open_one.pk)

    purpose = request.POST.get("purpose") or AdmissionEpisode.Purpose.TREATMENT
    episode = AdmissionEpisode.objects.create(
        patient=patient,
        referred_by=request.user,
        document_type=request.POST.get("document_type")
                      or AdmissionEpisode.DocumentType.JSHSHIR,
        document_number=(request.POST.get("number") or "").strip(),
        reason=(request.POST.get("reason") or "").strip(),
        purpose=purpose,
        purpose_note=(request.POST.get("purpose_note") or "").strip(),
        with_primary_exam=request.POST.get("with_primary_exam") == "1",
        visit=patient.visits.order_by("-visit_date").first(),
    )
    messages.success(request, "Yangi epizod ochildi.")
    return redirect("clinical:episode_detail", pk=episode.pk)


# --------------------------------------------------------------------------
#  4–7. EPIZOD KARTASI: dastlabki ko'rik, tashxislar, tekshiruvlar
# --------------------------------------------------------------------------

@role_required(*EPISODE_VIEW_ROLES)
def episode_detail(request, pk):
    from apps.clinical import selectors as clinical_selectors

    episode = get_object_or_404(
        AdmissionEpisode.objects.select_related(
            "patient", "referred_by", "room", "stay", "visit"
        ).prefetch_related("diagnoses__icd"),
        pk=pk,
    )

    # Tekshiruvlar ambulator qabulga bog'lanadi (ServiceOrder → Visit).
    visit = episode.visit
    exam_groups, exam_orders, assign_url = [], [], ""
    if visit is not None:
        assigned = {
            str(sid) for sid in visit.service_orders.exclude(
                status="cancelled").values_list("service_id", flat=True)
        }
        exam_groups = clinical_selectors.exam_picker_groups(assigned)
        assign_url = reverse(
            "clinical:consultation_assign_services", args=[visit.pk])

    # TEKSHIRUV TARIXI + VIPISKA PTECHKASI.
    #
    # Ilgari bu yerda faqat shu tashrifning tekshiruvlari ko'rinardi va
    # belgilash imkoni yo'q edi — shifokor tanlashni faqat vipiska
    # yozayotganda qilishi mumkin edi. Endi bemor yotgan paytda,
    # natijalar kelib turganda belgilaydi.
    exam_orders = episode_exam_history(episode)
    tanlangan_soni = sum(1 for o in exam_orders if o.vip_checked)

    # STATSIONAR HISOBOTLARI — bemor ilgari yotgan epizodlar.
    #
    # Ro'yxat bo'lib chiqadi (ptechkasiz): shifokor ichini modalda ko'rib,
    # kerakli qismini shablonga ko'chiradi. Ptechka bu yerda noto'g'ri
    # bo'lardi — eski vipiskaning butun matni yangi hujjatga ko'chib
    # o'tmaydi, undan faqat parcha olinadi.
    from apps.clinical.models import DischargeTemplate

    past_episodes = _past_episode_reports(episode)
    my_templates = list(
        DischargeTemplate.objects.filter(doctor=request.user).order_by("-created_at")
    )

    # Hamshira faqat KO'RADI — tahrir qila olmaydi.
    can_edit = (
        request.user.is_superuser
        or request.user.has_role(*EPISODE_ROLES)
    ) and episode.is_open

    # Registrator va qabulxona — faqat ko'rish va chop etish, tahrirlash emas
    can_write_discharge = not request.user.has_role(
        Role.Code.RECEPTION, Role.Code.ADMINISTRATOR
    )

    return render(request, "clinical/episode_detail.html", {
        "episode": episode,
        "patient": episode.patient,
        "visit": visit,
        "can_edit": can_edit,
        "can_write_discharge": can_write_discharge,
        "exam_groups": exam_groups,
        "exam_orders": exam_orders,
        "tanlangan_soni": tanlangan_soni,
        "vip_select_url": reverse("clinical:episode_select_orders", args=[episode.pk]),
        "past_episodes": past_episodes,
        "my_templates": my_templates,
        "assign_url": assign_url,
        "stages": EpisodeDiagnosis.Stage.choices,
        "kinds": EpisodeDiagnosis.Kind.choices,
        "courses": EpisodeDiagnosis.Course.choices,
        "purposes": AdmissionEpisode.Purpose.choices,
        "rooms": Room.objects.all().order_by("name"),
        "previous": episode.patient.episodes.exclude(pk=episode.pk)
                    .order_by("-created_at")[:10],
    })


@role_required(*EPISODE_ROLES)
@require_POST
def episode_select_orders(request, pk):
    """Vipiskaga qo'shiladigan tekshiruvlarni belgilash.

    Ptechka bosilganda chaqiriladi. Butun ro'yxat yuboriladi (bitta id
    emas): shunda «hammasini olib tashlash» ham to'g'ri saqlanadi va
    ikki oyna ochib qo'yilganda oxirgi holat aniq bo'ladi.
    """
    episode = get_object_or_404(AdmissionEpisode, pk=pk)

    tanlangan = request.POST.getlist("selected_orders")

    # Faqat SHU BEMORNING tekshiruvlari saqlanadi. Aks holda formaga
    # begona ID yuborib, boshqa bemorning natijasini vipiskaga
    # qo'shtirib yuborish mumkin bo'lardi.
    haqiqiy = {str(o.pk) for o in episode_exam_history(episode)}
    episode.selected_order_ids = [x for x in tanlangan if x in haqiqiy]
    episode.save(update_fields=["selected_order_ids", "updated_at"])

    return JsonResponse({
        "ok": True,
        "count": len(episode.selected_order_ids),
    })


@role_required(*EPISODE_ROLES)
@require_POST
@transaction.atomic
def refer_to_inpatient(request, visit_id):
    """Ambulator qabuldan STATSIONARGA yo'naltirish — bir bosishda.

    Ilgari statsionar epizodi faqat alohida sahifadan, JSHSHIR yoki
    metrika terib qidirish orqali ochilardi. Ammo qaror ambulator ko'rik
    paytida qabul qilinadi: shifokor bemorni ko'rib turib «yotqizish
    kerak» deydi. Uni qidiruv sahifasiga yuborib, allaqachon qo'lidagi
    bemorni qaytadan qidirtirish — ortiqcha ish va xato manbai.

    Epizod ochiladi va DARROV qabulxona hamshirasiga yuboriladi
    («sent»), shunda u ro'yxatda ko'rinadi va kravat beradi.
    """
    from apps.registration.models import Visit

    visit = get_object_or_404(
        Visit.objects.select_related("patient"), pk=visit_id)

    # Ochiq epizod bo'lsa yangisini yaratmaymiz — aks holda bitta bemor
    # ikki joyda «yotayotgan» bo'lib qoladi.
    epizod = visit.patient.episodes.filter(
        status__in=[AdmissionEpisode.Status.DRAFT,
                    AdmissionEpisode.Status.SENT,
                    AdmissionEpisode.Status.ADMITTED]
    ).order_by("-created_at").first()

    if epizod is None:
        epizod = AdmissionEpisode.objects.create(
            patient=visit.patient,
            visit=visit,
            referred_by=request.user,
            reason=(request.POST.get("reason") or "").strip(),
            purpose=request.POST.get("purpose") or AdmissionEpisode.Purpose.TREATMENT,
            with_primary_exam=True,
            document_type=(AdmissionEpisode.DocumentType.JSHSHIR
                           if visit.patient.jshshir
                           else AdmissionEpisode.DocumentType.BIRTH_CERT),
            document_number=(visit.patient.jshshir
                             or visit.patient.birth_certificate or ""),
        )

    yangi_yuborildi = False
    if epizod.status == AdmissionEpisode.Status.DRAFT:
        epizod.status = AdmissionEpisode.Status.SENT
        epizod.sent_at = timezone.now()
        epizod.save(update_fields=["status", "sent_at", "updated_at"])
        yangi_yuborildi = True
        xabar = (f"{visit.patient.full_name} statsionarga yo'naltirildi — "
                 f"qabulxona hamshirasi kravat beradi.")
    else:
        xabar = "Bu bemorda ochiq statsionar epizodi bor."

    # SAHIFA YANGILANMAYDI.
    #
    # Ilgari bu yerdan qayta yo'naltirilardi va shifokor yozib
    # o'tirgan xulosasi bilan birga butun sahifa qayta yuklanardi.
    # Endi AJAX bilan chaqiriladi va JSON qaytadi.
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({
            "ok": True,
            "yangi": yangi_yuborildi,
            "message": xabar,
            "episode_id": str(epizod.pk),
            "cancel_url": reverse("clinical:cancel_inpatient_referral",
                                  args=[epizod.pk]),
        })

    messages.success(request, xabar) if yangi_yuborildi else messages.info(
        request, xabar)
    return redirect(request.META.get("HTTP_REFERER")
                    or reverse("registration:queue"))


@role_required(*EPISODE_ROLES)
@require_POST
def cancel_inpatient_referral(request, pk):
    """Statsionarga yo'naltirishni BEKOR QILISH.

    Shifokor adashib bosgan yoki fikridan qaytgan bo'lishi mumkin.
    Bekor qilingach tugma yana ochiladi va qayta yuborish mumkin.

    LEKIN hamshira allaqachon kravat bergan bo'lsa — bekor qilinmaydi:
    bemor yotib bo'lgan, kravat band, hujjat ochilgan. Bunday holatda
    to'g'ri yo'l — statsionardan javob berish.
    """
    epizod = get_object_or_404(AdmissionEpisode, pk=pk)
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if epizod.status == AdmissionEpisode.Status.ADMITTED or epizod.stay_id:
        xabar = ("Bemor allaqachon yotqizilgan — yo'naltirishni bekor qilib "
                 "bo'lmaydi. Statsionardan javob bering.")
        if ajax:
            return JsonResponse({"ok": False, "error": xabar}, status=400)
        messages.error(request, xabar)
        return redirect(request.META.get("HTTP_REFERER")
                        or reverse("registration:queue"))

    epizod.status = AdmissionEpisode.Status.CANCELLED
    epizod.cancel_reason = (request.POST.get("reason")
                            or "Shifokor yo'naltirishni bekor qildi")[:255]
    epizod.save(update_fields=["status", "cancel_reason", "updated_at"])

    xabar = "Statsionarga yo'naltirish bekor qilindi."
    if ajax:
        return JsonResponse({"ok": True, "message": xabar})
    messages.success(request, xabar)
    return redirect(request.META.get("HTTP_REFERER")
                    or reverse("registration:queue"))


@role_required(*EPISODE_ROLES)
@require_POST
def episode_save_template(request, pk):
    """Yig'ilgan matnni shablon qilib saqlash.

    AJAX bilan chaqiriladi va JSON qaytaradi — SAHIFA YANGILANMAYDI.

    HAQIQIY XATO: ilgari bu oddiy forma edi va saqlangach sahifa qayta
    yuklanardi. Shifokor yuqorida to'ldirgan ko'rik matnlari (shikoyatlar,
    anamnez, status praesens) hali saqlanmagan bo'lsa — hammasi yo'qolardi.
    Ya'ni shablon saqlash boshqa ishni buzib yuborardi.
    """
    from apps.clinical.models import DischargeTemplate

    episode = get_object_or_404(AdmissionEpisode, pk=pk)
    nom = (request.POST.get("template_name") or "").strip()
    matn = (request.POST.get("template_content") or "").strip()
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if not nom or not matn:
        if ajax:
            return JsonResponse(
                {"ok": False, "error": "Shablon nomi va matni kiritilishi shart."},
                status=400)
        messages.error(request, "Shablon nomi va matni kiritilishi shart.")
        return redirect("clinical:episode_detail", pk=episode.pk)

    tpl = DischargeTemplate.objects.create(
        doctor=request.user, name=nom, content=matn)

    if ajax:
        return JsonResponse({
            "ok": True,
            "id": str(tpl.pk),
            "name": tpl.name,
            "content": tpl.content,
        })

    messages.success(request, f"Shablon «{nom}» saqlandi.")
    return redirect("clinical:episode_detail", pk=episode.pk)


@role_required(*EPISODE_ROLES)
@require_POST
def episode_delete_template(request, pk, tpl_id):
    """Shablonni o'chirish — FAQAT O'ZINIKINI.

    `doctor=request.user` filtri shart: aks holda ID topib, boshqa
    shifokorning shablonini o'chirib yuborish mumkin bo'lardi.
    """
    from apps.clinical.models import DischargeTemplate

    get_object_or_404(AdmissionEpisode, pk=pk)

    # `delete()` ning qaytarish turi menejerga bog'liq: Django'niki
    # (soni, tafsilot) tuple beradi, loyihaning soft-delete menejeri esa
    # oddiy son. Ikkalasini ham qabul qilamiz — aks holda 500 chiqadi.
    natija = DischargeTemplate.objects.filter(
        pk=tpl_id, doctor=request.user).delete()
    ochirildi = natija[0] if isinstance(natija, tuple) else (natija or 0)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": bool(ochirildi)},
                            status=200 if ochirildi else 404)

    if not ochirildi:
        messages.error(request, "Shablon topilmadi.")
    return redirect("clinical:episode_detail", pk=pk)


@role_required(*EPISODE_ROLES)
@require_POST
def episode_save_exam(request, pk):
    """Dastlabki ko'rik matnlarini saqlash."""
    episode = get_object_or_404(AdmissionEpisode, pk=pk)
    if not episode.is_open:
        messages.error(request, "Epizod yopilgan — o'zgartirib bo'lmaydi.")
        return redirect("clinical:episode_detail", pk=pk)

    fields = [
        "complaints", "anamnesis_morbi", "anamnesis_vitae", "status_localis",
        "epid_anamnesis", "status_praesens", "allergo_anamnesis",
        "neuro_status", "clinical_diagnosis",
    ]
    for f in fields:
        setattr(episode, f, (request.POST.get(f) or "").strip())

    episode.reason = (request.POST.get("reason") or episode.reason).strip()
    episode.purpose = request.POST.get("purpose") or episode.purpose
    episode.purpose_note = (request.POST.get("purpose_note") or "").strip()
    episode.with_primary_exam = request.POST.get("with_primary_exam") == "1"
    episode.department = (request.POST.get("department") or "").strip()

    # PALATA BU YERDA O'ZGARTIRILMAYDI.
    #
    # Maydon formadan olib tashlandi (palatani hamshira beradi). Agar
    # `room` ni baribir POST dan o'qiganimizda, har «Saqlash» bosilganda
    # bo'sh qiymat kelib, hamshira bergan palatani o'chirib yuborardi.
    ozgaradi = fields + [
        "reason", "purpose", "purpose_note", "with_primary_exam",
        "department", "updated_at",
    ]
    if "room" in request.POST:
        episode.room = _pick(Room, request.POST.get("room"))
        ozgaradi.append("room")

    episode.save(update_fields=ozgaradi)
    
    messages.success(request, "Dastlabki ko'rik saqlandi.")
        
    return redirect("clinical:episode_detail", pk=pk)


@role_required(*EPISODE_ROLES)
@require_POST
def episode_add_diagnosis(request, pk):
    """Tashxis qo'shish. Bitta epizodda bir nechta bo'lishi mumkin."""
    episode = get_object_or_404(AdmissionEpisode, pk=pk)
    if not episode.is_open:
        return JsonResponse({"error": "Epizod yopilgan."}, status=400)

    # DIQQAT: bo'sh satrni UUID maydoniga berib bo'lmaydi — Django
    # ValidationError tashlaydi va sahifa 500 beradi. Shuning uchun
    # avval qiymat borligini tekshiramiz.
    icd = _pick(ICD10Code, request.POST.get("icd"))
    free_text = (request.POST.get("free_text") or "").strip()
    if icd is None and not free_text:
        messages.error(request, "Tashxis tanlanmadi.")
        return redirect("clinical:episode_detail", pk=pk)

    EpisodeDiagnosis.objects.create(
        episode=episode,
        icd=icd,
        free_text=free_text,
        stage=request.POST.get("stage") or EpisodeDiagnosis.Stage.PRELIMINARY,
        kind=request.POST.get("kind") or EpisodeDiagnosis.Kind.MAIN,
        course=request.POST.get("course") or EpisodeDiagnosis.Course.UNSPECIFIED,
        note=(request.POST.get("note") or "").strip(),
    )
    messages.success(request, "Tashxis qo'shildi.")
    return redirect("clinical:episode_detail", pk=pk)


@role_required(*EPISODE_ROLES)
@require_POST
def episode_delete_diagnosis(request, pk, diagnosis_id):
    episode = get_object_or_404(AdmissionEpisode, pk=pk)
    EpisodeDiagnosis.objects.filter(pk=diagnosis_id, episode=episode).delete()
    messages.success(request, "Tashxis o'chirildi.")
    return redirect("clinical:episode_detail", pk=pk)


@role_required(*EPISODE_ROLES)
def icd_search(request):
    """MKB-10 bo'yicha jonli qidiruv (kod yoki nom bo'yicha)."""
    q = (request.GET.get("q") or "").strip()
    qs = ICD10Code.objects.filter(is_active=True)
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    return JsonResponse({
        "results": [
            {"id": str(c.id), "code": c.code, "name": c.name}
            for c in qs.order_by("code")[:30]
        ]
    })


# --------------------------------------------------------------------------
#  8. QABULXONA HAMSHIRASIGA YUBORISH / BEKOR QILISH
# --------------------------------------------------------------------------

@role_required(*EPISODE_ROLES)
@require_POST
def episode_send(request, pk):
    """Epizodni qabulxona hamshirasiga yuborish."""
    episode = get_object_or_404(AdmissionEpisode, pk=pk)
    if episode.status != AdmissionEpisode.Status.DRAFT:
        messages.warning(request, "Bu epizod allaqachon yuborilgan.")
        return redirect("clinical:episode_detail", pk=pk)

    if not episode.reason:
        messages.error(request, "Murojaat sababi kiritilmagan.")
        return redirect("clinical:episode_detail", pk=pk)

    # Agar bemor allaqachon yotqizilgan (yoki hatto chiqib ketgan) bo'lsa 
    # va o'sha yotish hali hech qaysi epizodga biriktirilmagan bo'lsa
    from apps.clinical.models import InpatientStay
    unattached_stay = InpatientStay.objects.filter(
        visit__patient=episode.patient, 
        episode__isnull=True
    ).order_by("-admission_date").first()

    if unattached_stay:
        episode.stay = unattached_stay
        episode.status = AdmissionEpisode.Status.ADMITTED
        episode.sent_at = timezone.now()
        episode.save(update_fields=["stay", "status", "sent_at", "updated_at"])
        messages.success(
            request, "Bemorning statsionar tarixi topildi va epizodga avtomat biriktirildi."
        )
    else:
        episode.status = AdmissionEpisode.Status.SENT
        episode.sent_at = timezone.now()
        episode.save(update_fields=["status", "sent_at", "updated_at"])
        messages.success(
            request, "Bemor qabulxona hamshirasiga yuborildi. Hamshira kravat beradi."
        )
    return redirect("clinical:episode_detail", pk=pk)


@role_required(*EPISODE_ROLES)
@require_POST
def episode_cancel(request, pk):
    """«Qabul yozuvini bekor qilish»."""
    episode = get_object_or_404(AdmissionEpisode, pk=pk)
    if episode.status == AdmissionEpisode.Status.ADMITTED:
        messages.error(
            request, "Bemor yotqizilgan — epizodni bekor qilib bo'lmaydi.")
        return redirect("clinical:episode_detail", pk=pk)

    episode.status = AdmissionEpisode.Status.CANCELLED
    episode.cancel_reason = (request.POST.get("cancel_reason") or "").strip()
    episode.save(update_fields=["status", "cancel_reason", "updated_at"])
    messages.success(request, "Qabul yozuvi bekor qilindi.")
    return redirect("clinical:episode_search")


# --------------------------------------------------------------------------
#  QABULXONA HAMSHIRASI — FAQAT KO'RADI
# --------------------------------------------------------------------------

@role_required(
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.RECEPTION,
    Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR,
)
def nurse_incoming(request):
    """Statsionarga yo'naltirilgan bemorlar ro'yxati (barcha statuslar)."""
    status_filter = request.GET.get("status", "").strip()
    
    # `stay` ham olinadi — holat belgisi yotishga qaraydi (bemor
    # chiqib ketgan bo'lsa «Yotibdi» deb ko'rsatilmasligi kerak).
    # `select_related`siz har qator uchun alohida so'rov ketardi.
    qs = (AdmissionEpisode.objects
          .select_related("patient", "referred_by", "room", "stay")
          .prefetch_related("diagnoses__icd"))
    
    if status_filter:
        qs = qs.filter(status=status_filter)
    
    episodes = list(qs.order_by("-updated_at")[:200])
    
    counts = {
        'all': AdmissionEpisode.objects.count(),
        'sent': AdmissionEpisode.objects.filter(status=AdmissionEpisode.Status.SENT).count(),
        'admitted': AdmissionEpisode.objects.filter(status=AdmissionEpisode.Status.ADMITTED).count(),
        'discharged': AdmissionEpisode.objects.filter(status=AdmissionEpisode.Status.DISCHARGED).count(),
    }
    
    return render(request, "clinical/nurse_incoming.html", {
        "episodes": episodes,
        "current_status": status_filter,
        "counts": counts,
    })


# ==========================================================================
#  VIPISKA — epizodning yakuniy hujjati
# ==========================================================================

@role_required(*EPISODE_VIEW_ROLES, Role.Code.LAB, Role.Code.RADIOLOGY)
@require_POST
def cancel_exam_order(request, order_id):
    """Tayinlangan tekshiruvni BEKOR QILISH.

    Ikki kishi bekor qila oladi:
      · tayinlagan shifokor (adashib buyurgan bo'lishi mumkin);
      · tekshiruvni bajarishi kerak bo'lgan xodim (laborant, EKG,
        UZI va h.k.) — u bemorga bu kerak emasligini ko'radi.

    NATIJA YOZILGAN BO'LSA — BEKOR QILINMAYDI. Bajarilgan tekshiruv
    tibbiy hujjat: uni chekdan olib tashlash klinikani bepul ishlaganга
    olib keladi, natija esa kasallik tarixida qolib ketadi.

    Bekor qilingach chek O'ZI qayta hisoblanadi (signal) va band
    registratorning to'lov ro'yxatidan tushadi.
    """
    from apps.clinical.models import ServiceOrder

    order = get_object_or_404(
        ServiceOrder.objects.select_related("service", "visit__doctor"),
        pk=order_id)

    qaytish = request.META.get("HTTP_REFERER") or reverse("registration:queue")

    if order.status == ServiceOrder.Status.CANCELLED:
        messages.info(request, "Bu tekshiruv allaqachon bekor qilingan.")
        return redirect(qaytish)

    if order.has_result:
        messages.error(
            request,
            f"«{order.service.name}» natijasi allaqachon kiritilgan — "
            f"bekor qilib bo'lmaydi.")
        return redirect(qaytish)

    # KIM BEKOR QILA OLADI.
    #
    # Bajaruvchi tekshiruvi `can_be_performed_by` orqali — tayinlash
    # mantig'i bilan BIR XIL funksiya. Alohida yozilsa, xodim o'ziga
    # ko'rinmaydigan tekshiruvni bekor qila olib qolardi.
    tayinlagan = order.visit and order.visit.doctor_id == request.user.pk
    bajaruvchi = order.service.can_be_performed_by(request.user)
    boshqaruv = (request.user.is_superuser
                 or request.user.has_role(Role.Code.SUPER_ADMIN,
                                          Role.Code.ADMINISTRATOR,
                                          Role.Code.CHIEF_DOCTOR))

    if not (tayinlagan or bajaruvchi or boshqaruv):
        messages.error(request, "Bu tekshiruvni bekor qilish huquqingiz yo'q.")
        return redirect(qaytish)

    kim = request.user.get_full_name() or request.user.username
    order.status = ServiceOrder.Status.CANCELLED
    order.result_text = (
        f"Bekor qilindi: {kim} ({timezone.now():%d.%m.%Y %H:%M}). "
        f"{(request.POST.get('reason') or '').strip()}"
    ).strip()
    order.save(update_fields=["status", "result_text", "updated_at"])

    messages.success(
        request,
        f"«{order.service.name}» bekor qilindi — to'lov ro'yxatidan chiqdi.")
    return redirect(qaytish)


# ==========================================================================
#  VIPISKA BOSHQARUVI — FAQAT SUPERADMIN
# ==========================================================================

# Necha kungacha o'chirilgan vipiskani tiklash mumkin.
#
# Muddat kerak: cheksiz tiklash imkoni bo'lsa, o'chirish umuman
# ma'nosiz bo'ladi va hisobotlar yillar o'tib ham o'zgarib turishi
# mumkin. Bir hafta — xatoni sezib, tuzatishga yetarli muddat.
VIPISKA_TIKLASH_KUNI = 7

SUPERADMIN_ONLY = (Role.Code.SUPER_ADMIN,)


def _superadminmi(user) -> bool:
    return bool(user.is_authenticated
                and (user.is_superuser or user.has_role(Role.Code.SUPER_ADMIN)))


@role_required(*SUPERADMIN_ONLY)
def discharge_admin(request):
    """Vipiskalar boshqaruvi: qayta ochish, o'chirish, tiklash."""
    from apps.clinical.models import DischargeSummary

    hammasi = list(
        DischargeSummary.all_objects
        .select_related("episode__patient", "discharged_by", "locked_by")
        .order_by("-created_at")[:300]
    )

    chek = timezone.now() - timedelta(days=VIPISKA_TIKLASH_KUNI)
    for s in hammasi:
        # Tiklash muddati o'tganmi — shablon shuni ko'rsatadi
        s.tiklash_mumkin = bool(s.is_deleted and s.deleted_at and s.deleted_at >= chek)
        s.muddat_otdi = bool(s.is_deleted and (not s.deleted_at or s.deleted_at < chek))

    return render(request, "clinical/discharge_admin.html", {
        "summaries": hammasi,
        "tiklash_kuni": VIPISKA_TIKLASH_KUNI,
    })


@role_required(*SUPERADMIN_ONLY)
@require_POST
def discharge_unlock(request, pk):
    """Vipiskani SHIFOKORGA QAYTA OCHISH.

    Shifokor xatolik bilan shakllantirib yuborgan bo'lishi mumkin.
    Qulf olinadi va u yana tahrirlay oladi.
    """
    from apps.clinical.models import DischargeSummary

    s = get_object_or_404(DischargeSummary.all_objects, pk=pk)
    s.is_locked = False
    s.locked_at = None
    s.locked_by = None
    s.save(update_fields=["is_locked", "locked_at", "locked_by", "updated_at"])

    messages.success(
        request,
        f"{s.episode.patient.full_name} vipiskasi shifokorga qayta ochildi.")
    return redirect("clinical:discharge_admin")


@role_required(*SUPERADMIN_ONLY)
@require_POST
def discharge_delete(request, pk):
    """Vipiskani o'chirish — YO'Q QILMAYDI, belgilab qo'yadi.

    Bir hafta ichida tiklash mumkin, shuning uchun jismonan o'chirmaymiz.
    """
    from apps.clinical.models import DischargeSummary

    s = get_object_or_404(DischargeSummary.all_objects, pk=pk)
    if s.is_deleted:
        messages.info(request, "Bu vipiska allaqachon o'chirilgan.")
        return redirect("clinical:discharge_admin")

    # Soft delete — kim o'chirgani ham yoziladi
    s.delete(user=request.user)

    # Epizod yana «yotibdi» holatiga qaytadi — vipiskasi yo'q axir
    ep = s.episode
    if ep.status == AdmissionEpisode.Status.DISCHARGED:
        ep.status = AdmissionEpisode.Status.ADMITTED
        ep.save(update_fields=["status", "updated_at"])

    messages.warning(
        request,
        f"Vipiska o'chirildi. {VIPISKA_TIKLASH_KUNI} kun ichida tiklash mumkin.")
    return redirect("clinical:discharge_admin")


@role_required(*SUPERADMIN_ONLY)
@require_POST
def discharge_restore(request, pk):
    """O'chirilgan vipiskani tiklash — FAQAT BIR HAFTA ICHIDA.

    Muddat qat'iy: cheksiz tiklash imkoni bo'lsa o'chirish ma'nosiz
    bo'lib qoladi va allaqachon topshirilgan hisobotlar yillar o'tib
    ham o'zgarib turishi mumkin.
    """
    from apps.clinical.models import DischargeSummary

    s = get_object_or_404(DischargeSummary.all_objects, pk=pk)

    if not s.is_deleted:
        messages.info(request, "Bu vipiska o'chirilmagan.")
        return redirect("clinical:discharge_admin")

    chek = timezone.now() - timedelta(days=VIPISKA_TIKLASH_KUNI)
    if not s.deleted_at or s.deleted_at < chek:
        messages.error(
            request,
            f"Tiklash muddati o'tgan — o'chirilganiga "
            f"{VIPISKA_TIKLASH_KUNI} kundan ko'p bo'ldi.")
        return redirect("clinical:discharge_admin")

    s.restore()

    ep = s.episode
    if ep.status != AdmissionEpisode.Status.DISCHARGED:
        ep.status = AdmissionEpisode.Status.DISCHARGED
        ep.save(update_fields=["status", "updated_at"])

    messages.success(
        request,
        f"{s.episode.patient.full_name} vipiskasi tiklandi.")
    return redirect("clinical:discharge_admin")


def _episode_dossier(episode, selected_order_ids=None,
                     selected_procedure_ids=None, selected_diagnosis_ids=None,
                     item_texts=None, only_selected=False,
                     selected_surgery_ids=None):
    """Vipiska uchun barcha ma'lumotni bir joyga yig'adi.

    Tekshiruvlar va muolajalar ptechka (checkbox) bilan ko'rsatiladi.
    Shifokor keraklilarini tanlab, vipiskaga kiritadi.
    selected_order_ids / selected_procedure_ids berilsa — faqat
    tanlanganlari qaytariladi (chop etish uchun).
    """
    from apps.clinical import selectors as clinical_selectors
    from apps.clinical.models import InpatientStay, DischargeTemplate

    visit = episode.visit
    orders, medicines = [], []

    if visit is not None:
        medicines = list(
            visit.dispensed_medicines.filter(is_returned=False)
            .select_related("batch__medicine")
        ) if hasattr(visit, "dispensed_medicines") else []

    # --- TEKSHIRUVLAR: bemorning BUTUN tarixi ---
    #
    # BITTA MANBA — `episode_exam_history()`. Shifokor epizod sahifasida
    # nimani belgilagan bo'lsa, vipiskada aynan o'sha chiqadi. Bu yerda
    # alohida hisoblasak, ikkisi muqarrar bir-biridan uzilib ketardi.
    all_orders = episode_exam_history(episode, chosen_override=selected_order_ids)
    orders = all_orders

    # Bemorning butun yotish tarixi — faqat KONTEKST uchun (o'ng panelda
    # ko'rsatiladi, vipiskaga chiqmaydi).
    all_stays = list(
        InpatientStay.objects.filter(visit__patient=episode.patient)
        .select_related("bed__room", "assigned_doctor")
        .order_by("-admission_date")
    )

    # SHU epizodning yotish yozuvi
    stay = getattr(episode, "stay", None)
    if not stay and visit:
        stay = visit.inpatient_stays.order_by("-admission_date").first()

    # MUOLAJALAR — FAQAT SHU EPIZODDAN.
    #
    # HAQIQIY XATO: ilgari bu yerda bemorning BARCHA yotishlaridagi
    # muolajalar yig'ilardi. Natijada mart oyida qilingan ukol avgustdagi
    # vipiskaga tushib qolardi — va ptechkada AVTOMATIK belgilangan
    # holatda, ya'ni shifokor sezmasa hujjatga chiqib ketardi.
    #
    # Vipiska — bitta yotishning hisoboti. Oldingi yotishlar alohida
    # vipiskaga ega va bu yerga aralashmasligi kerak.
    all_procedures = []
    if stay is not None:
        procs = list(stay.procedure_records.select_related("nurse").all())
        for p in procs:
            p.vip_stay = stay
        all_procedures = procs

    # --- OPERATSIYALAR ---
    #
    # Operatsiya bo'lgan bo'lsa, vipiskaning eng muhim qismi shu. Ilgari
    # bu yerda faqat bo'sh «Operatsiya bayoni» maydoni turardi va
    # shifokor jarrohlik bo'limidagi yozuvni qo'lda ko'chirib yozardi.
    # Endi qilingan operatsiyalar ro'yxat bo'lib chiqadi va ptechka
    # bilan tanlanadi — muolajalar bilan bir xil tartibda.
    #
    # Operatsiya bo'lmasa ro'yxat bo'sh qoladi va bo'lim ko'rinmaydi:
    # operatsiyasiz yotgan bemorning vipiskasida u ortiqcha.
    all_surgeries = []
    if visit is not None and hasattr(visit, "surgeries"):
        for sx in (visit.surgeries
                   .select_related("surgery_type", "surgeon", "assistant",
                                   "anesthesiologist", "operating_room", "report")
                   .exclude(status="cancelled")
                   .order_by("scheduled_time")):
            sx.vip_checked = (
                selected_surgery_ids is None
                or str(sx.pk) in {str(x) for x in selected_surgery_ids})
            all_surgeries.append(sx)

    # Chop etishda faqat belgilanganlari
    if only_selected:
        orders = [o for o in all_orders if o.vip_checked]
        all_surgeries = [x for x in all_surgeries if x.vip_checked]
    if selected_procedure_ids is not None:
        all_procedures = [p for p in all_procedures if str(p.pk) in selected_procedure_ids]

    # Shifokorning shablonlari
    discharge_templates = []
    if hasattr(episode, "_request_user"):
        discharge_templates = list(DischargeTemplate.objects.filter(doctor=episode._request_user).order_by("-created_at"))

    # --- TASHXISLAR: bemorning BUTUN tarixi ---
    #
    # Bemor uch marta yotgan bo'lsa, surunkali kasallik birinchi
    # yotishda qo'yilgan bo'lishi mumkin. Uni vipiskada ko'rsatish kerak,
    # lekin hamma tashxisni ko'r-ko'rona qo'shsak hujjat cho'zilib
    # ketadi. Shuning uchun: hammasi RO'YXAT bo'lib chiqadi, shu
    # epizodникilar avtomatik belgilanadi, eskilarini shifokor o'zi
    # belgilaydi.
    from apps.clinical.models import EpisodeDiagnosis

    own_ids = {str(d.pk) for d in episode.diagnoses.all()}
    if selected_diagnosis_ids is None:
        chosen = own_ids                       # forma: shu epizod belgilangan
    else:
        chosen = {str(x) for x in selected_diagnosis_ids}

    all_dx = []
    for d in (EpisodeDiagnosis.objects
              .filter(episode__patient=episode.patient)
              .select_related("icd", "episode")
              .order_by("-episode__created_at", "kind")):
        d.vip_is_own = str(d.pk) in own_ids       # shu epizodникimi
        d.vip_checked = str(d.pk) in chosen
        d.vip_episode_date = d.episode.created_at
        all_dx.append(d)

    # Chop etishda faqat belgilanganlari
    diagnoses = [d for d in all_dx if d.vip_checked] if only_selected else all_dx

    # --- OLDINGI YOTISHLAR HISOBOTI ---
    #
    # Epizod sahifasi bilan BITTA funksiyadan oziqlanadi — ikki joyda
    # alohida yig'ilsa, ular bir-biridan uzilib ketardi.
    past_episodes = _past_episode_reports(episode)

    # --- Vipiskadagi matnlar (shifokor qisqartirgani) ---
    texts = item_texts or {}
    for o in orders:
        o.vip_text = texts.get(str(o.pk), "")
    for p in all_procedures:
        p.vip_text = texts.get(str(p.pk), "")
    for sx in all_surgeries:
        sx.vip_text = texts.get(str(sx.pk), "")

    return {
        "diagnoses": diagnoses,
        "all_diagnoses": all_dx,
        "orders": orders,
        "all_orders": all_orders,
        "medicines": medicines,
        "all_stays": all_stays,
        "all_procedures": all_procedures,
        "all_surgeries": all_surgeries,
        "stay": stay,
        "discharge_templates": discharge_templates,
        "past_episodes": past_episodes,
    }


@role_required(*EPISODE_ROLES)
def episode_discharge(request, pk):
    """Vipiska yozish formasi."""
    from apps.clinical.models import DischargeSummary

    episode = get_object_or_404(
        AdmissionEpisode.objects.select_related("patient", "stay", "visit"), pk=pk)

    summary = getattr(episode, "discharge", None)

    if request.method == "POST":
        if request.POST.get("save_template"):
            from apps.clinical.models import DischargeTemplate
            tpl_name = (request.POST.get("template_name") or "").strip()
            tpl_content = (request.POST.get("template_content") or "").strip()
            if tpl_name and tpl_content:
                DischargeTemplate.objects.create(
                    doctor=request.user, name=tpl_name, content=tpl_content
                )
                messages.success(request, f"Shablon '{tpl_name}' saqlandi.")
            else:
                messages.error(request, "Shablon nomi va matni kiritilishi shart.")
            return redirect("clinical:episode_discharge", pk=episode.pk)

        if episode.status == AdmissionEpisode.Status.CANCELLED:
            messages.error(request, "Bekor qilingan epizodga vipiska yozib bo'lmaydi.")
            return redirect("clinical:episode_discharge", pk=episode.pk)

        # QULFLANGAN VIPISKANI TAHRIRLAB BO'LMAYDI.
        #
        # Shakllantirilgan vipiska — bemor qo'liga beriladigan rasmiy
        # hujjat. Uni keyin jimgina o'zgartirish mumkin bo'lsa, chop
        # etilgan nusxa bilan bazadagisi bir-biriga mos kelmay qoladi.
        # Xatolik bo'lsa superadmin qayta ochadi (audit iziga tushadi).
        if summary is not None and not summary.can_modify(request.user):
            messages.error(
                request,
                "Vipiska shakllantirilgan va qulflangan. Faqat epizodni "
                "ochgan shifokor yoki superadmin qayta tahrirlashi mumkin.")
            return redirect("clinical:episode_discharge", pk=episode.pk)

        # SAQLAB TURISH.
        #
        # Vipiskani yozib turganda kerakli statsionar yozuvi yoki
        # operatsiya hali kiritilmagan bo'lishi mumkin — hamshira
        # ukolni keyin yozadi, jarroh protokolni kechqurun to'ldiradi.
        # Ilgari yagona tugma bor edi va u vipiskani darrov QULFLARDI:
        # shifokor yo yarim ma'lumot bilan yakunlashi, yo yozganini
        # tashlab ketishi kerak edi.
        #
        # «To'xtatib turish» matnni saqlaydi, lekin qulflamaydi va
        # epizodni yopmaydi — yetishmagani qo'shilgach davom etadi.
        #
        # QULFLASH FAQAT ANIQ SO'RALGANDA.
        #
        # Ilgari `action` bo'lmagan HAR QANDAY yuborish vipiskani
        # qulflardi. Shifokor maydonda Enter bossa ham, boshqa yo'l
        # bilan forma yuborilib qolsa ham — hujjat rasmiy holatga o'tib,
        # keyin faqat superadmin ocha olardi.
        #
        # Vipiska bemor qo'liga beriladigan hujjat: uni qulflash ataylab
        # qilinadigan amal bo'lishi kerak, tasodifiy emas. Shuning uchun
        # standart holat — saqlab turish.
        toxtatib = request.POST.get("action") != "finalize"

        if summary is None:
            summary = DischargeSummary(episode=episode)
        summary.discharged_by = request.user
        summary.outcome = request.POST.get("outcome") or DischargeSummary.Outcome.IMPROVED
        summary.work_capacity = (request.POST.get("work_capacity")
                                 or DischargeSummary.WorkCapacity.NOT_APPLICABLE)
        summary.treatment_given = (request.POST.get("treatment_given") or "").strip()
        summary.condition_at_discharge = (
            request.POST.get("condition_at_discharge") or "").strip()
        summary.recommendations = (request.POST.get("recommendations") or "").strip()
        summary.follow_up = (request.POST.get("follow_up") or "").strip()
        summary.surgery_text = (request.POST.get("surgery_text") or "").strip()
        summary.selected_order_ids = request.POST.getlist("selected_orders")
        summary.selected_procedure_ids = request.POST.getlist("selected_procedures")
        summary.selected_surgery_ids = request.POST.getlist("selected_surgeries")
        summary.selected_diagnosis_ids = request.POST.getlist("selected_diagnoses")

        # Har bir element uchun shifokor qisqartirgan matn.
        # Maydon nomi: `text_<element_id>`. Bo'sh bo'lsa saqlamaymiz —
        # chop etishda asl matn ishlatiladi.
        texts = {}
        for key, val in request.POST.items():
            if key.startswith("text_"):
                val = (val or "").strip()
                if val:
                    texts[key[5:]] = val
        summary.item_texts = texts
        for f in ("sick_leave_from", "sick_leave_to"):
            setattr(summary, f, (request.POST.get(f) or None))

        if toxtatib:
            summary.is_locked = False
            summary.locked_at = None
            summary.locked_by = None
            summary.save()
            messages.success(
                request,
                "Vipiska saqlandi va to'xtatib turildi. Yetishmagan "
                "ma'lumotlar qo'shilgach shu yerdan davom ettirasiz.")
            return redirect("clinical:episode_discharge", pk=episode.pk)

        # SHAKLLANTIRILGACH QULFLANADI — rasmiy hujjat o'zgarmas bo'lishi
        # kerak. Superadmin qayta ocha oladi.
        summary.is_locked = True
        summary.locked_at = timezone.now()
        summary.locked_by = request.user
        summary.save()

        # Epizod yopiladi — endi u «vipiska berildi» holatida
        episode.status = AdmissionEpisode.Status.DISCHARGED
        episode.save(update_fields=["status", "updated_at"])

        messages.success(
            request,
            "Vipiska shakllantirildi va qulflandi. Keyin qayta "
            "tahrirlashingiz mumkin.")
        return redirect("clinical:discharge_print", pk=episode.pk)

    is_ready = episode.status != AdmissionEpisode.Status.CANCELLED
    ready_msg = "Vipiskani shakllantirishingiz mumkin. O'ng tomondagi ro'yxatdan kerakli ma'lumotlarni belgilang." if is_ready else "Bekor qilingan epizod."

    episode._request_user = request.user
    ctx = {
        "episode": episode,
        "patient": episode.patient,
        "summary": summary,
        "outcomes": DischargeSummary.Outcome.choices,
        "capacities": DischargeSummary.WorkCapacity.choices,
        "is_ready": is_ready,
        "ready_msg": ready_msg,
    }
    # Vipiska allaqachon yozilgan bo'lsa — o'sha paytdagi tanlov va
    # tahrirlangan matnlar qaytadi, aks holda shu epizodникilar
    # belgilangan holda chiqadi.
    dossier = _episode_dossier(
        episode,
        selected_diagnosis_ids=(summary.selected_diagnosis_ids if summary else None),
        item_texts=(summary.item_texts if summary else None),
        # DIQQAT: `or None` ISHLATILMAYDI.
        #
        # Bo'sh ro'yxat — «shifokor hech qaysi operatsiyani tanlamadi»
        # degani. `or None` qilinsa u «tanlov yo'q» ga aylanib, hammasi
        # qaytadan belgilanib chiqardi va olib tashlangan operatsiya
        # o'zicha hujjatga qaytardi. None faqat vipiska hali umuman
        # yozilmaganda beriladi.
        selected_surgery_ids=(summary.selected_surgery_ids if summary else None),
    )
    
    if summary is None:
        parts = []
        for sx in dossier.get("all_surgeries", []):
            if hasattr(sx, "report") and sx.report:
                report_parts = []
                if sx.report.performed_actions:
                    report_parts.append(f"Jarayon: {sx.report.performed_actions}")
                if sx.report.anesthesia:
                    report_parts.append(f"Narkoz: {sx.report.anesthesia}")
                if report_parts:
                    title = sx.surgery_type.name if sx.surgery_type else "Operatsiya"
                    parts.append(f"--- {title} ---\n" + "\n".join(report_parts))
        if parts:
            dossier["default_surgery_text"] = "\n\n".join(parts)

    ctx.update(dossier)
    return render(request, "clinical/discharge_form.html", ctx)


@role_required(*EPISODE_VIEW_ROLES)
def discharge_print(request, pk):
    """Vipiska — rasmiy blank (chop etish)."""
    episode = get_object_or_404(
        AdmissionEpisode.objects.select_related("patient", "stay", "visit",
                                                "referred_by", "room"),
        pk=pk)
    summary = getattr(episode, "discharge", None)
    if summary is None:
        messages.warning(request, "Bu epizod bo'yicha vipiska hali yozilmagan.")
        return redirect("clinical:episode_detail", pk=pk)

    ctx = {
        "episode": episode,
        "patient": episode.patient,
        "summary": summary,
        "printed_at": timezone.now(),
    }
    # Faqat tanlangan tekshiruvlar va muolajalarni chiqarish (dublikat yo'q)
    # DIQQAT: `or None` ISHLATILMAYDI — bo'sh ro'yxat = "hech biri tanlanmagan"
    ctx.update(_episode_dossier(
        episode,
        selected_order_ids=summary.selected_order_ids,
        selected_procedure_ids=summary.selected_procedure_ids,
        selected_diagnosis_ids=summary.selected_diagnosis_ids,
        selected_surgery_ids=summary.selected_surgery_ids,
        item_texts=summary.item_texts,
        only_selected=True,
    ))
    return render(request, "clinical/discharge_print.html", ctx)
