"""Core sahifalar: boshqaruv paneli va healthcheck."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import connection
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.views.generic import TemplateView


class HomeView(LoginRequiredMixin, TemplateView):
    """Bosh sahifa — kunlik ko'rsatkichlar paneli."""

    template_name = "core/home.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.role:
            if request.user.role.code == "accountant":
                from django.shortcuts import redirect
                return redirect("billing:dashboard")
            if request.user.role.code in ["lab", "radiology"]:
                from django.shortcuts import redirect
                return redirect("clinical:examiner_dashboard")
            if request.user.role.code == "tablo":
                from django.shortcuts import redirect
                return redirect("registration:board")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        from apps.patients.models import Patient
        from apps.registration.models import Visit
        from apps.registration.selectors import visits_today

        context = super().get_context_data(**kwargs)
        today_qs = visits_today()
        context.update(
            {
                "today": timezone.localdate(),
                "total_patients": Patient.objects.count(),
                "today_visits": today_qs.count(),
                "waiting_count": today_qs.filter(status=Visit.Status.WAITING).count(),
                "completed_count": today_qs.filter(status=Visit.Status.COMPLETED).count(),
                "recent_visits": today_qs[:8],
            }
        )
        return context


def health_check(request: HttpRequest) -> JsonResponse:
    """Load balancer / monitoring uchun DB holatini tekshiradi."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_ok = True
    except Exception:  # noqa: BLE001 - har qanday DB xatosi unhealthy
        db_ok = False
    status = 200 if db_ok else 503
    return JsonResponse({"status": "ok" if db_ok else "error", "database": db_ok}, status=status)
