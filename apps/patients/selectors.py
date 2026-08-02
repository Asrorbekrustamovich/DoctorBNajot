"""Patients selectors."""
from __future__ import annotations

import datetime
from typing import Optional

from django.db.models import Q, QuerySet

from apps.patients.models import Patient


def patient_list(*, search: str = "") -> QuerySet[Patient]:
    """Kartoteka ro'yxati: FIO, karta, telefon, JSHSHIR, pasport bo'yicha qidiruv."""
    qs = Patient.objects.all()
    search = search.strip()
    if search:
        qs = qs.filter(
            Q(card_number__icontains=search)
            | Q(last_name__icontains=search)
            | Q(first_name__icontains=search)
            | Q(middle_name__icontains=search)
            | Q(phone__icontains=search)
            | Q(jshshir__icontains=search)
            | Q(passport__icontains=search)
        )
    return qs


def patient_get(*, pk: str) -> Optional[Patient]:
    return Patient.objects.filter(pk=pk).first()


def find_duplicates(
    *,
    jshshir: Optional[str],
    passport: Optional[str],
    phone: str,
    last_name: str,
    first_name: str,
    birth_date: datetime.date,
) -> QuerySet[Patient]:
    """Takroriy bemor nomzodlari.

    Qat'iy mos: JSHSHIR yoki pasport bir xil.
    Gumonli mos: FIO + tug'ilgan sana bir xil, yoki telefon + familiya bir xil.
    """
    q = Q()
    if jshshir:
        q |= Q(jshshir=jshshir)
    if passport:
        q |= Q(passport=passport)
    q |= Q(
        last_name__iexact=last_name,
        first_name__iexact=first_name,
        birth_date=birth_date,
    )
    if phone:
        q |= Q(phone=phone, last_name__iexact=last_name)
    return Patient.objects.filter(q)
