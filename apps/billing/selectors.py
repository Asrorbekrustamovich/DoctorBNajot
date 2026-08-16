"""To'lov kutayotgan tayinlovlar — BITTA MANBA.

Shifokor tekshiruv yoki qabul tayinlaganda chekka «oldindan to'lanadigan»
band tushadi. Registrator o'sha bandni to'lagunicha bemor kabinetga
o'tolmaydi.

Shu ro'yxat ikki joyda ishlatiladi:
  · to'lov qabul qilish sahifasidagi hisoblagich;
  · boshqa sahifalarda chiqadigan bildirishnoma.

Ular alohida hisoblansa muqarrar farq qiladi: bildirishnomada «3 ta»
turadi, sahifada esa boshqa son chiqadi. Shuning uchun yagona funksiya.
"""
from __future__ import annotations

from django.db.models import QuerySet


def pending_prepaid_items() -> QuerySet:
    """To'lanmagan, oldindan to'lanishi shart bo'lgan chek bandlari.

    HAQIQAT MANBAI — CHEK BANDI, tayinlov statusi emas. Tekshiruvning
    `status` maydonini qo'lda o'zgartirib to'lovni chetlab o'tish
    mumkin bo'lardi, chek bandi esa kassaga bog'langan.
    """
    from apps.billing.models import Invoice, InvoiceItem

    return (
        InvoiceItem.objects.filter(
            payment_mode=InvoiceItem.PaymentMode.PREPAID,
            paid_at__isnull=True,
            total_price__gt=0,
        )
        .exclude(invoice__status=Invoice.Status.CANCELLED)
        .select_related("invoice__patient", "invoice__visit")
    )


def pending_summary(limit: int = 5) -> dict:
    """Bildirishnoma va hisoblagich uchun qisqa xulosa."""
    items = list(pending_prepaid_items().order_by("-created_at"))

    bemorlar = []
    korilgan = set()
    for it in items:
        p = it.invoice.patient if it.invoice_id else None
        if p is None or p.pk in korilgan:
            continue
        korilgan.add(p.pk)
        bemorlar.append(p)

    return {
        "count": len(items),                 # nechta tayinlov to'lov kutmoqda
        "patients": len(bemorlar),           # nechta bemor
        "total": sum((i.total_price or 0) for i in items),
        # Bildirishnomada ko'rsatiladigan oxirgilari
        "latest": [
            {
                "name": it.name,
                "patient": it.invoice.patient.full_name if it.invoice.patient_id else "",
                "amount": float(it.total_price or 0),
            }
            for it in items[:limit]
        ],
        # Yangi tayinlov kelganini bilish uchun belgi. Vaqt emas, ID'lar
        # yig'indisi: band to'langanda ham, yangisi qo'shilganda ham
        # o'zgaradi, ya'ni ikkala holatni ham ushlaydi.
        "signature": "|".join(sorted(str(i.pk) for i in items)),
    }
