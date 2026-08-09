"""Tekshiruvlar guruhlari daraxtini yaratish va mavjud xizmatlarni joylash.

NEGA MA'LUMOT MIGRATSIYASI: guruhlarni qo'lda kiritish uzoq va xatoga moyil,
qolaversa har bir o'rnatilgan nusxada bir xil bo'lishi kerak — aks holda
«+Analiz» modali bir serverda to'la, boshqasida bo'sh chiqadi.

Mavjud xizmatlar nomiga qarab guruhga taqsimlanadi. Topilmagani guruhsiz
qoladi (modalda ko'rinmaydi, lekin yo'qolmaydi) — superadmin uni keyin
qo'lda joylashi mumkin.
"""
import re

from django.db import migrations

# (guruh nomi, tugma yozuvi, belgi, turi, tartib, [ichki guruhlar])
TREE = [
    ("Laboratoriya", "+Analiz", "🧪", "lab", 10, [
        "Klinik tahlillar",
        "Biokimyoviy tahlillar",
        "Gormonlar",
        "Gepatit",
        "Koagulogramma",
        "Markazlashgan serologiya va PZR-diagnostika",
        "Sitologiya",
    ]),
    ("EKG", "+EKG", "📈", "diagnostic", 20, []),
    ("UZI", "+UZI", "🔊", "diagnostic", 30, []),
    ("Endoskopiya", "+Endoskop", "🔦", "diagnostic", 40, []),
    ("Rentgen", "+Rentgen", "🩻", "diagnostic", 50, []),
    ("Funksional diagnostika", "+Funksional", "📊", "diagnostic", 60, []),
]

# Bular umuman tekshiruv emas — shifokor qabullari va maslahatlar.
# Guruhga tushmasligi kerak, aks holda «+Analiz» modalida kardiolog qabuli
# analiz bo'lib chiqadi.
SKIP = ["qabul", "konsultatsiya", "maslahat", "ko'rik", "korik"]

# Mavjud xizmatlarni nomidagi kalit so'zga qarab guruhga joylash.
#
# TARTIB MUHIM — birinchi mos kelgani oladi. Asboб (modallik) nomi hal
# qiluvchi: «UZI — Buyraklar va siydik yo'llari» dagi «siydik» so'zi uni
# klinik tahlilga tortib ketmasligi uchun UZI/EKG/Rentgen qoidalari
# laboratoriya qoidalaridan OLDIN turadi.
RULES = [
    # --- 1) Asbob turi bo'yicha (eng kuchli belgi) ---
    ("EKG", ["ekg", "elektrokardio", "exokardio", "exo-kg", "exokg", "holter", "экг"]),
    ("UZI", ["uzi", "ultratovush", "ultra tovush", "dopler", "doppler", "usdg",
             "echocg", "exocg", "узи"]),
    ("Endoskopiya", ["endoskop", "fgds", "gastroskop", "kolonoskop",
                     "bronxoskop", "kolposkop", "sistoskop", "rektoromanoskop"]),
    ("Rentgen", ["rentgen", "rg", "kt", "mrt", "mst", "flyuro", "mammograf",
                 "densitometr", "рентген"]),
    ("Funksional diagnostika",
     ["spirometr", "audiometr", "tonometr", "eeg", "elektroensefalo",
      "kapillyaroskop", "veloergometr", "stress-test"]),

    # --- 2) Laboratoriya bo'limlari ---
    ("Sitologiya", ["sitolog", "цитолог"]),
    ("Gepatit", ["gepatit", "hbsag", "hcv", "гепатит"]),
    ("Koagulogramma", ["koagulogramma", "protrombin", "fibrinogen", "mno", "inr"]),
    ("Markazlashgan serologiya va PZR-diagnostika",
     ["pzr", "pcr", "serolog", "rw", "vich", "hiv", "oiv", "oits", "zaxm",
      "zahar", "sifilis", "immunofermen", "ifa", "revmatoid"]),
    ("Gormonlar", ["gormon", "tsh", "t3", "t4", "prolaktin", "kortizol",
                   "testosteron", "estradiol", "insulin", "fsh", "lh",
                   "tireoid", "гормон"]),
    ("Biokimyoviy tahlillar",
     ["bioximiy", "biokimyo", "alt", "ast", "bilirubin", "kreatinin", "mochevina",
      "xolesterin", "kolesterol", "glyukoza", "qand", "amilaza", "oqsil",
      "crp", "ferritin", "onkomarker", "ca-125", "cea", "psa", "triglitserid",
      "hdl", "ldl", "vitamin", "folat", "temir", "tibc", "биохим"]),
    ("Klinik tahlillar",
     ["qon ivish", "leykoform", "leykofom", "leykotsitar", "najas", "malar",
      "malariya", "skatolog", "koprogramma", "umumiy qon", "umumiy siydik",
      "siydik", "qon tahlil", "qon guruhi", "rh-omil", "eritrotsit",
      "gemoglobin", "hba1c", "soe", "bakposev", "nechi", "клиничес"]),
]

