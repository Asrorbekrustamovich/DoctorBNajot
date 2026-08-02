"""Auditable mixin — modelga avtomatik CREATE/UPDATE/DELETE audit beradi.

Ishlatilishi:
    class Patient(Auditable, BaseModel): ...

Diff DB'dagi eski holat bilan solishtirib hisoblanadi, shuning uchun
qo'shimcha signal yoki kesh talab qilinmaydi.
"""
from __future__ import annotations

from typing import Any, Optional

from django.db import models


class Auditable(models.Model):
    """save()/delete() paytida audit jurnaliga avtomatik yozadi."""

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        from apps.audit import services as audit

        old_snapshot: Optional[dict[str, Any]] = None
        is_create = self._state.adding
        if not is_create:
            old = type(self).all_objects.filter(pk=self.pk).first() if hasattr(
                type(self), "all_objects"
            ) else type(self)._default_manager.filter(pk=self.pk).first()
            if old is not None:
                old_snapshot = audit.snapshot(old)

        super().save(*args, **kwargs)

        new_snapshot = audit.snapshot(self)
        if is_create:
            audit.log_action(
                action=audit.AuditLog.Action.CREATE,
                instance=self,
                changes={k: {"old": None, "new": v} for k, v in new_snapshot.items() if v is not None},
            )
        else:
            changes = audit.diff(old_snapshot or {}, new_snapshot)
            if not changes:
                return
            soft_delete_change = changes.get("is_deleted")
            if soft_delete_change and soft_delete_change["new"] is True:
                action = audit.AuditLog.Action.DELETE
            elif soft_delete_change and soft_delete_change["new"] is False:
                action = audit.AuditLog.Action.RESTORE
            else:
                action = audit.AuditLog.Action.UPDATE
                
            reason = getattr(self, "_audit_reason", None)
            if reason:
                changes["_reason"] = {"old": None, "new": reason}
                
            audit.log_action(action=action, instance=self, changes=changes)
