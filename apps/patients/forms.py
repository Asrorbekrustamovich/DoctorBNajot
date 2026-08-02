"""Patients formalari (Bootstrap 5)."""
from __future__ import annotations

from django import forms

from apps.patients.models import Patient

_TEXT = {"class": "form-control"}
_SELECT = {"class": "form-select"}


class PatientForm(forms.ModelForm):
    """Bemor yaratish/tahrirlash formasi.

    ModelForm ishlatiladi, lekin saqlash service layer orqali bajariladi —
    shuning uchun save() chaqirilmaydi (view'da services.patient_create/update).
    """

    class Meta:
        model = Patient
        fields = [
            "last_name", "first_name", "middle_name", "birth_date", "gender",
            "jshshir", "passport", "phone", "address", "notes",
        ]
        widgets = {
            "last_name": forms.TextInput(attrs=_TEXT),
            "first_name": forms.TextInput(attrs=_TEXT),
            "middle_name": forms.TextInput(attrs=_TEXT),
            "birth_date": forms.DateInput(attrs={**_TEXT, "type": "date"}),
            "gender": forms.Select(attrs=_SELECT),
            "jshshir": forms.TextInput(attrs={**_TEXT, "placeholder": "14 ta raqam"}),
            "passport": forms.TextInput(attrs={**_TEXT, "placeholder": "AA1234567"}),
            "phone": forms.TextInput(attrs={**_TEXT, "placeholder": "+998901234567"}),
            "address": forms.TextInput(attrs=_TEXT),
            "notes": forms.Textarea(attrs={**_TEXT, "rows": 3}),
        }

    def validate_unique(self) -> None:
        # Unique tekshiruv service layer'da (normalize bilan) bajariladi
        pass

