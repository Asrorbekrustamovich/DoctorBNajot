"""Registration formalari."""
from __future__ import annotations

from django import forms
from django.db.models import Q

from apps.accounts.models import User
from apps.patients.models import Patient


class VisitForm(forms.Form):
    """Qabul ochish formasi (service layer parametrlariga mos)."""

    patient = forms.ModelChoiceField(
        label="Bemor",
        queryset=Patient.objects.all(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    doctor = forms.ModelChoiceField(
        label="Shifokor",
        queryset=User.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )


    def __init__(self, *args: object, **kwargs: object) -> None:
        import re
        kwargs.pop("instance", None)  # CreateView yuboradi, lekin Form'ga kerak emas
        super().__init__(*args, **kwargs)
        self.fields["doctor"].queryset = User.objects.filter(  # type: ignore[attr-defined]
            Q(role__code="doctor") | Q(role__code="chief_doctor"),
            # Bayroq — asosiy belgi. Matn bo'yicha moslik esa eski
        # ma'lumotlar uchun zaxira: bayroq qo'yilmagan, lekin
        # mutaxassisligida «ambulator» yozilgan shifokorlar
        # ro'yxatdan tushib qolmasin.
        Q(is_ambulatory=True)
        | Q(specialty__icontains="ambulator")
        | Q(specialty__icontains="amblator"),
            is_active=True
        ).order_by("last_name")
        
        def format_doctor_label(obj):
            spec = obj.specialty or (obj.role.name if obj.role else 'Shifokor')
            spec = re.sub(r'(?i)\s*/\s*amb(?:u?)lator\b', '', spec).strip()
            return f"{obj.get_full_name() or obj.username} ({spec})"
            
        self.fields["doctor"].label_from_instance = format_doctor_label
        # RO'YXAT YORLIG'IGA METRIKA HAM QO'SHILADI.
        #
        # Registratordagi tezkor qidiruv shu matn ustidan ishlaydi. Metrika
        # bo'lmagani uchun bolani topib bo'lmasdi: ularda pasport yo'q,
        # metrika esa yagona hujjat.
        def yorliq(obj):
            qism = [f"{obj.last_name} {obj.first_name}".strip()]
            if obj.jshshir:
                qism.append(f"JSHSHIR: {obj.jshshir}")
            if obj.passport:
                qism.append(f"Seria: {obj.passport}")
            if obj.birth_certificate:
                qism.append(f"Metrika: {obj.birth_certificate}")
            if obj.card_number:
                qism.append(obj.card_number)
            return " | ".join(qism)

        self.fields["patient"].label_from_instance = yorliq
