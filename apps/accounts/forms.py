"""Accounts formalari (Bootstrap 5 uslubida)."""
from __future__ import annotations

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from apps.accounts.models import Role, User


class LoginForm(AuthenticationForm):
    """Kirish formasi."""

    username = forms.CharField(
        label="Login",
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Login", "autofocus": True}
        ),
    )
    password = forms.CharField(
        label="Parol",
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "placeholder": "Parol"}
        ),
    )


class UserForm(forms.ModelForm):
    """Xodim profili formasi (admin panel tashqarisidagi CRUD uchun)."""

    class Meta:
        model = User
        fields = [
            "username", "last_name", "first_name", "middle_name",
            "phone", "email", "role", "extra_roles", "is_active",
        ]
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "middle_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+998901234567"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "extra_roles": forms.SelectMultiple(attrs={"class": "form-select select2", "data-placeholder": "Qo'shimcha rollar..."}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.order_by("name")
        self.fields["extra_roles"].queryset = Role.objects.order_by("name")
        self.fields["extra_roles"].required = False  # type: ignore[attr-defined]


class StaffCreateForm(forms.ModelForm):
    """Yangi xodim/shifokor yaratish formasi (parol bilan)."""

    password = forms.CharField(
        label="Parol",
        min_length=6,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": "Kamida 6 belgi"}),
    )
    password2 = forms.CharField(
        label="Parolni takrorlang",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = User
        fields = [
            "username", "last_name", "first_name", "middle_name",
            "phone", "email", "role", "extra_roles", "specialty",
        ]
        labels = {
            "username": "Login (foydalanuvchi nomi)",
            "specialty": "Mutaxassislik (ixtiyoriy)",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control", "placeholder": "Masalan: dr_karimov"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "middle_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+998901234567"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "extra_roles": forms.SelectMultiple(attrs={"class": "form-select select2", "data-placeholder": "Qo'shimcha rollar..."}),
            "specialty": forms.TextInput(attrs={"class": "form-control", "placeholder": "Masalan: Kardiolog"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.order_by("name")
        self.fields["extra_roles"].queryset = Role.objects.order_by("name")
        self.fields["extra_roles"].required = False

    def clean(self):
        cleaned_data = super().clean()
        pw1 = cleaned_data.get("password")
        pw2 = cleaned_data.get("password2")
        if pw1 and pw2 and pw1 != pw2:
            self.add_error("password2", "Parollar mos kelmadi.")
        return cleaned_data


class StaffEditForm(forms.ModelForm):
    """Mavjud xodim ma'lumotlarini tahrirlash (parolsiz)."""

    class Meta:
        model = User
        fields = [
            "username", "last_name", "first_name", "middle_name",
            "phone", "email", "role", "extra_roles", "specialty", "is_active",
        ]
        labels = {
            "specialty": "Mutaxassislik (ixtiyoriy)",
        }
        widgets = {
            "username": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "middle_name": forms.TextInput(attrs={"class": "form-control"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+998901234567"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "role": forms.Select(attrs={"class": "form-select"}),
            "extra_roles": forms.SelectMultiple(attrs={"class": "form-select select2", "data-placeholder": "Qo'shimcha rollar..."}),
            "specialty": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["role"].queryset = Role.objects.order_by("name")
        self.fields["extra_roles"].queryset = Role.objects.order_by("name")
        self.fields["extra_roles"].required = False


class ServiceForm(forms.ModelForm):
    """Xizmat katalogi uchun forma (UZI, EKG, tahlillar va h.k.)."""

    class Meta:
        from apps.clinical.models import ServiceCatalog
        model = ServiceCatalog
        fields = ["name", "price", "allowed_role", "room", "responsible_staff", "is_active"]
        labels = {
            "name": "Xizmat nomi",
            "price": "Narxi (so'm)",
            "allowed_role": "Bajaruvchi xodim roli (ixtiyoriy)",
            "room": "Kabinet — bemor qaysi xonaga boradi",
            "responsible_staff": "Mas'ul xodim — bemor kimning oldiga boradi",
            "is_active": "Faolmi?",
        }
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Masalan: UZI (Qorin bo'shlig'i)"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "placeholder": "0"}),
            "allowed_role": forms.Select(attrs={"class": "form-select"}),
            "room": forms.Select(attrs={"class": "form-select"}),
            "responsible_staff": forms.Select(attrs={"class": "form-select"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        from apps.accounts.models import User
        from apps.clinical.models import AmbulatoryRoom

        self.fields["allowed_role"].queryset = Role.objects.order_by("name")
        self.fields["allowed_role"].required = False

        self.fields["room"].queryset = AmbulatoryRoom.objects.filter(
            is_active=True
        ).order_by("name")
        self.fields["room"].required = False
        self.fields["room"].empty_label = "— kabinet ko'rsatilmagan —"

        self.fields["responsible_staff"].queryset = User.objects.filter(
            is_active=True, role__isnull=False
        ).select_related("role").order_by("first_name", "last_name")
        self.fields["responsible_staff"].required = False
        self.fields["responsible_staff"].empty_label = "— rol bo'yicha kim bo'sh bo'lsa —"
        self.fields["responsible_staff"].label_from_instance = (
            lambda u: f"{u.get_full_name() or u.username}"
                      f"{f' ({u.specialty})' if u.specialty else f' ({u.role.name})' if u.role else ''}"
        )

    def clean(self):
        """Mas'ul xodim tanlansa, u xizmatning roliga mos bo'lishi kerak."""
        data = super().clean()
        staff = data.get("responsible_staff")
        role = data.get("allowed_role")
        if staff and role and staff.role_id and staff.role_id != role.id:
            self.add_error(
                "responsible_staff",
                f"{staff.get_full_name() or staff.username} — «{staff.role.name}» roli, "
                f"tanlangan «{role.name}» roliga to'g'ri kelmaydi.",
            )
        return data

