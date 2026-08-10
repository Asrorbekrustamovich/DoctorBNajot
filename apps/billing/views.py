from django.shortcuts import render, get_object_or_404, redirect
from django.views.generic import TemplateView, DetailView
from django.contrib import messages
from django.utils import timezone
from decimal import Decimal

from apps.accounts.permissions import RoleRequiredMixin, role_required
from apps.accounts.models import Role
from apps.registration.models import Visit
from .models import Invoice, Refund
from .services import generate_invoice_for_visit


def _invoice_locked(request, invoice):
    """Chek qulflangan bo'lsa va foydalanuvchi superadmin bo'lmasa — True (bloklash)."""
    if invoice is None:
        return False
    if invoice.is_locked and not invoice.can_modify(request.user):
        messages.error(request, "Chek qulflangan — faqat superadmin o'zgartira oladi.")
        return True
    return False


def _visit_invoice_locked(request, visit):
    """Vizitning cheki qulflanganini tekshiradi (bilvosita o'zgartirishlar uchun)."""
    inv = Invoice.objects.filter(visit=visit).first() if visit else None
    return _invoice_locked(request, inv)

class BillingDashboardView(RoleRequiredMixin, TemplateView):
    """Kassa va Buxgalteriya asosiy ekrani."""
    allowed_roles = (Role.Code.CASHIER, Role.Code.ACCOUNTANT, Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION)
    template_name = "billing/dashboard.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.has_role(Role.Code.ADMINISTRATOR, Role.Code.RECEPTION) and not request.user.has_role(Role.Code.CASHIER, Role.Code.ACCOUNTANT, Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN):
            return redirect("billing:registrator_payments")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        from django.db.models import Q
        from apps.patients.models import Patient

        context = super().get_context_data(**kwargs)

        # Kassa BEMORLAR bo'yicha ko'rsatiladi (har bemor bitta qator) —
        # navbat/tashrif bo'yicha emas, aks holda bir bemor takrorlanib chalkashadi.
        qs = Patient.objects.filter(visits__isnull=False).distinct()

        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(card_number__icontains=search)
                | Q(phone__icontains=search)
            )
        qs = qs.order_by("last_name", "first_name")[:200]

        rows = []
        for p in qs:
            invoices = list(p.invoices.select_related("visit").all())
            total = sum((i.total_amount or 0) for i in invoices)
            paid = sum((i.paid_amount or 0) for i in invoices)
            debt = sum((i.debt or 0) for i in invoices)
            open_count = sum(1 for i in invoices if (i.debt or 0) > 0)
            last_visit = p.visits.order_by("-visit_date", "-created_at").first()
            # Ochiq (to'lanmagan) cheki bo'lsa — tez ochish uchun o'sha tashrif
            open_invoice = next((i for i in invoices if (i.debt or 0) > 0 and i.visit_id), None)
            rows.append({
                "patient": p,
                "invoice_count": len(invoices),
                "total": total,
                "paid": paid,
                "debt": debt,
                "open_count": open_count,
                "last_visit": last_visit,
                "quick_visit_id": (open_invoice.visit_id if open_invoice
                                   else (last_visit.id if last_visit else None)),
            })
        # Qarzdorlar birinchi, keyin alifbo
        rows.sort(key=lambda r: (r["debt"] <= 0, r["patient"].last_name.lower()))

        context["rows"] = rows
        context["total_debt"] = sum(r["debt"] for r in rows)
        context["debtor_count"] = sum(1 for r in rows if r["debt"] > 0)
        return context


# Chekni KO'RISH — klinik va registratura xodimlari ham ko'ra oladi (faqat o'qish).
# Pul amallari (to'lov, qaytarish, bekor) esa quyidagi alohida view'larda
# kassir/buxgalter/direktor bilan cheklangan bo'lib qoladi.
_INVOICE_VIEW_ROLES = (
    Role.Code.CASHIER, Role.Code.ACCOUNTANT, Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN,
    Role.Code.ADMINISTRATOR, Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR,
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.RECEPTION,
    Role.Code.SURGEON, Role.Code.SURGERY_ADMIN,
)
_INVOICE_EDIT_ROLES = (
    Role.Code.CASHIER, Role.Code.ACCOUNTANT, Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN,
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
)


