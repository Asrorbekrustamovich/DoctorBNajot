"""Accounts DRF serializerlari."""
from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.accounts.models import Role, User


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "code", "name", "description", "is_read_only"]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    role = RoleSerializer(read_only=True)
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id", "username", "full_name", "first_name", "last_name",
            "middle_name", "phone", "email", "role", "is_active",
            "date_joined",
        ]
        read_only_fields = fields


class UserCreateSerializer(serializers.Serializer):
    """user_create service uchun kirish ma'lumotlari."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, min_length=8)
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", required=False, allow_null=True
    )
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")

    def create(self, validated_data: dict[str, Any]) -> User:
        from apps.accounts.services import user_create

        return user_create(**validated_data)

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError("Yangilash uchun UserUpdateSerializer ishlatiladi.")


class UserUpdateSerializer(serializers.Serializer):
    """user_update service uchun kirish ma'lumotlari."""

    first_name = serializers.CharField(max_length=150, required=False)
    last_name = serializers.CharField(max_length=150, required=False)
    middle_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=16, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)

    def create(self, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError

    def update(self, instance: User, validated_data: dict[str, Any]) -> User:
        from apps.accounts.services import user_update

        return user_update(user=instance, **validated_data)


class SetRoleSerializer(serializers.Serializer):
    role_id = serializers.PrimaryKeyRelatedField(
        queryset=Role.objects.all(), source="role", allow_null=True
    )

    def create(self, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError


class ChangePasswordSerializer(serializers.Serializer):
    new_password = serializers.CharField(write_only=True, min_length=8)

    def create(self, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError
