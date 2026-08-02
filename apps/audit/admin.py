"""Audit jurnali admini — faqat o'qish uchun."""
from __future__ import annotations

from django.contrib import admin
from django.http import HttpRequest

from apps.audit.models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor_display", "action", "model_name", "object_repr", "ip_address")
    list_filter = ("action", "model_name", "created_at")
    search_fields = ("actor_display", "object_repr", "object_id", "ip_address")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    list_per_page = 50

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: AuditLog | None = None) -> bool:
        return False