@role_required(*_INVOICE_VIEW_ROLES)
def view_invoice(request, visit_id):
    """Bitta vizit (bemor) ning hamma xarajatlarini ko'rish va hisoblash.

    Bemor boshqa shifokorga yo'naltirilgan bo'lsa ham Visit bitta,
    shuning uchun chek ham bitta bo'ladi (barcha xizmatlar shu yerda).

    Chekni barcha klinik/registratura xodimlari ko'ra oladi, lekin pul
    amallari (to'lov/qaytarish/bekor) faqat can_edit=True bo'lganda ko'rinadi.
    """
    visit = get_object_or_404(Visit, id=visit_id)

    # Har safar ko'rganda hisobni qaytadan avtomat yangilaymiz (toki u to'liq yopilmagan bo'lsa)
    invoice = generate_invoice_for_visit(visit)

    user = request.user
    can_edit = user.is_superuser or user.has_role(*_INVOICE_EDIT_ROLES)

    ctx = {
        "visit": visit,
        "invoice": invoice,
        "can_edit": can_edit,
    }
    # Rasmiy Word yuklab olish
    if request.GET.get("format") == "word":
        from django.template.loader import render_to_string
        from apps.core.exports import export_html_to_word
        ctx["word_export"] = True
        html = render_to_string("billing/invoice_detail.html", ctx, request=request)
        fname = f"Chek_{visit.patient.last_name}_{visit.patient.first_name}"
        return export_html_to_word(html, fname)
    return render(request, "billing/invoice_detail.html", ctx)


@role_required(*_INVOICE_EDIT_ROLES)
def edit_inpatient_days(request, stay_id):
    """Kassir yoki Buxgalterga statsionar yotish kunlarini o'zgartirish imkonini beradi."""
    if request.method == "POST":
        from apps.clinical.models import InpatientStay
        from django.db import transaction
        from .services import generate_invoice_for_visit
        
        stay = get_object_or_404(InpatientStay, id=stay_id)
        try:
            new_days = int(request.POST.get("total_days", stay.total_days))
            reason = request.POST.get("audit_reason", "").strip()
            
            if not reason:
                messages.error(request, "Tahrirlash sababini kiritish majburiy!")
                return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
                
            if new_days < 0:
                messages.error(request, "Kunlar soni manfiy bo'lishi mumkin emas.")
            elif new_days != stay.total_days:
                with transaction.atomic():
                    # 1. Update stay days
                    stay.total_days = new_days
                    
                    # 2. Recalculate stay amount
                    total = new_days * stay.daily_price
                    if stay.is_companion:
                        total += new_days * stay.companion_daily_price
                    stay.total_amount = total
                    
                    stay._audit_reason = reason
                    stay.save(update_fields=["total_days", "total_amount"])
                    
                    # 3. Regenerate invoice
                    generate_invoice_for_visit(stay.visit)
                    
                    messages.success(request, f"Bemorning yotish kunlari {new_days} kunga o'zgartirildi va chek qayta hisoblandi.")
            else:
                messages.info(request, "Kunlar soni o'zgarmadi.")
        except ValueError:
            messages.error(request, "Noto'g'ri raqam kiritildi.")
            
    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")

@role_required(*_INVOICE_EDIT_ROLES)
def cancel_inpatient_stay(request, stay_id):
    """Kassir yoki Buxgalterga statsionar yotishni bekor qilish imkonini beradi."""
    if request.method == "POST":
        from apps.clinical.models import InpatientStay
        from django.db import transaction
        from .services import generate_invoice_for_visit
        
        with transaction.atomic():
            stay = get_object_or_404(InpatientStay.objects.select_for_update(), id=stay_id)
            if _visit_invoice_locked(request, stay.visit):
                return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
            if stay.status == InpatientStay.Status.CANCELLED:
                messages.warning(request, "Bu xona allaqachon bekor qilingan.")
            else:
                stay.status = InpatientStay.Status.CANCELLED
                stay.save(update_fields=["status"])
                generate_invoice_for_visit(stay.visit)
                messages.success(request, "Xona yotishi bekor qilindi va chekdan o'chirildi.")
                
    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")


