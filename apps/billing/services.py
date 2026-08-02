from decimal import Decimal
from django.db import transaction
from .models import Invoice, InvoiceItem

def generate_invoice_for_visit(visit):
    """
    Bemorning bitta qabuli (Visit) bo'yicha barcha xarajatlarni hisoblab,
    Chek (Invoice) va uning bandlarini (InvoiceItem) yaratadi yoki yangilaydi.
    """
    with transaction.atomic():
        invoice, created = Invoice.objects.get_or_create(
            visit=visit,
            defaults={
                'patient': visit.patient,
                'total_amount': Decimal(0),
                'status': Invoice.Status.UNPAID
            }
        )
        
        # Eski bandlarni tozalaymiz (agar yangilanish kiritilgan bo'lsa, ikki marta yozilmasligi uchun)
        invoice.items.all().delete()
        
        total = Decimal(0)

        # 0. SHIFOKOR QABULI (Consultation.fee — o'sha paytdagi narx snapshoti).
        # Yo'naltirilganda ham hamma shifokorlarning qabullari SHU bitta chekda.
        for cons in visit.consultations.filter(fee__gt=0).select_related("doctor"):
            InvoiceItem.objects.create(
                invoice=invoice,
                item_type=InvoiceItem.ItemType.SERVICE,
                name=f"Shifokor qabuli: {cons.doctor.get_full_name() or cons.doctor.username}",
                quantity=Decimal(1),
                price=cons.fee,
                total_price=cons.fee,
                reference_id=cons.id
            )
            total += cons.fee

        # 1. Shifokor va Tahlillar (ServiceOrders)
        # Faqat narxi 0 dan katta va BEKOR QILINMAGAN xizmatlar olinadi
        # price_snapshot ishlatiladi — katalog narxi o'zgarsa ham eski chek o'zgarmaydi
        for order in visit.service_orders.filter(price_snapshot__gt=0).exclude(
            status="cancelled"
        ).select_related("service"):
            price = order.price_snapshot
            InvoiceItem.objects.create(
                invoice=invoice,
                item_type=InvoiceItem.ItemType.SERVICE,
                name=f"Xizmat: {order.service.name}",
                service=order.service,
                quantity=Decimal(1),
                price=price,
                total_price=price,
                reference_id=order.id
            )
            total += price
            
        # 2. Dori-darmonlar (MedicineDispense) — qaytarilganlari va PAKETLI
        # statsionar dorilari (narxi yotish ichida) chekka tushmaydi
        for dispense in visit.dispensed_medicines.filter(is_returned=False, is_package=False):
            if dispense.price_at_dispense > 0:
                item_total = dispense.quantity * dispense.price_at_dispense
                unit_name = dispense.batch.medicine.unit.short_name or dispense.batch.medicine.unit.name
                InvoiceItem.objects.create(
                    invoice=invoice,
                    item_type=InvoiceItem.ItemType.MEDICINE,
                    name=f"Dori: {dispense.batch.medicine.name}",
                    quantity=dispense.quantity,
                    price=dispense.price_at_dispense,
                    total_price=item_total,
                    reference_id=dispense.id
                )
                total += item_total
                
        # 3. Statsionar yotish (InpatientStay) — bekor qilinganlari hisobga olinmaydi
        for stay in visit.inpatient_stays.exclude(status="cancelled"):
            if stay.total_amount > 0 and stay.total_days > 0:
                days = Decimal(stay.total_days)
                
                if stay.is_companion:
                    # Eski (legacy) hamroh yozuvlari — yangi tizimda yaratilmaydi
                    name = f"Statsionar (Hamroh - {stay.companion_name}): {stay.bed.room.name} {stay.bed.number}-o'rin"
                    price = stay.companion_daily_price
                else:
                    name = f"Statsionar ({stay.get_stay_type_display()}): {stay.bed.room.name} {stay.bed.number}-o'rin"
                    price = stay.daily_price
                
                InvoiceItem.objects.create(
                    invoice=invoice,
                    item_type=InvoiceItem.ItemType.INPATIENT,
                    name=name,
                    quantity=days,
                    price=price,
                    total_price=stay.total_amount,
                    reference_id=stay.id
                )
                total += stay.total_amount

        # 4. Operatsiyalar (SurgerySchedule) - bekor qilinmaganlari
        for surgery in visit.surgeries.exclude(status="cancelled"):
            if surgery.actual_price > 0:
                InvoiceItem.objects.create(
                    invoice=invoice,
                    item_type=InvoiceItem.ItemType.SURGERY,
                    name=f"Jarrohlik: {surgery.surgery_type.name}",
                    quantity=Decimal(1),
                    price=surgery.actual_price,
                    total_price=surgery.actual_price,
                    reference_id=surgery.id
                )
                total += surgery.actual_price

        # 4. Asosiy shifokor ko'rigi uchun (agar u ServiceCatalog bo'yicha yozilmagan bo'lsa, 
        # odatda ko'rik navbatga olinayotganda ServiceOrder orqali biriktiriladi. 
        # Shuning uchun uni bu yerda qoldiramiz, aks holda alohida yozish kerak.)

        # Umumiy summani yangilash va statusni qayta hisoblash
        # (qaytarilgan pullar ham inobatga olinadi)
        invoice.total_amount = total
        invoice.recompute_status()
        invoice.save()

    return invoice
