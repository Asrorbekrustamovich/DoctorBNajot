"""Core moduli testlari: soft delete, BaseModel, healthcheck."""
from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import Role
from apps.accounts.services import seed_default_roles


class SoftDeleteTests(TestCase):
    """Role (BaseModel meros oluvchi) misolida soft delete xatti-harakati."""

    def setUp(self) -> None:
        seed_default_roles()

    def test_delete_is_soft(self) -> None:
        role = Role.objects.get(code="viewer")
        role.delete()
        self.assertFalse(Role.objects.filter(code="viewer").exists())
        self.assertTrue(Role.all_objects.filter(code="viewer").exists())
        deleted = Role.all_objects.get(code="viewer")
        self.assertTrue(deleted.is_deleted)
        self.assertIsNotNone(deleted.deleted_at)

    def test_restore(self) -> None:
        role = Role.objects.get(code="viewer")
        role.delete()
        deleted = Role.all_objects.get(code="viewer")
        deleted.restore()
        self.assertTrue(Role.objects.filter(code="viewer").exists())

    def test_queryset_delete_is_soft(self) -> None:
        Role.objects.filter(code="viewer").delete()
        self.assertTrue(Role.all_objects.filter(code="viewer", is_deleted=True).exists())

    def test_uuid_primary_key(self) -> None:
        import uuid

        role = Role.objects.get(code="doctor")
        self.assertIsInstance(role.pk, uuid.UUID)


class HealthCheckTests(TestCase):
    def test_healthz_returns_ok(self) -> None:
        response = self.client.get("/healthz/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["database"])