@role_required(*_INVOICE_EDIT_ROLES)
def pay_invoice(request, invoice_id):
    """To'lovni qabul qilish (Qisman yoki To'liq)."""
    if request.method == "POST":
        payment_amount_str = request.POST.get("amount", "0").replace(",", ".").strip()

        try:
            amount = Decimal(payment_amount_str)
        except Exception:
            messages.error(request, "Summani to'g'ri kiriting.")
            return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")

        from django.db import transaction
        with transaction.atomic():
            invoice = get_object_or_404(
                Invoice.objects.select_for_update(), id=invoice_id
            )

            if invoice.status == Invoice.Status.CANCELLED:
                messages.error(request, "Bekor qilingan chekka to'lov qabul qilinmaydi.")
            elif invoice.status == Invoice.Status.PAID:
                messages.warning(request, "Bu chek allaqachon to'liq to'langan.")
            elif amount <= 0:
                messages.warning(request, "Nol yoki manfiy summa kiritish mumkin emas.")
            elif amount > invoice.debt:
                messages.warning(
                    request,
                    f"Kiritilgan summa qarzdorlikdan katta. Qarzdorlik: {invoice.debt} so'm.",
                )
            else:
                # To'lovni qo'shish
                invoice.paid_amount += amount



                # Holatni yangilash (qaytarilgan pullar ham hisobga olinadi)
                invoice.recompute_status()
                if invoice.status == Invoice.Status.PAID and not invoice.paid_at:
                    invoice.paid_at = timezone.now()

                invoice.cashier = request.user
                invoice.save()

                # To'langan pulni bandlarga taqsimlaymiz. Oldindan
                # to'lanadigan bandlar (qabul, tekshiruvlar) birinchi
                # qoplanadi — shundan keyingina laboratoriya bemorni
                # chaqira oladi.
                from apps.billing.services import settle_prepaid_items
                settle_prepaid_items(invoice, cashier=request.user)
                messages.success(
                    request,
                    f"{amount} so'm to'lov qabul qilindi. "
                    f"Qarzdorlik: {max(Decimal(0), invoice.debt)} so'm.",
                )

    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")


@role_required(*_INVOICE_EDIT_ROLES)
def refund_invoice(request, invoice_id):
    """Pul qaytarish (xatolik, otmen yoki dori qaytarilishi sababli).

    Faqat amalda to'langan (va hali qaytarilmagan) summa doirasida
    qaytariladi. Har bir qaytarish sabab bilan tarixda saqlanadi.
    """
    if request.method != "POST":
        return redirect("billing:dashboard")

    amount_str = request.POST.get("amount", "0").replace(",", ".").strip()
    reason = request.POST.get("reason", "").strip()

    try:
        amount = Decimal(amount_str)
    except Exception:
        messages.error(request, "Summani to'g'ri kiriting.")
        return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")

    from django.db import transaction
    with transaction.atomic():
        invoice = get_object_or_404(Invoice.objects.select_for_update(), id=invoice_id)

        if _invoice_locked(request, invoice):
            return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
        if not reason:
            messages.error(request, "Qaytarish sababini yozish shart.")
        elif invoice.status == Invoice.Status.CANCELLED:
            messages.error(request, "Bekor qilingan chek bo'yicha qaytarish mumkin emas.")
        elif amount <= 0:
            messages.warning(request, "Nol yoki manfiy summa kiritish mumkin emas.")
        elif amount > invoice.refundable_amount:
            messages.warning(
                request,
                f"Qaytarish summasi to'langan puldan oshmasligi kerak. "
                f"Maksimal: {invoice.refundable_amount} so'm.",
            )
        else:
            Refund.objects.create(
                invoice=invoice, amount=amount, reason=reason,
                refunded_by=request.user,
            )
            invoice.refunded_amount += amount

            if hasattr(invoice, 'visit') and invoice.visit and invoice.visit.doctor:
                share_amount = -(amount / Decimal('3'))
                from apps.billing.models import DoctorShare
                DoctorShare.objects.create(
                    doctor=invoice.visit.doctor,
                    invoice=invoice,
                    amount=share_amount,
                    description=f"Qaytarilgan to'lov uchun ulush chegirildi ({amount} so'm)"
                )
            invoice.recompute_status()
            invoice.cashier = request.user
            invoice.save()
            messages.success(
                request,
                f"{amount} so'm qaytarildi ({reason}). "
                f"Kassada qolgan: {invoice.net_paid} so'm.",
            )

    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")


