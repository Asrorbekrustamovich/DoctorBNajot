"""Accounts admin — professional sozlangan."""
from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.http import HttpRequest

from apps.accounts.models import Role, User


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "is_read_only", "user_count", "created_at")
    list_filter = ("is_read_only",)
    search_fields = ("name", "code")
    filter_horizontal = ("permissions",)
    readonly_fields = ("created_at", "updated_at", "created_by", "updated_by")
    fieldsets = (
        (None, {"fields": ("code", "name", "description", "is_read_only")}),
        ("Huquqlar", {"fields": ("permissions",)}),
        ("Meta", {"fields": ("created_at", "updated_at", "created_by", "updated_by"),
                  "classes": ("collapse",)}),
    )

    @admin.display(description="Userlar soni")
    def user_count(self, obj: Role) -> int:
        return obj.users.filter(is_active=True).count()

    def has_delete_permission(self, request: HttpRequest, obj: Role | None = None) -> bool:
        # Rollar o'chirilmaydi — userlar PROTECT bilan bog'langan
        return False


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    list_display = ("username", "get_full_name", "role", "phone", "is_active", "date_joined")
    list_filter = ("role", "is_active", "is_staff", "is_deleted")
    search_fields = ("username", "first_name", "last_name", "middle_name", "phone", "email")
    ordering = ("last_name", "first_name")
    autocomplete_fields = ()
    filter_horizontal = ("extra_roles",)
    readonly_fields = ("last_login", "date_joined", "deleted_at")
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Shaxsiy ma'lumot", {"fields": ("last_name", "first_name", "middle_name",
                                          "phone", "email", "avatar")}),
        ("Rol va huquqlar", {"fields": ("role", "extra_roles", "is_active",
                                         "is_staff", "is_superuser")}),
        ("Muhim sanalar", {"fields": ("last_login", "date_joined", "deleted_at"),
                            "classes": ("collapse",)}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "password1", "password2", "last_name",
                        "first_name", "middle_name", "phone", "role"),
        }),
    )

    def get_queryset(self, request: HttpRequest):  # type: ignore[no-untyped-def]
        # Adminda soft-deleted userlar ham ko'rinadi (tiklash imkoniyati uchun)
        return User.all_objects.select_related("role")
