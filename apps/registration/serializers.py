"""Registration DRF serializerlari."""
from __future__ import annotations

from typing import Any

from django.db.models import Q, QuerySet
from rest_framework import serializers

from apps.accounts.models import User
from apps.accounts.serializers import UserSerializer
from apps.patients.models import Patient
from apps.patients.serializers import PatientSerializer
from apps.registration.models import Appointment, Visit


def _doctors_qs() -> QuerySet[User]:
    return User.objects.filter(
        Q(role__code="doctor") | Q(role__code="chief_doctor"),
        Q(specialty__icontains="ambulator") | Q(specialty__icontains="amblator"),
        is_active=True
    )


class VisitSerializer(serializers.ModelSerializer):
    patient = PatientSerializer(read_only=True)
    doctor = UserSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Visit
        fields = [
            "id", "patient", "doctor", "appointment", "visit_date", "queue_number",
            "complaint", "referral", "preliminary_diagnosis", "status",
            "status_display", "cancel_reason", "accepted_at", "completed_at",
            "created_at",
        ]
        read_only_fields = fields


class VisitCreateSerializer(serializers.Serializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        queryset=Patient.objects.all(), source="patient"
    )
    doctor_id = serializers.PrimaryKeyRelatedField(
        queryset=_doctors_qs(), source="doctor",
        required=False, allow_null=True, default=None,
    )
    complaint = serializers.CharField(required=False, allow_blank=True, default="")
    referral = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    preliminary_diagnosis = serializers.CharField(
        max_length=255, required=False, allow_blank=True, default=""
    )

    def create(self, validated_data: dict[str, Any]) -> Visit:
        from apps.registration.services import visit_create

        return visit_create(**validated_data)

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError


class VisitTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Visit.Status.choices)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def create(self, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError


class AppointmentSerializer(serializers.ModelSerializer):
    patient = PatientSerializer(read_only=True)
    doctor = UserSerializer(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Appointment
        fields = [
            "id", "patient", "doctor", "scheduled_at", "duration_minutes",
            "reason", "status", "status_display", "notes", "created_at",
        ]
        read_only_fields = fields


class AppointmentCreateSerializer(serializers.Serializer):
    patient_id = serializers.PrimaryKeyRelatedField(
        queryset=Patient.objects.all(), source="patient"
    )
    doctor_id = serializers.PrimaryKeyRelatedField(
        queryset=_doctors_qs(), source="doctor"
    )
    scheduled_at = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField(min_value=5, max_value=240, default=15)
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")

    def create(self, validated_data: dict[str, Any]) -> Appointment:
        from apps.registration.services import appointment_create

        return appointment_create(**validated_data)

    def update(self, instance: Any, validated_data: dict[str, Any]) -> Any:
        raise NotImplementedError
