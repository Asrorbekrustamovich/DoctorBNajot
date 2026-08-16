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
        # METRIKA (tug'ilganlik guvohnomasi) HAM BOR.
        #
        # HAQIQIY XATO: formada faqat JSHSHIR va pasport bor edi.
        # Bolalarda esa pasport bo'lmaydi va metrika yagona hujjat —
        # ya'ni bolani hujjatsiz ro'yxatga olishga to'g'ri kelardi.
        # Qidiruv metrikani qo'llab-quvvatlagani bilan, kiritish joyi
        # bo'lmagach undan foyda yo'q edi.
        fields = [
            "last_name", "first_name", "middle_name", "birth_date", "gender",
            "jshshir", "passport", "birth_certificate", "phone", "address", "notes",
        ]
        widgets = {
            "last_name": forms.TextInput(attrs=_TEXT),
            "first_name": forms.TextInput(attrs=_TEXT),
            "middle_name": forms.TextInput(attrs=_TEXT),
            "birth_date": forms.DateInput(attrs={**_TEXT, "type": "date"}),
            "gender": forms.Select(attrs=_SELECT),
            "jshshir": forms.TextInput(attrs={**_TEXT, "placeholder": "14 ta raqam"}),
            "passport": forms.TextInput(attrs={**_TEXT, "placeholder": "AA1234567"}),
            "birth_certificate": forms.TextInput(attrs={
                **_TEXT, "placeholder": "I-AB 123456 (bolalar uchun)"}),
            "phone": forms.TextInput(attrs={**_TEXT, "placeholder": "+998901234567"}),
            "address": forms.TextInput(attrs=_TEXT),
            "notes": forms.Textarea(attrs={**_TEXT, "rows": 3}),
        }

    def validate_unique(self) -> None:
        # Unique tekshiruv service layer'da (normalize bilan) bajariladi
        pass

    # ------------------------------------------------------------------
    #  NOYOBLIK TEKSHIRUVI — O'CHIRILGANLARNI HAM HISOBGA OLIB
    # ------------------------------------------------------------------
    #  HAQIQIY XATO: `Patient` da soft delete ishlatiladi — o'chirilgan
    #  bemor bazadan yo'qolmaydi, faqat `is_deleted=True` bo'ladi.
    #  ModelForm esa noyoblikni `objects` (faqat tiriklar) bo'yicha
    #  tekshiradi va o'chirilgan bemordagi JSHSHIR ni KO'RMAYDI.
    #  Natijada forma «hammasi joyida» deydi, baza esa UNIQUE cheklovini
    #  buzib IntegrityError tashlaydi va foydalanuvchi 500 sahifani ko'radi.
    #
    #  Bu yerda o'chirilganlarni ham tekshiramiz va tushunarli xabar
    #  beramiz: bunday bemor allaqachon bor, uni TIKLASH kerak — yangisini
    #  yaratish emas (bu bir xil odam).

    def _check_unique(self, field: str, label: str):
        value = self.cleaned_data.get(field)
        if not value:
            return value
        qs = Patient.all_objects.filter(**{field: value})
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        found = qs.first()
        if found is None:
            return value
        if found.is_deleted:
            raise forms.ValidationError(
                f"Bu {label} o'chirilgan bemorda band: {found.full_name} "
                f"({found.card_number}). Bu o'sha odam bo'lsa — uni tiklang, "
                f"yangisini yaratmang."
            )
        raise forms.ValidationError(
            f"Bu {label} allaqachon ro'yxatda: {found.full_name} "
            f"({found.card_number})."
        )

    def clean_jshshir(self):
        # Bo'sh qiymat NULL bo'lishi SHART. Bo'sh satr (`""`) saqlansa,
        # JSHSHIR'siz IKKINCHI bemor ham `""` oladi va unique cheklovi
        # buziladi. NULL lar esa bir-biriga xalaqit bermaydi.
        value = (self.cleaned_data.get("jshshir") or "").strip() or None
        self.cleaned_data["jshshir"] = value
        return self._check_unique("jshshir", "JSHSHIR")

    def clean_passport(self):
        value = (self.cleaned_data.get("passport") or "").strip().upper() or None
        self.cleaned_data["passport"] = value
        return self._check_unique("passport", "pasport")

    def clean(self):
        """KAMIDA BITTA HUJJAT bo'lishi kerak — lekin QAYSI BIRI, farqi yo'q.

        Kattalarda JSHSHIR yoki pasport, bolalarda metrika. Ilgari hech
        qanday qoida yo'q edi va bemorni umuman hujjatsiz saqlash mumkin
        edi — keyin uni na topib, na boshqasidan ajratib bo'lardi.

        MUHIMI: metrika ham TO'LIQ HUJJAT hisoblanadi. Bolada JSHSHIR
        ham, pasport ham bo'lmaydi va ularni talab qilish — bolani
        ro'yxatga ololmaslik demakdir.
        """
        tozalangan = super().clean()

        bor = any([
            (tozalangan.get("jshshir") or "").strip(),
            (tozalangan.get("passport") or "").strip(),
            (tozalangan.get("birth_certificate") or "").strip(),
        ])
        if not bor:
            raise forms.ValidationError(
                "Kamida bitta hujjat kiritilishi kerak: JSHSHIR, pasport "
                "yoki metrika. Bolalarda metrikaning o'zi yetarli."
            )
        return tozalangan

    def clean_birth_certificate(self):
        """Metrika — JSHSHIR va pasport bilan bir xil qoidalar.

        U ham unikal maydon, ya'ni bo'sh satr saqlansa metrikasiz
        IKKINCHI bemor ham `""` olib, unique cheklovi buziladi va
        foydalanuvchi 500 sahifani ko'radi.

        Bo'shliq va tirelar olib tashlanmaydi — hujjatda qanday yozilgan
        bo'lsa shundayligicha saqlanadi. Qidiruv baribir ikkala
        ko'rinishni ham topadi.
        """
        value = (self.cleaned_data.get("birth_certificate") or "").strip().upper() or None
        self.cleaned_data["birth_certificate"] = value
        return self._check_unique("birth_certificate", "metrika")
