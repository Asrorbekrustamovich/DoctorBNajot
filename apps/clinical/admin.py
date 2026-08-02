"""Clinical admin — operatsiya boshqaruvi (xonalar, anesteziolog ombori va h.k.)."""
from __future__ import annotations

from django.contrib import admin

from apps.clinical.models import (
    AnesthesiaRequest,
    AnesthesiaRequestItem,
    AnesthesiaStock,
    NurseUsageItem,
    OperatingRoom,
    SurgerySchedule,
    SurgeryType,
    SurgeryVitals,
)


@admin.register(OperatingRoom)
class OperatingRoomAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    list_editable = ("is_active",)


@admin.register(AnesthesiaStock)
class AnesthesiaStockAdmin(admin.ModelAdmin):
    list_display = ("name", "quantity", "unit", "selling_price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    list_editable = ("quantity", "selling_price", "is_active")
    fields = ("name", "unit", "quantity", "selling_price", "is_active")


@admin.register(SurgeryType)
class SurgeryTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class AnesthesiaRequestItemInline(admin.TabularInline):
    model = AnesthesiaRequestItem
    extra = 0
    autocomplete_fields = ("stock",)
    readonly_fields = ("price_snapshot",)


@admin.register(AnesthesiaRequest)
class AnesthesiaRequestAdmin(admin.ModelAdmin):
    list_display = ("surgery", "status", "sent_at", "sent_by")
    list_filter = ("status",)
    inlines = [AnesthesiaRequestItemInline]
    readonly_fields = ("sent_at", "sent_by", "requested_by")


class SurgeryVitalsInline(admin.TabularInline):
    model = SurgeryVitals
    extra = 0
    readonly_fields = ("recorded_at", "recorded_by")


class NurseUsageItemInline(admin.TabularInline):
    model = NurseUsageItem
    extra = 0


@admin.register(SurgerySchedule)
class SurgeryScheduleAdmin(admin.ModelAdmin):
    list_display = (
        "visit", "surgery_type", "surgeon", "operating_room",
        "scheduled_time", "status", "stage",
    )
    list_filter = ("status", "stage", "operating_room")
    search_fields = ("visit__patient__last_name", "visit__patient__first_name")
    autocomplete_fields = ("visit", "surgery_type")
    inlines = [SurgeryVitalsInline, NurseUsageItemInline]
    fieldsets = (
        ("Asosiy", {"fields": ("visit", "surgery_type", "scheduled_time",
                               "operating_room", "status", "stage", "actual_price")}),
        ("Jamoa", {"fields": ("surgeon", "assistant", "anesthesiologist", "operating_nurse")}),
        ("Bosqichlar", {"fields": ("anesthesia_exam_note", "anesthesia_exam_at",
                                    "preparation_note", "preparation_at", "room_prepared",
                                    "started_at", "finished_at", "notes"),
                        "classes": ("collapse",)}),
    )
