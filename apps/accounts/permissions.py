"""RBAC permission sinflari (DRF va view mixinlari)."""
from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import UserPassesTestMixin
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class DenyWriteForReadOnlyRoles(BasePermission):
    """Auditor/Viewer rollariga faqat SAFE (GET/HEAD/OPTIONS) metodlar."""

    message = "Sizning rolingiz faqat ko'rish huquqiga ega."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        return not getattr(user, "is_read_only", False)


class HasRole(BasePermission):
    """View'dagi `allowed_roles` ro'yxatiga qarab tekshiradi.

    class MyView(APIView):
        permission_classes = [HasRole]
        allowed_roles = [Role.Code.RECEPTION, Role.Code.ADMINISTRATOR]

    Superuser doim o'tadi.
    """

    message = "Bu bo'lim sizning rolingiz uchun ochiq emas."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        allowed: tuple[str, ...] = tuple(getattr(view, "allowed_roles", ()))
        if not allowed:
            return True
        return user.has_role(*allowed)


class HasRoleForWrite(BasePermission):
    """SAFE metodlar hammaga (autentifikatsiyalangan), yozish — `write_roles` ga.

    class PatientViewSet(...):
        permission_classes = [DenyWriteForReadOnlyRoles, HasRoleForWrite]
        write_roles = ("reception", "administrator", "super_admin")
    """

    message = "Bu amal sizning rolingiz uchun ruxsat etilmagan."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS or user.is_superuser:
            return True
        write_roles: tuple[str, ...] = tuple(getattr(view, "write_roles", ()))
        if not write_roles:
            return True
        return user.has_role(*write_roles)


class IsSuperAdmin(BasePermission):
    """Faqat superuser yoki Super Admin roli."""

    message = "Faqat Super Admin uchun."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = request.user
        return bool(
            user
            and user.is_authenticated
            and (user.is_superuser or user.has_role("super_admin"))
        )


def role_required(*codes: str):
    """Funksiya-view'lar uchun rol tekshiruvi dekoratori.

    @role_required(*Role.DOCTOR_ROLES, Role.Code.CHIEF_DOCTOR)
    def my_view(request, ...): ...

    Superuser doim o'tadi. HTMX so'rovlarga alert, oddiylariga redirect.
    """
    from functools import wraps

    from django.contrib import messages
    from django.http import HttpResponse
    from django.shortcuts import redirect

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            user = request.user
            # SUPER_ADMIN roli — to'liq nazorat: superuser kabi hamma joydan o'tadi
            allowed = user.is_authenticated and (
                user.is_superuser
                or user.has_role("super_admin")
                or not codes
                or user.has_role(*codes)
            )
            if allowed:
                return view_func(request, *args, **kwargs)
            if request.headers.get("HX-Request"):
                return HttpResponse(
                    "<div class='alert alert-danger'>Bu amal sizning "
                    "rolingiz uchun ruxsat etilmagan.</div>"
                )
            messages.error(request, "Bu amal sizning rolingiz uchun ruxsat etilmagan.")
            return redirect("core:home" if user.is_authenticated else "accounts:login")

        return _wrapped

    return decorator


class RoleRequiredMixin(UserPassesTestMixin):
    """Template view'lar uchun rol tekshiruvi.

    class WardListView(RoleRequiredMixin, ListView):
        allowed_roles = ("reception", "administrator")
    """

    allowed_roles: tuple[str, ...] = ()
    permission_denied_message = "Bu bo'lim sizning rolingiz uchun ochiq emas."

    def test_func(self) -> bool:
        user: Any = self.request.user  # type: ignore[attr-defined]
        if not user.is_authenticated:
            return False
        # SUPER_ADMIN roli — to'liq nazorat
        if user.is_superuser or user.has_role("super_admin"):
            return True
        if not self.allowed_roles:
            return True
        return user.has_role(*self.allowed_roles)
