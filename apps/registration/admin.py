"""Registration admin."""
from __future__ import annotations

from django.contrib import admin

from apps.registration.models import Appointment, Visit


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("queue_number", "patient", "doctor", "visit_date", "status",
                    "accepted_at", "completed_at")
    list_filter = ("status", "visit_date")
    search_fields = ("patient__last_name", "patient__first_name",
                     "patient__card_number", "queue_number")
    readonly_fields = ("queue_number", "visit_date", "accepted_at", "completed_at",
                       "created_at", "updated_at", "created_by", "updated_by")
    date_hierarchy = "visit_date"
    autocomplete_fields = ("patient",)
    list_per_page = 50


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("patient", "doctor", "scheduled_at", "duration_minutes", "status")
    list_filter = ("status", "scheduled_at", "doctor")
    search_fields = ("patient__last_name", "patient__card_number")
    date_hierarchy = "scheduled_at"
    autocomplete_fields = ("patient",)
