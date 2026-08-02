"""Patients admin."""
from __future__ import annotations

from django.contrib import admin

from apps.patients.models import Patient


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("card_number", "full_name", "birth_date", "age", "gender",
                    "phone", "jshshir", "created_at")
    list_filter = ("gender", "is_deleted", "created_at")
    search_fields = ("card_number", "last_name", "first_name", "middle_name",
                     "phone", "jshshir", "passport")
    readonly_fields = ("card_number", "created_at", "updated_at",
                       "created_by", "updated_by", "deleted_at", "deleted_by")
    date_hierarchy = "created_at"
    list_per_page = 50
    fieldsets = (
        ("Shaxsiy", {"fields": ("card_number", "last_name", "first_name", "middle_name",
                                 "birth_date", "gender", "phone", "passport", "jshshir",
                                 "address")}),
        ("Qarindosh", {"fields": ("relative_name", "relative_phone")}),
        ("Sug'urta", {"fields": ("insurance_company", "insurance_number")}),
        ("Boshqa", {"fields": ("notes",)}),
        ("Meta", {"fields": ("created_at", "updated_at", "created_by", "updated_by",
                              "deleted_at", "deleted_by"), "classes": ("collapse",)}),
    )

    @admin.display(description="FIO")
    def full_name(self, obj: Patient) -> str:
        return obj.full_name

    @admin.display(description="Yosh")
    def age(self, obj: Patient) -> int:
        return obj.age

    def get_queryset(self, request):  # type: ignore[no-untyped-def]
        return Patient.all_objects.all()
