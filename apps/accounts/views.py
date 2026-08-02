"""Accounts view'lari: web login/logout + REST API."""
from __future__ import annotations

from typing import Any

from django.contrib.auth import views as auth_views
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from apps.accounts import selectors, services
from apps.accounts.forms import LoginForm
from apps.accounts.models import Role, User
from apps.accounts.permissions import (
    DenyWriteForReadOnlyRoles,
    HasRole,
    IsSuperAdmin,
)
from apps.accounts.serializers import (
    ChangePasswordSerializer,
    RoleSerializer,
    SetRoleSerializer,
    UserCreateSerializer,
    UserSerializer,
    UserUpdateSerializer,
)


class LoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True


class LogoutView(auth_views.LogoutView):
    next_page = "accounts:login"


class RoleViewSet(viewsets.ReadOnlyModelViewSet):
    """Rollar ro'yxati (faqat o'qish; rollar seed orqali boshqariladi)."""

    serializer_class = RoleSerializer
    permission_classes = [DenyWriteForReadOnlyRoles]

    def get_queryset(self) -> Any:
        return selectors.role_list()


class UserViewSet(viewsets.ModelViewSet):
    """Xodimlarni boshqarish. Yozish amallari service layer orqali."""

    serializer_class = UserSerializer
    permission_classes = [DenyWriteForReadOnlyRoles, HasRole]
    allowed_roles = (Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.DIRECTOR)
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    search_fields = ["username", "first_name", "last_name", "phone"]
    ordering_fields = ["last_name", "date_joined"]
    filterset_fields = {"is_active": ["exact"], "role__code": ["exact"]}

    def get_queryset(self) -> Any:
        return selectors.user_list()

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        instance = self.get_object()
        serializer = UserUpdateSerializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        services.user_deactivate(user=self.get_object())
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def set_role(self, request: Request, pk: str | None = None) -> Response:
        """Userga rol biriktirish (faqat Super Admin)."""
        serializer = SetRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = services.user_set_role(
            user=self.get_object(), role=serializer.validated_data["role"]
        )
        return Response(UserSerializer(user).data)

    @action(detail=True, methods=["post"], permission_classes=[IsSuperAdmin])
    def change_password(self, request: Request, pk: str | None = None) -> Response:
        """Parolni majburiy almashtirish (faqat Super Admin)."""
        serializer = ChangePasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.user_change_password(
            user=self.get_object(),
            new_password=serializer.validated_data["new_password"],
        )
        return Response({"detail": "Parol yangilandi."})

    @action(detail=False, methods=["get"], permission_classes=[DenyWriteForReadOnlyRoles])
    def me(self, request: Request) -> Response:
        """Joriy user profili — barcha rollar uchun ochiq."""
        return Response(UserSerializer(request.user).data)
