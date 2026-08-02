"""Audit jurnal modeli.

AuditLog o'zi BaseModel emas (soft delete/stamping kerak emas) —
audit yozuvi hech qachon o'zgartirilmaydi va o'chirilmaydi.
"""
from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Kim, qachon, nimani, qanday o'zgartirgani haqidagi o'zgarmas yozuv."""

    class Action(models.TextChoices):
        CREATE = "create", "Yaratildi"
        UPDATE = "update", "O'zgartirildi"
        DELETE = "delete", "O'chirildi (soft)"
        RESTORE = "restore", "Tiklandi"
        LOGIN = "login", "Kirish"
        LOGOUT = "logout", "Chiqish"
        LOGIN_FAILED = "login_failed", "Kirish muvaffaqiyatsiz"
        APPROVE = "approve", "Tasdiqlandi"
        EXPORT = "export", "Eksport"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Bajaruvchi",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
    )
    actor_display = models.CharField(
        "Bajaruvchi (snapshot)", max_length=255, blank=True,
        help_text="User o'chirilsa ham kim ekani ko'rinib turadi.",
    )
    action = models.CharField("Amal", max_length=20, choices=Action.choices, db_index=True)
    model_name = models.CharField("Model", max_length=120, db_index=True, blank=True)
    object_id = models.CharField("Obyekt ID", max_length=64, db_index=True, blank=True)
    object_repr = models.CharField("Obyekt", max_length=255, blank=True)
    changes = models.JSONField(
        "O'zgarishlar", default=dict, blank=True,
        help_text='{"maydon": {"old": ..., "new": ...}} ko\'rinishida.',
    )
    ip_address = models.GenericIPAddressField("IP manzil", null=True, blank=True)
    user_agent = models.CharField("Qurilma (User-Agent)", max_length=512, blank=True)
    created_at = models.DateTimeField("Vaqt", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Audit yozuvi"
        verbose_name_plural = "Audit jurnali"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["model_name", "object_id"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.actor_display or 'Tizim'} — {self.get_action_display()} — {self.model_name}#{self.object_id}"
