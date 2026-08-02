"""Audit service layer: log yozish va model snapshot/diff hisoblash."""
from __future__ import annotations

import datetime
import decimal
import uuid
from typing import Any, Optional

from django.db import models

from apps.audit.models import AuditLog
from apps.core.middleware import get_client_ip, get_current_user, get_user_agent

# Diffda ko'rsatilmaydigan texnik/maxfiy maydonlar
EXCLUDED_FIELDS: frozenset[str] = frozenset(
    {"password", "updated_at", "updated_by", "last_login"}
)


def _serialize(value: Any) -> Any:
    """Qiymatni JSON-safe ko'rinishga keltiradi."""
    if isinstance(value, (uuid.UUID, decimal.Decimal)):
        return str(value)
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, models.Model):
        return str(value.pk)
    return value


def snapshot(instance: models.Model) -> dict[str, Any]:
    """Model instansiyasining barcha konkret maydonlari snapshotini oladi."""
    data: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        if field.name in EXCLUDED_FIELDS:
            continue
        data[field.name] = _serialize(getattr(instance, field.attname))
    return data


def diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Ikki snapshot orasidagi farq: {"maydon": {"old": x, "new": y}}."""
    changed: dict[str, dict[str, Any]] = {}
    for key in new:
        if old.get(key) != new.get(key):
            changed[key] = {"old": old.get(key), "new": new.get(key)}
    return changed


def log_action(
    *,
    action: str,
    instance: Optional[models.Model] = None,
    actor: Any = None,
    changes: Optional[dict[str, Any]] = None,
    model_name: str = "",
    object_id: str = "",
    object_repr: str = "",
) -> AuditLog:
    """Audit jurnaliga yozuv qo'shadi.

    actor berilmasa thread-local'dagi joriy userdan olinadi;
    IP va User-Agent joriy requestdan olinadi.
    """
    actor = actor or get_current_user()
    if instance is not None:
        model_name = model_name or f"{instance._meta.app_label}.{instance._meta.model_name}"
        object_id = object_id or str(instance.pk)
        object_repr = object_repr or str(instance)[:255]
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        actor_display=str(actor) if actor else "",
        action=action,
        model_name=model_name,
        object_id=object_id,
        object_repr=object_repr,
        changes=changes or {},
        ip_address=get_client_ip(),
        user_agent=get_user_agent(),
    )
