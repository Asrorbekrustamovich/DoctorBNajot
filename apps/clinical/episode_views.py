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

@role_required(*EPISODE_ROLES)
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
            norm = re.sub(r"[\s\-]", "", number).upper()
            for p in Patient.objects.exclude(
                Q(birth_certificate__isnull=True) | Q(birth_certificate="")
            ):
                if re.sub(r"[\s\-]", "", p.birth_certificate).upper() == norm:
                    patient = p
                    break

        if patient is None and not error:
            error = "Bunday hujjat bo'yicha bemor topilmadi."

        if patient is not None:
            # Eski yotqizilishlari — yangi epizod ochishdan oldin ko'rinishi
            # kerak, aks holda shifokor takroriy epizod yaratadi.
            episodes = list(
                patient.episodes.select_related("referred_by", "room", "stay")
                .prefetch_related("diagnoses__icd")
                .order_by("-created_at")[:20]
            )

    return render(request, "clinical/episode_search.html", {
        "doc_types": AdmissionEpisode.DocumentType.choices,
        "doc_type": doc_type,
        "number": number,
        "patient": patient,
        "episodes": episodes,
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
        exam_orders = clinical_selectors.visit_exam_orders(visit)
        assign_url = reverse(
            "clinical:consultation_assign_services", args=[visit.pk])

    # Hamshira faqat KO'RADI — tahrir qila olmaydi.
    can_edit = (
        request.user.is_superuser
        or request.user.has_role(*EPISODE_ROLES)
    ) and episode.is_open

    return render(request, "clinical/episode_detail.html", {
        "episode": episode,
        "patient": episode.patient,
        "visit": visit,
        "can_edit": can_edit,
        "exam_groups": exam_groups,
        "exam_orders": exam_orders,
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
    episode.room = _pick(Room, request.POST.get("room"))

    episode.save(update_fields=fields + [
        "reason", "purpose", "purpose_note", "with_primary_exam",
        "department", "room", "updated_at",
    ])
    
    if request.POST.get("action_send") == "1":
        if not episode.reason:
            messages.error(request, "Murojaat sababi kiritilmagan. Yuborish bekor qilindi.")
        else:
            episode.status = AdmissionEpisode.Status.SENT
            episode.sent_at = timezone.now()
            episode.save(update_fields=["status", "sent_at", "updated_at"])
            messages.success(request, "Saqlandi va Qabulxona hamshirasiga yuborildi.")
    else:
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

    episode.status = AdmissionEpisode.Status.SENT
    episode.sent_at = timezone.now()
    episode.save(update_fields=["status", "sent_at", "updated_at"])
    messages.success(
        request, "Bemor qabulxona hamshirasiga yuborildi. Hamshira kravat beradi.")
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
    
    qs = AdmissionEpisode.objects.select_related("patient", "referred_by", "room").prefetch_related("diagnoses__icd")
    
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

def _episode_dossier(episode):
    """Vipiska uchun barcha ma'lumotni bir joyga yig'adi.

    Shifokor qo'lda ko'chirib yozmasligi kerak: tashxislar, tekshiruv
    natijalari, berilgan dorilar, operatsiya — hammasi tizimda allaqachon
    bor. Vipiska ularni JAMLAYDI, qaytadan kiritmaydi.
    """
    from apps.clinical import selectors as clinical_selectors

    visit = episode.visit
    orders, medicines, surgeries, procedures = [], [], [], []

    if visit is not None:
        orders = [o for o in clinical_selectors.visit_exam_orders(visit) if o.has_result]
        medicines = list(
            visit.dispensed_medicines.filter(is_returned=False)
            .select_related("batch__medicine")
        ) if hasattr(visit, "dispensed_medicines") else []
        surgeries = list(
            visit.surgery_schedules.select_related("surgery_type", "surgeon", "anesthesiologist", "report")
        ) if hasattr(visit, "surgery_schedules") else []

    stay = getattr(episode, "stay", None)
    if not stay and visit:
        stay = visit.inpatient_stays.order_by("-admission_date").first()

    if stay:
        procedures = list(stay.procedure_records.select_related("nurse").all())

    return {
        "diagnoses": list(episode.diagnoses.select_related("icd").all()),
        "orders": orders,
        "medicines": medicines,
        "surgeries": surgeries,
        "procedures": procedures,
        "stay": stay,
    }


@role_required(*EPISODE_ROLES)
def episode_discharge(request, pk):
    """Vipiska yozish formasi."""
    from apps.clinical.models import DischargeSummary

    episode = get_object_or_404(
        AdmissionEpisode.objects.select_related("patient", "stay", "visit"), pk=pk)

    summary = getattr(episode, "discharge", None)

    if request.method == "POST":
        if episode.status != AdmissionEpisode.Status.ADMITTED:
            messages.error(request, "Xatolik: Bemor hali palataga yotqizilmagan (kravat berilmagan). Vipiska yozishga ruxsat yo'q.")
            return redirect("clinical:episode_discharge", pk=episode.pk)

        if episode.purpose == AdmissionEpisode.Purpose.SURGERY:
            has_surgery = False
            if hasattr(episode, 'visit') and episode.visit:
                has_surgery = episode.visit.surgeries.filter(status='completed').exists()
            
            if not has_surgery:
                messages.error(request, "Xatolik: Bemor operatsiya uchun yotqizilgan, lekin hech qanday yakunlangan operatsiya topilmadi! Oldin operatsiya bayonnomasini to'ldiring.")
                return redirect("clinical:episode_discharge", pk=episode.pk)

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
        for f in ("sick_leave_from", "sick_leave_to"):
            setattr(summary, f, (request.POST.get(f) or None))
        summary.save()

        # Epizod yopiladi — endi u «vipiska berildi» holatida
        episode.status = AdmissionEpisode.Status.DISCHARGED
        episode.save(update_fields=["status", "updated_at"])

        messages.success(request, "Vipiska shakllantirildi.")
        return redirect("clinical:discharge_print", pk=episode.pk)

    is_ready = True
    ready_msg = ""
    
    if episode.status != AdmissionEpisode.Status.ADMITTED:
        is_ready = False
        ready_msg = "Kutilyapti: Bemor hali palataga yotqizilmagan (kravat berilmagan). Vipiska yozishga ruxsat yo'q."
    elif episode.purpose == AdmissionEpisode.Purpose.SURGERY:
        has_surgery = False
        if hasattr(episode, 'visit') and episode.visit:
            has_surgery = episode.visit.surgeries.filter(status='completed').exists()
        if not has_surgery:
            is_ready = False
            ready_msg = "Kutilyapti: Operatsiya bayonnomasi kiritilmagan. Hozircha Vipiska yozishga ruxsat yo'q."
        else:
            ready_msg = "Tayyor: Bemor yotqizilgan va operatsiya bajarilgan. Vipiskani shakllantirishingiz mumkin."
    else:
        ready_msg = "Tayyor: Bemor yotqizilgan va davolash yakunlangan. Vipiskani shakllantirishingiz mumkin."

    ctx = {
        "episode": episode,
        "patient": episode.patient,
        "summary": summary,
        "outcomes": DischargeSummary.Outcome.choices,
        "capacities": DischargeSummary.WorkCapacity.choices,
        "is_ready": is_ready,
        "ready_msg": ready_msg,
    }
    ctx.update(_episode_dossier(episode))
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
    ctx.update(_episode_dossier(episode))
    return render(request, "clinical/discharge_print.html", ctx)
