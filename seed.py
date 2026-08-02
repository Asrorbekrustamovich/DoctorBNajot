import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
django.setup()

from django.contrib.auth import get_user_model
from apps.accounts.models import Role
from apps.clinical.models import ServiceCatalog

User = get_user_model()


def seed_roles():
    roles_data = [
        ("director", "Direktor", "Klinika rahbari"),
        ("chief_doctor", "Bosh shifokor", "Bosh shifokor"),
        ("administrator", "Qabulxona (Admin)", "Mijozlarni qabul qilish"),
        ("cashier", "Kassir", "To'lovlarni qabul qilish"),
        ("doctor", "Shifokor", "Bemorlarni ko'rikdan o'tkazish"),
        ("nurse", "Hamshira", "Muolajalar va statsionar"),
        ("ward_nurse", "Palata hamshirasi", "Palatalarda parvarish"),
        ("lab", "Laborant", "Tahlillarni o'tkazish"),
        ("radiology", "Radiologiya", "Rentgen va UZI"),
        ("pharmacy", "Farmatsevt", "Dori va farmatsevtika"),
        ("warehouse", "Ombor mudiri", "Dori va jihozlar ombori"),
        ("surgeon", "Jarroh shifokor", "Operatsiyalarni o'tkazish"),
        ("surgery_admin", "Jarrohlik bo'limi administratori", "Jarrohlik jarayonlarini boshqarish"),
        ("sterilization", "Sterilizatsiya (Avtoklav)", "Asboblarni sterilizatsiya qilish"),
        ("accountant", "Buxgalter", "Moliyaviy hisobotlar"),
        ("super_admin", "Super Admin", "Tizimning to'liq huquqi"),
        ("auditor", "Auditor (faqat ko'rish)", "Faqat ko'rish huquqi"),
    ]
    for code, name, desc in roles_data:
        role, created = Role.objects.get_or_create(code=code, defaults={"name": name, "description": desc})
        if created:
            print(f"  Rol yaratildi: {name}")
    print("Rollar tayyor.")


def seed_users():
    director_role = Role.objects.get(code="director")
    if not User.objects.filter(username="admin").exists():
        user = User.objects.create_superuser("admin", "admin@edumed.com", "admin123")
        user.first_name = "Super"
        user.last_name = "Admin"
        user.role = director_role
        user.save()
        print("  Superuser yaratildi: admin / admin123")

    cashier_role = Role.objects.get(code="cashier")
    if not User.objects.filter(username="kassir").exists():
        user = User.objects.create_user("kassir", "kassir@edumed.com", "admin123")
        user.first_name = "Test"
        user.last_name = "Kassir"
        user.role = cashier_role
        user.save()
        print("  Kassir yaratildi: kassir / admin123")

    doctor_role = Role.objects.get(code="doctor")
    if not User.objects.filter(username="dr_karimov").exists():
        user = User.objects.create_user("dr_karimov", "karimov@edumed.com", "admin123")
        user.first_name = "Bobur"
        user.last_name = "Karimov"
        user.middle_name = "Aliyevich"
        user.role = doctor_role
        user.specialty = "Terapevt"
        user.phone = "+998901234567"
        user.save()
        print("  Shifokor yaratildi: dr_karimov / admin123")

    print("Foydalanuvchilar tayyor.")


