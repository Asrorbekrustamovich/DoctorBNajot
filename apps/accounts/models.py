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
        THERAPIST = "therapist", "Terapevt"
        PEDIATRICIAN = "pediatrician", "Pediatr"
        CARDIOLOGIST = "cardiologist", "Kardiolog"
        NEUROLOGIST = "neurologist", "Nevrolog"
        GYNECOLOGIST = "gynecologist", "Ginekolog"
        UROLOGIST = "urologist", "Urolog"
        ENDOCRINOLOGIST = "endocrinologist", "Endokrinolog"
        OTOLARYNGOLOGIST = "otolaryngologist", "Otolaringolog"
        OPHTHALMOLOGIST = "ophthalmologist", "Oftalmolog"
        TRAUMATOLOGIST = "traumatologist", "Travmatolog"
        GASTROENTEROLOGIST = "gastroenterologist", "Gastroenterolog" 
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
        # OPERATSION HAMSHIRA — jarrohlik blokida ishlaydigan hamshira.
        #
        # Ilgari operatsion blok butun «hamshira» va «palata hamshirasi»
        # rollariga ochiq edi. Natijada bo'lim hamshirasi ham operatsion
        # xonalar ro'yxatini ko'rardi — uning ishiga aloqasi bo'lmasa ham.
        # Bu rol qo'shimcha qilib biriktiriladi: hamshiralik o'z joyida
        # qoladi, ustiga operatsion blok ochiladi.
        OPERATING_NURSE = "operating_nurse", "Operatsion hamshira"
        STERILIZATION = "sterilization", "Sterilizatsiya (Avtoklav)"
        TABLO = "tablo", "Navbat tablosi (Display)"
        AUDITOR = "auditor", "Auditor (faqat ko'rish)"
        VIEWER = "viewer", "Viewer (faqat ko'rish)"

    code = models.CharField("Kod", max_length=32, choices=Code.choices, unique=True)

    DOCTOR_ROLES = (
        Code.THERAPIST, Code.PEDIATRICIAN, Code.CARDIOLOGIST,
        Code.NEUROLOGIST, Code.GYNECOLOGIST, Code.UROLOGIST,
        Code.ENDOCRINOLOGIST, Code.OTOLARYNGOLOGIST, Code.OPHTHALMOLOGIST,
        Code.TRAUMATOLOGIST, Code.GASTROENTEROLOGIST
    )

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
    # QO'SHIMCHA ROLLAR.
    #
    # Kichik klinikada bitta xodim ikki ish qiladi: qabulxona hamshirasi
    # ayni paytda omborni ham yuritadi. Asosiy rolni almashtirsak,
    # hamshiralik ekranlari yopilib qoladi. Shuning uchun asosiy rol
    # o'z joyida qoladi, qo'shimchasi shu yerga biriktiriladi.
    extra_roles = models.ManyToManyField(
        "accounts.Role", verbose_name="Qo'shimcha rollar",
        blank=True, related_name="extra_users",
        help_text="Asosiy roldan tashqari ochiladigan bo'limlar.",
    )

    specialty = models.CharField("Mutaxassislik", max_length=100, blank=True)
    # Registraturada bemorni kimga yozdirish mumkinligini shu bayroq
    # hal qiladi.
    #
    # NEGA ALOHIDA MAYDON: ilgari bu `specialty` matnida «ambulator»
    # so'zi bor-yo'qligiga qarab aniqlanardi. Bu jimgina buziladi —
    # xodim qo'shayotgan odam «Ambulatoriya», «ambulator shifokor» yoki
    # kirillcha yozsa, shifokor registratura ro'yxatidan G'OYIB BO'LADI
    # va sababi hech qayerda ko'rinmaydi. Endi bu ochiq belgi.
    is_ambulatory = models.BooleanField(
        "Ambulator qabul qiladi", default=False,
        help_text="Belgilansa, registraturada shu shifokorga bemor yozdirish mumkin.",
    )
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

    @property
    def role_codes(self) -> set[str]:
        """Asosiy rol + qo'shimcha rollar.

        Bitta so'rov davomida qayta-qayta o'qiladi, shuning uchun
        natija keshlanadi — har tekshiruvda bazaga bormaydi.
        """
        kesh = getattr(self, "_role_codes_kesh", None)
        if kesh is None:
            kesh = {self.role_code} if self.role_code else set()
            if self.pk:
                kesh |= set(
                    self.extra_roles.values_list("code", flat=True))
            self._role_codes_kesh = kesh
        return kesh

    def has_role(self, *codes: str) -> bool:
        """User berilgan rollardan biriga egami (qo'shimchalari bilan)."""
        return bool(self.role_codes & set(codes))

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
        Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, *Role.DOCTOR_ROLES,
        Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.CASHIER,
        Role.Code.ACCOUNTANT, Role.Code.AUDITOR, Role.Code.VIEWER,
        Role.Code.LAB, Role.Code.RADIOLOGY,
    )
    _PATIENT_WRITE_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
    )
    _VISIT_VIEW_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
        Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, *Role.DOCTOR_ROLES,
        Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.CASHIER,
        Role.Code.ACCOUNTANT, Role.Code.AUDITOR, Role.Code.VIEWER,
    )
    _VISIT_WRITE_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
    )
    _VISIT_TRANSITION_ROLES = (
        Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
        *Role.DOCTOR_ROLES, Role.Code.CHIEF_DOCTOR, Role.Code.NURSE,
    )

    @property
    def can_operating_block(self) -> bool:
        """Jarrohlik bloki va operatsion xonalar shu odamga ochiqmi.

        Palata hamshiralari ham kiradi: bemorni operatsiyaga
        tayyorlash, olib borish va qaytarib olish ularning ishi.

        Oddiy hamshira esa faqat aniq biriktirilganda kiradi —
        anestiziska va operatsion hamshiraga «operatsion hamshira»
        roli qo'shimcha qilib beriladi. Ilgari bu bo'lim klinikadagi
        HAMMA hamshiraga ochiq edi.
        """
        return self.is_superuser or self.has_role(
            Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR,
            Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR,
            Role.Code.SURGEON, Role.Code.SURGERY_ADMIN,
            Role.Code.ANESTHESIOLOGIST, Role.Code.STERILIZATION,
            Role.Code.OPERATING_NURSE, Role.Code.WARD_NURSE,
        )

    @property
    def can_warehouse(self) -> bool:
        """Ombor bo'limi shu odamga ochiqmi.

        Shablonda `user.role.code == "warehouse"` deb tekshirilsa,
        qo'shimcha rol e'tiborga olinmay qolardi.
        """
        return self.is_superuser or self.has_role(
            Role.Code.WAREHOUSE, Role.Code.SUPER_ADMIN)

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

def users_with_role(*codes: str):
    """Berilgan roldagi xodimlar — QO'SHIMCHA rollar bilan birga.

    Nega alohida funksiya
    ---------------------
    `User.objects.filter(role__code=...)` faqat ASOSIY rolni ko'radi.
    Amalda esa xirurg ayni paytda ambulator qabul ham qiladi: uning
    asosiy roli «shifokor», jarrohlik esa qo'shimcha. Shu sababli
    operatsiya oynasidagi «Jarroh» ro'yxati bo'm-bo'sh chiqardi —
    xirurglar bazada bor bo'lsa ham.

    `distinct()` shart: bir odamda ham asosiy, ham qo'shimcha rol mos
    kelsa, ro'yxatda ikki marta chiqib qolardi.
    """
    from django.db.models import Q

    return (
        User.objects.filter(
            Q(role__code__in=codes) | Q(extra_roles__code__in=codes),
            is_active=True,
        )
        .distinct()
        .order_by("last_name", "first_name")
    )

