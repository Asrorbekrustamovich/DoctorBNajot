"""Ma'lumot tuzatish: price_snapshot=0 bo'lib qolgan xizmat buyurtmalari.

Avvalgi kodda "not self.pk" sharti UUID pk tufayli ishlamagan va
snapshot yozilmagan — bunday yozuvlar chekka tushmay qolgan edi.
Ushbu migratsiya ularni xizmatning joriy katalog narxi bilan to'ldiradi.
"""
from django.db import migrations


def backfill(apps, schema_editor):
    ServiceOrder = apps.get_model("clinical", "ServiceOrder")
    for order in ServiceOrder.objects.filter(price_snapshot=0).select_related("service"):
        if order.service and order.service.price:
            order.price_snapshot = order.service.price
            order.save(update_fields=["price_snapshot"])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("clinical", "0008_serviceorder_price_snapshot_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, noop),
    ]
