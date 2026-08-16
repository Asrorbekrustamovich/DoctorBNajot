"""Tekshiruv guruhlariga STANDART mas'ul biriktirish.

MUAMMO: biriktirish har bir xizmatda alohida qilingan va izchil emas
bo'lib qolgan. Masalan «Funksional diagnostika» guruhi ichida uchta
xizmat uch xil odamga tegishli edi: biri Radiologiyaga, biri
Shifokorga, biri Jarrohlik ma'muriga. Yangi xizmat qo'shilganda esa
umuman biriktirilmay qolardi va u hech kimning ro'yxatida ko'rinmasdi.

YECHIM: guruh darajasida standart mas'ul. Xizmatda alohida ko'rsatilgan
bo'lsa — o'sha ustun turadi; ko'rsatilmagan bo'lsa guruhdagisi ishlaydi.
Shunda yangi xizmat ham avtomatik egasiz qolmaydi.

DIQQAT: bu faqat STANDART qiymat. Superadmin «Xizmatlar sozlamalari»
sahifasidan istalgan tekshiruvni aniq xodimga biriktira oladi —
masalan EKG ni kardiologga.
"""
from django.db import migrations

# guruh nomi -> standart rol kodi
DEFAULTS = {
    "Laboratoriya": "laboratory",
    "EKG": "radiology",
    "UZI": "radiology",
    "Rentgen": "radiology",
    "Endoskopiya": "doctor",
    "Funksional diagnostika": "radiology",
}


def forward(apps, schema_editor):
    ServiceCategory = apps.get_model("clinical", "ServiceCategory")
    Role = apps.get_model("accounts", "Role")

    for name, role_code in DEFAULTS.items():
        role = Role.objects.filter(code=role_code).first()
        if role is None:
            continue
        # Faqat bo'sh bo'lsa to'ldiramiz — qo'lda qilingan sozlamani buzmaymiz
        for cat in ServiceCategory.objects.filter(name=name, default_role__isnull=True):
            cat.default_role = role
            cat.save(update_fields=["default_role"])
            # Ichki guruhlar ham (Klinik tahlillar, Gormonlar…)
            ServiceCategory.objects.filter(
                parent=cat, default_role__isnull=True
            ).update(default_role=role)


def backward(apps, schema_editor):
    ServiceCategory = apps.get_model("clinical", "ServiceCategory")
    ServiceCategory.objects.update(default_role=None)


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0037_dischargesummary_item_texts_and_more"),
        ("accounts", "0006_backfill_is_ambulatory"),
    ]
    operations = [migrations.RunPython(forward, backward)]
