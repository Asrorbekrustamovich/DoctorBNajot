"""Accounts service layer — barcha yozish amallari shu yerda.

Views/serializers to'g'ridan-to'g'ri model yaratmaydi: service chaqiradi.
Har bir yozish amali transaction.atomic ichida va auditlanadi.
"""
from __future__ import annotations

from typing import Any, Optional

from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from apps.accounts.models import Role, User
from apps.audit.models import AuditLog
from apps.audit.services import log_action
from apps.core.exceptions import DomainError

# Standart rollar: (kod, nom, faqat_korish)
DEFAULT_ROLES: tuple[tuple[str, str, bool], ...] = (
    (Role.Code.SUPER_ADMIN, "Super Admin", False),
    (Role.Code.ADMINISTRATOR, "Registrator", False),
    (Role.Code.DIRECTOR, "Direktor", False),
    (Role.Code.CHIEF_DOCTOR, "Bosh shifokor", False),
    (Role.Code.RECEPTION, "Registratura", False),
    (Role.Code.THERAPIST, "Terapevt", False),
    (Role.Code.NURSE, "Hamshira", False),
    (Role.Code.WARD_NURSE, "Palata hamshirasi", False),
    (Role.Code.LAB, "Laboratoriya", False),
    (Role.Code.RADIOLOGY, "Radiologiya", False),
    (Role.Code.WAREHOUSE, "Ombor mudiri", False),
    (Role.Code.CASHIER, "Kassir", False),
    (Role.Code.ACCOUNTANT, "Buxgalter", False),
    (Role.Code.SURGERY_ADMIN, "Jarrohlik bo'limi administratori", False),
    (Role.Code.SURGEON, "Jarroh shifokor", False),
    (Role.Code.ANESTHESIOLOGIST, "Anesteziolog", False),
    (Role.Code.STERILIZATION, "Sterilizatsiya (Avtoklav)", False),
    (Role.Code.TABLO, "Navbat tablosi (Display)", True),
    (Role.Code.AUDITOR, "Auditor", True),
    (Role.Code.VIEWER, "Viewer", True),
)


@transaction.atomic
def seed_default_roles() -> list[Role]:
    """Standart rollarni yaratadi (idempotent — bor bo'lsa yangilamaydi)."""
    roles: list[Role] = []
    for code, name, read_only in DEFAULT_ROLES:
        role, _ = Role.all_objects.get_or_create(
            code=code, defaults={"name": name, "is_read_only": read_only}
        )
        roles.append(role)
    return roles


@transaction.atomic
def user_create(
    *,
    username: str,
    password: str,
    role: Optional[Role] = None,
    first_name: str = "",
    last_name: str = "",
    middle_name: str = "",
    phone: str = "",
    email: str = "",
    is_staff: bool = False,
) -> User:
    """Yangi xodim yaratadi (parol validatsiyasi + audit bilan)."""
    if User.all_objects.filter(username=username).exists():
        raise DomainError("Bu login band.", code="username_taken")
    user = User(
        username=username,
        first_name=first_name,
        last_name=last_name,
        middle_name=middle_name,
        phone=phone,
        email=email,
        role=role,
        is_staff=is_staff,
    )
    validate_password(password, user=user)
    user.set_password(password)
    user.full_clean(exclude=["password"])
    user.save()
    log_action(action=AuditLog.Action.CREATE, instance=user,
               changes={"username": {"old": None, "new": username},
                        "role": {"old": None, "new": str(role) if role else None}})
    return user


@transaction.atomic
def user_update(*, user: User, **fields: Any) -> User:
    """User maydonlarini yangilaydi va farqni auditlaydi."""
    allowed = {"first_name", "last_name", "middle_name", "phone", "email", "is_active"}
    changes: dict[str, dict[str, Any]] = {}
    for name, value in fields.items():
        if name not in allowed:
            raise DomainError(f"'{name}' maydonini bu service orqali o'zgartirib bo'lmaydi.")
        old = getattr(user, name)
        if old != value:
            changes[name] = {"old": old, "new": value}
            setattr(user, name, value)
    if not changes:
        return user
    user.full_clean(exclude=["password"])
    user.save(update_fields=list(changes))
    # UPDATE auditi accounts.signals dagi pre_save handler orqali yoziladi
    return user


@transaction.atomic
def user_set_role(*, user: User, role: Optional[Role]) -> User:
    """Userga rol biriktiradi/o'zgartiradi."""
    user.role = role
    user.save(update_fields=["role"])
    # Audit signals orqali yoziladi
    return user


@transaction.atomic
def user_change_password(*, user: User, new_password: str) -> User:
    """Parolni validatsiya bilan almashtiradi."""
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=["password"])
    log_action(action=AuditLog.Action.UPDATE, instance=user,
               changes={"password": {"old": "***", "new": "***"}})
    return user


@transaction.atomic
def user_deactivate(*, user: User) -> User:
    """Userni soft delete qiladi (login bloklanadi, tarix saqlanadi).

    DELETE auditi signals orqali yoziladi (is_deleted o'zgarishi asosida).
    """
    user.delete()
    return user
