"""Registration service layer: navbat, FSM o'tishlar, appointment."""
from __future__ import annotations

import datetime
from typing import Optional

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

from apps.core.exceptions import DomainError, InvalidTransitionError
from apps.core.models import Sequence
from apps.patients.models import Patient
from apps.registration.models import Appointment, Visit


def _queue_sequence_name(visit_date: datetime.date) -> str:
    return f"visit_queue:{visit_date:%Y%m%d}"


@transaction.atomic
def visit_create(
    *,
    patient: Patient,
    doctor: Optional[models.Model] = None,
    complaint: str = "",
    referral: str = "",
    preliminary_diagnosis: str = "",
    appointment: Optional[Appointment] = None,
    to_waiting: bool = True,
) -> Visit:
    """Yangi qabul ochadi va kunlik navbat raqamini atomik beradi.

    Bir bemorda bir kunda bitta ochiq tashrif bo'lishi mumkin.
    """
    today = timezone.localdate()
    open_statuses = (
        Visit.Status.CREATED, Visit.Status.WAITING,
        Visit.Status.ACCEPTED, Visit.Status.IN_PROGRESS,
    )
    if Visit.objects.filter(
        patient=patient, visit_date=today, status__in=open_statuses
    ).exists():
        raise DomainError(
            "Bu bemorning bugungi ochiq qabuli allaqachon mavjud.",
            code="visit_already_open",
        )

    visit = Visit(
        patient=patient,
        doctor=doctor,
        appointment=appointment,
        visit_date=today,
        queue_number=Sequence.get_next(_queue_sequence_name(today)),
        complaint=complaint,
        referral=referral,
        preliminary_diagnosis=preliminary_diagnosis,
        status=Visit.Status.WAITING if to_waiting else Visit.Status.CREATED,
    )
    visit.full_clean()
    visit.save()

    # Agar shifokorga yozilgan bo'lsa, avtomatik ravishda Qabul (Consultation)
    # yaratamiz. Shunda uning narxi darhol chek (Invoice) da ko'rinadi.
    if visit.doctor:
        from apps.clinical.models import Consultation, DoctorPrice
        fee = DoctorPrice.current_fee_for(visit.doctor)
        Consultation.objects.create(
            visit=visit,
            doctor=visit.doctor,
            fee=fee,
        )
        
    return visit


@transaction.atomic
def visit_transition(*, visit: Visit, new_status: str, reason: str = "") -> Visit:
    """Visit statusini FSM qoidalari bo'yicha o'tkazadi."""
    if not visit.can_transition(new_status):
        raise InvalidTransitionError(
            f"'{visit.get_status_display()}' holatidan "
            f"'{dict(Visit.Status.choices).get(new_status, new_status)}' ga o'tib bo'lmaydi."
        )
    visit.status = new_status
    update_fields = ["status"]
    if new_status == Visit.Status.ACCEPTED:
        visit.accepted_at = timezone.now()
        update_fields.append("accepted_at")
    elif new_status == Visit.Status.COMPLETED:
        visit.completed_at = timezone.now()
        update_fields.append("completed_at")
    elif new_status == Visit.Status.CANCELLED:
        visit.cancel_reason = reason
        update_fields.append("cancel_reason")
    visit.save(update_fields=update_fields)
    return visit