# So'z BOSHI: satr boshi yoki harf/raqam bo'lmagan belgi.
#
# DIQQAT — nima uchun so'z OXIRI tekshirilmaydi: o'zbek tili qo'shimchali,
# «biokimyoviy», «glyukozasi», «flyurografiya» kabi shakllar o'zakdan uzun.
# To'liq so'z chegarasi talab qilinganda «biokimyo» kaliti «Biokimyoviy qon
# tahlili» ni topa olmay, u klinik tahlilga tushib qolgan edi.
#
# Bu «ast» kabi qisqa kalitlarni xavfli qilmaydi, chunki ular ham faqat
# so'z BOSHIDA qidiriladi: «Gastroenterolog» ichidagi «ast» so'z boshida
# emas, shuning uchun mos kelmaydi.
_WORD_START = r"(?:^|[^0-9a-zа-яёʻʼ'])"


def _matches(low: str, key: str) -> bool:
    if " " in key:            # ko'p so'zli kalit — oddiy qism satr yetarli
        return key in low
    return re.search(_WORD_START + re.escape(key), low) is not None


def seed(apps, schema_editor):
    ServiceCategory = apps.get_model("clinical", "ServiceCategory")
    ServiceCatalog = apps.get_model("clinical", "ServiceCatalog")

    by_name = {}
    for name, button, icon, kind, order, children in TREE:
        root, _ = ServiceCategory.objects.get_or_create(
            parent=None, name=name,
            defaults={"button_label": button, "icon": icon,
                      "kind": kind, "sort_order": order, "is_active": True},
        )
        by_name[name] = root
        for i, child in enumerate(children, start=1):
            node, _ = ServiceCategory.objects.get_or_create(
                parent=root, name=child,
                defaults={"kind": kind, "sort_order": i * 10, "is_active": True},
            )
            by_name[child] = node

    # Mavjud xizmatlarni taqsimlaymiz. Faqat guruhsizlarga tegamiz —
    # qayta ishga tushirilsa qo'lda qilingan taqsimotni buzmaydi.
    for svc in ServiceCatalog.objects.filter(category__isnull=True):
        low = (svc.name or "").lower().replace("’", "'").replace("ʻ", "'")
        if any(s in low for s in SKIP):
            continue
        for group, keys in RULES:
            if any(_matches(low, k) for k in keys):
                svc.category = by_name.get(group)
                svc.save(update_fields=["category"])
                break


def unseed(apps, schema_editor):
    ServiceCatalog = apps.get_model("clinical", "ServiceCatalog")
    ServiceCategory = apps.get_model("clinical", "ServiceCategory")
    ServiceCatalog.objects.update(category=None)
    ServiceCategory.objects.filter(parent__isnull=False).delete()
    ServiceCategory.objects.filter(parent__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0030_alter_servicecatalog_options_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
