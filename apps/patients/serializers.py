"""Patients DRF serializerlari."""
from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.patients.models import Patient


class PatientSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(read_only=True)

    class Meta:
        model = Patient
        fields = [
            "id", "card_number", "full_name", "last_name", "first_name",
            "middle_name", "birth_date", "age", "gender", "phone", "passport",
            "jshshir", "address", "relative_name", "relative_phone",
            "insurance_company", "insurance_number", "notes", "created_at",
        ]
        read_only_fields = ["id", "card_number", "full_name", "age", "created_at"]


class PatientWriteSerializer(serializers.Serializer):
    """patient_create/patient_update service kirishi."""

    last_name = serializers.CharField(max_length=100)
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    birth_date = serializers.DateField()
    gender = serializers.ChoiceField(choices=Patient.Gender.choices)
    phone = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    passport = serializers.CharField(max_length=9, required=False, allow_blank=True, allow_null=True, default=None)
    jshshir = serializers.CharField(max_length=14, required=False, allow_blank=True, allow_null=True, default=None)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    relative_name = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    relative_phone = serializers.CharField(max_length=16, required=False, allow_blank=True, default="")
    insurance_company = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    insurance_number = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    allow_duplicate = serializers.BooleanField(required=False, default=False, write_only=True)

    def create(self, validated_data: dict[str, Any]) -> Patient:
        from apps.patients.services import patient_create

        return patient_create(**validated_data)

    def update(self, instance: Patient, validated_data: dict[str, Any]) -> Patient:
        from apps.patients.services import patient_update

        validated_data.pop("allow_duplicate", None)
        return patient_update(patient=instance, **validated_data)
