"""Patients service layer."""
from __future__ import annotations

import datetime
from typing import Any, Optional

from django.db import transaction

from apps.core.exceptions import DomainError
from apps.core.models import Sequence
from apps.patients.models import Patient
from apps.patients.selectors import find_duplicates

CARD_SEQUENCE = "patient_card"

_UPDATABLE_FIELDS = frozenset(
    {"last_name", "first_name", "middle_name", "birth_date", "gender", "phone",
     "passport", "jshshir", "address", "relative_name", "relative_phone",
     "insurance_company", "insurance_number", "notes"}
)


def _normalize(value: Optional[str]) -> Optional[str]:
    """Bo'sh satrni None ga aylantiradi (unique NULL uchun)."""
    value = (value or "").strip()
    return value or None


@transaction.atomic
def patient_create(
    *,
    last_name: str,
    first_name: str,
    birth_date: datetime.date,
    gender: str,
    middle_name: str = "",
    phone: str = "",
    passport: Optional[str] = None,
    jshshir: Optional[str] = None,
    address: str = "",
    relative_name: str = "",
    relative_phone: str = "",
    insurance_company: str = "",
    insurance_number: str = "",
    notes: str = "",
    allow_duplicate: bool = False,
) -> Patient:
    """Yangi bemor yaratadi.

    Takroriy bemor gumoni bo'lsa (JSHSHIR/pasport/telefon+FIO mos kelsa)
    DomainError ko'taradi; registratura ongli ravishda allow_duplicate=True
    bilan davom etishi mumkin (JSHSHIR/pasport mosligi bundan mustasno —
    ular qat'iy unique).
    """
    passport = _normalize(passport.upper() if passport else passport)
    jshshir = _normalize(jshshir)

    duplicates = find_duplicates(
        jshshir=jshshir, passport=passport, phone=phone.strip(),
        last_name=last_name.strip(), first_name=first_name.strip(),
        birth_date=birth_date,
    )
    if duplicates.exists():
        exact = duplicates.filter(jshshir=jshshir).exists() if jshshir else False
        exact = exact or (duplicates.filter(passport=passport).exists() if passport else False)
        if exact:
            match = duplicates.first()
            raise DomainError(
                f"Bu JSHSHIR/pasport bilan bemor allaqachon mavjud: {match}",
                code="patient_exists",
            )
        if not allow_duplicate:
            match = duplicates.first()
            raise DomainError(
                f"Takroriy bemor gumoni: {match}. Tasdiqlasangiz allow_duplicate=True yuboring.",
                code="duplicate_suspected",
            )

    patient = Patient(
        card_number=f"P-{Sequence.get_next(CARD_SEQUENCE):06d}",
        last_name=last_name.strip(),
        first_name=first_name.strip(),
        middle_name=middle_name.strip(),
        birth_date=birth_date,
        gender=gender,
        phone=phone.strip(),
        passport=passport,
        jshshir=jshshir,
        address=address.strip(),
        relative_name=relative_name.strip(),
        relative_phone=relative_phone.strip(),
        insurance_company=insurance_company.strip(),
        insurance_number=insurance_number.strip(),
        notes=notes,
    )
    patient.full_clean()
    patient.save()
    return patient


@transaction.atomic
def patient_update(*, patient: Patient, **fields: Any) -> Patient:
    """Bemor ma'lumotlarini yangilaydi (audit Auditable orqali)."""
    changed: list[str] = []
    for name, value in fields.items():
        if name not in _UPDATABLE_FIELDS:
            raise DomainError(f"'{name}' maydonini o'zgartirib bo'lmaydi.")
        if name in {"passport", "jshshir"}:
            value = _normalize(value.upper() if name == "passport" and value else value)
        if getattr(patient, name) != value:
            setattr(patient, name, value)
            changed.append(name)
    if changed:
        patient.full_clean()
        patient.save(update_fields=changed)
    return patient


@transaction.atomic
def patient_delete(*, patient: Patient) -> Patient:
    """Bemorni soft delete qiladi (tarix va hisob-kitoblar saqlanadi)."""
    patient.delete()
    return patient
