"""Foydalanuvchi va RBAC rol modellari."""
from __future__ import annotations

import uuid
from typing import Any

from django.contrib.auth.models import AbstractUser, Permission
from django.contrib.auth.models import UserManager as DjangoUserManager
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.audit.mixins import Auditable
from apps.core.models import BaseModel

phone_validator = RegexValidator(
    regex=r"^\+?\d{9,15}$",
    message="Telefon raqami +998901234567 formatida bo'lishi kerak.",
)


class Role(Auditable, BaseModel):
    """RBAC roli. Django Permission'lar bilan bog'lanadi.

    is_read_only=True bo'lgan rollar (Auditor, Viewer) uchun barcha
    yozish amallari permission darajasida bloklanadi.
    """

    class Code(models.TextChoices):
        SUPER_ADMIN = "super_admin", "Super Admin"
        ADMINISTRATOR = "administrator", "Registrator"
        DIRECTOR = "director", "Direktor"
        CHIEF_DOCTOR = "chief_doctor", "Bosh shifokor"
        RECEPTION = "reception", "Registratura"
        DOCTOR = "doctor", "Shifokor"
        NURSE = "nurse", "Hamshira"
        WARD_NURSE = "ward_nurse", "Palata hamshirasi"
        LAB = "lab", "Laboratoriya"
        RADIOLOGY = "radiology", "Radiologiya"
        WAREHOUSE = "warehouse", "Ombor mudiri"
        CASHIER = "cashier", "Kassir"
        ACCOUNTANT = "accountant", "Buxgalter"
        SURGERY_ADMIN = "surgery_admin", "Jarrohlik bo'limi administratori"
        SURGEON = "surgeon", "Jarroh shifokor"
        ANESTHESIOLOGIST = "anesthesiologist", "Anesteziolog"
        STERILIZATION = "sterilization", "Sterilizatsiya (Avtoklav)"
        TABLO = "tablo", "Navbat tablosi (Display)"
        AUDITOR = "auditor", "Auditor (faqat ko'rish)"
        VIEWER = "viewer", "Viewer (faqat ko'rish)"

    code = models.CharField("Kod", max_length=32, choices=Code.choices, unique=True)
    name = models.CharField("Nomi", max_length=100)
    description = models.TextField("Tavsif", blank=True)
    is_read_only = models.BooleanField(
        "Faqat ko'rish",
        default=False,
        help_text="Belgilansa bu roldagi userlar hech narsani o'zgartira olmaydi.",
    )
    permissions = models.ManyToManyField(
        Permission,
        verbose_name="Huquqlar",
        blank=True,
        related_name="his_roles",
    )

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Rollar"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class UserManager(DjangoUserManager):
    """Soft-deleted userlarni autentifikatsiyadan chiqaradigan manager."""

    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(is_deleted=False)


class User(AbstractUser):
    """Tizim foydalanuvchisi (xodim).

    Auditable emas: last_login kabi texnik saqlashlar jurnalga shovqin
    bermasligi uchun user o'zgarishlari accounts.signals orqali auditlanadi.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    middle_name = models.CharField("Otasining ismi", max_length=150, blank=True)
    phone = models.CharField(
        "Telefon", max_length=16, blank=True, validators=[phone_validator]
    )
    role = models.ForeignKey(
        Role,
        verbose_name="Rol",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="users",
    )
    specialty = models.CharField("Mutaxassislik", max_length=100, blank=True)
    avatar = models.ImageField("Rasm", upload_to="avatars/%Y/%m/", blank=True)

    # Soft delete (BaseModel'dan emas, chunki AbstractUser bilan MRO soddaligi uchun)
    is_deleted = models.BooleanField("O'chirilgan", default=False, db_index=True)
    deleted_at = models.DateTimeField("O'chirilgan vaqt", null=True, blank=True)

    objects = UserManager()
    all_objects = DjangoUserManager()

    class Meta:
        verbose_name = "Foydalanuvchi"
        verbose_name_plural = "Foydalanuvchilar"
        ordering = ["last_name", "first_name"]

    def __str__(self) -> str:
        return self.get_full_name() or self.username

    def get_full_name(self) -> str:
        parts = [self.last_name, self.first_name, self.middle_name]
        return " ".join(p for p in parts if p).strip()

    # --- Rol tekshiruvlari -------------------------------------------------
    @property
    def role_code(self) -> str:
        return self.role.code if self.role_id and self.role else ""

    def has_role(self, *codes: str) -> bool:
        """User berilgan rollardan biriga egami."""
        return self.role_code in codes

    @property
    def is_read_only(self) -> bool:
        """Auditor/Viewer kabi faqat-ko'rish rollari."""
        return bool(self.role_id and self.role.is_read_only)

    def has_module_perm(self, perm: str) -> bool:
        """RBAC tekshiruvi: superuser yoki rol permissionlari orqali.

        perm — "app_label.codename" ko'rinishida.
        """
        if self.is_superuser:
            return True
        if not self.is_active or self.role_id is None:
            return False
        app_label, _, codename = perm.partition(".")
        return self.role.permissions.filter(
            content_type__app_label=app_label, codename=codename
        ).exists()

    # --- Sahifa ko'rish/yozish ruxsatlari (template uchun) -----------------
    _PATIENT_VIEW_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
        Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR,
        Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.CASHIER,
        Role.Code.ACCOUNTANT, Role.Code.AUDITOR, Role.Code.VIEWER,
        Role.Code.LAB, Role.Code.RADIOLOGY,
    )
    _PATIENT_WRITE_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
    )
    _VISIT_VIEW_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
        Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR,
        Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.CASHIER,
        Role.Code.ACCOUNTANT, Role.Code.AUDITOR, Role.Code.VIEWER,
    )
    _VISIT_WRITE_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
    )
    _VISIT_TRANSITION_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
        Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR, Role.Code.NURSE,
    )

    @property
    def can_view_patients(self) -> bool:
        return self.is_superuser or self.has_role(*self._PATIENT_VIEW_ROLES)

    @property
    def can_write_patients(self) -> bool:
        return self.is_superuser or self.has_role(*self._PATIENT_WRITE_ROLES)

    @property
    def can_view_visits(self) -> bool:
        return self.is_superuser or self.has_role(*self._VISIT_VIEW_ROLES)

    @property
    def can_write_visits(self) -> bool:
        return self.is_superuser or self.has_role(*self._VISIT_WRITE_ROLES)

    @property
    def can_transition_visits(self) -> bool:
        return self.is_superuser or self.has_role(*self._VISIT_TRANSITION_ROLES)

    def delete(self, using: Any = None, keep_parents: bool = False) -> None:  # type: ignore[override]
        """Userni soft delete qiladi va faolsizlantiradi."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.is_active = False
        self.save(update_fields=["is_deleted", "deleted_at", "is_active"])
