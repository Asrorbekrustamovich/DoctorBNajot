from django import forms
from apps.accounts.models import User
from apps.clinical.models import Consultation, ServiceCatalog, ServiceOrder
from django.db.models import Q

class ConsultationForm(forms.ModelForm):
    referred_doctor = forms.ModelChoiceField(
        label="Boshqa shifokorga yo'naltirish (ixtiyoriy)",
        queryset=User.objects.filter(Q(role__code="doctor") | Q(role__code="chief_doctor"), is_active=True).order_by("last_name"),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"})
    )
    
    # UZI, EKG kabi xizmatlarni tanlash uchun
    recommended_services = forms.ModelMultipleChoiceField(
        label="Tekshiruvlarga yuborish (UZI, EKG va h.k.)",
        queryset=ServiceCatalog.objects.filter(is_active=True).select_related(
            "room", "responsible_staff", "allowed_role"
        ),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"})
    )
    
    referral_notes = forms.CharField(
        label="Yo'naltirilayotgan shifokor uchun xulosa/tashxis",
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Ushbu shifokorga nima maqsadda yuborilayotganini yozing..."})
    )

    class Meta:
        model = Consultation
        fields = [
            "complaint", "anamnesis", "objective_status", 
            "diagnosis", "prescription", "recommendations"
        ]
        widgets = {
            "complaint": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "anamnesis": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "objective_status": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "diagnosis": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "prescription": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "recommendations": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["referred_doctor"].label_from_instance = lambda obj: f"{obj.get_full_name() or obj.username} ({obj.specialty or (obj.role.name if obj.role else 'Shifokor')})"
        # Xizmat yonida bemor QAYERGA borishi ko'rinib tursin
        self.fields["recommended_services"].label_from_instance = (
            lambda s: f"{s.name} → {s.destination}" if s.destination else s.name
        )