@transaction.atomic
def visit_refer(
    *,
    visit: Visit,
    new_doctor: models.Model,
    referred_by: models.Model,
    notes: str = "",
) -> Visit:
    """Bemorni boshqa shifokorga YO'NALTIRADI — yangi Visit ochilmaydi.

    O'sha Visit instansi yangi shifokorga o'tkazilib, qayta navbatga
    (WAITING) qaytariladi. Navbat raqami, chek (Invoice) va barcha
    xizmatlar bitta tashrif ichida qoladi.
    """
    visit = Visit.objects.select_for_update().get(pk=visit.pk)

    referable = (Visit.Status.WAITING, Visit.Status.ACCEPTED, Visit.Status.IN_PROGRESS)
    if visit.status not in referable:
        raise DomainError(
            "Faqat ochiq (navbatda/qabulda) tashrifni yo'naltirish mumkin.",
            code="visit_not_open",
        )

    role_code = getattr(getattr(new_doctor, "role", None), "code", "")
    if not (getattr(new_doctor, "is_superuser", False) or role_code in ("doctor", "chief_doctor")):
        raise DomainError("Yo'naltirish faqat shifokorga qilinadi.", code="not_a_doctor")

    if visit.doctor_id == new_doctor.pk:
        raise DomainError(
            "Bemor allaqachon shu shifokorda. Boshqa shifokorni tanlang.",
            code="same_doctor",
        )

    # Yo'naltirish tarixini bitta Visit ichida saqlaymiz
    referrer_name = referred_by.get_full_name() or getattr(referred_by, "username", "")
    new_doctor_name = new_doctor.get_full_name() or getattr(new_doctor, "username", "")
    entry = f"{referrer_name} → {new_doctor_name}"
    if notes:
        entry += f": {notes}"
    visit.referral = f"{visit.referral}\n{entry}".strip()[:255]

    visit.doctor = new_doctor
    if visit.status != Visit.Status.WAITING:
        if not visit.can_transition(Visit.Status.WAITING):
            raise InvalidTransitionError(
                f"'{visit.get_status_display()}' holatidan navbatga qaytarib bo'lmaydi."
            )
        visit.status = Visit.Status.WAITING
    visit.save(update_fields=["doctor", "status", "referral"])
    return visit


@transaction.atomic
def appointment_create(
    *,
    patient: Patient,
    doctor: models.Model,
    scheduled_at: datetime.datetime,
    duration_minutes: int = 15,
    reason: str = "",
    notes: str = "",
) -> Appointment:
    """Shifokorga yozilish (vaqt to'qnashuvi tekshiriladi)."""
    if scheduled_at <= timezone.now():
        raise DomainError("Yozilish vaqti kelajakda bo'lishi kerak.", code="past_datetime")
    role_code = getattr(getattr(doctor, "role", None), "code", "")
    if role_code not in ("doctor", "chief_doctor"):
        raise DomainError("Yozilish faqat shifokorga qilinadi.", code="not_a_doctor")

    end_at = scheduled_at + timezone.timedelta(minutes=duration_minutes)
    active = (Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED)
    # Nomzod to'qnashuvlar: shifokorning ±4 soat oralig'idagi faol yozilishlari
    candidates = Appointment.objects.select_for_update().filter(
        doctor=doctor,
        status__in=active,
        scheduled_at__lt=end_at,
        scheduled_at__gte=scheduled_at - timezone.timedelta(hours=4),
    )
    for appt in candidates:
        if appt.scheduled_at < end_at and scheduled_at < appt.end_at:
            raise DomainError(
                f"Shifokorning bu vaqti band: {appt.scheduled_at:%H:%M}–{appt.end_at:%H:%M}.",
                code="slot_taken",
            )

    appointment = Appointment(
        patient=patient, doctor=doctor, scheduled_at=scheduled_at,
        duration_minutes=duration_minutes, reason=reason, notes=notes,
    )
    appointment.full_clean()
    appointment.save()
    return appointment


@transaction.atomic
def appointment_set_status(*, appointment: Appointment, new_status: str) -> Appointment:
    """Appointment statusini o'zgartiradi (yakuniy holatlardan qaytish yo'q)."""
    terminal = (Appointment.Status.CANCELLED, Appointment.Status.NO_SHOW,
                Appointment.Status.ARRIVED)
    if appointment.status in terminal:
        raise InvalidTransitionError("Yakuniy holatdagi yozilishni o'zgartirib bo'lmaydi.")
    if new_status not in Appointment.Status.values:
        raise DomainError("Noto'g'ri status.")
    appointment.status = new_status
    appointment.save(update_fields=["status"])
    return appointment


@transaction.atomic
def visit_from_appointment(*, appointment: Appointment) -> Visit:
    """Bemor kelganda yozilishdan qabul ochadi (appointment → ARRIVED)."""
    if appointment.status not in (
        Appointment.Status.SCHEDULED, Appointment.Status.CONFIRMED
    ):
        raise InvalidTransitionError("Bu yozilishdan qabul ochib bo'lmaydi.")
    visit = visit_create(
        patient=appointment.patient,
        doctor=appointment.doctor,
        complaint=appointment.reason,
        appointment=appointment,
    )
    appointment.status = Appointment.Status.ARRIVED
    appointment.save(update_fields=["status"])
    return visit
