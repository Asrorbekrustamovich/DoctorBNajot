"""MKB-10 kodlarining boshlang'ich to'plami.

To'liq MKB-10 da 14 000 dan ortiq kod bor — uni migratsiyaga sig'dirib
bo'lmaydi va kerak ham emas. Bu yerda klinikada eng ko'p uchraydigan
kodlar bor, qolganini superadmin qo'shadi yoki rasmiy ro'yxatni
import qiladi.

Kodsiz ishlab bo'lmaydi: shifokor tashxisni qo'lda yozsa har xil
yozadi («Z99.9», «z99,9», «Z 99.9») va statistika yig'ilmaydi.
"""
from django.db import migrations

CODES = [
    # --- Umumiy / kuzatuv ---
    ("Z00.0", "Umumiy tibbiy ko'rik", "Z00–Z99 Sog'liqqa ta'sir etuvchi omillar"),
    ("Z99.9", "Qurilma va moslamalarga bog'liqlik, aniqlanmagan", "Z00–Z99"),
    ("Z03.9", "Kuzatuv, kasallik gumoni bilan", "Z00–Z99"),

    # --- Yuqumli ---
    ("A09", "Yuqumli kelib chiqishi taxmin qilinadigan diareya va gastroenterit", "A00–B99"),
    ("B34.9", "Virusli infeksiya, aniqlanmagan", "A00–B99"),

    # --- Qon ---
    ("D50.9", "Temir tanqisligi anemiyasi, aniqlanmagan", "D50–D89"),
    ("D64.9", "Anemiya, aniqlanmagan", "D50–D89"),

    # --- Endokrin ---
    ("E11.9", "2-tip qandli diabet, asoratsiz", "E00–E90"),
    ("E10.9", "1-tip qandli diabet, asoratsiz", "E00–E90"),
    ("E03.9", "Gipotireoz, aniqlanmagan", "E00–E90"),
    ("E66.9", "Semizlik, aniqlanmagan", "E00–E90"),

    # --- Asab ---
    ("G40.9", "Epilepsiya, aniqlanmagan", "G00–G99"),
    ("G43.9", "Migren, aniqlanmagan", "G00–G99"),
    ("G62.9", "Polinevropatiya, aniqlanmagan", "G00–G99"),

    # --- Yurak-qon tomir ---
    ("I10", "Essensial (birlamchi) arterial gipertenziya", "I00–I99"),
    ("I20.0", "Beqaror stenokardiya", "I00–I99"),
    ("I21.9", "O'tkir miokard infarkti, aniqlanmagan", "I00–I99"),
    ("I25.9", "Surunkali yurak ishemik kasalligi, aniqlanmagan", "I00–I99"),
    ("I50.9", "Yurak yetishmovchiligi, aniqlanmagan", "I00–I99"),
    ("I63.9", "Miya infarkti, aniqlanmagan", "I00–I99"),
    ("I83.9", "Oyoq venalarining varikoz kengayishi", "I00–I99"),

    # --- Nafas ---
    ("J06.9", "Yuqori nafas yo'llarining o'tkir infeksiyasi", "J00–J99"),
    ("J18.9", "Pnevmoniya, qo'zg'atuvchisi aniqlanmagan", "J00–J99"),
    ("J20.9", "O'tkir bronxit, aniqlanmagan", "J00–J99"),
    ("J45.9", "Bronxial astma, aniqlanmagan", "J00–J99"),
    ("J44.9", "Surunkali obstruktiv o'pka kasalligi", "J00–J99"),
    ("J35.0", "Surunkali tonzillit", "J00–J99"),

    # --- Hazm ---
    ("K25.9", "Oshqozon yarasi, aniqlanmagan", "K00–K93"),
    ("K29.7", "Gastrit, aniqlanmagan", "K00–K93"),
    ("K35.8", "O'tkir appendisit, boshqa va aniqlanmagan", "K00–K93"),
    ("K40.9", "Chov churrasi, obstruksiyasiz", "K00–K93"),
    ("K80.2", "O't pufagi toshi, xolesistitsiz", "K00–K93"),
    ("K81.0", "O'tkir xolesistit", "K00–K93"),
    ("K85.9", "O'tkir pankreatit, aniqlanmagan", "K00–K93"),

    # --- Teri ---
    ("L02.9", "Teri absessi, furunkul, karbunkul", "L00–L99"),
    ("L30.9", "Dermatit, aniqlanmagan", "L00–L99"),

    # --- Suyak-mushak ---
    ("M17.9", "Tizza bo'g'imi gonartrozi", "M00–M99"),
    ("M51.1", "Umurtqalararo disk churrasi, radikulopatiya bilan", "M00–M99"),
    ("M54.5", "Bel og'rig'i", "M00–M99"),
    ("M79.1", "Mialgiya", "M00–M99"),

    # --- Siydik-tanosil ---
    ("N10", "O'tkir tubulointerstitsial nefrit (pielonefrit)", "N00–N99"),
    ("N20.0", "Buyrak toshi", "N00–N99"),
    ("N30.0", "O'tkir sistit", "N00–N99"),
    ("N40", "Prostata giperplaziyasi", "N00–N99"),

    # --- Homiladorlik ---
    ("O80", "Bir homilali o'z-o'zidan tug'ruq", "O00–O99"),
    ("O82", "Kesar kesish yo'li bilan tug'ruq", "O00–O99"),

    # --- Alomatlar ---
    ("R10.4", "Qorin sohasidagi boshqa va aniqlanmagan og'riq", "R00–R99"),
    ("R50.9", "Isitma, aniqlanmagan", "R00–R99"),
    ("R51", "Bosh og'rig'i", "R00–R99"),

    # --- Jarohat ---
    ("S06.0", "Miya chayqalishi", "S00–T98"),
    ("S72.0", "Son suyagi bo'ynining sinishi", "S00–T98"),
    ("T14.9", "Jarohat, aniqlanmagan", "S00–T98"),
]


def seed(apps, schema_editor):
    ICD10Code = apps.get_model("clinical", "ICD10Code")
    for code, name, chapter in CODES:
        ICD10Code.objects.get_or_create(
            code=code,
            defaults={"name": name, "chapter": chapter, "is_active": True},
        )


def unseed(apps, schema_editor):
    ICD10Code = apps.get_model("clinical", "ICD10Code")
    ICD10Code.objects.filter(code__in=[c[0] for c in CODES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0032_admissionepisode_icd10code_episodediagnosis_and_more"),
    ]

    operations = [migrations.RunPython(seed, unseed)]
