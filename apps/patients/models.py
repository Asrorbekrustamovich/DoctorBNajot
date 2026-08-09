"""Bemor kartotekasi modeli."""
from __future__ import annotations

import datetime

from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone

from apps.accounts.models import phone_validator
from apps.audit.mixins import Auditable
from apps.core.models import BaseModel

jshshir_validator = RegexValidator(
    regex=r"^\d{14}$", message="JSHSHIR 14 ta raqamdan iborat bo'lishi kerak."
)
passport_validator = RegexValidator(
    regex=r"^[A-Z]{2}\d{7}$", message="Pasport AA1234567 formatida bo'lishi kerak."
)


class Patient(Auditable, BaseModel):
    """Bemor. Karta raqami avtomatik, JSHSHIR/pasport takrorlanmas."""

    class Gender(models.TextChoices):
        MALE = "male", "Erkak"
        FEMALE = "female", "Ayol"

    card_number = models.CharField(
        "Karta raqami", max_length=20, unique=True, editable=False
    )
    last_name = models.CharField("Familiya", max_length=100)
    first_name = models.CharField("Ism", max_length=100)
    middle_name = models.CharField("Otasining ismi", max_length=100, blank=True)
    birth_date = models.DateField("Tug'ilgan sana")
    gender = models.CharField("Jinsi", max_length=10, choices=Gender.choices)
    phone = models.CharField(
        "Telefon", max_length=16, blank=True, validators=[phone_validator]
    )
    passport = models.CharField(
        "Pasport", max_length=9, null=True, blank=True, unique=True,
        validators=[passport_validator],
    )
    jshshir = models.CharField(
        "JSHSHIR", max_length=14, null=True, blank=True, unique=True,
        validators=[jshshir_validator],
    )
    # Bolalarda JSHSHIR hali bo'lmaydi — ular tug'ilganlik haqidagi
    # guvohnoma (metrika) bo'yicha qidiriladi. Statsionarga
    # rasmiylashtirishda hujjat turi shu ikkovidan tanlanadi.
    birth_certificate = models.CharField(
        "Metrika (tug'ilganlik guvohnomasi)", max_length=20,
        null=True, blank=True, unique=True,
        help_text="Bolalar uchun. Masalan: I-AB 123456",
    )
    address = models.CharField("Manzil", max_length=255, blank=True)
    relative_name = models.CharField("Qarindoshi (FIO)", max_length=200, blank=True)
    relative_phone = models.CharField(
        "Qarindoshi telefoni", max_length=16, blank=True, validators=[phone_validator]
    )
    insurance_company = models.CharField("Sug'urta kompaniyasi", max_length=200, blank=True)
    insurance_number = models.CharField("Sug'urta polisi", max_length=50, blank=True)
    notes = models.TextField("Izohlar", blank=True)

    class Meta:
        verbose_name = "Bemor"
        verbose_name_plural = "Bemorlar"
        ordering = ["last_name", "first_name"]
        indexes = [
            models.Index(fields=["last_name", "first_name"]),
            models.Index(fields=["phone"]),
            models.Index(fields=["birth_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.card_number} — {self.full_name}"

    @property
    def full_name(self) -> str:
        return " ".join(
            p for p in (self.last_name, self.first_name, self.middle_name) if p
        )

    @property
    def age(self) -> int:
        """Bugungi sanaga ko'ra yosh."""
        today: datetime.date = timezone.localdate()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years
