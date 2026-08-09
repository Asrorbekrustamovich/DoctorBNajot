"""Klinik ma'lumotlarni o'qish uchun yordamchi funksiyalar (selectors).

Bu yerda faqat O'QISH mantig'i turadi — view'lar uni chaqiradi, o'zi
ma'lumotni yig'maydi. Shu sababli bitta daraxt bir nechta joyda (qabul
modali, statsionar, registratura) bir xil chiqadi.
"""
from __future__ import annotations

from decimal import Decimal

from django.db.models import Prefetch

from apps.clinical.models import ServiceCatalog, ServiceCategory, ServiceOrder


def exam_picker_groups(assigned_ids: set | None = None) -> list[dict]:
    """Tekshiruv tayinlash modali uchun guruhlangan daraxt.

    Qaytadi::

        [
          {"id":…, "label":"+Analiz", "icon":"🧪", "count": 26,
           "services": [...],                      # bevosita ichidagilar
           "children": [{"id":…, "name":"Klinik tahlillar",
                         "services":[…]}, …]},
          …
        ]

    Har bir xizmat lug'ati narx, kim bajarishi va allaqachon tayinlanganmi
    degan ma'lumotni olib yuradi — shablon hech narsani qayta so'ramaydi
    (N+1 so'rovning oldi olinadi).
    """
    assigned_ids = assigned_ids or set()

    active_services = ServiceCatalog.objects.filter(is_active=True).select_related(
        "responsible_staff", "allowed_role", "room",
        "category", "category__default_staff",
        "category__default_role", "category__default_room",
    ).order_by("sort_order", "name")

    roots = (
        ServiceCategory.objects.filter(parent__isnull=True, is_active=True)
        .select_related("default_staff", "default_role", "default_room")
        .prefetch_related(
            Prefetch("services", queryset=active_services),
            Prefetch(
                "children",
                queryset=ServiceCategory.objects.filter(is_active=True)
                .select_related("default_staff", "default_role", "default_room")
                .prefetch_related(Prefetch("services", queryset=active_services))
                .order_by("sort_order", "name"),
            ),
        )
        .order_by("sort_order", "name")
    )

    def pack(svc: ServiceCatalog) -> dict:
        return {
            "id": str(svc.id),
            "name": svc.name,
            "price": svc.price,
            # Shablonda `{{ s.price|floatformat:0 }}` ishlatiladi; JS uchun
            # esa toza son kerak.
            "price_num": float(svc.price or 0),
            "owner": svc.owner_label,
            "destination": svc.destination,
            "assigned": str(svc.id) in assigned_ids,
        }

    groups: list[dict] = []
    for root in roots:
        direct = [pack(s) for s in root.services.all()]
        children = []
        for child in root.children.all():
            items = [pack(s) for s in child.services.all()]
            if items:
                children.append({"id": str(child.id), "name": child.name,
                                 "services": items})
        total = len(direct) + sum(len(c["services"]) for c in children)
        if not total:
            continue
        groups.append({
            "id": str(root.id),
            "label": root.label,
            "name": root.name,
            "icon": root.icon or "🔬",
            "count": total,
            "services": direct,
            "children": children,
        })
    return groups


def visit_exam_orders(visit) -> list[ServiceOrder]:
    """Tashrifga tayinlangan tekshiruvlar — natijalari bilan birga."""
    return list(
        visit.service_orders.exclude(status=ServiceOrder.Status.CANCELLED)
        .select_related("service", "service__category", "performed_by")
        .prefetch_related("result_rows")
        .order_by("created_at")
    )


def orders_total(orders) -> Decimal:
    return sum((o.price_snapshot or Decimal("0")) for o in orders) or Decimal("0")
