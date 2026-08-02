"""Audit view'lari: har bir foydalanuvchi O'ZINING qilgan ishlarini ko'radi."""
from __future__ import annotations

import datetime
from typing import Any

from django.apps import apps as django_apps
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.views.generic import ListView

from apps.audit.models import AuditLog

# model_name -> odam tushunadigan nom (fallback: modelning verbose_name'i)
FRIENDLY_MODELS = {
    "clinic_registration.visit": "Qabul (tashrif)",
    "clinic_registration.appointment": "Yozilish",
    "patients.patient": "Bemor",
    "clinical.consultation": "Tibbiy xulosa",
    "clinical.consultationtemplate": "Tashxis shabloni",
    "clinical.serviceorder": "Tekshiruv buyurtmasi",
    "clinical.doctorprice": "Qabul narxi",
    "clinical.inpatientstay": "Statsionar yotish",
    "clinical.staychecklistitem": "Statsionar hujjat bandi",
    "clinical.procedurerecord": "Muolaja qaydi",
    "clinical.surgeryschedule": "Operatsiya",
    "clinical.surgeryreport": "Operatsiya bayonnomasi",
    "clinical.surgicalitem": "Jarrohlik uskunasi",
    "clinical.room": "Palata",
    "clinical.bed": "Kravat",
    "billing.invoice": "Chek (hisob)",
    "billing.invoiceitem": "Chek bandi",
    "billing.refund": "Pul qaytarish",
    "pharmacy.medicinebatch": "Dori partiyasi",
    "pharmacy.medicinedispense": "Dori chiqimi",
    "pharmacy.medicine": "Dori",
    "accounts.user": "Foydalanuvchi",
}


def _friendly_model(model_name: str) -> str:
    if not model_name:
        return "—"
    if model_name in FRIENDLY_MODELS:
        return FRIENDLY_MODELS[model_name]
    try:
        app_label, mname = model_name.split(".")
        return str(django_apps.get_model(app_label, mname)._meta.verbose_name).capitalize()
    except Exception:
        return model_name


class MyActivityView(LoginRequiredMixin, ListView):
    """"Mening ishlarim" — foydalanuvchining o'z faoliyat tarixi.

    Tizim hamma amalni (yaratish, o'zgartirish, to'lov, dori berish,
    hujjat belgilash va h.k.) audit jurnaliga avtomatik yozadi — bu
    sahifa faqat JORIY foydalanuvchining yozuvlarini ko'rsatadi.
    """

    template_name = "audit/my_activity.html"
    context_object_name = "logs"
    paginate_by = 50

    def get(self, request, *args, **kwargs):
        if request.GET.get("format") == "excel":
            from apps.core.exports import export_queryset_to_excel
            qs = self.get_queryset()
            columns = [
                ("Sana/vaqt", "created_at"),
                ("Amal", "get_action_display"),
                ("Bo'lim", "model_name"),
                ("Nima ustida", "object_repr"),
            ]
            return export_queryset_to_excel(qs, columns, "Mening_ishlarim")
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> Any:
        qs = AuditLog.objects.filter(actor=self.request.user)

        action = self.request.GET.get("action", "")
        if action in AuditLog.Action.values:
            qs = qs.filter(action=action)

        try:
            days = int(self.request.GET.get("days", "30"))
        except ValueError:
            days = 30
        if days > 0:
            qs = qs.filter(created_at__gte=timezone.now() - datetime.timedelta(days=days))

        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(object_repr__icontains=search)

        return qs

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        for log in context["logs"]:
            log.friendly_model = _friendly_model(log.model_name)

        my_logs = AuditLog.objects.filter(actor=self.request.user)
        today = timezone.localdate()
        context.update({
            "total_count": my_logs.count(),
            "today_count": my_logs.filter(created_at__date=today).count(),
            "week_count": my_logs.filter(
                created_at__gte=timezone.now() - datetime.timedelta(days=7)
            ).count(),
            "actions": AuditLog.Action.choices,
            "current_action": self.request.GET.get("action", ""),
            "current_days": self.request.GET.get("days", "30"),
            "current_q": self.request.GET.get("q", ""),
        })
        return context
