"""Kassa va billing modellari."""
from django.conf import settings
from django.db import models

from apps.audit.mixins import Auditable
from apps.core.models import BaseModel, LockableMixin
from apps.patients.models import Patient
from apps.registration.models import Visit
from apps.clinical.models import ServiceCatalog


class Invoice(Auditable, LockableMixin, BaseModel):
    """Bemorning bitta qabuli bo'yicha umumiy hisobi (Chek)."""

    class Status(models.TextChoices):
        UNPAID = "unpaid", "To'lanmagan"
        PARTIAL = "partial", "Qisman to'langan"
        PAID = "paid", "To'langan"
        REFUNDED = "refunded", "Pul qaytarilgan"
        CANCELLED = "cancelled", "Bekor qilingan"

    patient = models.ForeignKey(
        Patient, verbose_name="Bemor", on_delete=models.PROTECT, related_name="invoices"
    )
    visit = models.OneToOneField(
        Visit, verbose_name="Qabul", on_delete=models.CASCADE, related_name="invoice"
    )
    total_amount = models.DecimalField("Umumiy summa", max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField("To'langan summa", max_digits=12, decimal_places=2, default=0)
    refunded_amount = models.DecimalField("Qaytarilgan summa", max_digits=12, decimal_places=2, default=0)
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.UNPAID
    )
    cashier = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Kassir", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="processed_invoices"
    )
    paid_at = models.DateTimeField("To'langan vaqt", null=True, blank=True)

    class Meta:
        verbose_name = "Hisob (Chek)"
        verbose_name_plural = "Hisoblar (Cheklar)"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Chek #{self.pk} - {self.patient.full_name} ({self.total_amount} so'm)"

    @property
    def net_paid(self):
        """Amalda kassada qolgan pul (to'langan - qaytarilgan)."""
        return self.paid_amount - self.refunded_amount

    @property
    def debt(self):
        return self.total_amount - self.net_paid

    @property
    def refundable_amount(self):
        """Maksimal qaytarish mumkin bo'lgan summa."""
        return max(self.paid_amount - self.refunded_amount, 0)

    @property
    def overpaid_amount(self):
        """Otmen tufayli ortiqcha to'lanib qolgan (qaytarilishi lozim) summa."""
        return max(self.net_paid - self.total_amount, 0)

    def recompute_status(self) -> None:
        """paid/refunded/total asosida statusni qayta hisoblaydi (saqlamaydi)."""
        if self.status == self.Status.CANCELLED:
            return
        if self.total_amount > 0 and self.net_paid >= self.total_amount:
            self.status = self.Status.PAID
        elif self.net_paid > 0:
            self.status = self.Status.PARTIAL
        elif self.refunded_amount > 0:
            self.status = self.Status.REFUNDED
        else:
            self.status = self.Status.UNPAID


class Refund(Auditable, BaseModel):
    """Kassadan pul qaytarish (xatolik, otmen, dori qaytarish va h.k.)."""

    invoice = models.ForeignKey(
        Invoice, verbose_name="Hisob", on_delete=models.CASCADE, related_name="refunds"
    )
    amount = models.DecimalField("Qaytarilgan summa", max_digits=12, decimal_places=2)
    reason = models.CharField("Sabab", max_length=255)
    refunded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Qaytardi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="refunds_made",
    )

    class Meta:
        verbose_name = "Pul qaytarish"
        verbose_name_plural = "Pul qaytarishlar"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.invoice.patient.full_name}: -{self.amount} so'm ({self.reason})"


class InvoiceItem(Auditable, BaseModel):
    """Chek ichidagi alohida xizmatlar (Shifokor, UZI, Palata)."""

    class ItemType(models.TextChoices):
        SERVICE = "service", "Xizmat (Shifokor, Tahlil)"
        MEDICINE = "medicine", "Dori-darmon"
        INPATIENT = "inpatient", "Statsionar (Palata, Hamroh)"
        SURGERY = "surgery", "Jarrohlik amaliyoti"
        OTHER = "other", "Boshqa"

    invoice = models.ForeignKey(
        Invoice, verbose_name="Hisob", on_delete=models.CASCADE, related_name="items"
    )
    item_type = models.CharField("Turi", max_length=20, choices=ItemType.choices, default=ItemType.SERVICE)
    name = models.CharField("Nomi", max_length=255, default="Xizmat")
    service = models.ForeignKey(
        ServiceCatalog, verbose_name="Katalog xizmati", null=True, blank=True, on_delete=models.SET_NULL, related_name="invoice_items"
    )
    reference_id = models.UUIDField("Asosiy hujjat ID-si", null=True, blank=True)
    quantity = models.DecimalField("Soni/Miqdori", max_digits=10, decimal_places=2, default=1)
    price = models.DecimalField("Narxi", max_digits=12, decimal_places=2)
    total_price = models.DecimalField("Jami narxi", max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Hisob bandi"
        verbose_name_plural = "Hisob bandlari"

    def __str__(self) -> str:
        return f"{self.name} x{self.quantity} = {self.total_price}"

    def save(self, *args, **kwargs):
        self.total_price = self.price * self.quantity
        super().save(*args, **kwargs)


class DoctorShare(Auditable, BaseModel):
    """Shifokorga ajratilgan ulush (ish haqi)."""
    doctor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shares", verbose_name="Shifokor")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="doctor_shares", verbose_name="To'lov (Chek)")
    amount = models.DecimalField("Ulush summasi", max_digits=12, decimal_places=2)
    description = models.CharField("Izoh", max_length=255, blank=True)

    class Meta:
        verbose_name = "Shifokor ulushi"
        verbose_name_plural = "Shifokor ulushlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.doctor.get_full_name()} - {self.amount} so'm ({self.invoice.pk})"