@role_required(*_INVOICE_EDIT_ROLES, Role.Code.DOCTOR)
def cancel_service_order(request, order_id):
    """Xizmat buyurtmasini otmen qilish — chekdan avtomatik chiqadi.

    Agar chek allaqachon to'langan bo'lsa, ortiqcha summa chekda
    "qaytarilishi lozim" bo'lib ko'rinadi va kassir uni qaytaradi.
    """
    from apps.clinical.models import ServiceOrder

    if request.method != "POST":
        return redirect("billing:dashboard")

    from django.db import transaction
    with transaction.atomic():
        order = get_object_or_404(
            ServiceOrder.objects.select_for_update().select_related("visit", "service"),
            id=order_id,
        )
        if _visit_invoice_locked(request, order.visit):
            return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
        if order.status == ServiceOrder.Status.CANCELLED:
            messages.warning(request, "Bu xizmat allaqachon bekor qilingan.")
        elif order.status in (ServiceOrder.Status.IN_PROGRESS, ServiceOrder.Status.COMPLETED):
            messages.error(
                request,
                "Bajarilayotgan/bajarilgan xizmatni otmen qilib bo'lmaydi. "
                "Xatolik bo'lsa, pul qaytarish bo'limidan foydalaning.",
            )
        else:
            order.status = ServiceOrder.Status.CANCELLED
            order.result_text = (
                f"Otmen qilindi: {request.user.get_full_name() or request.user.username}. "
                + request.POST.get("reason", "").strip()
            ).strip()
            order.save(update_fields=["status", "result_text"])
            generate_invoice_for_visit(order.visit)
            messages.success(request, f"'{order.service.name}' xizmati bekor qilindi, chek yangilandi.")

    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")


@role_required(*_INVOICE_EDIT_ROLES)
def return_medicine(request, dispense_id):
    """Dorini qaytarib olish: ombor qoldig'i tiklanadi, chek yangilanadi."""
    from apps.pharmacy.models import MedicineBatch, MedicineDispense

    if request.method != "POST":
        return redirect("billing:dashboard")

    from django.db import transaction
    with transaction.atomic():
        dispense = get_object_or_404(
            MedicineDispense.objects.select_for_update().select_related("batch__medicine", "visit"),
            id=dispense_id,
        )
        if _visit_invoice_locked(request, dispense.visit):
            return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
        if dispense.is_returned:
            messages.warning(request, "Bu dori allaqachon qaytarilgan.")
        else:
            dispense.is_returned = True
            dispense.returned_at = timezone.now()
            dispense.returned_by = request.user
            dispense.return_reason = request.POST.get("reason", "").strip()
            dispense.save(update_fields=[
                "is_returned", "returned_at", "returned_by", "return_reason",
            ])

            # Ombor qoldig'ini tiklash
            batch = MedicineBatch.objects.select_for_update().get(pk=dispense.batch_id)
            batch.quantity_available += dispense.quantity
            batch.save(update_fields=["quantity_available"])

            generate_invoice_for_visit(dispense.visit)
            messages.success(
                request,
                f"{dispense.batch.medicine.name} (x{dispense.quantity}) qaytarib olindi, "
                "ombor qoldig'i tiklandi, chek yangilandi.",
            )

    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")


