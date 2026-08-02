"""Registration selectors."""
from __future__ import annotations

import datetime
from typing import Optional

from django.db.models import QuerySet
from django.utils import timezone

from apps.patients.models import Patient
from apps.registration.models import Appointment, Visit


def visits_today(*, status: str = "", user=None) -> QuerySet[Visit]:
    """Bugungi tashriflar (navbat tartibida).

    Agar shifokor kirsa — faqat o'ziga yo'naltirilgan bemorlar ko'rinadi.
    Admin/Reception — hammani ko'radi.
    """
    from apps.accounts.models import Role

    qs = (
        Visit.objects.filter(visit_date=timezone.localdate())
        .select_related("patient", "doctor", "doctor__role")
        .order_by("queue_number")
    )
    if status:
        qs = qs.filter(status=status)

    # Shifokor faqat o'ziga assigned vizitlarni ko'radi
    if user and not user.is_superuser and user.role:
        doctor_only_roles = {
            Role.Code.DOCTOR, Role.Code.SURGEON,
            Role.Code.CHIEF_DOCTOR, Role.Code.NURSE,
            Role.Code.WARD_NURSE, Role.Code.LAB, Role.Code.RADIOLOGY,
        }
        if user.role.code in doctor_only_roles:
            qs = qs.filter(doctor=user)

    return qs


def queue_waiting() -> QuerySet[Visit]:
    """Hozir navbatda turganlar."""
    return visits_today(status=Visit.Status.WAITING)


def patient_visits(*, patient: Patient) -> QuerySet[Visit]:
    """Bemorning barcha tashrif tarixi."""
    return patient.visits.select_related("doctor").order_by("-visit_date", "-queue_number")


def appointments_for_day(
    *, day: Optional[datetime.date] = None, doctor: Optional[object] = None
) -> QuerySet[Appointment]:
    """Kun bo'yicha yozilishlar (ixtiyoriy shifokor filtri)."""
    day = day or timezone.localdate()
    qs = (
        Appointment.objects.filter(scheduled_at__date=day)
        .select_related("patient", "doctor")
        .order_by("scheduled_at")
    )
    if doctor is not None:
        qs = qs.filter(doctor=doctor)
    return qs
