"""Klinika XARAJATLARI — statsionar dorilari va operatsiya sarfi.

Nega alohida
------------
Tushum hisoboti klinikaga qancha PUL KIRGANINI ko'rsatadi. Lekin
foydani bilish uchun qancha CHIQQANI ham kerak, chunki ikkalasi butunlay
boshqa manbalarda yotadi:

  · statsionarda bemorga berilgan dorilar — dorixona omborida;
  · operatsiyada sarflangan materiallar — anesteziolog omborida
    (anesteziolog zayavkasi + operatsion hamshira anjomlari).

Ilgari bu ikkisi hech qayerda jamlanmagan edi. Direktor «bu oy dorига
qancha ketdi?» deb so'rasa, javob yo'q edi.

IKKI XIL NARX
-------------
Dorining ikki narxi bor: KELISH narxi (klinika to'lagani) va SOTISH
narxi (bemordan olingani). Xarajat — kelish narxi. Sotish narxi bilan
hisoblansak, klinika o'ziga o'zi sotgan bo'lib chiqadi va raqam
haqiqatdan katta chiqadi.
"""
from __future__ import annotations

from decimal import Decimal


def _nol() -> Decimal:
    return Decimal("0.00")


def stationar_dori_xarajati(start, end):
    """Statsionarda berilgan dorilarning KELISH narxi bo'yicha xarajati.

    Faqat statsionarda yotgan bemorga berilganlari: ambulator bemorga
    sotilgan dori xarajat emas, u savdo.

    Qaytarilganlari chiqarib tashlanadi — ular omborga qaytgan.
    """
    from apps.clinical.models import InpatientStay
    from apps.pharmacy.models import MedicineDispense

    yotish_visit_id = set(
        InpatientStay.objects.values_list("visit_id", flat=True))

    qatorlar = []
    jami = _nol()
    if not yotish_visit_id:
        return {"jami": jami, "qatorlar": qatorlar}

    qs = (MedicineDispense.objects
          .filter(created_at__date__gte=start, created_at__date__lte=end,
                  visit_id__in=yotish_visit_id, is_returned=False)
          .exclude(status="cancelled")
          .select_related("batch__medicine", "visit__patient"))

    yigindi = {}
    for d in qs:
        dori = getattr(d.batch, "medicine", None)
        nom = dori.name if dori else "—"
        kelish = (d.batch.purchase_price if d.batch else None) or _nol()
        summa = (d.quantity or _nol()) * kelish
        jami += summa
        joriy = yigindi.setdefault(nom, {"nom": nom, "soni": _nol(),
                                         "summa": _nol()})
        joriy["soni"] += d.quantity or _nol()
        joriy["summa"] += summa

    qatorlar = sorted(yigindi.values(), key=lambda r: r["summa"], reverse=True)
    return {"jami": jami, "qatorlar": qatorlar}


def operatsiya_xarajati(start, end):
    """Operatsiyalarda sarflangan material xarajati.

    Ikki manbadan: anesteziolog zayavkasi (psixotrop va boshqa dorilar)
    va operatsion hamshira ishlatgan anjomlar. Ikkalasi ham anesteziolog
    omboridan chiqadi va narxi zayavka paytida qotirilgan
    (`price_snapshot` / `price`) — keyin ombor narxi o'zgarsa, o'tgan
    operatsiya xarajati o'zgarmaydi.
    """
    from apps.clinical.models import SurgerySchedule

    qs = (SurgerySchedule.objects
          .filter(created_at__date__gte=start, created_at__date__lte=end)
          .exclude(status="cancelled")
          .select_related("visit__patient", "surgery_type", "surgeon")
          .prefetch_related("anesthesia_request__items__stock",
                            "nurse_usages__stock"))

    qatorlar = []
    jami_anest = _nol()
    jami_hamshira = _nol()
    for sx in qs:
        anest = sx.anesthesia_expense_total or _nol()
        hamshira = sx.nurse_expense_total or _nol()
        if not anest and not hamshira:
            continue
        jami_anest += anest
        jami_hamshira += hamshira
        qatorlar.append({
            "operatsiya": sx,
            "bemor": sx.visit.patient.full_name if sx.visit_id else "—",
            "turi": sx.surgery_type.name if sx.surgery_type_id else "—",
            "sana": sx.scheduled_time,
            "anest": anest,
            "hamshira": hamshira,
            "jami": anest + hamshira,
            "narxi": sx.actual_price or _nol(),
        })

    qatorlar.sort(key=lambda r: r["jami"], reverse=True)
    return {
        "jami": jami_anest + jami_hamshira,
        "anest": jami_anest,
        "hamshira": jami_hamshira,
        "qatorlar": qatorlar,
    }


def xarajat_hisoboti(start, end):
    """Ikki xarajat manbasini bitta joyga yig'adi."""
    dori = stationar_dori_xarajati(start, end)
    op = operatsiya_xarajati(start, end)
    return {
        "dori": dori,
        "operatsiya": op,
        "jami_xarajat": dori["jami"] + op["jami"],
    }
