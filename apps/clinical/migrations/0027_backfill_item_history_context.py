"""Mavjud uskuna tarixiga bemor/jarroh ma'lumotini to'ldirish.

Eski yozuvlarda faqat "qachon" bor edi. Operatsiyaga bog'langan yozuvlar
uchun bemor, jarroh, operatsiya turi va xonani to'ldiramiz.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    SurgicalItemHistory = apps.get_model("clinical", "SurgicalItemHistory")
    qs = SurgicalItemHistory.objects.filter(surgery__isnull=False).select_related(
        "surgery__visit__patient", "surgery__surgeon",
        "surgery__surgery_type", "surgery__operating_room",
    )
    updated = []
    for h in qs:
        s = h.surgery
        patient = getattr(getattr(s, "visit", None), "patient", None)
        surgeon = s.surgeon
        h.patient_id = getattr(patient, "id", None)
        h.surgeon_id = getattr(surgeon, "id", None)
        if patient is not None:
            name = " ".join(
                p for p in [patient.last_name, patient.first_name,
                            getattr(patient, "middle_name", "")] if p
            ).strip()
            h.patient_snapshot = name[:200]
        if surgeon is not None:
            name = f"{surgeon.first_name} {surgeon.last_name}".strip() or surgeon.username
            h.surgeon_snapshot = name[:200]
        if s.surgery_type_id:
            h.surgery_snapshot = (s.surgery_type.name or "")[:200]
        if s.operating_room_id:
            h.room_snapshot = (s.operating_room.name or "")[:120]
        updated.append(h)

    if updated:
        SurgicalItemHistory.objects.bulk_update(
            updated,
            ["patient", "surgeon", "patient_snapshot", "surgeon_snapshot",
             "surgery_snapshot", "room_snapshot"],
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0026_surgicalitemhistory_patient_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
