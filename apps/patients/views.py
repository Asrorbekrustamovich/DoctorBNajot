"""Patients view'lari: web (HTMX) + REST API."""
from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DetailView, ListView, UpdateView
from rest_framework import status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts.models import Role
from apps.accounts.permissions import (
    DenyWriteForReadOnlyRoles,
    HasRoleForWrite,
    RoleRequiredMixin,
)
from apps.core.exceptions import DomainError
from apps.patients import selectors, services
from apps.patients.forms import PatientForm
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer, PatientWriteSerializer

WRITE_ROLES = (
    Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
)
VIEW_ROLES = WRITE_ROLES + (
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, *Role.DOCTOR_ROLES,
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.CASHIER,
    Role.Code.ACCOUNTANT, Role.Code.AUDITOR, Role.Code.VIEWER,
    Role.Code.LAB, Role.Code.RADIOLOGY,
)


# --------------------------------------------------------------------------
# Web (HTMX)
# --------------------------------------------------------------------------
class PatientListView(RoleRequiredMixin, ListView):
    allowed_roles = VIEW_ROLES
    model = Patient
    paginate_by = 25
    template_name = "patients/list.html"
    context_object_name = "patients"

    def get_queryset(self) -> Any:
        return selectors.patient_list(search=self.request.GET.get("q", ""))

    def get_template_names(self) -> list[str]:
        if getattr(self.request, "htmx", False):
            return ["patients/_table.html"]
        return [self.template_name]

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'excel':
            from apps.core.exports import export_queryset_to_excel
            qs = self.get_queryset()
            columns = [
                ("Karta raqami", "card_number"),
                ("F.I.SH.", "full_name"),
                ("Tug'ilgan sana", "birth_date"),
                ("Jinsi", "get_gender_display"),
                ("Telefon", "phone_number"),
                ("Manzil", "address"),
                ("Ro'yxatdan o'tgan sana", "created_at"),
            ]
            return export_queryset_to_excel(qs, columns, "Bemorlar_Royxati")
        return super().get(request, *args, **kwargs)


class PatientDetailView(RoleRequiredMixin, DetailView):
    allowed_roles = VIEW_ROLES
    model = Patient
    template_name = "patients/detail.html"
    context_object_name = "patient"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # «Operatsiyaga yozish» oynasi jarrohlik panelidagi bilan bir xil
        # to'liqlikda bo'lishi uchun umumiy kontekstdan olinadi
        # (jamoa: asistent, anesteziolog, hamshiralar + operatsion xona).
        from apps.clinical.views import surgery_team_context
        context.update(surgery_team_context())
        return context


class PatientCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = WRITE_ROLES
    form_class = PatientForm
    template_name = "patients/form.html"

    def form_valid(self, form: PatientForm) -> Any:
        from django.db import IntegrityError

        try:
            self.object = services.patient_create(
                **form.cleaned_data,
                allow_duplicate=self.request.POST.get("allow_duplicate") == "1",
            )
        except DomainError as exc:
            form.add_error(None, exc.message)
            if exc.code == "duplicate_suspected":
                form.duplicate_suspected = True  # template tasdiq checkboxini ko'rsatadi
            return self.form_invalid(form)
        except IntegrityError as exc:
            # OXIRGI HIMOYA. Formadagi tekshiruvlar asosiy holatlarni
            # ushlaydi, lekin ikki xodim bir vaqtda bir xil JSHSHIR bilan
            # saqlasa, tekshiruv bilan yozish orasida poyga bo'ladi.
            # Bunda ham foydalanuvchi 500 sahifani emas, tushunarli
            # xabarni ko'rishi kerak.
            form.add_error(None,
                           "Bu ma'lumot bilan bemor allaqachon ro'yxatga olingan. "
                           "JSHSHIR yoki pasportni tekshiring. "
                           f"({str(exc)[:120]})")
            return self.form_invalid(form)
        messages.success(self.request, f"Bemor yaratildi: {self.object}")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        return reverse_lazy("patients:detail", kwargs={"pk": self.object.pk})


class PatientUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = WRITE_ROLES
    model = Patient
    form_class = PatientForm
    template_name = "patients/form.html"

    def form_valid(self, form: PatientForm) -> Any:
        from django.db import IntegrityError

        try:
            services.patient_update(patient=self.object, **form.cleaned_data)
        except DomainError as exc:
            form.add_error(None, exc.message)
            return self.form_invalid(form)
        except IntegrityError as exc:
            form.add_error(None,
                           "Bu JSHSHIR yoki pasport boshqa bemorda band. "
                           f"({str(exc)[:120]})")
            return self.form_invalid(form)
        messages.success(self.request, "Bemor ma'lumotlari yangilandi.")
        return super().form_valid(form)

    def get_success_url(self) -> str:
        return reverse_lazy("patients:detail", kwargs={"pk": self.object.pk})


# --------------------------------------------------------------------------
# REST API
# --------------------------------------------------------------------------
class PatientViewSet(viewsets.ModelViewSet):
    serializer_class = PatientSerializer
    permission_classes = [DenyWriteForReadOnlyRoles, HasRoleForWrite]
    write_roles = WRITE_ROLES
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    filterset_fields = {"gender": ["exact"], "birth_date": ["gte", "lte"]}
    search_fields = ["card_number", "last_name", "first_name", "phone", "jshshir", "passport"]
    ordering_fields = ["last_name", "created_at", "birth_date"]

    def get_queryset(self) -> Any:
        return selectors.patient_list(search=self.request.query_params.get("q", ""))

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PatientWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        patient = serializer.save()
        return Response(PatientSerializer(patient).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = PatientWriteSerializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        patient = serializer.save()
        return Response(PatientSerializer(patient).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.patient_delete(patient=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)