@role_required(*_INVOICE_EDIT_ROLES)
def edit_medicine_quantity(request, dispense_id):
    """Kassir yoki dorixonachiga dori miqdorini tahrirlash imkonini beradi."""
    from apps.pharmacy.models import MedicineBatch, MedicineDispense
    from .services import generate_invoice_for_visit
    
    if request.method == "POST":
        from django.db import transaction
        from decimal import Decimal
        
        try:
            new_qty = Decimal(request.POST.get("quantity", "0").replace(",", "."))
            reason = request.POST.get("audit_reason", "").strip()
            
            if not reason:
                messages.error(request, "Tahrirlash sababini kiritish majburiy!")
                return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
                
            if new_qty < 0:
                messages.error(request, "Miqdor manfiy bo'lishi mumkin emas.")
                return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
        except Exception:
            messages.error(request, "Miqdorni to'g'ri kiriting.")
            return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
            
        with transaction.atomic():
            dispense = get_object_or_404(
                MedicineDispense.objects.select_for_update().select_related("batch__medicine", "visit"),
                id=dispense_id,
            )
            
            if dispense.is_returned:
                messages.error(request, "Qaytarilgan dorining miqdorini tahrirlab bo'lmaydi.")
            elif new_qty != dispense.quantity:
                batch = MedicineBatch.objects.select_for_update().get(pk=dispense.batch_id)
                diff = new_qty - dispense.quantity
                
                # Agar miqdor oshsa, omborda yetarlimi tekshiramiz
                if diff > 0 and batch.quantity_available < diff:
                    messages.error(request, f"Omborda yetarli qoldiq yo'q. Qoldiq: {batch.quantity_available}")
                else:
                    batch.quantity_available -= diff
                    batch.save(update_fields=["quantity_available"])
                    
                    dispense.quantity = new_qty
                    dispense._audit_reason = reason
                    dispense.save(update_fields=["quantity"])
                    
                    generate_invoice_for_visit(dispense.visit)
                    messages.success(request, f"{dispense.batch.medicine.name} miqdori {new_qty} ga o'zgartirildi.")
            else:
                messages.info(request, "Miqdor o'zgarmadi.")
                
    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")

@role_required(*_INVOICE_EDIT_ROLES)
def edit_consultation_fee(request, cons_id):
    """Kassir yoki Buxgalterga shifokor qabuli narxini tahrirlash imkonini beradi."""
    from apps.clinical.models import Consultation
    from .services import generate_invoice_for_visit
    
    if request.method == "POST":
        from django.db import transaction
        from decimal import Decimal
        
        try:
            new_fee = Decimal(request.POST.get("fee", "0").replace(",", "."))
            reason = request.POST.get("audit_reason", "").strip()
            
            if not reason:
                messages.error(request, "Tahrirlash sababini kiritish majburiy!")
                return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
                
            if new_fee < 0:
                messages.error(request, "Narx manfiy bo'lishi mumkin emas.")
                return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
        except Exception:
            messages.error(request, "Narxni to'g'ri kiriting.")
            return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")
            
        with transaction.atomic():
            cons = get_object_or_404(Consultation.objects.select_for_update(), id=cons_id)
            if cons.fee != new_fee:
                cons.fee = new_fee
                cons._audit_reason = reason
                cons.save(update_fields=["fee"])
                generate_invoice_for_visit(cons.visit)
                messages.success(request, "Shifokor qabuli narxi muvaffaqiyatli o'zgartirildi.")
            else:
                messages.info(request, "Narx o'zgarmadi.")
                
    return redirect(request.META.get('HTTP_REFERER') or "billing:dashboard")


@role_required(*_INVOICE_VIEW_ROLES)
def patient_invoices(request, patient_id):
    """Bemorning BARCHA cheklari ro'yxati (har tashrif — alohida chek).

    Har bir kelishi uchun alohida chek ochiladi: qachon ochilgani,
    qachon yopilgani (to'langani), summasi va qarzi ko'rinadi.
    Eski chek ustiga qo'shilmaydi.
    """
    from apps.patients.models import Patient
    from apps.billing.models import Invoice

    patient = get_object_or_404(Patient, id=patient_id)
    invoices = (
        Invoice.objects.filter(patient=patient)
        .select_related("visit", "cashier")
        .prefetch_related("items")
        .order_by("-created_at")
    )

    totals = {
        "count": invoices.count(),
        "total": sum((i.total_amount or 0) for i in invoices),
        "paid": sum((i.paid_amount or 0) for i in invoices),
        "refunded": sum((i.refunded_amount or 0) for i in invoices),
        "debt": sum((i.debt or 0) for i in invoices),
        "open_count": sum(1 for i in invoices if (i.debt or 0) > 0),
    }

    user = request.user
    return render(request, "billing/patient_invoices.html", {
        "patient": patient,
        "invoices": invoices,
        "totals": totals,
        "can_edit": user.is_superuser or user.has_role(*_INVOICE_EDIT_ROLES),
    })

