"""Accounts moduli unit testlari."""
from __future__ import annotations

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import Role, User
from apps.accounts.services import (
    seed_default_roles,
    user_create,
    user_deactivate,
    user_set_role,
    user_update,
)
from apps.audit.models import AuditLog
from apps.core.exceptions import DomainError

STRONG_PASSWORD = "Xk9#mPl2$vQz"


class RoleSeedTests(TestCase):
    def test_seed_creates_all_default_roles(self) -> None:
        from apps.accounts.services import DEFAULT_ROLES

        roles = seed_default_roles()
        # Rollar soni DEFAULT_ROLES dan olinadi — yangi rol qo'shilganda
        # test o'z-o'zidan moslashadi (qattiq raqamga bog'lanmaydi).
        self.assertEqual(len(roles), len(DEFAULT_ROLES))
        self.assertTrue(Role.objects.filter(code="super_admin").exists())
        self.assertTrue(Role.objects.filter(code="surgeon").exists())
        self.assertTrue(Role.objects.filter(code="anesthesiologist").exists())
        self.assertTrue(Role.objects.filter(code="tablo").exists())

    def test_seed_is_idempotent(self) -> None:
        from apps.accounts.services import DEFAULT_ROLES

        seed_default_roles()
        seed_default_roles()
        self.assertEqual(Role.objects.count(), len(DEFAULT_ROLES))

    def test_auditor_and_viewer_are_read_only(self) -> None:
        seed_default_roles()
        self.assertTrue(Role.objects.get(code="auditor").is_read_only)
        self.assertTrue(Role.objects.get(code="viewer").is_read_only)


class UserServiceTests(TestCase):
    def setUp(self) -> None:
        seed_default_roles()
        self.doctor_role = Role.objects.get(code="doctor")

    def test_user_create_success(self) -> None:
        user = user_create(
            username="dr_aziz",
            password=STRONG_PASSWORD,
            role=self.doctor_role,
            first_name="Aziz",
            last_name="Karimov",
            phone="+998901234567",
        )
        self.assertTrue(user.check_password(STRONG_PASSWORD))
        self.assertEqual(user.role_code, "doctor")
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.CREATE, object_id=str(user.pk)
            ).exists()
        )

    def test_user_create_duplicate_username_fails(self) -> None:
        user_create(username="dr_aziz", password=STRONG_PASSWORD)
        with self.assertRaises(DomainError):
            user_create(username="dr_aziz", password=STRONG_PASSWORD)

    def test_user_update_writes_audit_diff(self) -> None:
        user = user_create(username="nurse1", password=STRONG_PASSWORD)
        user_update(user=user, phone="+998911112233")
        log = AuditLog.objects.filter(
            action=AuditLog.Action.UPDATE, object_id=str(user.pk)
        ).latest("created_at")
        self.assertEqual(log.changes["phone"]["new"], "+998911112233")

    def test_user_set_role(self) -> None:
        user = user_create(username="stat1", password=STRONG_PASSWORD)
        user_set_role(user=user, role=self.doctor_role)
        user.refresh_from_db()
        self.assertEqual(user.role_code, "doctor")

    def test_user_deactivate_soft_deletes(self) -> None:
        user = user_create(username="temp1", password=STRONG_PASSWORD)
        user_deactivate(user=user)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())  # default manager
        deleted = User.all_objects.get(pk=user.pk)
        self.assertTrue(deleted.is_deleted)
        self.assertFalse(deleted.is_active)
        self.assertTrue(
            AuditLog.objects.filter(
                action=AuditLog.Action.DELETE, object_id=str(user.pk)
            ).exists()
        )

    def test_weak_password_rejected(self) -> None:
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            user_create(username="weak1", password="12345678")


class RolePermissionTests(TestCase):
    def setUp(self) -> None:
        seed_default_roles()
        self.client = APIClient()

    def _make_user(self, username: str, role_code: str) -> User:
        return user_create(
            username=username,
            password=STRONG_PASSWORD,
            role=Role.objects.get(code=role_code),
        )

    def test_viewer_cannot_create_user(self) -> None:
        viewer = self._make_user("viewer1", "viewer")
        self.client.force_authenticate(viewer)
        response = self.client.post(
            "/api/v1/accounts/users/",
            {"username": "newbie", "password": STRONG_PASSWORD},
        )
        self.assertEqual(response.status_code, 403)

    def test_doctor_cannot_access_user_admin_api(self) -> None:
        doctor = self._make_user("doc1", "doctor")
        self.client.force_authenticate(doctor)
        response = self.client.get("/api/v1/accounts/users/")
        self.assertEqual(response.status_code, 403)

    def test_administrator_can_list_users(self) -> None:
        admin = self._make_user("admin1", "administrator")
        self.client.force_authenticate(admin)
        response = self.client.get("/api/v1/accounts/users/")
        self.assertEqual(response.status_code, 200)

    def test_only_super_admin_can_set_role(self) -> None:
        admin = self._make_user("admin2", "administrator")
        target = self._make_user("target1", "nurse")
        doctor_role = Role.objects.get(code="doctor")
        self.client.force_authenticate(admin)
        response = self.client.post(
            f"/api/v1/accounts/users/{target.pk}/set_role/",
            {"role_id": str(doctor_role.pk)},
        )
        self.assertEqual(response.status_code, 403)

        super_admin = self._make_user("root1", "super_admin")
        self.client.force_authenticate(super_admin)
        response = self.client.post(
            f"/api/v1/accounts/users/{target.pk}/set_role/",
            {"role_id": str(doctor_role.pk)},
        )
        self.assertEqual(response.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.role_code, "doctor")

    def test_me_endpoint_open_to_all_roles(self) -> None:
        nurse = self._make_user("nurse_me", "nurse")
        self.client.force_authenticate(nurse)
        response = self.client.get("/api/v1/accounts/users/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["username"], "nurse_me")

    def test_anonymous_rejected(self) -> None:
        response = self.client.get("/api/v1/accounts/users/")
        self.assertEqual(response.status_code, 403)


class LoginAuditTests(TestCase):
    def test_login_creates_audit_log(self) -> None:
        seed_default_roles()
        user_create(username="cashier1", password=STRONG_PASSWORD,
                    role=Role.objects.get(code="cashier"))
        logged_in = self.client.login(username="cashier1", password=STRONG_PASSWORD)
        self.assertTrue(logged_in)
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.LOGIN).exists()
        )

    def test_failed_login_logged(self) -> None:
        self.client.login(username="ghost", password="wrong-pass-123")
        self.assertTrue(
            AuditLog.objects.filter(action=AuditLog.Action.LOGIN_FAILED).exists()
        )
