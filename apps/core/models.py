"""Barcha domen modellari uchun abstrakt asos modellar.

Qoidalar:
- UUID primary key (tashqi integratsiya va xavfsizlik uchun).
- created_at/updated_at hamma yozuvda.
- Soft delete: hech narsa jismonan o'chirilmaydi.
- created_by/updated_by middleware orqali avtomatik to'ldiriladi.
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.middleware import get_current_user


class UUIDModel(models.Model):
    """UUID primary key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    """Yaratilgan/yangilangan vaqt."""

    created_at = models.DateTimeField("Yaratilgan", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Yangilangan", auto_now=True)

    class Meta:
        abstract = True


class SoftDeleteQuerySet(models.QuerySet):
    """Soft delete'ni qo'llab-quvvatlovchi queryset."""

    def delete(self) -> int:
        """Ommaviy soft delete."""
        return super().update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        """Jismoniy o'chirish — faqat texnik ehtiyoj uchun."""
        return super().delete()

    def alive(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=False)

    def dead(self) -> "SoftDeleteQuerySet":
        return self.filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """`objects` — faqat tiriklar; `all_objects` — hammasi."""

    def __init__(self, *args: Any, alive_only: bool = True, **kwargs: Any) -> None:
        self.alive_only = alive_only
        super().__init__(*args, **kwargs)

    def get_queryset(self) -> SoftDeleteQuerySet:
        qs = SoftDeleteQuerySet(self.model, using=self._db)
        return qs.alive() if self.alive_only else qs


class SoftDeleteModel(models.Model):
    """Soft delete maydonlari va metodlari."""

    is_deleted = models.BooleanField("O'chirilgan", default=False, db_index=True)
    deleted_at = models.DateTimeField("O'chirilgan vaqt", null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="O'chirgan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    objects = SoftDeleteManager()
    all_objects = SoftDeleteManager(alive_only=False)

    class Meta:
        abstract = True

    def delete(  # type: ignore[override]
        self,
        using: Optional[str] = None,
        keep_parents: bool = False,
        user: Any = None,
    ) -> None:
        """Yozuvni soft delete qiladi (jismonan o'chirmaydi)."""
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.deleted_by = user or get_current_user()
        update_fields = ["is_deleted", "deleted_at", "deleted_by"]
        if hasattr(self, "updated_at"):
            update_fields.append("updated_at")
        self.save(using=using, update_fields=update_fields)

    def hard_delete(self, using: Optional[str] = None, keep_parents: bool = False) -> None:
        """Jismoniy o'chirish — faqat texnik ehtiyoj uchun."""
        super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        """Soft delete'ni bekor qiladi."""
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        update_fields = ["is_deleted", "deleted_at", "deleted_by"]
        if hasattr(self, "updated_at"):
            update_fields.append("updated_at")
        self.save(update_fields=update_fields)


class UserStampedModel(models.Model):
    """Kim yaratgan / kim oxirgi marta o'zgartirgan."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Yaratgan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="O'zgartirgan",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        editable=False,
    )

    class Meta:
        abstract = True

    def save(self, *args: Any, **kwargs: Any) -> None:
        user = get_current_user()
        if user is not None:
            if self._state.adding and self.created_by_id is None:
                self.created_by = user
                update_fields = kwargs.get("update_fields")
                if update_fields is not None:
                    kwargs["update_fields"] = list(set(update_fields) | {"created_by"})
            self.updated_by = user
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = list(set(update_fields) | {"updated_by"})
        super().save(*args, **kwargs)


class BaseModel(UUIDModel, TimeStampedModel, UserStampedModel, SoftDeleteModel):
    """Barcha domen modellari uchun standart asos."""

    class Meta:
        abstract = True


class LockableMixin(models.Model):
    """Hujjatni "o'zgarmas qilib" qulflash uchun.

    Qulflangach hujjatni FAQAT superadmin ocha/tahrirlaydi (audit bilan).
    Boshqa hech kim (jarroh, kassir, hamshira va h.k.) o'zgartira olmaydi.
    """

    is_locked = models.BooleanField("Qulflangan (o'zgarmas)", default=False)
    locked_at = models.DateTimeField("Qulflangan vaqt", null=True, blank=True)
    locked_by = models.ForeignKey(
        "accounts.User", verbose_name="Qulflagan xodim",
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="locked_%(class)s_set",
    )

    class Meta:
        abstract = True

    @staticmethod
    def _is_superadmin(user) -> bool:
        return bool(
            user and user.is_authenticated
            and (user.is_superuser or user.has_role("super_admin"))
        )

    def can_modify(self, user) -> bool:
        """Qulflanmagan bo'lsa — hamma (ruxsati borlar); qulf bo'lsa — faqat superadmin."""
        if not self.is_locked:
            return True
        return self._is_superadmin(user)

    def lock(self, user):
        from django.utils import timezone
        self.is_locked = True
        self.locked_at = timezone.now()
        self.locked_by = user if (user and user.is_authenticated) else None
        self.save(update_fields=["is_locked", "locked_at", "locked_by"])

    def unlock(self, user):
        """Faqat superadmin ocha oladi."""
        if not self._is_superadmin(user):
            return False
        self.is_locked = False
        self.save(update_fields=["is_locked"])
        return True


class Sequence(models.Model):
    """Atomik raqam generatori (karta raqami, kunlik navbat va h.k.).

    PostgreSQL'da select_for_update qator darajasida qulflaydi —
    parallel so'rovlarda ham takrorlanmas raqam kafolatlanadi.
    """

    name = models.CharField("Nomi", max_length=100, unique=True)
    value = models.BigIntegerField("Qiymat", default=0)

    class Meta:
        verbose_name = "Raqam ketma-ketligi"
        verbose_name_plural = "Raqam ketma-ketliklari"

    def __str__(self) -> str:
        return f"{self.name}={self.value}"

    @classmethod
    def get_next(cls, name: str) -> int:
        """Keyingi raqamni atomik oladi (yo'q bo'lsa 1 dan boshlaydi)."""
        from django.db import transaction

        with transaction.atomic():
            obj, _ = cls.objects.select_for_update().get_or_create(name=name)
            obj.value += 1
            obj.save(update_fields=["value"])
            return obj.value
