"""Registration view'lari: navbat paneli (HTMX) + REST API."""
from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, ListView, TemplateView
from rest_framework import status as http_status
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import (
    DenyWriteForReadOnlyRoles,
    HasRoleForWrite,
    RoleRequiredMixin,
)
from apps.core.exceptions import DomainError
from apps.registration import selectors, services
from apps.registration.forms import VisitForm
from apps.registration.models import Visit
from apps.registration.serializers import (
    AppointmentCreateSerializer,
    AppointmentSerializer,
    VisitCreateSerializer,
    VisitSerializer,
    VisitTransitionSerializer,
)

WRITE_ROLES = (Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION)
TRANSITION_ROLES = WRITE_ROLES + (Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR, Role.Code.NURSE)
VIEW_ROLES = TRANSITION_ROLES + (
    Role.Code.DIRECTOR, Role.Code.WARD_NURSE, Role.Code.CASHIER,
    Role.Code.ACCOUNTANT, Role.Code.AUDITOR, Role.Code.VIEWER,
)


# --------------------------------------------------------------------------
# Web (HTMX)
# --------------------------------------------------------------------------
class QueueView(RoleRequiredMixin, ListView):
    """Bugungi navbat paneli."""

    allowed_roles = VIEW_ROLES
    template_name = "registration/queue.html"
    context_object_name = "visits"

    def get_queryset(self) -> Any:
        return selectors.visits_today(
            status=self.request.GET.get("status", ""),
            user=self.request.user,
        )

    def get_template_names(self) -> list[str]:
        if getattr(self.request, "htmx", False):
            return ["registration/_queue_table.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        context = super().get_context_data(**kwargs)
        context["statuses"] = Visit.Status.choices
        context["current_status"] = self.request.GET.get("status", "")
        return context


class VisitCreateWebView(RoleRequiredMixin, CreateView):
    allowed_roles = WRITE_ROLES
    form_class = VisitForm
    template_name = "registration/visit_form.html"
    success_url = reverse_lazy("registration:queue")

    def get_initial(self) -> dict[str, Any]:
        initial = super().get_initial()
        patient_id = self.request.GET.get("patient")
        if patient_id:
            initial["patient"] = patient_id
        return initial

    def form_valid(self, form: VisitForm) -> Any:
        try:
            visit = services.visit_create(**form.cleaned_data)
        except DomainError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        messages.success(self.request, f"Qabul ochildi: navbat №{visit.queue_number}")
        return redirect(self.success_url)


def visit_transition_web(request: Any, pk: str) -> Any:
    """HTMX tugmasi: statusni keyingi bosqichga o'tkazish."""
    if request.method != "POST":
        return redirect("registration:queue")
    user = request.user
    if not (user.is_superuser or user.has_role(*TRANSITION_ROLES)):
        messages.error(request, "Bu amal uchun huquq yo'q.")
        return redirect("registration:queue")
    visit = get_object_or_404(Visit, pk=pk)
    try:
        services.visit_transition(
            visit=visit,
            new_status=request.POST.get("status", ""),
            reason=request.POST.get("reason", ""),
        )
    except DomainError as exc:
        messages.error(request, exc.message)
    if getattr(request, "htmx", False):
        return render(request, "registration/_queue_table.html",
                      {"visits": selectors.visits_today()})
    return redirect("registration:queue")


# --------------------------------------------------------------------------
# Navbat Tablosi (kutish xonasi ekrani)
# --------------------------------------------------------------------------
BOARD_ROLES = (
    Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
    Role.Code.DIRECTOR, Role.Code.TABLO,
)


class BoardView(RoleRequiredMixin, TemplateView):
    """Kutish xonasi uchun to'liq ekranli navbat tablosi."""

    allowed_roles = BOARD_ROLES
    template_name = "registration/board.html"


def board_feed(request: Any) -> JsonResponse:
    """Tablo uchun JSON: bugun chaqirilgan (qabul qilingan) bemorlar.

    Eng oxirgi chaqirilgani birinchi bo'ladi. Tablo yangi chaqiruvlarni
    ovoz bilan e'lon qiladi.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not (
        user.is_superuser or user.has_role(*BOARD_ROLES)
    ):
        return JsonResponse({"calls": []}, status=403)
    today = timezone.localdate()

    def _doctor_room(doc):
        """Shifokorning FAOL kabineti (nofaol xonalar e'lon qilinmasin)."""
        if not doc:
            return ""
        room = doc.ambulatory_rooms.filter(is_active=True).first()
        return room.name if room else ""

    calls = []

    # --- 1) Shifokor qabuliga chaqirilganlar ---
    visits = (
        Visit.objects.filter(
            visit_date=today,
            accepted_at__isnull=False,
            status__in=[Visit.Status.ACCEPTED, Visit.Status.IN_PROGRESS],
        )
        .select_related("patient", "doctor")
        .prefetch_related("doctor__ambulatory_rooms")
        .order_by("-accepted_at")[:15]
    )
    for v in visits:
        doc = v.doctor
        calls.append({
            "id": f"v{v.pk}",
            "kind": "visit",
            "n": v.queue_number,
            "patient": v.patient.full_name if v.patient else "",
            "doctor": doc.get_full_name() if doc else "",
            "specialty": getattr(doc, "specialty", "") if doc else "",
            "room": _doctor_room(doc),
            "service": "",
            "at": v.accepted_at.isoformat() if v.accepted_at else "",
        })

    # --- 2) Tekshiruvga chaqirilganlar (UZI, EKG, tahlil...) ---
    # Faqat xodim «Chaqirish» tugmasini bosganlari chiqadi.
    from apps.clinical.models import ServiceOrder
    orders = (
        ServiceOrder.objects.filter(
            called_at__date=today,
        )
        .exclude(status__in=[ServiceOrder.Status.COMPLETED, ServiceOrder.Status.CANCELLED])
        .select_related(
            "visit__patient", "service__room",
            "service__responsible_staff", "called_by",
        )
        .order_by("-called_at")[:15]
    )
    for o in orders:
        xodim = o.service.responsible_staff or o.called_by
        room = o.service.room
        room_name = room.name if (room and room.is_active) else _doctor_room(xodim)
        calls.append({
            "id": f"s{o.pk}",
            "kind": "service",
            "n": o.visit.queue_number,
            "patient": o.visit.patient.full_name if o.visit.patient else "",
            "doctor": xodim.get_full_name() if xodim else "",
            "specialty": getattr(xodim, "specialty", "") if xodim else "",
            "room": room_name,
            "service": o.service.name,
            "at": o.called_at.isoformat() if o.called_at else "",
        })

    # Ikkala ro'yxat aralashtirilib, eng oxirgi chaqiruv birinchi bo'ladi
    calls.sort(key=lambda c: c["at"], reverse=True)
    return JsonResponse({"calls": calls[:15]})

from django.http import HttpResponse
from django.conf import settings
import os
import hashlib
import subprocess

# Tabloda ishlatiladigan o'zbekcha ovoz (tts_speak bilan bir xil bo'lishi shart)
DEFAULT_VOICE = "uz-UZ-MadinaNeural"

from django.contrib.auth.decorators import login_required

@login_required
def tts_speak(request):
    """Matnni mp3 ga o'girib, audio qaytaradigan endpoint."""
    text = request.GET.get("text", "").strip()
    if not text:
        return HttpResponse(status=400)
    
    # Hash the text to cache it
    text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
    tts_dir = os.path.join(settings.MEDIA_ROOT, "tts")
    os.makedirs(tts_dir, exist_ok=True)
    file_path = os.path.join(tts_dir, f"{text_hash}.mp3")
    
    # Fayl yo'q YOKI bo'sh (avvalgi buzuq urinishdan) bo'lsa — qayta yaratamiz
    needs_generate = (not os.path.exists(file_path)) or os.path.getsize(file_path) == 0
    if needs_generate:
        # edge-tts orqali toza o'zbekcha ovoz (uz-UZ-MadinaNeural).
        # "edge-tts" buyrug'i PATH da bo'lmasligi mumkin — shuning uchun
        # avval python moduli sifatida (python -m edge_tts), keyin buyruq sifatida
        # urinamiz. Birinchi marta sekinroq bo'lgani uchun timeout 20s.
        import sys
        commands = [
            [sys.executable, "-m", "edge_tts", "--voice", "uz-UZ-MadinaNeural",
             "--text", text, "--write-media", file_path],
            ["edge-tts", "--voice", "uz-UZ-MadinaNeural",
             "--text", text, "--write-media", file_path],
        ]
        ok = False
        last_err = ""
        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, timeout=20,
                               capture_output=True)
                if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
                    ok = True
                    break
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                continue
        if not ok:
            # Buzuq/bo'sh fayl qolmasin
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                pass
            return HttpResponse(
                "edge-tts ishlamadi. Internet borligini va 'pip install edge-tts' "
                "bajarilganini tekshiring. " + last_err,
                status=503, content_type="text/plain; charset=utf-8",
            )

    with open(file_path, "rb") as f:
        resp = HttpResponse(f.read(), content_type="audio/mpeg")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp


@login_required
def tts_health(request):
    """Serverda o'zbekcha ovoz ishlayaptimi — bir qarashda javob.

    NEGA KERAK: tabloda ovoz chiqmaganda sabab uchta bo'lishi mumkin va
    ular tashqaridan bir xil ko'rinadi:
      1) brauzer avtoijroni to'sgan (ekranda qizil tugma chiqadi)
      2) serverda `edge-tts` o'rnatilmagan
      3) server internetga chiqa olmaydi (edge-tts Microsoft xizmatiga
         ulanadi; ko'p VPS'larda chiquvchi trafik yopiq bo'ladi)

    Bu endpoint 2 va 3 ni ajratib beradi.
    """
    import shutil
    import sys

    info = {
        "python": sys.executable,
        "edge_tts_module": False,
        "edge_tts_command": bool(shutil.which("edge-tts")),
        "cache_dir_writable": False,
        "generated": False,
        "error": "",
    }

    try:
        import edge_tts  # noqa: F401
        info["edge_tts_module"] = True
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"modul yo'q: {exc}"

    tts_dir = os.path.join(settings.MEDIA_ROOT, "tts")
    try:
        os.makedirs(tts_dir, exist_ok=True)
        probe = os.path.join(tts_dir, ".probe")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        info["cache_dir_writable"] = True
    except OSError as exc:
        info["error"] = info["error"] or f"papkaga yozib bo'lmadi: {exc}"

    # Haqiqiy generatsiya — internet borligini ham tekshiradi
    if info["edge_tts_module"] or info["edge_tts_command"]:
        out = os.path.join(tts_dir, "_health.mp3")
        try:
            subprocess.run(
                [sys.executable, "-m", "edge_tts", "--voice", DEFAULT_VOICE,
                 "--text", "sinov", "--write-media", out],
                check=True, timeout=25, capture_output=True,
            )
            info["generated"] = os.path.exists(out) and os.path.getsize(out) > 0
            if not info["generated"]:
                info["error"] = "fayl yaratilmadi (internet yopiq bo'lishi mumkin)"
        except Exception as exc:  # noqa: BLE001
            info["error"] = f"generatsiya xatosi: {str(exc)[:300]}"

    info["ok"] = info["generated"] and info["cache_dir_writable"]
    return JsonResponse(info)


# --------------------------------------------------------------------------
# REST API
# --------------------------------------------------------------------------
class VisitViewSet(viewsets.ModelViewSet):
    serializer_class = VisitSerializer
    permission_classes = [DenyWriteForReadOnlyRoles, HasRoleForWrite]
    write_roles = WRITE_ROLES + (Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR, Role.Code.NURSE)
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = {"status": ["exact"], "visit_date": ["exact", "gte", "lte"],
                        "patient": ["exact"], "doctor": ["exact"]}
    ordering_fields = ["visit_date", "queue_number"]

    def get_queryset(self) -> Any:
        return Visit.objects.select_related("patient", "doctor").order_by(
            "-visit_date", "queue_number"
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = VisitCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visit = serializer.save()
        return Response(VisitSerializer(visit).data, status=http_status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def transition(self, request: Request, pk: str | None = None) -> Response:
        """Status o'tkazish: {"status": "accepted", "reason": ""}."""
        serializer = VisitTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        visit = services.visit_transition(
            visit=self.get_object(),
            new_status=serializer.validated_data["status"],
            reason=serializer.validated_data["reason"],
        )
        return Response(VisitSerializer(visit).data)

    @action(detail=False, methods=["get"])
    def today(self, request: Request) -> Response:
        """Bugungi navbat."""
        qs = selectors.visits_today(status=request.query_params.get("status", ""))
        page = self.paginate_queryset(qs)
        serializer = VisitSerializer(page or qs, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [DenyWriteForReadOnlyRoles, HasRoleForWrite]
    write_roles = WRITE_ROLES
    http_method_names = ["get", "post", "head", "options"]
    filterset_fields = {"status": ["exact"], "doctor": ["exact"], "patient": ["exact"]}

    def get_queryset(self) -> Any:
        from apps.registration.models import Appointment

        return Appointment.objects.select_related("patient", "doctor").order_by(
            "-scheduled_at"
        )

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = AppointmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        appointment = serializer.save()
        return Response(
            AppointmentSerializer(appointment).data, status=http_status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def arrive(self, request: Request, pk: str | None = None) -> Response:
        """Bemor keldi → qabul ochish."""
        visit = services.visit_from_appointment(appointment=self.get_object())
        return Response(VisitSerializer(visit).data, status=http_status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def set_status(self, request: Request, pk: str | None = None) -> Response:
        """Status o'zgartirish: {"status": "confirmed"}."""
        appointment = services.appointment_set_status(
            appointment=self.get_object(),
            new_status=request.data.get("status", ""),
        )
        return Response(AppointmentSerializer(appointment).data)
