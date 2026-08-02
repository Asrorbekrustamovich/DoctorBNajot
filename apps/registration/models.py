"""Registratura: qabul (Visit) va oldindan yozilish (Appointment)."""
from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.audit.mixins import Auditable
from apps.core.models import BaseModel
from apps.patients.models import Patient


class Appointment(Auditable, BaseModel):
    """Shifokorga oldindan yozilish."""

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Rejalashtirilgan"
        CONFIRMED = "confirmed", "Tasdiqlangan"
        ARRIVED = "arrived", "Keldi"
        CANCELLED = "cancelled", "Bekor qilingan"
        NO_SHOW = "no_show", "Kelmadi"

    patient = models.ForeignKey(
        Patient, verbose_name="Bemor", on_delete=models.PROTECT,
        related_name="appointments",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor",
        on_delete=models.PROTECT, related_name="appointments",
    )
    scheduled_at = models.DateTimeField("Belgilangan vaqt", db_index=True)
    duration_minutes = models.PositiveSmallIntegerField("Davomiylik (daqiqa)", default=15)
    reason = models.CharField("Sabab", max_length=255, blank=True)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices,
        default=Status.SCHEDULED, db_index=True,
    )
    notes = models.TextField("Izoh", blank=True)

    class Meta:
        verbose_name = "Yozilish"
        verbose_name_plural = "Yozilishlar"
        ordering = ["scheduled_at"]
        indexes = [models.Index(fields=["doctor", "scheduled_at"])]

    def __str__(self) -> str:
        return f"{self.patient.full_name} → {self.doctor} ({self.scheduled_at:%d.%m.%Y %H:%M})"

    @property
    def end_at(self) -> "timezone.datetime":
        return self.scheduled_at + timezone.timedelta(minutes=self.duration_minutes)


class Visit(Auditable, BaseModel):
    """Bemorning klinikaga bitta tashrifi (qabul epizodi).

    Status oqimi:
        created → waiting → accepted → in_progress → completed → archived
        created/waiting/accepted → cancelled → archived
        accepted/in_progress → waiting (boshqa shifokorga yo'naltirilganda,
        o'sha Visit qayta navbatga qaytadi — yangi Visit ochilmaydi)
    """

    class Status(models.TextChoices):
        CREATED = "created", "Yaratildi"
        WAITING = "waiting", "Navbatda"
        ACCEPTED = "accepted", "Qabul qilindi"
        IN_PROGRESS = "in_progress", "Davolanmoqda"
        COMPLETED = "completed", "Yakunlandi"
        CANCELLED = "cancelled", "Bekor qilindi"
        ARCHIVED = "archived", "Arxivlandi"

    VALID_TRANSITIONS: dict[str, frozenset[str]] = {
        Status.CREATED: frozenset({Status.WAITING, Status.CANCELLED}),
        Status.WAITING: frozenset({Status.ACCEPTED, Status.CANCELLED}),
        Status.ACCEPTED: frozenset({Status.IN_PROGRESS, Status.WAITING, Status.CANCELLED}),
        Status.IN_PROGRESS: frozenset({Status.COMPLETED, Status.WAITING}),
        Status.COMPLETED: frozenset({Status.ARCHIVED}),
        Status.CANCELLED: frozenset({Status.ARCHIVED}),
        Status.ARCHIVED: frozenset(),
    }

    patient = models.ForeignKey(
        Patient, verbose_name="Bemor", on_delete=models.PROTECT, related_name="visits"
    )
    appointment = models.OneToOneField(
        Appointment, verbose_name="Yozilish", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="visit",
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor", null=True, blank=True,
        on_delete=models.PROTECT, related_name="visits",
    )
    visit_date = models.DateField("Tashrif sanasi", db_index=True)
    queue_number = models.PositiveIntegerField("Navbat raqami")
    complaint = models.TextField("Shikoyat", blank=True)
    referral = models.CharField("Yo'llanma", max_length=255, blank=True)
    preliminary_diagnosis = models.CharField("Birlamchi tashxis", max_length=255, blank=True)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices,
        default=Status.CREATED, db_index=True,
    )
    cancel_reason = models.CharField("Bekor qilish sababi", max_length=255, blank=True)
    accepted_at = models.DateTimeField("Qabul vaqti", null=True, blank=True)
    completed_at = models.DateTimeField("Yakun vaqti", null=True, blank=True)

    class Meta:
        verbose_name = "Qabul (tashrif)"
        verbose_name_plural = "Qabullar (tashriflar)"
        ordering = ["-visit_date", "queue_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["visit_date", "queue_number"], name="uniq_queue_per_day"
            )
        ]
        indexes = [models.Index(fields=["status", "visit_date"])]

    def __str__(self) -> str:
        return f"№{self.queue_number} {self.patient.full_name} ({self.visit_date:%d.%m.%Y})"

    def can_transition(self, new_status: str) -> bool:
        return new_status in self.VALID_TRANSITIONS.get(self.status, frozenset())
