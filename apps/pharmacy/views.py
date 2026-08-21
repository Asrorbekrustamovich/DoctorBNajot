from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import TemplateView
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone

from apps.accounts.models import Role
from apps.accounts.permissions import RoleRequiredMixin, role_required
from .models import MeasurementUnit, Medicine, MedicineBatch

# Ombor (sklad) boshqaruvi uchun rollar
STOCK_ROLES = (Role.Code.WAREHOUSE, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
# Dori chiqimi (bemorga ishlatish) uchun rollar
DISPENSE_ROLES = STOCK_ROLES + (
    *Role.DOCTOR_ROLES, Role.Code.CHIEF_DOCTOR, Role.Code.NURSE,
    Role.Code.WARD_NURSE,
)

class PharmacyDashboardView(RoleRequiredMixin, TemplateView):
    """Ombor mudiri uchun asosiy ekran (Sklad)"""
    allowed_roles = (Role.Code.WAREHOUSE, Role.Code.SUPER_ADMIN)
    template_name = "pharmacy/dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Jami dori turlari
        context["medicines"] = Medicine.objects.prefetch_related('batches', 'unit').all()
        # O'lchov birliklari (yangi dori qo'shish uchun)
        context["units"] = MeasurementUnit.objects.all()
        
        # Eng oxirgi kirim qilinganlar (oxirgi 10 ta)
        context["recent_batches"] = MedicineBatch.objects.select_related('medicine', 'medicine__unit').order_by('-received_date')[:10]
        
        # Qoldig'i bor (aktiv) partiyalar (Narxni o'zgartirish uchun)
        context["active_batches"] = MedicineBatch.objects.filter(quantity_available__gt=0).select_related('medicine', 'medicine__unit').prefetch_related('price_history', 'price_history__changed_by').order_by('medicine__name')
        
        # Kutilayotgan (Sklad tasdiqlashi kerak bo'lgan) dorilar
        from .models import MedicineDispense
        context["pending_dispenses"] = MedicineDispense.objects.filter(
            status=MedicineDispense.Status.PENDING,
            is_returned=False
        ).select_related('visit__patient', 'batch__medicine', 'dispensed_by').order_by('dispensed_at')
        
        return context

@role_required(*STOCK_ROLES)
def add_measurement_unit(request):
    if request.method == "POST":
        name = request.POST.get("name")
        short_name = request.POST.get("short_name", "")
        if name:
            MeasurementUnit.objects.create(name=name, short_name=short_name)
            messages.success(request, f"Yangi o'lchov birligi qo'shildi: {name}")
    return redirect("pharmacy:dashboard")

@role_required(*STOCK_ROLES)
def add_medicine(request):
    if request.method == "POST":
        name = request.POST.get("name")
        unit_id = request.POST.get("unit")
        description = request.POST.get("description", "")
        
        if name and unit_id:
            unit = get_object_or_404(MeasurementUnit, id=unit_id)
            medicine = Medicine.objects.create(name=name, unit=unit, description=description)
            
            # QADOQ IYERARXIYASI YARATILMAYDI.
            #
            # «1 blok = 50 ampula» hisobni chalkashtirardi va blok
            # o'lchami keyin o'zgartirilsa eski qoldiqlar boshqacha
            # ko'rinib qolardi. Qoldiq faqat asosiy birlikda yuritiladi.

            messages.success(request, f"Yangi dori katalogga qo'shildi: {name}")
    return redirect("pharmacy:dashboard")

@role_required(*STOCK_ROLES)
def receive_medicine(request):
    """Yangi partiyani (kirim) omborga qabul qilish."""
    if request.method == "POST":
        medicine_id = request.POST.get("medicine_id")
        batch_number = request.POST.get("batch_number", "")
        quantity_str = request.POST.get("quantity")
        purchase_price = request.POST.get("purchase_price", 0)
        selling_price = request.POST.get("selling_price")
        if medicine_id and quantity_str and selling_price:
            medicine = get_object_or_404(Medicine, id=medicine_id)
            try:
                # MIQDOR FAQAT ASOSIY BIRLIKDA kiritiladi.
                #
                # Ilgari «nechta blok» tanlanib, u ampulaga ko'paytirilardi.
                # Bu ikki xatoga yo'l ochardi: blok o'lchami noto'g'ri
                # kiritilsa butun qoldiq buzilardi, va bir xil dori turli
                # o'ramlarda kelganda hisob chalkashardi. Endi ombordor
                # nechta ampula kelganini o'zi sanab yozadi.
                quantity = float(quantity_str)
                base_quantity = quantity
                received_msg = f"{quantity:g} {medicine.unit.short_name or medicine.unit.name}"
                
                MedicineBatch.objects.create(
                    medicine=medicine,
                    batch_number=batch_number,
                    quantity_received=base_quantity,
                    quantity_available=base_quantity,
                    purchase_price=purchase_price,
                    selling_price=selling_price,
                    received_by=request.user
                )
                messages.success(request, f"{medicine.name} muvaffaqiyatli kirim qilindi. {received_msg}.")
            except ValueError:
                messages.error(request, "Miqdor noto'g'ri kiritildi.")
    return redirect("pharmacy:dashboard")

@role_required(*DISPENSE_ROLES)
def dispense_medicine(request):
    """Bemorga dori ishlatilishi (chiqim). Birdaniga bir nechta bo'lishi mumkin."""
    referer = request.META.get('HTTP_REFERER') or "/"
    if request.method == "POST":
        visit_id = request.POST.get("visit_id")
        batch_ids = request.POST.getlist("batch_ids[]")
        quantities = request.POST.getlist("quantities[]")
        
        if visit_id and batch_ids and quantities and len(batch_ids) == len(quantities):
            from decimal import Decimal
            from django.db import transaction
            from .models import MedicineDispense
            from apps.registration.models import Visit
            
            visit = get_object_or_404(Visit, id=visit_id)

            # Bemor paketli statsionarda yotgan bo'lsa — dori narxi yotish
            # ichida: chekka tushmaydi (lekin ombordan kamayadi).
            from apps.clinical.models import InpatientStay, StayChecklistItem
            active_stay = visit.inpatient_stays.filter(
                status=InpatientStay.Status.ACTIVE, is_companion=False
            ).first()
            in_package = bool(active_stay and active_stay.stay_type == InpatientStay.StayType.PACKAGE)

            try:
                with transaction.atomic():
                    for batch_id, qty_str in zip(batch_ids, quantities):
                        if not batch_id or not qty_str:
                            continue # Bo'sh qatorlarni tashlab ketamiz
                            
                        quantity = Decimal(qty_str)
                        batch = get_object_or_404(MedicineBatch, id=batch_id)

                        # Miqdor musbat bo'lishi shart (manfiy kiritilsa
                        # ombor qoldig'i sun'iy oshib ketadi!)
                        if quantity <= 0:
                            raise ValueError(
                                f"Xatolik: '{batch.medicine.name}' uchun miqdor musbat bo'lishi kerak."
                            )

                        # Qoldiqni tekshirish
                        if quantity > batch.quantity_available:
                            raise ValueError(f"Xatolik: '{batch.medicine.name}' dori uchun omborda yetarli qoldiq yo'q. So'raldi: {quantity}, Qoldiq: {batch.quantity_available}")
                        
                        # Chiqimni yaratish
                        dispense = MedicineDispense.objects.create(
                            visit=visit,
                            batch=batch,
                            quantity=quantity,
                            price_at_dispense=batch.selling_price,
                            dispensed_by=request.user,
                            is_package=in_package,
                        )

                        # Ombor qoldig'ini kamaytirish
                        batch.quantity_available -= quantity
                        batch.save()

                        # Statsionarda yotgan bo'lsa — hujjatlashtirish
                        # hisobotiga avtomatik yozamiz (berildi = +)
                        if active_stay:
                            StayChecklistItem.objects.create(
                                stay=active_stay,
                                category=StayChecklistItem.Category.MEDICINE,
                                title=f"{batch.medicine.name} x{quantity}"
                                      + (" (paket ichida)" if in_package else ""),
                                reference_id=dispense.id,
                                is_done=True,
                                done_at=timezone.now(),
                                done_by=request.user,
                            )
                        
                messages.success(request, f"{len(batch_ids)} ta dori muvaffaqiyatli tayinlandi! Sklad tasdig'i kutilmoqda.")
                
            except ValueError as e:
                messages.error(request, str(e))
            except Exception as e:
                messages.error(request, f"Xatolik yuz berdi: {str(e)}")
        else:
            messages.error(request, "Barcha majburiy maydonlarni to'ldiring (Dori, Miqdor).")
            
    return redirect(referer)

@role_required(*STOCK_ROLES)
def confirm_dispense(request, dispense_id):
    """Kutilayotgan dorini Topshirildi deb belgilash."""
    if request.method == "POST":
        from .models import MedicineDispense
        dispense = get_object_or_404(MedicineDispense, id=dispense_id, status=MedicineDispense.Status.PENDING)
        dispense.status = MedicineDispense.Status.DELIVERED
        dispense.save(update_fields=["status"])
        messages.success(request, f"{dispense.batch.medicine.name} dori muvaffaqiyatli topshirildi!")
    return redirect("pharmacy:dashboard")

@role_required(*DISPENSE_ROLES)
def cancel_dispense(request, dispense_id):
    """Tayinlangan dorini bekor qilish va omborga qaytarish."""
    if request.method == "POST":
        from .models import MedicineDispense
        dispense = get_object_or_404(MedicineDispense, id=dispense_id)
        # Faqat PENDING yoki DELIVERED bo'lsa bekor qilinishi mumkin, va avval qaytarilmagan bo'lishi kerak
        if not dispense.is_returned and dispense.status != MedicineDispense.Status.CANCELLED:
            from django.db import transaction
            from django.utils import timezone
            try:
                with transaction.atomic():
                    # Statusni o'zgartirish
                    dispense.status = MedicineDispense.Status.CANCELLED
                    dispense.is_returned = True
                    dispense.returned_at = timezone.now()
                    dispense.returned_by = request.user
                    dispense.return_reason = request.POST.get("reason", "Sklad yoki shifokor tomonidan bekor qilindi")
                    dispense.save()
                    
                    # Omborga miqdorni qaytarish (Lock qilish kerakmi? Ha)
                    batch = MedicineBatch.objects.select_for_update().get(id=dispense.batch.id)
                    batch.quantity_available += dispense.quantity
                    batch.save(update_fields=["quantity_available"])
                    
                    messages.success(request, f"{dispense.batch.medicine.name} bekor qilindi va omborga qaytarildi.")
            except Exception as e:
                messages.error(request, f"Xatolik yuz berdi: {str(e)}")
        else:
            messages.error(request, "Bu tayinlov allaqachon bekor qilingan yoki qaytarilgan.")
            
    referer = request.META.get('HTTP_REFERER') or "/"
    return redirect(referer)

@role_required(*STOCK_ROLES)
def update_batch_price(request, batch_id):
    """Mavjud partiyaning sotish narxini o'zgartirish."""
    referer = request.META.get('HTTP_REFERER') or "pharmacy:dashboard"
    if request.method == "POST":
        new_price = request.POST.get("new_selling_price")
        if new_price:
            from decimal import Decimal
            new_price_decimal = Decimal(new_price)
            batch = get_object_or_404(MedicineBatch, id=batch_id)
            
            if batch.selling_price != new_price_decimal:
                from .models import MedicinePriceHistory
                MedicinePriceHistory.objects.create(
                    batch=batch,
                    old_price=batch.selling_price,
                    new_price=new_price_decimal,
                    changed_by=request.user
                )
                batch.selling_price = new_price_decimal
                batch.save()
                messages.success(request, f"{batch.medicine.name} narxi yangilandi (Yangi narx: {new_price_decimal} so'm). Eski dori chiqimlari o'zgarmaydi.")
            else:
                messages.info(request, "Yangi narx eski narx bilan bir xil.")
        else:
            messages.error(request, "Yangi narxni kiriting.")
    return redirect(referer)

import csv
from django.http import HttpResponse

@role_required(*STOCK_ROLES)
def export_price_history_excel(request, batch_id):
    """Tanlangan partiyaning narx o'zgarish tarixini Excel (XLS/HTML format) da yuklash."""
    batch = get_object_or_404(MedicineBatch, id=batch_id)
    history_qs = batch.price_history.select_related('changed_by').order_by('-changed_at')
    
    # HTML asosidagi Excel fayl yasaymiz (hamma Excel versiyalarida kataklarga aniq tushadi)
    html_content = f"""<html xmlns:x="urn:schemas-microsoft-com:office:excel">
<head>
<meta charset="utf-8">
</head>
<body>
    <table border="1">
        <thead>
            <tr>
                <th style="background-color: #f2f2f2; font-weight: bold;">Sana</th>
                <th style="background-color: #f2f2f2; font-weight: bold;">Vaqt</th>
                <th style="background-color: #f2f2f2; font-weight: bold;">Dori Nomi</th>
                <th style="background-color: #f2f2f2; font-weight: bold;">Eski Narx</th>
                <th style="background-color: #f2f2f2; font-weight: bold;">Yangi Narx</th>
                <th style="background-color: #f2f2f2; font-weight: bold;">Xodim</th>
            </tr>
        </thead>
        <tbody>
"""
    
    for h in history_qs:
        date_str = h.changed_at.astimezone().strftime('%d.%m.%Y')
        time_str = h.changed_at.astimezone().strftime('%H:%M:%S')
        user_name = h.changed_by.get_full_name() or h.changed_by.username if h.changed_by else 'Noma\'lum'
        
        html_content += f"""
            <tr>
                <td>{date_str}</td>
                <td>{time_str}</td>
                <td>{batch.medicine.name}</td>
                <td>{h.old_price}</td>
                <td>{h.new_price}</td>
                <td>{user_name}</td>
            </tr>
"""
    
    html_content += """
        </tbody>
    </table>
</body>
</html>
"""
    
    response = HttpResponse(html_content, content_type='application/vnd.ms-excel; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="Narx_Tarixi_{batch.medicine.name}_{batch.batch_number or batch.id}.xls"'
    return response
