"""Patients selectors."""
from __future__ import annotations

import datetime
import re
from typing import Optional

from django.db.models import Q, QuerySet, Value
from django.db.models.functions import Replace, Upper

from apps.patients.models import Patient


def search_patients(qs: QuerySet[Patient], search: str) -> QuerySet[Patient]:
    """Bemorni FIO, karta, telefon va HUJJATLARI bo'yicha topadi.

    BITTA MANBA: kartoteka, kassa, registratura va API — hammasi shu
    funksiyadan foydalanadi. Qidiruv har joyda alohida yozilsa, ular
    muqarrar bir-biridan uzilib ketadi: bir joyda metrika topiladi,
    boshqasida topilmaydi.

    HUJJATLAR: JSHSHIR, pasport va METRIKA (tug'ilganlik guvohnomasi).
    Metrika ilgari umuman qidirilmasdi — bolalarni faqat ismi bo'yicha
    topish mumkin edi, holbuki ularda pasport bo'lmaydi va metrika
    yagona hujjat hisoblanadi.

    NORMALLASHTIRISH: metrika turlicha yoziladi — «I-AB 123456»,
    «I AB123456», «IAB123456». Oddiy `icontains` bunda ishlamaydi,
    shuning uchun bo'shliq va tirelar ikkala tomondan olib tashlanib
    solishtiriladi. JSHSHIR va pasportga ham shu qoida: registrator
    raqamni bo'shliq bilan terishi mumkin.
    """
    search = (search or "").strip()
    if not search:
        return qs

    siqiq = re.sub(r"[\s\-]", "", search).upper()

    shart = (
        Q(card_number__icontains=search)
        | Q(last_name__icontains=search)
        | Q(first_name__icontains=search)
        | Q(middle_name__icontains=search)
        | Q(phone__icontains=search)
        | Q(jshshir__icontains=search)
        | Q(passport__icontains=search)
        | Q(birth_certificate__icontains=search)
    )

    if siqiq:
        def siqib(maydon):
            """Maydondan bo'shliq va tirelarni olib tashlaydi."""
            return Replace(
                Replace(Upper(maydon), Value(" "), Value("")),
                Value("-"), Value(""),
            )

        qs = qs.annotate(
            norm_metrika=siqib("birth_certificate"),
            norm_pasport=siqib("passport"),
            norm_jshshir=siqib("jshshir"),
        )
        shart |= (
            Q(norm_metrika__contains=siqiq)
            | Q(norm_pasport__contains=siqiq)
            | Q(norm_jshshir__contains=siqiq)
        )

    return qs.filter(shart)


def patient_list(*, search: str = "") -> QuerySet[Patient]:
    """Kartoteka ro'yxati: FIO, karta, telefon va hujjatlar bo'yicha qidiruv."""
    return search_patients(Patient.objects.all(), search)


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