def seed_services():
    """Klinikadagi asosiy xizmatlarni narxlari bilan kiritish."""

    lab_role = Role.objects.filter(code="lab").first()
    radio_role = Role.objects.filter(code="radiology").first()
    doctor_role = Role.objects.filter(code="doctor").first()

    services = [
        # ── SHIFOKOR QABULLARI ──────────────────────────────────────
        ("Terapevt qabuli", 50_000, doctor_role),
        ("Kardiolog qabuli", 80_000, doctor_role),
        ("Nevropatolog qabuli", 80_000, doctor_role),
        ("Endokrinolog qabuli", 80_000, doctor_role),
        ("Gastroenterolog qabuli", 80_000, doctor_role),
        ("Urolog qabuli", 80_000, doctor_role),
        ("Ginekolog qabuli", 80_000, doctor_role),
        ("Oftalmolog (Ko'z shifokori) qabuli", 70_000, doctor_role),
        ("LOR (Quloq-burun-tomoq) qabuli", 70_000, doctor_role),
        ("Dermatolog qabuli", 70_000, doctor_role),
        ("Pediatr qabuli (Bola shifokori)", 60_000, doctor_role),
        ("Ortoped-Travmatolog qabuli", 90_000, doctor_role),
        ("Psixiatr qabuli", 90_000, doctor_role),
        ("Allergolog qabuli", 80_000, doctor_role),
        ("Onkolog qabuli", 100_000, doctor_role),
        ("Revmatolog qabuli", 80_000, doctor_role),
        ("Nefrologiya qabuli", 80_000, doctor_role),
        ("Pulmonolog qabuli", 80_000, doctor_role),

        # ── UZI (Ultratovush tekshiruvi) ─────────────────────────────
        ("UZI — Qorin bo'shlig'i a'zolari", 70_000, radio_role),
        ("UZI — Buyraklar va siydik yo'llari", 70_000, radio_role),
        ("UZI — Jigar va o't pufagi", 60_000, radio_role),
        ("UZI — Oshqozon osti bezi", 60_000, radio_role),
        ("UZI — Qalqonsimon bez", 60_000, radio_role),
        ("UZI — Ko'krak bezlari", 70_000, radio_role),
        ("UZI — Yurak (EchoCG — EKhoKG)", 100_000, radio_role),
        ("UZI — Qon tomirlar (USDG)", 80_000, radio_role),
        ("UZI — Bachadon va tuxumdonlar", 70_000, radio_role),
        ("UZI — Homiladorlik (obstetrik)", 80_000, radio_role),
        ("UZI — Prostat bezi", 60_000, radio_role),
        ("UZI — Bo'g'imlar", 60_000, radio_role),

        # ── EKG (Elektrokardiografiya) ────────────────────────────────
        ("EKG — Elektrokardiogramma (tinch holatda)", 40_000, radio_role),
        ("EKG — Holter monitoringi (24 soat)", 150_000, radio_role),
        ("EKG — Stress-test (Veloergometriya)", 120_000, radio_role),

        # ── RENTGEN ─────────────────────────────────────────────────
        ("Rentgen — Ko'krak qafasi (2 proyeksiya)", 50_000, radio_role),
        ("Rentgen — Qo'l/oyoq suyaklari", 45_000, radio_role),
        ("Rentgen — Umurtqa pog'onasi", 55_000, radio_role),
        ("Rentgen — Bosh suyagi", 50_000, radio_role),
        ("Rentgen — Bo'g'imlar", 45_000, radio_role),
        ("Flyurografiya (ko'krak tekshiruvi)", 25_000, radio_role),

        # ── QON TAHLILLARI ───────────────────────────────────────────
        ("Umumiy qon tahlili (KLA)", 30_000, lab_role),
        ("Biokimyoviy qon tahlili (to'liq)", 80_000, lab_role),
        ("Qon glyukozasi (shakar)", 20_000, lab_role),
        ("Qon guruhi va Rh-omil", 25_000, lab_role),
        ("Tireoid gormonlar (TSH, T3, T4)", 120_000, lab_role),
        ("Jinsiy gormonlar (FSH, LH, Prolaktin va b.)", 150_000, lab_role),
        ("Koagulogramma (qon ivishi)", 60_000, lab_role),
        ("Kolesterol, HDL, LDL, Triglitseridlar", 50_000, lab_role),
        ("Ferritin, Temir, TIBC", 60_000, lab_role),
        ("Vitamin D (25-OH)", 90_000, lab_role),
        ("Vitamin B12 va Folat kislota", 80_000, lab_role),
        ("PSA (Prostat spetsifik antigen)", 70_000, lab_role),
        ("CA-125 (Onkomarker)", 80_000, lab_role),
        ("CEA (Onkomarker)", 75_000, lab_role),
        ("HbA1c (Glikozillangan gemoglobin)", 60_000, lab_role),
        ("Insulin darajasi", 70_000, lab_role),
        ("Gepatit B (HBsAg)", 40_000, lab_role),
        ("Gepatit C (anti-HCV)", 40_000, lab_role),
        ("OIV (OITS) tekshiruvi", 40_000, lab_role),
        ("Zaxm (Sifilis/RW)", 35_000, lab_role),
        ("C-reaktiv oqsil (CRP)", 40_000, lab_role),
        ("Revmatoid faktor (RF)", 40_000, lab_role),

        # ── SIYDIK TAHLILLARI ────────────────────────────────────────
        ("Umumiy siydik tahlili (OAM)", 20_000, lab_role),
        ("Siydik nechi'da", 30_000, lab_role),
        ("Siydikda bakteriya ekishi (bakposev)", 50_000, lab_role),

        # ── BOSHQA PROTSEDURALAR ─────────────────────────────────────
        ("Spirometriya (o'pka funksiyasi)", 60_000, None),
        ("Kapsulali endoskopiya maslahati", 50_000, doctor_role),
        ("FGDS (Fibroezofagogastroduodenoskopiya)", 150_000, doctor_role),
        ("Kolonoskopiya", 200_000, doctor_role),
        ("Kolposkopiya", 100_000, doctor_role),
        ("Elektroensefalografiya (EEG)", 100_000, radio_role),
        ("Audiometriya (Eshitish tekshiruvi)", 50_000, None),
        ("Tonometriya (Ko'z bosimi)", 30_000, doctor_role),
        ("Kapillyaroskopiya", 60_000, doctor_role),
    ]

    created_count = 0
    for name, price, role in services:
        obj, created = ServiceCatalog.objects.get_or_create(
            name=name,
            defaults={"price": price, "allowed_role": role, "is_active": True}
        )
        if created:
            created_count += 1

    print(f"Xizmatlar tayyor: {created_count} ta yangi xizmat qo'shildi (jami {ServiceCatalog.objects.count()} ta).")


if __name__ == "__main__":
    print("=" * 50)
    print("Ma'lumotlar bazasi to'ldirilmoqda...")
    print("=" * 50)
    seed_roles()
    seed_users()
    seed_services()
    print("=" * 50)
    print("Hammasi tayyor!")
