"""Audit moduli testlari."""
from __future__ import annotations

from decimal import Decimal

from django.test import TestCase

from apps.accounts.models import Role
from apps.accounts.services import seed_default_roles
from apps.audit.models import AuditLog
from apps.audit.services import diff, log_action, snapshot


class AuditServiceTests(TestCase):
    def setUp(self) -> None:
        seed_default_roles()
        self.role = Role.objects.get(code="doctor")

    def test_snapshot_serializes_uuid_and_excludes_secrets(self) -> None:
        data = snapshot(self.role)
        self.assertEqual(data["code"], "doctor")
        self.assertIsInstance(data["id"], str)
        self.assertNotIn("password", data)

    def test_diff_detects_changes_only(self) -> None:
        old = {"name": "A", "price": str(Decimal("100.00"))}
        new = {"name": "A", "price": str(Decimal("150.00"))}
        result = diff(old, new)
        self.assertEqual(list(result), ["price"])
        self.assertEqual(result["price"]["old"], "100.00")
        self.assertEqual(result["price"]["new"], "150.00")

    def test_log_action_fills_instance_metadata(self) -> None:
        log = log_action(action=AuditLog.Action.APPROVE, instance=self.role)
        self.assertEqual(log.model_name, "accounts.role")
        self.assertEqual(log.object_id, str(self.role.pk))
        self.assertEqual(log.action, AuditLog.Action.APPROVE)

    def test_role_update_is_audited_via_auditable(self) -> None:
        self.role.description = "Yangilangan tavsif"
        self.role.save()
        log = AuditLog.objects.filter(
            model_name="accounts.role",
            object_id=str(self.role.pk),
            action=AuditLog.Action.UPDATE,
        ).latest("created_at")
        self.assertIn("description", log.changes)
