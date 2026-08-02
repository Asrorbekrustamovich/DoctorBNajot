"""Tibbiy xizmatlar katalogini to'ldirish (UZI, EKG, Rentgen, Tahlillar va b.)."""
from django.core.management.base import BaseCommand

from apps.accounts.models import Role
from apps.clinical.models import ServiceCatalog


SERVICES = [
    # ── SHIFOKOR QABULLARI ──────────────────────────────────────────────────
    ("Terapevt qabuli", 50_000, "doctor"),
    ("Kardiolog qabuli", 80_000, "doctor"),
    ("Nevropatolog qabuli", 80_000, "doctor"),
    ("Endokrinolog qabuli", 80_000, "doctor"),
    ("Gastroenterolog qabuli", 80_000, "doctor"),
    ("Urolog qabuli", 80_000, "doctor"),
    ("Ginekolog qabuli", 80_000, "doctor"),
    ("Oftalmolog (Ko'z shifokori) qabuli", 70_000, "doctor"),
    ("LOR (Quloq-burun-tomoq) qabuli", 70_000, "doctor"),
    ("Dermatolog qabuli", 70_000, "doctor"),
    ("Pediatr qabuli (Bola shifokori)", 60_000, "doctor"),
    ("Ortoped-Travmatolog qabuli", 90_000, "doctor"),
    ("Psixiatr qabuli", 90_000, "doctor"),
    ("Allergolog qabuli", 80_000, "doctor"),
    ("Onkolog qabuli", 100_000, "doctor"),
    ("Revmatolog qabuli", 80_000, "doctor"),
    ("Nefrologiya qabuli", 80_000, "doctor"),
    ("Pulmonolog qabuli", 80_000, "doctor"),

    # ── UZI (Ultratovush tekshiruvi) ─────────────────────────────────────────
    ("UZI — Qorin bo'shlig'i a'zolari", 70_000, "radiology"),
    ("UZI — Buyraklar va siydik yo'llari", 70_000, "radiology"),
    ("UZI — Jigar va o't pufagi", 60_000, "radiology"),
    ("UZI — Oshqozon osti bezi", 60_000, "radiology"),
    ("UZI — Qalqonsimon bez", 60_000, "radiology"),
    ("UZI — Ko'krak bezlari", 70_000, "radiology"),
    ("UZI — Yurak (EchoCG — EKhoKG)", 100_000, "radiology"),
    ("UZI — Qon tomirlar (USDG)", 80_000, "radiology"),
    ("UZI — Bachadon va tuxumdonlar", 70_000, "radiology"),
    ("UZI — Homiladorlik (obstetrik)", 80_000, "radiology"),
    ("UZI — Prostat bezi", 60_000, "radiology"),
    ("UZI — Bo'g'imlar", 60_000, "radiology"),

    # ── EKG (Elektrokardiografiya) ────────────────────────────────────────────
    ("EKG — Elektrokardiogramma (tinch holatda)", 40_000, "radiology"),
    ("EKG — Holter monitoringi (24 soat)", 150_000, "radiology"),
    ("EKG — Stress-test (Veloergometriya)", 120_000, "radiology"),

    # ── RENTGEN ──────────────────────────────────────────────────────────────
    ("Rentgen — Ko'krak qafasi (2 proyeksiya)", 50_000, "radiology"),
    ("Rentgen — Qo'l/oyoq suyaklari", 45_000, "radiology"),
    ("Rentgen — Umurtqa pog'onasi", 55_000, "radiology"),
    ("Rentgen — Bosh suyagi", 50_000, "radiology"),
    ("Rentgen — Bo'g'imlar", 45_000, "radiology"),
    ("Flyurografiya (ko'krak tekshiruvi)", 25_000, "radiology"),

    # ── QON TAHLILLARI ───────────────────────────────────────────────────────
    ("Umumiy qon tahlili (KLA)", 30_000, "lab"),
    ("Biokimyoviy qon tahlili (to'liq)", 80_000, "lab"),
    ("Qon glyukozasi (shakar)", 20_000, "lab"),
    ("Qon guruhi va Rh-omil", 25_000, "lab"),
    ("Tireoid gormonlar (TSH, T3, T4)", 120_000, "lab"),
    ("Jinsiy gormonlar (FSH, LH, Prolaktin va b.)", 150_000, "lab"),
    ("Koagulogramma (qon ivishi)", 60_000, "lab"),
    ("Kolesterol, HDL, LDL, Triglitseridlar", 50_000, "lab"),
    ("Ferritin, Temir, TIBC", 60_000, "lab"),
    ("Vitamin D (25-OH)", 90_000, "lab"),
    ("Vitamin B12 va Folat kislota", 80_000, "lab"),
    ("PSA (Prostat spetsifik antigen)", 70_000, "lab"),
    ("CA-125 (Onkomarker)", 80_000, "lab"),
    ("CEA (Onkomarker)", 75_000, "lab"),
    ("HbA1c (Glikozillangan gemoglobin)", 60_000, "lab"),
    ("Insulin darajasi", 70_000, "lab"),
    ("Gepatit B (HBsAg)", 40_000, "lab"),
    ("Gepatit C (anti-HCV)", 40_000, "lab"),
    ("OIV (OITS) tekshiruvi", 40_000, "lab"),
    ("Zaxm (Sifilis/RW)", 35_000, "lab"),
    ("C-reaktiv oqsil (CRP)", 40_000, "lab"),
    ("Revmatoid faktor (RF)", 40_000, "lab"),

    # ── SIYDIK TAHLILLARI ────────────────────────────────────────────────────
    ("Umumiy siydik tahlili (OAM)", 20_000, "lab"),
    ("Siydik nechi'da (Nechyporenko)", 30_000, "lab"),
    ("Siydikda bakteriya ekishi (bakposev)", 50_000, "lab"),

    # ── BOSHQA PROTSEDURALAR ─────────────────────────────────────────────────
    ("Spirometriya (o'pka funksiyasi)", 60_000, None),
    ("FGDS (Fibroezofagogastroduodenoskopiya)", 150_000, "doctor"),
    ("Kolonoskopiya", 200_000, "doctor"),
    ("Kolposkopiya", 100_000, "doctor"),
    ("Elektroensefalografiya (EEG)", 100_000, "radiology"),
    ("Audiometriya (Eshitish tekshiruvi)", 50_000, None),
    ("Tonometriya (Ko'z bosimi)", 30_000, "doctor"),
    ("Kapillyaroskopiya", 60_000, "doctor"),
]


class Command(BaseCommand):
    help = "Tibbiy xizmatlar katalogini narxlari bilan to'ldiradi (UZI, EKG, Rentgen, Tahlillar)"

    def handle(self, *args, **options):
        roles_cache: dict = {}
        created = 0
        updated = 0

        for name, price, role_code in SERVICES:
            role = None
            if role_code:
                if role_code not in roles_cache:
                    roles_cache[role_code] = Role.objects.filter(code=role_code).first()
                role = roles_cache[role_code]

            obj, was_created = ServiceCatalog.objects.get_or_create(
                name=name,
                defaults={"price": price, "allowed_role": role, "is_active": True},
            )
            if was_created:
                created += 1
            else:
                # Narxni yangilab qo'yish (agar o'zgargan bo'lsa)
                if obj.price != price:
                    obj.price = price
                    obj.save(update_fields=["price"])
                    updated += 1

        total = ServiceCatalog.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"{created} ta yangi xizmat qo'shildi, {updated} ta narx yangilandi "
                f"(jami: {total} ta xizmat)"
            )
        )