@role_required(*_INVOICE_EDIT_ROLES)
def registrator_payments(request):
    """Registrator uchun to'lov qabul qilish sahifasi.
    
    Faqat bugungi va oldindan to'lanishi kerak bo'lgan (ambulator ko'rik,
    tekshiruvlar) xizmatlar ko'rsatiladi.
    """
    from django.db.models import Q, Sum, F
    from apps.billing.models import Invoice, InvoiceItem
    from apps.registration.models import Visit
    from apps.clinical.models import ServiceOrder
    
    today = timezone.localdate()
    
    # Bugungi navbatdagi bemorlarning cheklari
    today_visits = Visit.objects.filter(
        visit_date=today
    ).select_related('patient', 'doctor').order_by('queue_number')
    
    rows = []
    for visit in today_visits:
        invoice = Invoice.objects.filter(visit=visit).first()
        if not invoice:
            # Chek hali yaratilmagan bo'lishi mumkin
            from .services import generate_invoice_for_visit
            invoice = generate_invoice_for_visit(visit)
        
        # Oldindan to'lanishi kerak bo'lgan bandlar (xizmat = ambulator ko'rik + tekshiruvlar)
        prepaid_items = list(invoice.items.filter(
            payment_mode=InvoiceItem.PaymentMode.PREPAID
        ).order_by('created_at'))
        
        prepaid_total = sum(i.total_price or 0 for i in prepaid_items)
        prepaid_paid = sum(i.total_price or 0 for i in prepaid_items if i.paid_at)
        prepaid_unpaid = prepaid_total - prepaid_paid
        
        # Tekshiruvlar (ServiceOrder) holati
        service_orders = list(visit.service_orders.exclude(
            status=ServiceOrder.Status.CANCELLED
        ).select_related('service'))
        
        rows.append({
            'visit': visit,
            'invoice': invoice,
            'prepaid_items': prepaid_items,
            'prepaid_total': prepaid_total,
            'prepaid_paid': prepaid_paid,
            'prepaid_unpaid': prepaid_unpaid,
            'service_orders': service_orders,
            'has_unpaid': prepaid_unpaid > 0,
        })
    
    # To'lanmagan bemorlar birinchi
    rows.sort(key=lambda r: (not r['has_unpaid'], r['visit'].queue_number))
    
    total_unpaid = sum(r['prepaid_unpaid'] for r in rows)
    unpaid_count = sum(1 for r in rows if r['has_unpaid'])
    
    return render(request, 'billing/registrator_payments.html', {
        'rows': rows,
        'total_unpaid': total_unpaid,
        'unpaid_count': unpaid_count,
        'today': today,
    })


class SuperadminStatisticsView(RoleRequiredMixin, TemplateView):
    """Umumiy statistika va Moliya paneli (faqat Superadmin va Direktor uchun)."""
    allowed_roles = (Role.Code.SUPER_ADMIN, Role.Code.DIRECTOR)
    template_name = "billing/superadmin_statistics.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.clinical.models import SurgerySchedule, InpatientStay
        from apps.registration.models import Visit
        from django.db.models import Sum, Count, F
        
        # Filtirlash uchun oy tanlash (default: joriy oy)
        month = self.request.GET.get("month")
        year = self.request.GET.get("year")
        now = timezone.now()
        
        try:
            target_month = int(month) if month else now.month
            target_year = int(year) if year else now.year
        except ValueError:
            target_month, target_year = now.month, now.year

        context["current_month"] = target_month
        context["current_year"] = target_year
        context["months"] = range(1, 13)
        context["years"] = range(now.year - 2, now.year + 2)

        # Asosiy QuerySetlar (Faqat tanlangan oy bo'yicha)
        surgeries = SurgerySchedule.objects.filter(
            scheduled_time__year=target_year, scheduled_time__month=target_month, status=SurgerySchedule.Status.COMPLETED
        ).select_related("surgery_type", "surgeon", "visit__patient")
        
        inpatient_stays = InpatientStay.objects.filter(
            created_at__year=target_year, created_at__month=target_month, is_companion=False
        ).select_related("visit__patient", "bed__room")
        
        ambulatory_visits = Visit.objects.filter(
            created_at__year=target_year, created_at__month=target_month
        ).select_related("patient", "doctor").annotate(
            is_inpatient=Count('inpatient_stays')
        ).filter(is_inpatient=0) # Faqat statsionarga yotmaganlar

        # 1. Operatsiyalar Moliya
        surgery_revenue = sum(s.actual_price or 0 for s in surgeries)
        surgery_profit = sum(s.surgery_profit or 0 for s in surgeries)
        surgery_clinic_expense = surgery_revenue - surgery_profit # Klinika chiqimlari (dorilar, oyliklar)
        
        # 2. Statsionar Moliya (Yotish kunlari xarajatlari)
        inpatient_revenue = sum(s.total_amount or 0 for s in inpatient_stays)
        
        # 3. Ambulator Moliya
        ambulatory_revenue = sum(v.consultation.fee or 0 for v in ambulatory_visits if hasattr(v, 'consultation'))

        # 4. Shifokorlar Ulushi (Kassaga to'langan puldan ajratilgan 1/3)
        from apps.billing.models import DoctorShare
        total_doctor_shares = DoctorShare.objects.filter(
            created_at__year=target_year, created_at__month=target_month
        ).aggregate(total=Sum('amount'))['total'] or 0


        context.update({
            "surgeries": surgeries,
            "inpatient_stays": inpatient_stays,
            "ambulatory_visits": ambulatory_visits[:100], # Ko'p bo'lsa 100 ta ko'rsatish
            
            "surgery_revenue": surgery_revenue,
            "surgery_profit": surgery_profit,
            "surgery_clinic_expense": surgery_clinic_expense,
            
            "inpatient_revenue": inpatient_revenue,
            "ambulatory_revenue": ambulatory_revenue,
            "total_doctor_shares": total_doctor_shares,
            
            "total_revenue": surgery_revenue + inpatient_revenue + ambulatory_revenue,
            "total_net_profit": surgery_profit + inpatient_revenue + ambulatory_revenue - total_doctor_shares,
        })
        return context


