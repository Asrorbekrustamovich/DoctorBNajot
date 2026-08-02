"""User modelini auditlash (Auditable mixin ishlatilmagani uchun signal orqali).

last_login kabi texnik yangilanishlar jurnalga yozilmaydi.
"""
from __future__ import annotations

from typing import Any

from django.db.models.signals import pre_save
from django.dispatch import receiver

from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.audit.services import diff, log_action, snapshot

_TRACKED_FIELDS = frozenset(
    {"username", "first_name", "last_name", "middle_name", "phone",
     "email", "role", "is_active", "is_staff", "is_superuser", "is_deleted"}
)


@receiver(pre_save, sender=User)
def audit_user_changes(sender: type[User], instance: User, **kwargs: Any) -> None:
    # Zaxira/fixture yuklanayotganda audit yozilmaydi (loaddata)
    if kwargs.get("raw", False):
        return
    if instance._state.adding:
        return  # CREATE audit service layer'da yoziladi
    old = User.all_objects.filter(pk=instance.pk).first()
    if old is None:
        return
    changes = {
        k: v
        for k, v in diff(snapshot(old), snapshot(instance)).items()
        if k in _TRACKED_FIELDS
    }
    if not changes:
        return
    deleted = changes.get("is_deleted")
    if deleted and deleted["new"] is True:
        action = AuditLog.Action.DELETE
    elif deleted and deleted["new"] is False:
        action = AuditLog.Action.RESTORE
    else:
        action = AuditLog.Action.UPDATE
    log_action(action=action, instance=instance, changes=changes)