@role_required(*_INVOICE_EDIT_ROLES)
def edit_surgery_price(request, surgery_id):
    """Operatsiya narxini tahrirlash."""
    from apps.clinical.models import SurgerySchedule
    from .services import generate_invoice_for_visit
    
    if request.method == "POST":
        from django.db import transaction
        from decimal import Decimal
        
        try:
            new_price = Decimal(request.POST.get("price", "0").replace(",", "."))
            reason = request.POST.get("audit_reason", "").strip()
            
            if not reason:
                messages.error(request, "Tahrirlash sababini kiritish majburiy!")
                return redirect(request.META.get('HTTP_REFERER') or "billing:registrator_payments")
                
            if new_price < 0:
                messages.error(request, "Narx manfiy bo'lishi mumkin emas.")
                return redirect(request.META.get('HTTP_REFERER') or "billing:registrator_payments")
        except Exception:
            messages.error(request, "Narxni to'g'ri kiriting.")
            return redirect(request.META.get('HTTP_REFERER') or "billing:registrator_payments")
            
        with transaction.atomic():
            surgery = get_object_or_404(SurgerySchedule.objects.select_for_update(), id=surgery_id)
            if surgery.actual_price != new_price:
                surgery.actual_price = new_price
                surgery._audit_reason = reason
                surgery.save(update_fields=["actual_price"])
                generate_invoice_for_visit(surgery.visit)
                messages.success(request, "Operatsiya narxi muvaffaqiyatli o'zgartirildi.")
            else:
                messages.info(request, "Narx o'zgarmadi.")
                
    return redirect(request.META.get('HTTP_REFERER') or "billing:registrator_payments")


@role_required(*_INVOICE_EDIT_ROLES)
def cancel_surgery(request, surgery_id):
    """Operatsiyani bekor qilish (chekdan o'chirish)."""
    from apps.clinical.models import SurgerySchedule
    from .services import generate_invoice_for_visit
    
    if request.method == "POST":
        from django.db import transaction
        with transaction.atomic():
            surgery = get_object_or_404(SurgerySchedule.objects.select_for_update(), id=surgery_id)
            if surgery.status == SurgerySchedule.Status.CANCELLED:
                messages.warning(request, "Bu operatsiya allaqachon bekor qilingan.")
            else:
                surgery.status = SurgerySchedule.Status.CANCELLED
                surgery.save(update_fields=["status"])
                generate_invoice_for_visit(surgery.visit)
                messages.success(request, "Operatsiya bekor qilindi va chekdan o'chirildi.")
                
    return redirect(request.META.get('HTTP_REFERER') or "billing:registrator_payments")
