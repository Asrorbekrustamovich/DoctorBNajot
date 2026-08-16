from django.contrib import messages
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.views.generic import CreateView, TemplateView, View
from django.db import transaction
from django.utils import timezone
from django.http import JsonResponse
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin

User = get_user_model()

from apps.accounts.permissions import RoleRequiredMixin, role_required
from apps.core.exceptions import DomainError
from apps.registration.models import Visit
from apps.registration import services as registration_services
from apps.clinical.models import (
    Consultation, ConsultationTemplate, DoctorPrice, ServiceOrder,
    ProcedureRecord, StayChecklistItem, SurgeryReport, ServiceCatalog,
    Room, Bed, InpatientStay, SurgeryType, SurgicalItem, SurgerySchedule,
    AnesthesiaRequest, SurgeryVitals, NurseUsageItem,
    ServiceCategory, ServiceResultRow, ResultTemplateRow, AmbulatoryRoom,
)
from apps.clinical.forms import ConsultationForm

# Visit shu holatlarda shifokor tomonidan tahrirlanishi mumkin
OPEN_VISIT_STATUSES = (
    Visit.Status.WAITING, Visit.Status.ACCEPTED, Visit.Status.IN_PROGRESS,
)


# --------------------------------------------------------------------------
# YANGA TIZIM (HTMX + Modal + Quill)
# --------------------------------------------------------------------------

class ConsultationModalView(RoleRequiredMixin, TemplateView):
    """Qabul xulosasi uchun HTMX Modal (Quill editor)."""
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]
    template_name = "clinical/modals/consultation_modal.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        visit = get_object_or_404(Visit, pk=self.kwargs["pk"])
        context["visit"] = visit
        templates = ConsultationTemplate.objects.filter(doctor=self.request.user)
        context["templates"] = templates
        # JS uchun xavfsiz JSON (json_script orqali chiqariladi)
        context["templates_map"] = {
            str(t.id): {"name": t.name, "html": t.report_html or ""}
            for t in templates
        }

        # O'z xulosasi oldin bor bo'lsa
        existing = Consultation.objects.filter(visit=visit, doctor=self.request.user).first()
        context["existing_report"] = existing.report_html if existing else ""

        # Tekshiruvlar — guruhlangan daraxt («+Analiz», «+UZI», …).
        # Tekis ro'yxat 60 dan ortiq xizmatda ishlatib bo'lmas edi.
        from apps.clinical import selectors as clinical_selectors

        assigned = {
            str(sid) for sid in visit.service_orders.exclude(
                status=ServiceOrder.Status.CANCELLED
            ).values_list("service_id", flat=True)
        }
        context["exam_groups"] = clinical_selectors.exam_picker_groups(assigned)
        context["assign_url"] = reverse(
            "clinical:consultation_assign_services", args=[visit.pk]
        )

        # JAVOBI KELMAGAN TEKSHIRUVLAR — «Yakunlash» tugmasi shularga qarab
        # yopiladi. Serverdagi tekshiruv bilan BIR XIL shart bo'lishi kerak,
        # aks holda tugma ochiq turadi-yu, bosilganda xato chiqadi.
        context["pending_exams"] = pending_exam_orders(visit)

        # STATSIONARGA YO'NALTIRISH HOLATI.
        #
        # Modal qayta ochilganda tugma to'g'ri ko'rinishi kerak: agar
        # allaqachon yuborilgan bo'lsa — kulrang «yuborildi», yonida
        # bekor qilish. Aks holda shifokor ikkinchi marta bosib,
        # o'zi ham bilmagan holda takror yuborardi.
        from apps.clinical.models import AdmissionEpisode

        context["open_episode"] = (
            AdmissionEpisode.objects
            .filter(patient=visit.patient,
                    status__in=[AdmissionEpisode.Status.DRAFT,
                                AdmissionEpisode.Status.SENT,
                                AdmissionEpisode.Status.ADMITTED])
            .order_by("-created_at").first()
        )
        # Tayinlangan tekshiruvlar va ularning natijalari — shifokor
        # qabul oynasidan chiqmasdan ko'radi.
        context["exam_orders"] = clinical_selectors.visit_exam_orders(visit)
        context["existing_orders"] = list(assigned)

        # Boshqa shifokorlar (yo'naltirish uchun)
        context["doctors"] = User.objects.filter(
            Q(role__code="doctor") | Q(role__code="chief_doctor"),
            is_active=True
        ).exclude(id=self.request.user.id).order_by("last_name")

        return context

def pending_exam_orders(visit):
    """Javobi hali chiqmagan tekshiruvlar.

    BITTA MANBA: ekrandagi «Yakunlash» tugmasi ham, serverdagi tekshiruv
    ham shu funksiyadan foydalanadi. Shart ikki joyda alohida yozilsa,
    ular albatta ajralib ketadi — tugma ochiq turadi-yu, bosilganda xato
    chiqadi (yoki teskarisi).

    Bekor qilinganlar hisobga olinmaydi: ular allaqachon «kerak emas»
    deb belgilangan.
    """
    return [
        o for o in visit.service_orders
        .exclude(status=ServiceOrder.Status.CANCELLED)
        .select_related("service")
        if not o.has_result
    ]


class ConsultationSaveModalView(RoleRequiredMixin, View):
    """Ajax orqali Modal dan saqlash."""
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]

    @transaction.atomic
    def post(self, request, pk):
        visit = get_object_or_404(Visit, pk=pk)
        if visit.status not in OPEN_VISIT_STATUSES:
            return JsonResponse({"error": "Qabul yopiq."}, status=400)
            
        report_html = request.POST.get("report_html", "")
        status = request.POST.get("status", "completed")

        # Qulflangan xulosani faqat superadmin o'zgartira oladi
        existing = Consultation.objects.filter(visit=visit, doctor=request.user).first()
        if existing and not existing.can_modify(request.user):
            return JsonResponse({"error": "Xulosa qulflangan — faqat superadmin o'zgartira oladi."}, status=403)

        # Xulosani saqlash
        consultation, _ = Consultation.objects.update_or_create(
            visit=visit,
            doctor=request.user,
            defaults={"report_html": report_html}
        )
        if request.POST.get("lock") == "1":
            consultation.lock(request.user)

        # Narx belgilash
        if consultation.fee == 0:
            doc_price = DoctorPrice.objects.filter(doctor=request.user, is_active=True).first()
            if doc_price:
                consultation.fee = doc_price.price
                consultation.save(update_fields=["fee"])

        # Tayinlangan xizmatlar (UZI, EKG va h.k.)
        recommended_services = request.POST.getlist("recommended_services")
        if recommended_services:
            for service_id in recommended_services:
                if not ServiceOrder.objects.filter(visit=visit, service_id=service_id).exclude(
                    status=ServiceOrder.Status.CANCELLED
                ).exists():
                    ServiceOrder.objects.create(
                        visit=visit,
                        service_id=service_id,
                        status=ServiceOrder.Status.WAITING,
                    )

        # TAYINLANGAN TEKSHIRUV NATIJASIZ QOLSA — YAKUNLAB BO'LMAYDI.
        #
        # Shifokor tekshiruv buyurgan bo'lsa, uning javobini ko'rmasdan
        # qabulni yopishi mantiqsiz: tashxis nimaga asoslanadi? Bundan
        # tashqari yopilgan qabulga natija kelsa, uni hech kim ko'rmay
        # qoladi va bemor javobini olmasdan ketadi.
        #
        # Bekor qilinganlar hisobga olinmaydi — ular allaqachon
        # «kerak emas» deb belgilangan.
        if status == "completed":
            natijasiz = pending_exam_orders(visit)
            if natijasiz:
                nomlar = ", ".join(o.service.name for o in natijasiz[:5])
                if len(natijasiz) > 5:
                    nomlar += f" va yana {len(natijasiz) - 5} ta"
                return JsonResponse({
                    "error": (
                        f"Qabulni yakunlab bo'lmaydi: {len(natijasiz)} ta "
                        f"tekshiruvning javobi hali chiqmagan ({nomlar}). "
                        f"Natijani kuting yoki keraksizini bekor qiling. "
                        f"Hozircha «Saqlab turish» tugmasidan foydalaning."
                    )
                }, status=400)

        # Statusni FSM zanjiri bo'yicha o'zgartirish
        # (waiting → accepted → in_progress → completed)
        try:
            if status == "completed":
                if visit.doctor_id and visit.doctor_id != request.user.pk:
                    # Bemor boshqa shifokorga yo'naltirilgan — faqat o'z
                    # xulosamiz saqlanadi, qabulni u yakunlaydi.
                    messages.success(request, "Xulosangiz saqlandi (qabul keyingi shifokorda).")
                    return JsonResponse({"status": "ok"})
                if visit.status == Visit.Status.WAITING:
                    registration_services.visit_transition(visit=visit, new_status=Visit.Status.ACCEPTED)
                if visit.status == Visit.Status.ACCEPTED:
                    registration_services.visit_transition(visit=visit, new_status=Visit.Status.IN_PROGRESS)
                if visit.status == Visit.Status.IN_PROGRESS:
                    registration_services.visit_transition(visit=visit, new_status=Visit.Status.COMPLETED)
            elif status == "in_progress" and visit.status != Visit.Status.IN_PROGRESS:
                if visit.status == Visit.Status.WAITING:
                    registration_services.visit_transition(visit=visit, new_status=Visit.Status.ACCEPTED)
                if visit.status == Visit.Status.ACCEPTED:
                    registration_services.visit_transition(visit=visit, new_status=Visit.Status.IN_PROGRESS)
        except DomainError as exc:
            return JsonResponse({"error": exc.message}, status=400)

        messages.success(request, "Xulosa saqlandi!")
        return JsonResponse({"status": "ok"})


def surgery_team_context():
    """«Operatsiyaga yozish» oynasi uchun umumiy tanlov ro'yxatlari.

    Bitta joyda saqlanadi — aks holda oyna qaysi sahifadan ochilganiga qarab
    har xil maydonlarni ko'rsatib qolardi (jarrohlik paneli to'liq, bemor
    kartasi esa faqat 4 ta maydon bilan).
    """
    from apps.clinical.models import OperatingRoom

    from apps.accounts.models import users_with_role

    # QO'SHIMCHA ROLLAR HAM HISOBGA OLINADI.
    #
    # Ilgari bu yerda `role__code=...` deb faqat asosiy rol qidirilardi
    # va «Jarroh» hamda «Anesteziolog» ro'yxatlari bo'm-bo'sh chiqardi:
    # klinikadagi xirurglarning asosiy roli «shifokor» (ular ambulator
    # qabul ham qiladi), jarrohlik esa qo'shimcha rol.
    return {
        "surgery_types": SurgeryType.objects.filter(is_active=True).order_by("name"),
        "surgeons": users_with_role(Role.Code.SURGEON),
        # ANESTIZISKA — anesteziologning yordamchisi.
        #
        # Bu maydon ilgari «Operatsion asistent» deb atalardi va unga
        # shifokorlar ham, hamshiralar ham aralash chiqardi. Amalda esa
        # bu o'rinda anestiziska turadi — hamshira. Shifokorlar ro'yxatga
        # tushishi faqat chalkashtirardi.
        "assistants": users_with_role(Role.Code.NURSE, Role.Code.WARD_NURSE),
        "anesthesiologists": users_with_role(Role.Code.ANESTHESIOLOGIST),
        "operating_nurses": users_with_role(Role.Code.NURSE, Role.Code.WARD_NURSE),
        "ward_nurses": users_with_role(Role.Code.WARD_NURSE),
        "operating_rooms": OperatingRoom.objects.filter(is_active=True).order_by("name"),
    }


class AssignServicesAjaxView(RoleRequiredMixin, View):
    """Qabul oynasini yopmasdan turib xizmatlarni (UZI, EKG) tayinlash uchun AJAX endpoint."""
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]

    @transaction.atomic
    def post(self, request, pk):
        visit = get_object_or_404(Visit, pk=pk)
        if visit.status not in OPEN_VISIT_STATUSES:
            return JsonResponse({"error": "Qabul yopiq. Xizmat tayinlab bo'lmaydi."}, status=400)

        recommended_services = request.POST.getlist("services")
        if not recommended_services:
            return JsonResponse({"error": "Hech qanday xizmat tanlanmadi."}, status=400)

        assigned_count = 0
        for service_id in recommended_services:
            if not ServiceOrder.objects.filter(visit=visit, service_id=service_id).exclude(
                status=ServiceOrder.Status.CANCELLED
            ).exists():
                ServiceOrder.objects.create(
                    visit=visit,
                    service_id=service_id,
                    status=ServiceOrder.Status.WAITING,
                )
                assigned_count += 1
                
        return JsonResponse({
            "status": "ok", 
            "message": f"{assigned_count} ta xizmat muvaffaqiyatli tayinlandi." if assigned_count else "Bu xizmatlar allaqachon tayinlangan."
        })



class SurgeryActView(LoginRequiredMixin, View):
    def get(self, request, schedule_id):
        from apps.clinical.models import SurgerySchedule, NurseUsageItem, AnesthesiaRequestItem
        from django.utils import timezone
        
        surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
        
        nurse_usages = NurseUsageItem.objects.filter(surgery=surgery).select_related('stock')
        
        anesthesia_request = getattr(surgery, 'anesthesia_request', None)
        anesthesia_usages = []
        if anesthesia_request:
            anesthesia_usages = anesthesia_request.items.all().select_related('stock')
            
        surgical_items = surgery.items_used.all()
        
        context = {
            "surgery": surgery,
            "nurse_usages": nurse_usages,
            "anesthesia_usages": anesthesia_usages,
            "surgical_items": surgical_items,
            "today": timezone.now(),
        }
        return render(request, "clinical/surgery_act_report.html", context)

class SurgeryReportView(RoleRequiredMixin, TemplateView):
    """Jarrohlik operatsiyasi bayonnomasini RASMIY (chop etish) ko'rinishda ochish."""
    allowed_roles = [
        "super_admin", "administrator", "chief_doctor", "doctor",
        "nurse", "ward_nurse", "reception", "director", "surgeon", "surgery_admin",
    ]
    template_name = "clinical/surgery_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.clinical.models import SurgerySchedule
        surgery = get_object_or_404(
            SurgerySchedule.objects.select_related("report", "visit__patient", "surgeon", "surgery_type"),
            pk=self.kwargs["schedule_id"]
        )
        context["surgery"] = surgery
        # BAYONNOMA HALI YOZILMAGAN BO'LISHI MUMKIN.
        #
        # `surgery.report` to'g'ridan-to'g'ri o'qilsa, yozuv yo'q paytda
        # `RelatedObjectDoesNotExist` ko'tarilib, sahifa 500 bilan
        # yiqilardi. Operatsiya rejalashtirilgan, lekin hali
        # o'tkazilmagan holat esa mutlaqo oddiy.
        context["report"] = getattr(surgery, "report", None)
        context["visit"] = surgery.visit
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if context["report"] is None:
            messages.warning(
                request,
                "Bu operatsiya bo'yicha bayonnoma hali yozilmagan.")
            return redirect("clinical:surgery_process",
                            schedule_id=self.kwargs["schedule_id"])
        if request.GET.get('format') == 'word':
            from django.template.loader import render_to_string
            from apps.core.exports import export_html_to_word
            
            context['word_export'] = True
            html = render_to_string(self.template_name, context, request=request)
            filename = f"Operatsiya_bayonnomasi_{context['visit'].patient.last_name}_{context['visit'].patient.first_name}"
            return export_html_to_word(html, filename)
        return self.render_to_response(context)


class ConsultationReportView(RoleRequiredMixin, TemplateView):
    """Saqlangan tibbiy xulosani RASMIY (chop etish) ko'rinishda ochish.

    Tizimning istalgan joyidan (bemor tarixi, navbat va h.k.) kimdir
    xulosani ko'rmoqchi bo'lsa — shu sahifa ochiladi: klinika sarlavhasi,
    bemor ma'lumotlari (Ismi familiyasi, Karta, Sana yorliqlari bilan),
    xulosa matni va shifokor imzo joyi.
    """
    allowed_roles = [
        "super_admin", "administrator", "chief_doctor", "doctor",
        "nurse", "ward_nurse", "reception", "director",
    ]
    template_name = "clinical/consultation_report.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        consultation = get_object_or_404(
            Consultation.objects.select_related(
                "visit__patient", "doctor", "doctor__role"
            ),
            pk=self.kwargs["pk"],
        )
        context["consultation"] = consultation
        context["visit"] = consultation.visit
        return context

    def get(self, request, *args, **kwargs):
        context = self.get_context_data(**kwargs)
        if request.GET.get('format') == 'word':
            from django.template.loader import render_to_string
            from apps.core.exports import export_html_to_word
            
            context['word_export'] = True
            html = render_to_string(self.template_name, context, request=request)
            filename = f"Xulosa_{context['visit'].patient.last_name}_{context['visit'].patient.first_name}"
            return export_html_to_word(html, filename)
        return self.render_to_response(context)


class PatientSummaryView(RoleRequiredMixin, TemplateView):
    """BEMOR UMUMIY HISOBOTI — hamma ma'lumot bitta joyda.

    Barcha tashriflar xronologik: shifokor xulosalari, tekshiruvlar,
    dorilar, statsionar yotishlar (hujjatlar, muolajalar, BEMOR IMZOSI),
    operatsiyalar (bayonnoma bilan) va moliyaviy yakun (cheklar).
    """
    allowed_roles = [
        "super_admin", "administrator", "chief_doctor", "doctor",
        "nurse", "ward_nurse", "reception", "director", "surgeon",
        "surgery_admin", "cashier", "accountant",
    ]
    template_name = "clinical/patient_summary.html"

    def get_context_data(self, **kwargs):
        from apps.patients.models import Patient
        from decimal import Decimal

        context = super().get_context_data(**kwargs)
        patient = get_object_or_404(Patient, pk=self.kwargs["patient_id"])

        visits = (
            patient.visits.select_related("doctor")
            .prefetch_related(
                "consultations__doctor",
                "service_orders__service",
                "service_orders__performed_by",
                "dispensed_medicines__batch__medicine",
                "inpatient_stays__bed__room",
                "inpatient_stays__doc_nurse",
                "inpatient_stays__procedure_nurse",
                "inpatient_stays__checklist_items__done_by",
                "inpatient_stays__procedure_records__nurse",
                "surgeries__surgery_type",
                "surgeries__surgeon",
                "surgeries__report",
            )
            .order_by("-visit_date", "-created_at")
        )

        # Moliyaviy yakun (barcha cheklar bo'yicha)
        from apps.billing.models import Invoice
        invoices = Invoice.objects.filter(visit__patient=patient).exclude(
            status=Invoice.Status.CANCELLED
        )
        totals = {
            "accrued": sum((i.total_amount for i in invoices), Decimal(0)),
            "paid": sum((i.paid_amount for i in invoices), Decimal(0)),
            "refunded": sum((i.refunded_amount for i in invoices), Decimal(0)),
        }
        totals["debt"] = totals["accrued"] - (totals["paid"] - totals["refunded"])

        context.update({
            "patient": patient,
            "visits": visits,
            "totals": totals,
            "visit_count": visits.count(),
        })
        return context


class MyTemplatesPageView(RoleRequiredMixin, TemplateView):
    """Shifokorning SHABLON USTAXONASI (alohida sahifa).

    Bu yerda shifokor o'z shablonlarini yaratadi: jadval va turli
    shakllar bilan (CKEditor), «MAXSUS SO'Z»lar (avtomatik to'ladi) va
    _________ bo'sh joylar (xulosa yozishda to'ldiriladi) qo'shib.
    """
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]
    template_name = "clinical/my_templates.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        templates = ConsultationTemplate.objects.filter(doctor=self.request.user)
        context["templates"] = templates
        context["templates_map"] = {
            str(t.id): {"name": t.name, "html": t.report_html or ""}
            for t in templates
        }
        return context


class TemplateSaveModalView(RoleRequiredMixin, View):
    """Yangi shablonni Ajax orqali saqlash (bir xil nom bo'lsa — yangilaydi)."""
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]

    def post(self, request):
        name = (request.POST.get("name") or "").strip()[:150]
        report_html = request.POST.get("report_html")
        if not name or not report_html:
            return JsonResponse({"error": "Nomi va matni majburiy."}, status=400)

        t, created = ConsultationTemplate.objects.update_or_create(
            doctor=request.user,
            name=name,
            defaults={"report_html": report_html},
        )
        return JsonResponse({
            "id": str(t.id), "name": t.name,
            "report_html": t.report_html, "created": created,
        })


class TemplateUpdateModalView(RoleRequiredMixin, View):
    """Tanlangan shablonni joriy matn bilan YANGILASH (faqat o'ziniki)."""
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]

    def post(self, request, template_id):
        t = get_object_or_404(ConsultationTemplate, id=template_id, doctor=request.user)
        report_html = request.POST.get("report_html")
        if not report_html:
            return JsonResponse({"error": "Matn bo'sh."}, status=400)
        new_name = (request.POST.get("name") or "").strip()[:150]
        t.report_html = report_html
        if new_name:
            t.name = new_name
        t.save(update_fields=["report_html", "name"])
        return JsonResponse({"id": str(t.id), "name": t.name, "report_html": t.report_html})


class TemplateDeleteModalView(RoleRequiredMixin, View):
    """Shablonni o'chirish (faqat o'ziniki)."""
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]

    def post(self, request, template_id):
        t = get_object_or_404(ConsultationTemplate, id=template_id, doctor=request.user)
        t.delete()
        return JsonResponse({"status": "deleted"})

class VisitConsultationView(RoleRequiredMixin, CreateView):
    """Shifokor qabuli (tashxis, dori va yo'llanmalar).

    Har bir shifokor bitta Visit ichida O'Z xulosasini yozadi —
    yo'naltirishda yangi Visit ochilmaydi.
    """

    # Faqat shifokorlar (davolovchi yoki bosh) bu yerga kira oladi
    allowed_roles = ["super_admin", "administrator", "chief_doctor", "doctor"]
    form_class = ConsultationForm
    template_name = "clinical/consultation_form.html"

    def get_visit(self):
        return get_object_or_404(
            Visit.objects.select_related("patient", "doctor"), pk=self.kwargs["pk"]
        )

    def get_own_consultation(self, visit):
        """Ushbu shifokorning shu Visit'dagi mavjud xulosasi (bo'lsa)."""
        return Consultation.objects.filter(visit=visit, doctor=self.request.user).first()

    def get_initial(self):
        # "Davom etish" bosilganda avval yozilganlar yo'qolmasin
        initial = super().get_initial()
        existing = self.get_own_consultation(self.get_visit())
        if existing:
            initial.update({
                "complaint": existing.complaint,
                "anamnesis": existing.anamnesis,
                "objective_status": existing.objective_status,
                "diagnosis": existing.diagnosis,
                "prescription": existing.prescription,
                "recommendations": existing.recommendations,
            })
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        visit = self.get_visit()
        context["visit"] = visit
        # Shu tashrif ichida boshqa shifokorlar yozgan xulosalar
        # (yo'naltirilgan bemorda juda muhim) + avvalgi yakunlangan tashriflar.
        context["visit_consultations"] = (
            visit.consultations.exclude(doctor=self.request.user)
            .select_related("doctor", "doctor__role").order_by("created_at")
        )
        context["past_consultations"] = (
            Consultation.objects.filter(
                visit__patient=visit.patient,
                visit__status=Visit.Status.COMPLETED,
            )
            .exclude(visit=visit)
            .select_related("doctor", "doctor__role")
            .order_by("-created_at")
        )
        # Shifokorning SHAXSIY tashxis shablonlari (tanlab qo'llash uchun)
        import json
        templates = ConsultationTemplate.objects.filter(doctor=self.request.user)
        context["my_templates"] = templates
        context["my_templates_json"] = json.dumps({
            str(t.id): {
                "name": t.name,
                "complaint": t.complaint,
                "anamnesis": t.anamnesis,
                "objective_status": t.objective_status,
                "diagnosis": t.diagnosis,
                "prescription": t.prescription,
                "recommendations": t.recommendations,
            } for t in templates
        })
        return context

    @transaction.atomic
    def form_valid(self, form):
        visit = self.get_visit()
        action = self.request.POST.get("action")

        # Yopiq (yakunlangan/bekor qilingan) tashrifni tahrirlab bo'lmaydi
        if visit.status not in OPEN_VISIT_STATUSES:
            messages.error(
                self.request,
                f"Bu qabul '{visit.get_status_display()}' holatida — tahrirlab bo'lmaydi.",
            )
            return redirect("core:home")

        # 1. Tashxisni saqlash — har bir shifokor uchun alohida yozuv,
        # boshqa shifokorning xulosasi ustidan yozilmaydi.
        # Yangi yozuvda qabul narxi (fee) o'sha paytdagi narxdan SNAPSHOT
        # qilinadi — keyin narx o'zgarsa ham bu chek o'zgarmaydi.
        consultation, created = Consultation.objects.get_or_create(
            visit=visit,
            doctor=self.request.user,
            defaults={
                "complaint": form.cleaned_data.get("complaint", ""),
                "anamnesis": form.cleaned_data.get("anamnesis", ""),
                "objective_status": form.cleaned_data.get("objective_status", ""),
                "diagnosis": form.cleaned_data.get("diagnosis", ""),
                "prescription": form.cleaned_data.get("prescription", ""),
                "recommendations": form.cleaned_data.get("recommendations", ""),
                "fee": DoctorPrice.current_fee_for(self.request.user),
            },
        )
        if not created:
            # Tahrirda fee tegilmaydi (tarixiy narx saqlanadi)
            consultation.complaint = form.cleaned_data.get("complaint", "")
            consultation.anamnesis = form.cleaned_data.get("anamnesis", "")
            consultation.objective_status = form.cleaned_data.get("objective_status", "")
            consultation.diagnosis = form.cleaned_data.get("diagnosis", "")
            consultation.prescription = form.cleaned_data.get("prescription", "")
            consultation.recommendations = form.cleaned_data.get("recommendations", "")
            consultation.save()

        # 2. Xizmatlarga (UZI, EKG) yo'naltirish
        recommended_services = form.cleaned_data.get("recommended_services")
        if recommended_services:
            for service in recommended_services:
                # Agar oldin yuborilmagan (bekor qilinmagan) bo'lsa qo'shamiz
                if not ServiceOrder.objects.filter(visit=visit, service=service).exclude(
                    status=ServiceOrder.Status.CANCELLED
                ).exists():
                    ServiceOrder.objects.create(
                        visit=visit,
                        service=service,
                        status=ServiceOrder.Status.WAITING,
                    )

        # 3. Hozirgi qabulni FSM orqali "Yakunlandi" qilish
        if action == "complete":
            # Agar qabul allaqachon boshqa shifokorga yo'naltirilgan bo'lsa (yoki bizniki bo'lmasa),
            # joriy shifokor faqat o'z xulosasini saqlaydi, qabulni butunlay yopa olmaydi.
            if visit.doctor != self.request.user:
                messages.success(self.request, "Sizning qismingiz yakunlandi. Bemor boshqa shifokorga yo'naltirilgan.")
                return redirect("core:home")

            try:
                # waiting → accepted → in_progress → completed zanjiri
                if visit.status == Visit.Status.WAITING:
                    registration_services.visit_transition(
                        visit=visit, new_status=Visit.Status.ACCEPTED
                    )
                if visit.status == Visit.Status.ACCEPTED:
                    registration_services.visit_transition(
                        visit=visit, new_status=Visit.Status.IN_PROGRESS
                    )
                registration_services.visit_transition(
                    visit=visit, new_status=Visit.Status.COMPLETED
                )
            except DomainError as exc:
                messages.error(self.request, exc.message)
                return redirect("clinical:consultation", pk=visit.pk)
            messages.success(self.request, "Qabul muvaffaqiyatli yakunlandi!")
            return redirect("core:home")

        messages.success(self.request, "Xulosa saqlandi.")
        return redirect("clinical:consultation", pk=visit.pk)

from django.http import JsonResponse, HttpResponse, Http404
from apps.accounts.models import User


@role_required("super_admin", "administrator", "chief_doctor", "doctor")
def visit_redirect_htmx(request, pk):
    """Bemorni boshqa shifokorga yo'naltirish (AJAX).
    
    Yangi Visit YARATILMAYDI — o'sha Visit yangi shifokorga
    o'tkazilib qayta navbatga qaytadi.
    """
    if request.method != "POST":
        return JsonResponse({"error": "Faqat POST ruxsat etiladi"}, status=405)

    visit = get_object_or_404(Visit, pk=pk)
    referred_doctor_id = request.POST.get("referred_doctor")
    referral_notes = request.POST.get("referral_notes", "").strip()
    report_html = request.POST.get("report_html", "").strip()

    if not referred_doctor_id:
        return JsonResponse({"error": "Iltimos, shifokorni tanlang!"}, status=400)

    referred_doctor = get_object_or_404(User, id=referred_doctor_id, is_active=True)

    try:
        with transaction.atomic():
            # MUHIM QOIDA: yo'naltirgan shifokorga pul HISOBLANMAYDI (fee = 0).
            consultation, created = Consultation.objects.update_or_create(
                visit=visit,
                doctor=request.user,
                defaults={
                    "report_html": report_html or f"<p><strong>Yo'naltirish sababi:</strong> {referral_notes}</p>",
                    "fee": Decimal(0),
                },
            )
            if not created:
                # Avval fee yozilib qolgan bo'lsa ham nol qilinadi
                consultation.fee = Decimal(0)
                consultation.save(update_fields=["fee"])

            # 2. Visit'ni yangi shifokorga biriktirish va xabar qoldirish
            visit.doctor = referred_doctor
            if referral_notes:
                old_reason = visit.cancel_reason or ""
                visit.cancel_reason = f"{old_reason}\n[{request.user.get_full_name()}] Yo'naltirdi: {referral_notes}".strip()
            visit.save(update_fields=["doctor", "cancel_reason"])

            # 3. Visit statusini qayta WAITING ga o'tkazish
            if visit.status != Visit.Status.WAITING:
                registration_services.visit_transition(
                    visit=visit, new_status=Visit.Status.WAITING
                )

            return JsonResponse({"status": "ok", "message": f"Bemor {referred_doctor.get_full_name()} ga yo'naltirildi!"})
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)


from django.views.generic import TemplateView
from apps.accounts.permissions import RoleRequiredMixin
from apps.accounts.models import Role
from apps.clinical.models import Room, Bed, InpatientStay

class InpatientDashboardView(RoleRequiredMixin, TemplateView):
    """Palatalar holati (Dashbord) Admin, Registratura va Shifokorlar uchun."""
    allowed_roles = (Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON, Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.ANESTHESIOLOGIST)
    template_name = "clinical/inpatient_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["rooms"] = Room.objects.prefetch_related(
            "beds__stays__visit__patient",
            "beds__stays__assigned_doctor",
            "beds__stays__doc_nurse",
            "beds__stays__procedure_nurse",
            "beds__stays__visit__service_orders__service",
            "beds__stays__visit__dispensed_medicines__batch__medicine"
        ).filter(is_active=True)
        from apps.pharmacy.models import MedicineBatch
        context["available_batches"] = MedicineBatch.objects.filter(quantity_available__gt=0).select_related('medicine', 'medicine__unit').order_by('medicine__name')
        from apps.clinical.models import ServiceCatalog
        context["services"] = ServiceCatalog.objects.all()
        return context

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
    Role.Code.NURSE, Role.Code.WARD_NURSE
)
def _create_stay(request, visit, bed):
    """Yotqizishning umumiy logikasi: tur, narx va 2 ta hamshira.

    Hamroh logikasi OLIB TASHLANGAN. Statsionar 2 xil:
      - Oddiy: yotish + dorilar alohida to'lanadi
      - Paketli: dori narxi yotish ichida (bemor faqat yotganiga to'laydi,
        dorilar klinika omboridan beriladi va chekka tushmaydi)
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()

    stay_type = request.POST.get("stay_type", InpatientStay.StayType.STANDARD)
    if stay_type not in InpatientStay.StayType.values:
        stay_type = InpatientStay.StayType.STANDARD

    # Yotqizish oynasidan qo'lda kiritilgan paketli narx (ixtiyoriy)
    manual_price = None
    raw = (request.POST.get("package_price") or "").replace(" ", "").replace(",", ".").strip()
    if raw:
        try:
            manual_price = Decimal(raw)
        except Exception:
            return None, "Paketli narx noto'g'ri kiritildi."
        if manual_price <= 0:
            return None, "Paketli narx musbat bo'lishi kerak."

    if stay_type == InpatientStay.StayType.PACKAGE:
        if manual_price:
            # Kiritilgan narx shu yotish uchun ishlatiladi VA kravatga
            # saqlanadi (keyingi safar tayyor turadi) — tarix bilan.
            if bed.package_price_per_day != manual_price:
                from .models import BedPriceHistory
                BedPriceHistory.objects.create(
                    bed=bed,
                    old_price=bed.price_per_day,
                    new_price=bed.price_per_day,
                    old_companion_price=bed.package_price_per_day,
                    new_companion_price=manual_price,
                    changed_by=request.user,
                )
                bed.package_price_per_day = manual_price
                bed.save(update_fields=["package_price_per_day"])
            daily_price = manual_price
        elif bed.package_price_per_day > 0:
            daily_price = bed.package_price_per_day
        else:
            return None, (
                "Bu kravat uchun 'Paketli' kunlik narx belgilanmagan. "
                "Formadagi 'Paketli kunlik narx' maydoniga narxni kiriting."
            )
    else:
        daily_price = bed.price_per_day

    # HUJJAT HAMSHIRASI — YOTQIZISHNI RASMIYLASHTIRAYOTGAN ODAM.
    #
    # Formadan OLINMAYDI: hujjatni bemorni qabul qilgan odam yuritadi.
    # Ilgari bu ro'yxatdan tanlanardi va ikki xato mumkin edi — boshqa
    # hamshira tanlanib qolishi, yoki bo'sh qoldirilib hujjat egasiz
    # qolishi. Ikkinchisida keyin kim yozganini aniqlab bo'lmasdi.
    #
    # Shablonda maydon o'zgarmas qilingan, lekin unga ishonmaymiz:
    # POST'ni qo'lda yuborib chetlab o'tish mumkin.
    doc_nurse = request.user if request.user.is_authenticated else None
    procedure_nurse = User.objects.filter(
        id=request.POST.get("procedure_nurse") or None, is_active=True
    ).first()
    assigned_doctor = User.objects.filter(
        id=request.POST.get("assigned_doctor") or None, is_active=True
    ).first()

    stay = InpatientStay.objects.create(
        visit=visit,
        bed=bed,
        is_companion=False,
        status=InpatientStay.Status.ACTIVE,
        stay_type=stay_type,
        daily_price=daily_price,
        companion_daily_price=0,
        doc_nurse=doc_nurse,
        procedure_nurse=procedure_nurse,
        assigned_doctor=assigned_doctor,
    )

    # YOTISHNI EPIZODGA BOG'LAYMIZ.
    #
    # HAQIQIY XATO: kravat berilganda `AdmissionEpisode.stay` bo'sh
    # qolardi. Natijada shifokor yo'llagan epizod va hamshira ochgan
    # yotish bir-birini «tanimasdi»: statsionar tarixida bemor ko'rinardi,
    # lekin «Statsionar hisobotlari» bo'sh chiqardi va vipiskada yotgan
    # kunlar hisoblanmasdi.
    #
    # Shu tashrifning ochiq epizodi bo'lsa — biriktiramiz va uni
    # «Yotqizildi» holatiga o'tkazamiz.
    from apps.clinical.models import AdmissionEpisode

    episode = (
        AdmissionEpisode.objects.filter(visit=visit, stay__isnull=True)
        .exclude(status=AdmissionEpisode.Status.CANCELLED)
        .order_by("-created_at")
        .first()
    )
    if episode is not None:
        episode.stay = stay
        maydonlar = ["stay", "updated_at"]
        if episode.status != AdmissionEpisode.Status.ADMITTED:
            episode.status = AdmissionEpisode.Status.ADMITTED
            maydonlar.append("status")
        episode.save(update_fields=maydonlar)

    # Bemor yotqizilganda faqat statsionar paytida tayinlangan narsalar ro'yxatga tushishi kerak
    # Shu sababli ambulatoriya (asosiy visit) xizmatlarini avtomatik ko'chirmaymiz.
    return stay, None


@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
    Role.Code.NURSE, Role.Code.WARD_NURSE
)
def assign_bed_htmx(request, bed_id):
    """Kravatga bemor yotqizish (HTMX). Hamrohsiz, 2 xil statsionar."""
    if request.method == "POST":
        visit_id = request.POST.get("visit_id")

        if not visit_id:
            return HttpResponse("<div class='alert alert-danger'>Bemorni tanlang!</div>")

        visit = get_object_or_404(Visit, id=visit_id)

        # Bemor allaqachon yotgan bo'lsa — ikkinchi marta yotqizmaymiz
        if visit.inpatient_stays.filter(status=InpatientStay.Status.ACTIVE).exists():
            return HttpResponse("<div class='alert alert-warning'>Bu bemor allaqachon statsionarda yotibdi!</div>")

        with transaction.atomic():
            # Band kravatga qayta yotqizishni bloklaymiz
            bed = Bed.objects.select_for_update().filter(id=bed_id, is_occupied=False).first()
            if bed is None:
                return HttpResponse("<div class='alert alert-danger'>Bu kravat allaqachon band!</div>")

            stay, err = _create_stay(request, visit, bed)
            if err:
                return HttpResponse(f"<div class='alert alert-danger'>{err}</div>")

            bed.is_occupied = True
            bed.save(update_fields=["is_occupied"])

        return HttpResponse("<script>window.location.reload();</script>")

    # GET request for form
    from django.contrib.auth import get_user_model
    User = get_user_model()
    bed = get_object_or_404(Bed, id=bed_id)

    # Har bir bemorning ENG OXIRGI qabuli.
    #
    # DIQQAT: ilgari bu `Max("id")` orqali qilingan edi. `id` — UUID, uning
    # «maksimumi» tasodifiy: u vaqt bo'yicha emas, alifbo bo'yicha eng katta
    # UUID ni beradi. Natijada ro'yxatga bemorning eski qabuli tushib
    # qolishi mumkin edi. Sana bo'yicha saralab, birinchisini olamiz.
    seen: set = set()
    recent_visits = []
    
    # 1. Operatsiyasi rejalashtirilgan bemorlarni (ochiq tashriflarini) birinchi qo'shamiz
    from apps.clinical.models import SurgerySchedule
    pending_surgeries = SurgerySchedule.objects.filter(
        status__in=[SurgerySchedule.Status.SCHEDULED, SurgerySchedule.Status.IN_PROGRESS]
    ).select_related("visit", "visit__patient")
    
    for ps in pending_surgeries:
        if ps.visit and ps.visit.patient_id not in seen:
            seen.add(ps.visit.patient_id)
            recent_visits.append(ps.visit)

    # 2. So'ngra oxirgi tashriflarni qo'shamiz
    for v in (Visit.objects.select_related("patient")
              .order_by("-visit_date", "-created_at")[:400]):
        if v.patient_id in seen:
            continue
        seen.add(v.patient_id)
        recent_visits.append(v)
        if len(recent_visits) >= 50:
            break
    nurses = User.objects.filter(role__code__in=(Role.Code.NURSE, Role.Code.WARD_NURSE), is_active=True)
    doctors = User.objects.filter(role__code__in=(Role.Code.DOCTOR, Role.Code.SURGEON, Role.Code.CHIEF_DOCTOR), is_active=True)

    # DIQQAT: bu yerda ham aniqlanmagan `ward_nurses` bor edi va forma
    # NameError bilan qulardi — HTMX esa 500 javobni ekranga chiqarmaydi,
    # shuning uchun modal «Yuklanmoqda…» holatida qotib qolardi.
    # Shablon `nurses` ni ishlatadi, uning ichida palata hamshiralari ham bor.
    return render(request, "clinical/_assign_bed_form.html", {
        "bed": bed,
        "recent_visits": recent_visits,
        "nurses": nurses,
        "doctors": doctors,
    })

@role_required(
    Role.Code.WARD_NURSE, Role.Code.RECEPTION,
    Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR
)
def admit_visit_htmx(request, visit_id):
    """Bemor viziti (Navbat) orqali statsionarga yotqizish (HTMX)."""
    visit = get_object_or_404(Visit, id=visit_id)

    # Bemor allaqachon yotgan bo'lsa
    if visit.inpatient_stays.filter(status=InpatientStay.Status.ACTIVE).exists():
        return HttpResponse("<div class='alert alert-warning'>Bu bemor allaqachon statsionarda yotibdi!</div>")

    if request.method == "POST":
        bed_id = request.POST.get("bed_id")

        if not bed_id:
            return HttpResponse("<div class='alert alert-danger'>Kravatni tanlang!</div>")

        with transaction.atomic():
            bed = Bed.objects.select_for_update().filter(id=bed_id, is_occupied=False).first()
            if bed is None:
                return HttpResponse("<div class='alert alert-danger'>Bu kravat allaqachon band!</div>")

            stay, err = _create_stay(request, visit, bed)
            if err:
                return HttpResponse(f"<div class='alert alert-danger'>{err}</div>")

            bed.is_occupied = True
            bed.save(update_fields=["is_occupied"])

        return HttpResponse("<script>window.location.reload();</script>")

    # GET request for form
    from django.contrib.auth import get_user_model
    User = get_user_model()
    nurses = User.objects.filter(role__code__in=(Role.Code.NURSE, Role.Code.WARD_NURSE), is_active=True)
    doctors = User.objects.filter(role__code__in=(Role.Code.DOCTOR, Role.Code.SURGEON, Role.Code.CHIEF_DOCTOR), is_active=True)
    empty_beds = Bed.objects.filter(is_occupied=False).order_by("room__name", "number")
    
    # DIQQAT: bu yerda «ward_nurses» degan aniqlanmagan o'zgaruvchi bor edi
    # va yotqizish formasi har safar NameError bilan qulardi. Shablon uni
    # umuman ishlatmaydi — `nurses` ichida palata hamshiralari ham bor.
    return render(request, "clinical/_admit_visit_form.html", {
        "visit": visit,
        "nurses": nurses,
        "doctors": doctors,
        "empty_beds": empty_beds,
    })

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
)
def order_inpatient_services(request, stay_id):
    """Statsionardagi bemorga tekshiruv (UZI, EKG, Laboratoriya) tayinlash."""
    if request.method == "POST":
        stay = get_object_or_404(InpatientStay, id=stay_id)
        service_ids = request.POST.getlist("services[]")
        
        if service_ids:
            from apps.clinical.models import ServiceCatalog, ServiceOrder
            
            services = ServiceCatalog.objects.filter(id__in=service_ids)
            count = 0
            for service in services:
                # Agar shu stay davomida ayni shu xizmat tayinlanmagan bo'lsa (yoki holati bajarilmadi/bekor qilindi bo'lsa)
                ServiceOrder.objects.create(
                    visit=stay.visit,
                    service=service,
                    status=ServiceOrder.Status.WAITING,
                )
                count += 1
            if count > 0:
                messages.success(request, f"{count} ta tekshiruv muvaffaqiyatli tayinlandi!")
        else:
            messages.warning(request, "Hech qanday tekshiruv tanlanmadi.")
            
    referer = request.META.get('HTTP_REFERER') or "/"
    return redirect(referer)

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
)
def add_companion_to_stay_htmx(request, visit_id):
    """Bemor yotgan bo'lsa, ustiga keyinchalik hamroh qo'shish."""
    visit = get_object_or_404(Visit, id=visit_id)
    active_patient_stay = visit.inpatient_stays.filter(status=InpatientStay.Status.ACTIVE, is_companion=False).first()
    
    if not active_patient_stay:
        return HttpResponse("<div class='alert alert-danger'>Asosiy bemor topilmadi yoki u allaqachon javob berilgan!</div>")
        
    if request.method == "POST":
        companion_name = request.POST.get("companion_name", "")
        companion_bed_id = request.POST.get("companion_bed")
        
        with transaction.atomic():
            comp_bed = None
            if companion_bed_id:
                comp_bed = Bed.objects.select_for_update().filter(
                    id=companion_bed_id, is_occupied=False
                ).first()
                if not comp_bed:
                    return HttpResponse("<div class='alert alert-danger'>Tanlangan kravat band yoki mavjud emas!</div>")
            
            comp_price = comp_bed.companion_price_per_day if comp_bed else active_patient_stay.bed.companion_price_per_day
            InpatientStay.objects.create(
                visit=visit,
                bed=comp_bed if comp_bed else active_patient_stay.bed,
                assigned_nurse=active_patient_stay.assigned_nurse,
                is_companion=True,
                companion_name=companion_name,
                status=InpatientStay.Status.ACTIVE,
                daily_price=0,
                companion_daily_price=comp_price
            )
            
            if comp_bed:
                comp_bed.is_occupied = True
                comp_bed.save(update_fields=["is_occupied"])
                
        return HttpResponse("<script>window.location.reload();</script>")
        
    empty_beds = Bed.objects.filter(is_occupied=False).order_by("room__name", "number")
    return render(request, "clinical/_add_companion_form.html", {
        "visit": visit,
        "active_patient_stay": active_patient_stay,
        "empty_beds": empty_beds
    })

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
    Role.Code.NURSE, Role.Code.WARD_NURSE
)
def discharge_bed(request, stay_id):
    """Kravatdan chiqarish va kassaga hisoblash."""
    if request.method == "POST":
        stay = get_object_or_404(InpatientStay, id=stay_id)

        # Faqat faol yotishni chiqarish mumkin (ikki marta hisoblanmasin)
        if stay.status != InpatientStay.Status.ACTIVE:
            messages.warning(request, "Bu bemor allaqachon chiqarilgan.")
            return redirect("clinical:inpatient_dashboard")

        # Holatini yangilash
        stay.status = InpatientStay.Status.DISCHARGED
        stay.discharge_date = timezone.now()
        
        # Kunlarni hisoblash
        delta = stay.discharge_date - stay.admission_date
        days = max(1, delta.days) # Kamida 1 kun
        stay.total_days = days
        
        # Summani hisoblash (eski qotirilgan narxlar bo'yicha)
        total = days * stay.daily_price
        if stay.is_companion:
            total += days * stay.companion_daily_price
                
        stay.total_amount = total
        stay.save()
        
        # Epizod holati O'ZGARTIRILMAYDI — vipiska yozilganda DISCHARGED bo'ladi.
        # patient_left property InpatientStay.status orqali "Chiqdi" ni ko'rsatadi.
        
        # Kravatni bo'shatish (faqatgina agar bu kravatda boshqa faol yotish bo'lmasa)
        # Masalan: Bemor javob berildi, lekin hamroh (shu kravatda) hali yotgan bo'lishi mumkin.
        # Yoki hamroh ketdi, lekin bemor shu kravatda yotibdi.
        if not stay.bed.stays.filter(status='active').exclude(id=stay.id).exists() and not stay.bed.companion_stays.filter(status='active').exclude(id=stay.id).exists():
            stay.bed.is_occupied = False
            stay.bed.save(update_fields=["is_occupied"])
            
        # Agar bu asosiy bemor bo'lsa va uning hamrohi hali yotgan bo'lsa, uni ham chiqarish taklif qilinishi mumkin, 
        # lekin biz hozircha faqat shu InpatientStay ni chiqaryapmiz.
        
        # Hisobni (Invoice) yangilash
        from apps.billing.services import generate_invoice_for_visit
        generate_invoice_for_visit(stay.visit)
        
        messages.success(request, f"{stay} muvaffaqiyatli palatadan chiqarildi. Jami {stay.total_amount} so'm yozildi.")
        return redirect("clinical:inpatient_dashboard")
    return redirect("clinical:inpatient_dashboard")

# ==========================================
# SURGERY VIEWS
# ==========================================
from apps.clinical.models import SurgerySchedule, SurgeryType
from django.utils.dateparse import parse_datetime

def _with_past_reports(surgeries):
    """Har bir operatsiyaga bemorning oldingi bayonnomalarini biriktiradi.

    HAMMA BAYONNOMA BITTA SO'ROVDA olinadi.

    Har bir operatsiya uchun alohida so'rov yuborilsa, jarrohlik panelida
    20 ta operatsiya bo'lganda 100 dan ortiq so'rov ketardi — panel esa
    kun bo'yi ochiq turadi va o'z-o'zidan yangilanadi.

    Shablon `surgery.past_reports` orqali o'qiydi.
    """
    natija = list(surgeries)
    if not natija:
        return natija

    bemorlar = {s.visit.patient_id for s in natija
                if s.visit_id and s.visit.patient_id}
    if not bemorlar:
        for s in natija:
            s.past_reports = []
        return natija

    # Shu bemorlarning BARCHA bayonnomali operatsiyalari — bir marta
    hammasi = list(
        SurgerySchedule.objects
        .filter(visit__patient_id__in=bemorlar, report__isnull=False)
        .exclude(status="cancelled")
        .select_related("report", "surgery_type", "surgeon", "visit")
        .order_by("-scheduled_time")
    )

    bemor_boyicha = {}
    for s in hammasi:
        bemor_boyicha.setdefault(s.visit.patient_id, []).append(s)

    for s in natija:
        bemor_id = s.visit.patient_id if s.visit_id else None
        s.past_reports = _reports_from(
            bemor_boyicha.get(bemor_id, []), skip_pk=s.pk)
    return natija


def _reports_from(schedules, skip_pk=None):
    """Tayyor ro'yxatdan nusxalanadigan bo'laklarni yig'adi."""
    natija = []
    for s in schedules:
        if skip_pk is not None and s.pk == skip_pk:
            continue          # o'zidan nusxa olishning ma'nosi yo'q
        rep = getattr(s, "report", None)
        if rep is None or getattr(rep, "is_deleted", False):
            continue

        bloklar = [
            ("Bemor ahvoli (kelganda)", rep.arrival_condition, "arrival_condition"),
            ("Nimalar qilindi", rep.performed_actions, "performed_actions"),
            ("Narkoz", rep.anesthesia, "anesthesia"),
            ("Yozilgan dorilar", rep.medications, "medications"),
            ("Qilingan ukollar", rep.injections, "injections"),
            ("Sarflangan materiallar", rep.consumables, "consumables"),
            ("Qo'shimcha izohlar", rep.notes, "notes"),
        ]
        bloklar = [(n, (m or "").strip(), f)
                   for n, m, f in bloklar if (m or "").strip()]
        if not bloklar:
            continue          # bo'sh bayonnomadan nusxa olib bo'lmaydi

        natija.append({
            "surgery": s,
            "sana": s.scheduled_time,
            "turi": s.surgery_type.name if s.surgery_type_id else "",
            "usul": s.surgery_type.get_kind_display() if s.surgery_type_id else "",
            "jarroh": s.surgeon,
            "bloklar": bloklar,
        })
    return natija


def past_surgery_reports(surgery):
    """Bemorning OLDINGI operatsiya bayonnomalari — nusxalash uchun.

    Vipiskadagi «Statsionar hisobotlari» bilan bir xil mantiq: jarroh
    bayonnomani noldan yozmaydi, oldingisidan tayyor parchani oladi.
    Ayniqsa takroriy va bir turdagi operatsiyalarda matn deyarli bir xil.

    Bloklarni yig'ish `_reports_from` da — panel uchun ham, bitta
    operatsiya uchun ham AYNAN SHU funksiya ishlatiladi, aks holda
    ikkisi bir-biridan ajralib ketardi.
    """
    bemor_id = getattr(getattr(surgery, "visit", None), "patient_id", None)
    if not bemor_id:
        return []

    schedules = (
        SurgerySchedule.objects
        .filter(visit__patient_id=bemor_id)
        .exclude(status="cancelled")
        .select_related("report", "surgery_type", "surgeon", "operating_room")
        .order_by("-scheduled_time")
    )
    return _reports_from(schedules, skip_pk=surgery.pk)


def _surgery_items_error(schedule, selected) -> str:
    """Operatsiyani boshlash uchun anjomlar yetarlimi — USULGA QARAB.

    Ochiq va endoskopik operatsiyaning anjomlari butunlay boshqa:

      · OCHIQ — jarrohlik nabori (avtoklavda sterillangan) + belyo yoki
        boshqa steril anjom;
      · ENDOSKOPIK — endoskopik anjom (rastvorda tozalanadi, avtoklav
        uni buzadi) + belyo yoki boshqa steril anjom.

    Bo'sh satr qaytsa — hammasi joyida.
    """
    kind = getattr(schedule.surgery_type, "kind", None)

    if kind == SurgeryType.Kind.ENDOSCOPIC:
        if not selected.filter(item_type=SurgicalItem.Type.ENDO_INSTRUMENT).exists():
            return ("Endoskopik operatsiyani boshlab bo'lmaydi: kamida bitta "
                    "ENDOSKOPIK ANJOM tanlanishi shart (u rastvorda "
                    "tozalanadi — avtoklav uni buzadi).")
        if not selected.exclude(item_type=SurgicalItem.Type.ENDO_INSTRUMENT).exists():
            return ("Endoskopik operatsiya uchun belyo yoki boshqa steril "
                    "anjom ham tanlanishi shart.")
        return ""

    # Ochiq operatsiya (standart)
    if not selected.filter(item_type=SurgicalItem.Type.NABOR).exists():
        return ("Operatsiyani boshlab bo'lmaydi: kamida bitta 'Jarrohlik "
                "nabori' tanlanishi shart.")
    if not selected.exclude(item_type=SurgicalItem.Type.NABOR).exists():
        return ("Operatsiyani boshlab bo'lmaydi: jarrohlik nabori bilan birga "
                "kamida bitta sterilizatsiyadan o'tgan boshqa uskuna "
                "tanlanishi shart.")
    return ""


class SurgeryDashboardView(RoleRequiredMixin, TemplateView):
    """Jarrohlik bloki (Operatsiya) oynasi."""
    # `NURSE` o'rniga `OPERATING_NURSE` + `WARD_NURSE`: jarrohlik bloki
    # klinikadagi hamma hamshiraga emas, palata va operatsion
    # hamshiralarga ochiq.
    allowed_roles = (Role.Code.SURGEON, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN, Role.Code.ANESTHESIOLOGIST, Role.Code.OPERATING_NURSE, Role.Code.WARD_NURSE, Role.Code.SURGERY_ADMIN, Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR)
    template_name = "clinical/surgery_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Barcha kutilayotgan yoki bugungi operatsiyalar
        context["surgeries"] = _with_past_reports(
            SurgerySchedule.objects
            .select_related("visit__patient", "surgery_type", "surgeon")
            .order_by("scheduled_time"))
        context["anesthesia_stocks"] = AnesthesiaStock.objects.filter(is_active=True)
        # Jamoa va xona tanlovlari — umumiy manbadan (surgery_team_context)
        context.update(surgery_team_context())
        from apps.patients.models import Patient
        # Operatsiyaga yozishda bemor BEMORLAR RO'YXATIDAN tanlanadi (navbatdan emas)
        context["patients"] = Patient.objects.order_by("last_name", "first_name")
        context["recent_visits"] = Visit.objects.order_by("-created_at")[:50]
        context["ready_items"] = SurgicalItem.objects.filter(status=SurgicalItem.Status.READY)
        context.update(_role_flags(self.request.user))
        return context

class AdminSurgeryListView(RoleRequiredMixin, TemplateView):
    """Administrator uchun faqat ko'rishga mo'ljallangan operatsiyalar ro'yxati."""
    allowed_roles = (Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN, Role.Code.SURGERY_ADMIN)
    template_name = "clinical/surgery_admin_list.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.clinical.models import SurgerySchedule
        context["surgeries"] = SurgerySchedule.objects.select_related("visit__patient", "surgery_type", "surgeon").order_by("-scheduled_time")
        return context

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'excel':
            from apps.core.exports import export_queryset_to_excel
            from apps.clinical.models import SurgerySchedule
            qs = SurgerySchedule.objects.select_related("visit__patient", "surgery_type", "surgeon").order_by("-scheduled_time")
            columns = [
                ("Karta raqami", "visit.patient.card_number"),
                ("Bemor F.I.SH.", "visit.patient.full_name"),
                ("Operatsiya turi", "surgery_type.name"),
                ("Belgilangan vaqt", "scheduled_time"),
                ("Holati", "get_status_display"),
                ("Jarroh", "surgeon.get_full_name"),
            ]
            return export_queryset_to_excel(qs, columns, "Operatsiyalar_Royxati")
        return super().get(request, *args, **kwargs)

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
    Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR,
    Role.Code.SURGEON, Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR,
)
def schedule_surgery(request):
    """Yangi operatsiyani rejalashtirish."""
    referer = request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard"
    if request.method == "POST":
        visit_id = request.POST.get("visit_id")
        patient_id = request.POST.get("patient_id")
        surgery_type_id = request.POST.get("surgery_type_id")
        surgeon_id = request.POST.get("surgeon_id")
        scheduled_time_str = request.POST.get("scheduled_time")
        notes = request.POST.get("notes", "")

        # Bemor BEMORLAR RO'YXATIDAN tanlanadi (navbatdan emas — takrorlanmasligi uchun).
        # Operatsiya bemorning ochiq tashrifiga biriktiriladi; ochiq tashrif bo'lmasa
        # eng oxirgi tashrifiga. Statsionardan yozilsa visit_id to'g'ridan-to'g'ri keladi.
        if patient_id and not visit_id:
            from apps.patients.models import Patient
            patient = get_object_or_404(Patient, id=patient_id)
            open_statuses = [
                Visit.Status.CREATED, Visit.Status.WAITING,
                Visit.Status.ACCEPTED, Visit.Status.IN_PROGRESS,
            ]
            visit = (
                patient.visits.filter(status__in=open_statuses).order_by("-created_at").first()
                or patient.visits.order_by("-created_at").first()
            )
            if visit is None:
                messages.error(
                    request,
                    f"{patient.full_name}da tashrif yo'q. Avval registraturada qabul oching.",
                )
                return redirect(referer)
            visit_id = visit.id

        if not all([visit_id, surgery_type_id, surgeon_id, scheduled_time_str]):
            messages.error(request, "Barcha maydonlarni to'ldirish shart!")
            return redirect(referer)

        visit = get_object_or_404(Visit, id=visit_id)
        surgery_type = get_object_or_404(SurgeryType, id=surgery_type_id)
        surgeon = get_object_or_404(User, id=surgeon_id)

        # Jamoa (ixtiyoriy) va xona — tanlash orqali
        def _opt_user(key):
            uid = request.POST.get(key)
            return User.objects.filter(id=uid).first() if uid else None

        from apps.clinical.models import OperatingRoom
        assistant = _opt_user("assistant_id")
        anesthesiologist = _opt_user("anesthesiologist_id")
        operating_nurse = _opt_user("operating_nurse_id")
        ward_nurse = _opt_user("ward_nurse_id")
        room_id = request.POST.get("operating_room_id")
        operating_room = OperatingRoom.objects.filter(id=room_id).first() if room_id else None

        scheduled_time = parse_datetime(scheduled_time_str)
        if not scheduled_time:
            scheduled_time = timezone.now()
        elif timezone.is_naive(scheduled_time):
            # Brauzer <input type="datetime-local"> vaqt mintaqasiz yuboradi.
            # Aware qilmasak, vaqt UTC deb qabul qilinib, jadvalda soat
            # farq bilan (Toshkent uchun 5 soat) ko'rinardi.
            scheduled_time = timezone.make_aware(
                scheduled_time, timezone.get_current_timezone()
            )

        # Check for duplicate active surgery
        if SurgerySchedule.objects.filter(
            visit=visit,
            surgery_type=surgery_type,
            status__in=[SurgerySchedule.Status.SCHEDULED, SurgerySchedule.Status.IN_PROGRESS]
        ).exists():
            messages.warning(
                request, 
                f"{visit.patient.full_name} uchun {surgery_type.name} operatsiyasi allaqachon yozilgan va hali tugatilmagan! Operatsiya tugamaguncha qayta yozish mumkin emas."
            )
            return redirect(referer)

        SurgerySchedule.objects.create(
            visit=visit,
            surgery_type=surgery_type,
            surgeon=surgeon,
            assistant=assistant,
            anesthesiologist=anesthesiologist,
            operating_nurse=operating_nurse,
            ward_nurse=ward_nurse,
            operating_room=operating_room,
            scheduled_time=scheduled_time,
            notes=notes,
            status=SurgerySchedule.Status.SCHEDULED,
            actual_price=surgery_type.price
        )
        
        messages.success(request, f"{visit.patient.full_name} operatsiyaga yozildi.")
        return redirect(referer)
    return redirect(referer)

@role_required(
    Role.Code.SURGEON, Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.ANESTHESIOLOGIST, Role.Code.NURSE,
)
def edit_surgery_schedule(request, schedule_id):
    """Operatsiya jamoasini (yoki boshqa detallarni) sabab bilan tahrirlash."""
    referer = request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard"
    if request.method == "POST":
        reason = request.POST.get("audit_reason", "").strip()
        if not reason:
            messages.error(request, "Tahrirlash sababini kiritish majburiy!")
            return redirect(referer)
            
        schedule = get_object_or_404(SurgerySchedule, id=schedule_id)
        
        def _opt_user(key):
            uid = request.POST.get(key)
            return User.objects.filter(id=uid).first() if uid else None

        surgeon = _opt_user("surgeon_id")
        assistant = _opt_user("assistant_id")
        anesthesiologist = _opt_user("anesthesiologist_id")
        operating_nurse = _opt_user("operating_nurse_id")
        ward_nurse = _opt_user("ward_nurse_id")
        
        if surgeon:
            schedule.surgeon = surgeon
        schedule.assistant = assistant
        schedule.anesthesiologist = anesthesiologist
        schedule.operating_nurse = operating_nurse
        schedule.ward_nurse = ward_nurse
        
        # AuditLog uchun sabab
        schedule._audit_reason = reason
        schedule.save(update_fields=["surgeon", "assistant", "anesthesiologist", "operating_nurse", "ward_nurse"])
        
        messages.success(request, "Operatsiya ma'lumotlari tahrirlandi.")
    return redirect(referer)

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
    Role.Code.SURGEON, Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.ANESTHESIOLOGIST, Role.Code.NURSE,
)
def update_surgery_status(request, schedule_id):
    """Operatsiya holatini o'zgartirish (Boshlash, Yakunlash)."""
    referer = request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard"
    if request.method == "POST":
        schedule = get_object_or_404(SurgerySchedule, id=schedule_id)
        new_status = request.POST.get("status")
        
        if new_status in dict(SurgerySchedule.Status.choices):
            schedule.status = new_status
            schedule.save()
            
            # Agar boshlansa, tanlangan uskunalarni biriktirish
            if new_status == SurgerySchedule.Status.IN_PROGRESS:
                item_ids = request.POST.getlist("items")

                selected = SurgicalItem.objects.filter(
                    id__in=item_ids, status=SurgicalItem.Status.READY
                )

                # ANJOM QOIDASI OPERATSIYA USULIGA BOG'LIQ.
                #
                # HAQIQIY XATO: `SurgeryType.kind` (ochiq / endoskopik)
                # modelda bor edi, lekin HECH QAYERDA ishlatilmasdi.
                # Natijada endoskopik operatsiyani ochiq jarrohlik nabori
                # bilan boshlab yuborish mumkin edi — endoskopik anjom
                # umuman tanlanmasa ham tizim ruxsat berardi.
                #
                # Endi:
                #   · ochiq       — jarrohlik nabori + boshqa steril anjom;
                #   · endoskopik  — endoskopik anjom (rastvorda tozalangan)
                #                   + belyo yoki boshqa steril anjom.
                xato = _surgery_items_error(schedule, selected)
                if xato:
                    # Statusni orqaga qaytaramiz — operatsiya boshlanmaydi
                    schedule.status = SurgerySchedule.Status.SCHEDULED
                    schedule.save(update_fields=["status"])
                    messages.error(request, xato)
                    return redirect(referer)

                if item_ids:
                    items = selected
                    for item in items:
                        item.status = SurgicalItem.Status.IN_USE
                        item.current_room = schedule.operating_room
                        item.save(update_fields=["status", "current_room"])
                        schedule.items_used.add(item)
                        SurgicalItemHistory.log(
                            item, "Operatsiyada ishlatilishi boshlandi",
                            user=request.user, surgery=schedule,
                        )

            # Agar yakunlansa, uskunalarni ifloslanganga (USED) o'tkazish
            elif new_status == SurgerySchedule.Status.COMPLETED:
                for item in schedule.items_used.all():
                    item.status = SurgicalItem.Status.USED
                    item.save(update_fields=["status"])
                    SurgicalItemHistory.log(
                        item, "Operatsiyada ishlatildi — tozalashga qaytarildi",
                        user=request.user, surgery=schedule,
                    )

            # Agar bekor qilinib, orqaga (SCHEDULED) qaytarilsa, uskunalarni ozod qilish
            elif new_status == SurgerySchedule.Status.SCHEDULED:
                for item in schedule.items_used.all():
                    item.status = SurgicalItem.Status.READY
                    item.current_room = None
                    item.save(update_fields=["status", "current_room"])
                    SurgicalItemHistory.log(
                        item, "Operatsiya bekor qilindi — anjom bo'shatildi",
                        user=request.user, surgery=schedule,
                    )
                schedule.items_used.clear()

            messages.success(request, f"Operatsiya holati yangilandi: {schedule.get_status_display()}")
            
        return redirect(referer)
    return redirect(referer)

# ==========================================
# STERILIZATSIYA (AVTOKLAV) VIEWS
# ==========================================
from apps.clinical.models import SurgicalItem, SurgicalItemHistory

STERIL_VIEW_ROLES = (
    Role.Code.STERILIZATION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.SUPER_ADMIN,
)


def _items_with_history():
    """Anjomlar + to'liq tarixi (bemor/jarroh bilan) — bitta so'rovda.

    N+1 ni oldini olish uchun tarix `select_related` bilan oldindan olinadi.
    """
    from django.db.models import Prefetch
    return SurgicalItem.objects.select_related("current_room").prefetch_related(
        Prefetch(
            "history",
            queryset=SurgicalItemHistory.objects.select_related(
                "changed_by", "patient", "surgeon",
                "surgery__surgery_type", "surgery__visit__patient", "surgery__surgeon",
            ).order_by("-used_at"),
            to_attr="full_history",
        )
    ).order_by("name")


class SterilizationDashboardView(RoleRequiredMixin, TemplateView):
    """Avtoklav/Sterilizatsiya oynasi."""
    allowed_roles = STERIL_VIEW_ROLES
    template_name = "clinical/sterilization_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["items"] = _items_with_history()
        return context

@role_required(*STERIL_VIEW_ROLES)
def clean_surgical_item(request, item_id):
    """Ifloslangan uskunani tozalanganiga (READY) o'tkazish."""
    if request.method == "POST":
        item = get_object_or_404(SurgicalItem, id=item_id)
        if item.status == SurgicalItem.Status.USED:
            # Oxirgi ishlatilgan operatsiyani topamiz — tozalash yozuvi ham
            # KIMDAN keyin tozalangani bilan birga saqlanadi.
            last_use = item.history.filter(surgery__isnull=False).order_by("-used_at").first()
            last_surgery = last_use.surgery if last_use else None

            item.status = SurgicalItem.Status.READY
            # Avtoklav asbobni xonadan OLIB QAYTADI — sterilizatsiya/omborga
            item.current_room = None
            item.save(update_fields=["status", "current_room"])

            method = item.get_steril_method_display()
            SurgicalItemHistory.log(
                item, f"Sterilizatsiyadan o'tdi ({method})",
                user=request.user, surgery=last_surgery,
            )
            messages.success(request, f"{item.name} sterilizatsiyadan o'tdi ({method}).")
        else:
            messages.error(request, "Faqat ifloslangan uskunani tozalash mumkin.")
    return redirect("clinical:sterilization_dashboard")

@role_required(Role.Code.STERILIZATION, Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR)
def add_surgical_item(request):
    """Yangi uskuna yoki klapan qo'shish."""
    if request.method == "POST":
        name = request.POST.get("name")
        item_type = request.POST.get("item_type")
        serial_number = request.POST.get("serial_number", "")
        
        if name and item_type:
            SurgicalItem.objects.create(
                name=name,
                item_type=item_type,
                serial_number=serial_number,
                status=SurgicalItem.Status.USED,
                created_by=request.user
            ,
            steril_method=request.POST.get("steril_method", "autoclave"))
            messages.success(request, f"{name} muvaffaqiyatli qo'shildi.")
        else:
            messages.error(request, "Barcha majburiy maydonlarni to'ldiring.")
    return redirect("clinical:sterilization_dashboard")


# ==========================================
# INPATIENT SETTINGS VIEWS
# ==========================================

class RoomsSettingsView(RoleRequiredMixin, TemplateView):
    """Palatalar va kravatlar narxini sozlash."""
    allowed_roles = (Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
    template_name = "clinical/rooms_settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from django.db.models import Prefetch
        from .models import BedPriceHistory, InpatientStay
        
        beds_prefetch = Prefetch(
            "beds",
            queryset=Bed.objects.prefetch_related(
                Prefetch("price_history", queryset=BedPriceHistory.objects.order_by("-created_at")),
                Prefetch("stays", queryset=InpatientStay.objects.select_related("visit__patient").order_by("-admission_date"))
            ).order_by("number")
        )
        context["rooms"] = Room.objects.prefetch_related(beds_prefetch, "assigned_doctor").order_by("floor", "name")
        from apps.accounts.models import User, Role
        context["doctors"] = User.objects.filter(role__code__in=[Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR, Role.Code.SURGEON], is_active=True).order_by("first_name", "last_name")
        return context

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def update_bed_price(request, bed_id):
    """Kravat narxini yangilash."""
    if request.method == "POST":
        bed = get_object_or_404(Bed, id=bed_id)
        try:
            new_price = Decimal(request.POST.get("price_per_day", 0))
            new_companion_price = Decimal(request.POST.get("companion_price_per_day", 0) or 0)
            new_package_price = Decimal(request.POST.get("package_price_per_day", 0) or 0)

            if (new_price != bed.price_per_day
                    or new_companion_price != bed.companion_price_per_day
                    or new_package_price != bed.package_price_per_day):
                from .models import BedPriceHistory
                BedPriceHistory.objects.create(
                    bed=bed,
                    old_price=bed.price_per_day,
                    new_price=new_price,
                    old_companion_price=bed.companion_price_per_day,
                    new_companion_price=new_companion_price,
                    changed_by=request.user
                )
                bed.price_per_day = new_price
                bed.companion_price_per_day = new_companion_price
                bed.package_price_per_day = new_package_price
                bed.save(update_fields=[
                    "price_per_day", "companion_price_per_day", "package_price_per_day",
                ])
                messages.success(request, f"{bed} narxlari yangilandi (eski yotishlarga ta'sir qilmaydi).")
            else:
                messages.info(request, "Narx o'zgarmadi.")
        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
            
    return redirect("clinical:rooms_settings")

def _norm_room_name(name):
    """Palata nomini solishtirish uchun normallashtirish:
    '1-Xona', '1 xona', '1xona' — bularning hammasi bitta deb hisoblanadi."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def add_room(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        floor = request.POST.get("floor", 1)
        doctor_id = request.POST.get("assigned_doctor_id")
        if not name:
            messages.error(request, "Palata nomi kiritilmadi.")
            return redirect("clinical:rooms_settings")
        # Dublikat nazorati (yozilish farqlarini hisobga olib)
        norm = _norm_room_name(name)
        for r in Room.all_objects.all():
            if _norm_room_name(r.name) == norm:
                messages.error(
                    request,
                    f"Bunday palata allaqachon mavjud: '{r.name}'. "
                    "Xuddi shu nomni boshqacha yozib qo'shib bo'lmaydi.",
                )
                return redirect("clinical:rooms_settings")
        Room.objects.create(name=name, floor=floor, assigned_doctor_id=doctor_id if doctor_id else None)
        messages.success(request, f"'{name}' palatasi qo'shildi.")
    return redirect("clinical:rooms_settings")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def delete_room(request, room_id):
    """Palatani o'chirish — faqat ichida yotgan bemor bo'lmasa."""
    if request.method == "POST":
        room = get_object_or_404(Room, id=room_id)
        occupied = room.beds.filter(is_occupied=True).exists()
        if occupied:
            messages.error(request, f"'{room.name}' palatasida bemor yotibdi — o'chirib bo'lmaydi.")
        else:
            name = room.name
            # Kravatlarni ham birga o'chiramiz (soft delete)
            for bed in room.beds.all():
                bed.delete()
            room.delete()
            messages.success(request, f"'{name}' palatasi o'chirildi.")
    return redirect("clinical:rooms_settings")

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def add_bed(request):
    if request.method == "POST":
        room_id = request.POST.get("room_id")
        number = request.POST.get("number")
        try:
            price = Decimal(request.POST.get("price_per_day", 0))
            comp_price = Decimal(request.POST.get("companion_price_per_day", 0) or 0)
            package_price = Decimal(request.POST.get("package_price_per_day", 0) or 0)
            room = get_object_or_404(Room, id=room_id)
            if number:
                Bed.objects.create(
                    room=room,
                    number=number,
                    price_per_day=price,
                    companion_price_per_day=comp_price,
                    package_price_per_day=package_price,
                )
                messages.success(request, f"'{room.name}' ga {number}-kravat qo'shildi.")
            else:
                messages.error(request, "Kravat raqami kiritilmadi.")
        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
    return redirect("clinical:rooms_settings")


@require_POST
@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def release_bed(request, bed_id):
    """Kravatni majburan bo'shatish — FAQAT ADMINISTRATOR.

    NIMA UCHUN KERAK: `Bed.is_occupied` yotishlardan alohida saqlanadigan
    bayroq. U normal holatda faqat bitta joyda — bemorga javob berilganda
    (`discharge_bed`) — o'chadi. Agar shu zanjir uzilsa (baza tozalandi,
    yozuv qo'lda o'chirildi, server yarim yo'lda to'xtadi), kravat abadiy
    «band» bo'lib qoladi va statsionar to'silib qoladi: bemor yo'q, lekin
    yangi bemorni ham yotqizib bo'lmaydi. Bu holatdan chiqishning yagona
    yo'li bazaga kirish edi.

    XAVFSIZLIK: agar kravatda HAQIQATDAN faol yotish bo'lsa, bo'shatishga
    ruxsat berilmaydi. Aks holda bemor tizimda «yotgan» bo'lib turadi-yu,
    o'rniga boshqasi yotqiziladi va ikkalasi bitta kravatda ko'rinadi.
    Bunday holatda to'g'ri yo'l — bemorga javob berish.
    """
    bed = get_object_or_404(Bed, id=bed_id)

    active = bed.stays.filter(status=InpatientStay.Status.ACTIVE).first()
    if active is None:
        active = bed.companion_stays.filter(
            status=InpatientStay.Status.ACTIVE
        ).first()

    if active is not None:
        messages.error(
            request,
            f"{bed} bo'shatilmadi — unda bemor yotibdi "
            f"({active.visit.patient.full_name}). Avval javob bering.",
        )
        return redirect("clinical:rooms_settings")

    if not bed.is_occupied:
        messages.info(request, f"{bed} allaqachon bo'sh.")
        return redirect("clinical:rooms_settings")

    bed.is_occupied = False
    bed.save(update_fields=["is_occupied"])
    messages.success(
        request,
        f"{bed} bo'shatildi — endi yangi bemor yotqizish mumkin.",
    )
    return redirect("clinical:rooms_settings")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def service_settings(request):
    """Xizmatlar katalogi: narx, guruh va KIM BAJARISHI.

    «Radiolog» degan alohida rol yo'q, shuning uchun har bir tekshiruvni
    kim bajarishi shu yerda biriktiriladi: aniq xodim, yoki rol (bo'lim),
    yoki guruhdan meros. Kabinet ham shu yerda — bemorga «qayerga borish»
    ko'rsatiladi.
    """
    services = (
        ServiceCatalog.objects.select_related(
            "category", "category__parent", "allowed_role",
            "responsible_staff", "room",
        )
        .order_by("category__sort_order", "category__name", "sort_order", "name")
    )

    # Guruhlar bo'yicha ajratamiz — 90 ta xizmatni tekis ro'yxatda
    # boshqarib bo'lmaydi.
    grouped: dict[str, list] = {}
    for svc in services:
        key = str(svc.category) if svc.category_id else "Guruhsiz (shifokor qabullari va h.k.)"
        grouped.setdefault(key, []).append(svc)

    categories = (
        ServiceCategory.objects.select_related("parent", "default_role",
                                               "default_staff", "default_room")
        .order_by("parent__sort_order", "sort_order", "name")
    )

    roles = Role.objects.all().order_by("name")
    staff = User.objects.filter(is_active=True).order_by("last_name", "first_name")
    rooms = AmbulatoryRoom.objects.all().order_by("name")

    # Tanlov ro'yxatlari SAHIFAGA BIR MARTA yuboriladi.
    # Ilgari har bir xizmat qatorida to'rtta <select> chizilardi:
    # 74 xizmat × ~70 variant = 1 MB dan ortiq HTML. Xodimlar soni oshgani
    # sayin bu yomonlashardi. Endi ro'yxat JSON bo'lib bir marta ketadi va
    # umumiy modalga JS orqali joylanadi.
    picker_options = {
        "categories": [[str(c.id), str(c)] for c in categories],
        "roles": [[str(r.id), r.name] for r in roles],
        "staff": [[str(u.id), u.get_full_name() or u.username] for u in staff],
        "rooms": [[str(r.id), r.name] for r in rooms],
    }

    # OGOHLANTIRISHLAR — jimgina buzilishlarni ko'rsatamiz.
    # Mas'uli yo'q tekshiruv hech kimning ro'yxatida chiqmaydi va bemor
    # kutib qoladi; narxi 0 bo'lsa kassa uni bepul deb hisoblaydi.
    unassigned = [s for s in services
                  if s.category_id and s.is_active
                  and s.owner_label == "Biriktirilmagan"]
    no_price = [s for s in services
                if s.category_id and s.is_active and (s.price or 0) <= 0]

    return render(request, "clinical/service_settings.html", {
        "services": services,
        "grouped": grouped,
        "unassigned": unassigned,
        "no_price": no_price,
        "categories": categories,
        "roles": roles,
        "staff": staff,
        "rooms": rooms,
        "picker_options": picker_options,
    })


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
@require_POST
def update_service_routing(request, service_id):
    """Tekshiruvni guruhga joylash va mas'ulini biriktirish.

    Narxga TEGMAYDI — narx alohida endpoint orqali o'zgaradi, chunki uning
    tarixi yozilishi shart.
    """
    svc = get_object_or_404(ServiceCatalog, id=service_id)

    def pick(model, field):
        raw = (request.POST.get(field) or "").strip()
        if not raw:
            return None
        return model.objects.filter(pk=raw).first()

    svc.category = pick(ServiceCategory, "category")
    svc.allowed_role = pick(Role, "allowed_role")
    svc.responsible_staff = pick(User, "responsible_staff")
    svc.room = pick(AmbulatoryRoom, "room")
    svc.save(update_fields=["category", "allowed_role", "responsible_staff",
                            "room", "updated_at"])
    messages.success(request, f"«{svc.name}» sozlamalari saqlandi. Mas'ul: {svc.owner_label}.")
    return redirect("clinical:service_settings")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
@require_POST
def update_category_defaults(request, category_id):
    """Guruh darajasidagi standart mas'ul va kabinet.

    Har bir tekshiruvni alohida sozlash zerikarli — «Laboratoriya» guruhiga
    bir marta laborant biriktirilsa, ichidagi hamma tahlil o'shanga boradi.
    """
    cat = get_object_or_404(ServiceCategory, id=category_id)

    def pick(model, field):
        raw = (request.POST.get(field) or "").strip()
        return model.objects.filter(pk=raw).first() if raw else None

    cat.default_role = pick(Role, "default_role")
    cat.default_staff = pick(User, "default_staff")
    cat.default_room = pick(AmbulatoryRoom, "default_room")
    cat.save(update_fields=["default_role", "default_staff", "default_room",
                            "updated_at"])
    messages.success(request, f"«{cat}» guruhi sozlamalari saqlandi.")
    return redirect("clinical:service_settings")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def add_service(request):
    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        price = request.POST.get("price", "0").replace(",", ".")
        try:
            price_dec = Decimal(price)
            if price_dec < 0:
                messages.error(request, "Narx manfiy bo'lishi mumkin emas!")
            elif ServiceCatalog.objects.filter(name__iexact=name).exists():
                messages.error(request, "Bunday nomdagi xizmat allaqachon mavjud!")
            else:
                ServiceCatalog.objects.create(name=name, price=price_dec)
                messages.success(request, f"{name} xizmati qo'shildi.")
        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
    return redirect("clinical:service_settings")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def update_service_price(request, service_id):
    if request.method == "POST":
        from .models import ServiceCatalogPriceHistory
        svc = get_object_or_404(ServiceCatalog, id=service_id)
        price_str = request.POST.get("price", "0").replace(",", ".")
        try:
            from django.db import transaction as txn
            new_price = Decimal(price_str)
            if new_price < 0:
                messages.error(request, "Narx manfiy bo'lishi mumkin emas!")
                return redirect("clinical:service_settings")
            with txn.atomic():
                ServiceCatalogPriceHistory.objects.create(
                    service=svc,
                    old_price=svc.price,
                    new_price=new_price,
                    changed_by=request.user,
                )
                svc.price = new_price
                svc.save(update_fields=["price"])
            messages.success(request, f"{svc.name} narxi yangilandi.")
        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
    return redirect("clinical:service_settings")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def toggle_service(request, service_id):
    if request.method == "POST":
        svc = get_object_or_404(ServiceCatalog, id=service_id)
        svc.is_active = not svc.is_active
        svc.save(update_fields=["is_active"])
        status = "faollashtirildi" if svc.is_active else "o'chirildi"
        messages.success(request, f"{svc.name} {status}.")
    return redirect("clinical:service_settings")

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def surgery_settings(request):
    """Jarrohlik turlari va narxlarini boshqarish sahifasi."""
    from .models import SurgeryType
    surgery_types = SurgeryType.objects.all().order_by("name")
    return render(request, "clinical/surgery_settings.html", {"surgery_types": surgery_types})

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def add_surgery_type(request):
    if request.method == "POST":
        from .models import SurgeryType
        name = request.POST.get("name", "").strip()
        price = request.POST.get("price", "0").replace(",", ".")
        try:
            price_dec = Decimal(price)
            if price_dec < 0:
                messages.error(request, "Narx manfiy bo'lishi mumkin emas!")
            elif SurgeryType.objects.filter(name__iexact=name).exists():
                messages.error(request, "Bunday nomdagi operatsiya turi allaqachon mavjud!")
            else:
                SurgeryType.objects.create(name=name, price=price_dec)
                messages.success(request, f"{name} operatsiyasi qo'shildi.")
        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
    return redirect("clinical:surgery_settings")

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def update_surgery_type_price(request, type_id):
    if request.method == "POST":
        from .models import SurgeryType, SurgeryTypePriceHistory
        st = get_object_or_404(SurgeryType, id=type_id)
        price_str = request.POST.get("price", "0").replace(",", ".")
        try:
            new_price = Decimal(price_str)
            if new_price < 0:
                messages.error(request, "Narx manfiy bo'lishi mumkin emas!")
            elif new_price != st.price:
                with transaction.atomic():
                    SurgeryTypePriceHistory.objects.create(
                        surgery_type=st,
                        old_price=st.price,
                        new_price=new_price,
                        changed_by=request.user
                    )
                    st.price = new_price
                    st.save(update_fields=["price"])
                messages.success(request, f"{st.name} narxi yangilandi.")
            else:
                messages.info(request, "Narx o'zgarmadi.")
        except Exception as e:
            messages.error(request, f"Xatolik: {e}")
    return redirect("clinical:surgery_settings")

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def toggle_surgery_type(request, type_id):
    if request.method == "POST":
        from .models import SurgeryType
        st = get_object_or_404(SurgeryType, id=type_id)
        st.is_active = not st.is_active
        st.save(update_fields=["is_active"])
        messages.success(request, f"{st.name} holati o'zgartirildi.")
    return redirect("clinical:surgery_settings")

# ==========================================
# AVTOKLAV (STERILIZATSIYA) VIEWS
# ==========================================

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def autoclave_settings(request):
    """Superadmin uchun jarrohlik anjomlari va klapanlar ro'yxati (Sozlamalar)."""
    return render(request, "clinical/autoclave_settings.html",
                  {"items": _items_with_history()})

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def autoclave_add_item(request):
    if request.method == "POST":
        from .models import SurgicalItem
        name = request.POST.get("name", "").strip()
        item_type = request.POST.get("item_type")
        serial_number = request.POST.get("serial_number", "").strip()
        
        if name and item_type:
            SurgicalItem.objects.create(
                name=name,
                item_type=item_type,
                serial_number=serial_number,
                status=SurgicalItem.Status.USED,
                created_by=request.user
            ,
            steril_method=request.POST.get("steril_method", "autoclave"))
            messages.success(request, f"{name} bazaga qo'shildi.")
        else:
            messages.error(request, "Nomi va turi majburiy.")
    return redirect("clinical:autoclave_settings")

@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def delete_surgical_item(request, item_id):
    if request.method == "POST":
        from .models import SurgicalItem
        item = get_object_or_404(SurgicalItem, id=item_id)

        # AUDIT HIMOYASI: operatsiyada qatnashgan yoki tarixi bor anjomni
        # o'chirish sterilizatsiya izini butunlay yo'q qiladi (CASCADE).
        # Shuning uchun bunday anjom o'chirilmaydi.
        if item.status == SurgicalItem.Status.IN_USE:
            messages.error(request, f"{item.name} hozir operatsiyada — o'chirib bo'lmaydi.")
        elif item.surgeries.exists() or item.history.exists():
            messages.error(
                request,
                f"{item.name} operatsiya tarixiga ega — o'chirib bo'lmaydi "
                "(epidemiologik iz saqlanishi shart).",
            )
        else:
            try:
                item.delete()
                messages.success(request, "Uskuna o'chirildi.")
            except Exception as e:
                messages.error(request, f"O'chirishda xatolik: {e}")
    return redirect("clinical:autoclave_settings")

@role_required(Role.Code.STERILIZATION, Role.Code.SUPER_ADMIN)
def autoclave_dashboard(request):
    """Avtoklav xodimi uchun asosiy panel. Anjomlar holati ko'rinadi."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    # Tozalagan xodimni tanlash uchun barcha xodimlarni jo'natamiz (asosan hamshiralar, doktorlar, avtoklavchilar)
    staff = User.objects.filter(is_active=True).select_related("role").order_by("first_name", "last_name")

    items = list(_items_with_history())
    # BO'SH HOLATNI to'g'ri ko'rsatish uchun ro'yxatlar shu yerda ajratiladi
    # (ilgari shablon "umuman anjom yo'q"ni "ifloslangan yo'q" bilan chalkashtirardi).
    return render(request, "clinical/autoclave_dashboard.html", {
        "items": items,
        "dirty_items": [i for i in items if i.status == SurgicalItem.Status.USED],
        "ready_items": [i for i in items if i.status == SurgicalItem.Status.READY],
        "in_use_items": [i for i in items if i.status == SurgicalItem.Status.IN_USE],
        "staff": staff,
    })

@role_required(Role.Code.STERILIZATION, Role.Code.SUPER_ADMIN)
def update_item_status(request, item_id):
    """Avtoklav xodimi asbob holatini o'zgartiradi."""
    if request.method == "POST":
        from .models import SurgicalItem, SurgicalItemHistory
        item = get_object_or_404(SurgicalItem, id=item_id)
        new_status = request.POST.get("status")

        if new_status not in dict(SurgicalItem.Status.choices):
            messages.error(request, "Noto'g'ri status.")
        elif (item.status == SurgicalItem.Status.IN_USE
              and new_status != SurgicalItem.Status.IN_USE
              and item.surgeries.filter(
                  status__in=[SurgerySchedule.Status.IN_PROGRESS,
                              SurgerySchedule.Status.PRE_OP,
                              SurgerySchedule.Status.SCHEDULED]).exists()):
            # XAVFSIZLIK: davom etayotgan operatsiyaga biriktirilgan anjomni
            # avtoklav paneli orqali "bo'shatib" yuborish mumkin emas.
            messages.error(
                request,
                f"{item.name} hozir operatsiyada band — holatini o'zgartirib "
                "bo'lmaydi. Operatsiya yakunlangach avtomatik qaytadi.",
            )
        else:
            from django.contrib.auth import get_user_model
            User = get_user_model()

            changed_by_user = request.user
            cleaned_by_id = request.POST.get("cleaned_by_id")
            if cleaned_by_id:
                try:
                    changed_by_user = User.objects.get(id=cleaned_by_id)
                except (User.DoesNotExist, ValueError, DjangoValidationError):
                    pass

            # Oxirgi operatsiya konteksti (kimga ishlatilgani) tarixga ko'chadi
            last_use = item.history.filter(surgery__isnull=False).order_by("-used_at").first()
            last_surgery = last_use.surgery if last_use else None

            item.status = new_status
            if new_status == SurgicalItem.Status.READY:
                # Sterillangan anjom operatsion xonada emas, omborda turadi
                item.current_room = None
            item.save(update_fields=["status", "current_room"])

            if new_status == SurgicalItem.Status.READY:
                action = f"Sterilizatsiyadan o'tdi ({item.get_steril_method_display()})"
            else:
                action = f"Holati o'zgartirildi: {item.get_status_display()}"
            SurgicalItemHistory.log(
                item, action, user=changed_by_user, surgery=last_surgery,
            )

            messages.success(request, f"{item.name} holati '{item.get_status_display()}' ga o'zgardi.")


    # Agar sorov dashboarddan kelsa o'sha yerga, settingsdan kelsa o'sha yerga qaytamiz
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect("clinical:autoclave_dashboard")


# ==========================================
# TASHXIS SHABLONLARI (har shifokor o'ziniki)
# ==========================================

@role_required("super_admin", "administrator", "chief_doctor", "doctor")
def save_consultation_template(request, pk):
    """Joriy forma qiymatlarini shifokorning shaxsiy shabloni sifatida saqlaydi."""
    if request.method != "POST":
        return redirect("clinical:consultation", pk=pk)

    name = request.POST.get("template_name", "").strip()
    if not name:
        messages.error(request, "Shablon nomini kiriting.")
        return redirect("clinical:consultation", pk=pk)

    ConsultationTemplate.objects.update_or_create(
        doctor=request.user,
        name=name,
        defaults={
            "complaint": request.POST.get("complaint", "").strip(),
            "anamnesis": request.POST.get("anamnesis", "").strip(),
            "objective_status": request.POST.get("objective_status", "").strip(),
            "diagnosis": request.POST.get("diagnosis", "").strip(),
            "prescription": request.POST.get("prescription", "").strip(),
            "recommendations": request.POST.get("recommendations", "").strip(),
        },
    )
    messages.success(request, f"'{name}' shabloni saqlandi. Endi uni tanlab qo'llashingiz mumkin.")
    return redirect("clinical:consultation", pk=pk)


@role_required("super_admin", "administrator", "chief_doctor", "doctor")
def delete_consultation_template(request, template_id):
    """Shifokor faqat O'Z shablonini o'chira oladi."""
    if request.method == "POST":
        template = get_object_or_404(
            ConsultationTemplate, id=template_id, doctor=request.user
        )
        name = template.name
        template.delete()
        messages.success(request, f"'{name}' shabloni o'chirildi.")
    return redirect(request.META.get("HTTP_REFERER") or "core:home")


# ==========================================
# STATSIONAR HUJJATLASHTIRISH (hamshira) + IMZO
# ==========================================

STAY_DOC_ROLES = (
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR,
    Role.Code.ADMINISTRATOR, Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN, Role.Code.SURGEON,
)


def _stay_clinical_context(stay) -> dict:
    """Yotishga bog'liq KLINIK yozuvlar: ko'rik matnlari va tashxislar.

    Epizod yotishga ikki yo'l bilan bog'langan bo'lishi mumkin:
      · `AdmissionEpisode.stay` — kravat berilganda biriktiriladi;
      · tashrif orqali — eski ma'lumotlarda bog'lanish bo'lmasligi mumkin.

    Ikkalasini ham qaraymiz, aks holda eski yotishlarda hujjat bo'sh
    chiqadi.
    """
    from apps.clinical.models import AdmissionEpisode

    episode = getattr(stay, "episode", None)

    # O'CHIRILGAN EPIZOD HISOBGA OLINMAYDI.
    #
    # `stay.episode` teskari bog'lanish soft delete'ni tekshirmaydi —
    # o'chirilgan epizod ham qaytadi va uning yozuvlari hujjatga chiqib
    # ketardi.
    if episode is not None and getattr(episode, "is_deleted", False):
        episode = None

    if episode is None and stay.visit_id:
        episode = (AdmissionEpisode.objects
                   .filter(visit_id=stay.visit_id)
                   .exclude(status=AdmissionEpisode.Status.CANCELLED)
                   .order_by("-created_at")
                   .first())

    if episode is None:
        return {"episode": None, "episode_diagnoses": [], "episode_bloklar": []}

    bloklar = [
        ("Murojaat sababi", episode.reason),
        ("Shikoyatlar", episode.complaints),
        ("Anamnesis morbi", episode.anamnesis_morbi),
        ("Anamnesis vitae", episode.anamnesis_vitae),
        ("Epidemiologik anamnez", episode.epid_anamnesis),
        ("Status praesens", episode.status_praesens),
        ("Status localis", episode.status_localis),
        ("Allergoanamnez", episode.allergo_anamnesis),
        ("Nevrologik holati", episode.neuro_status),
        ("Klinik tashxis", episode.clinical_diagnosis),
    ]
    return {
        "episode": episode,
        "episode_diagnoses": list(episode.diagnoses.select_related("icd")),
        # Bo'shlari chiqmaydi — hujjatni bekorga cho'zadi
        "episode_bloklar": [(n, (m or "").strip()) for n, m in bloklar if (m or "").strip()],
    }


@role_required(*STAY_DOC_ROLES)
def stay_documentation(request, stay_id):
    from apps.clinical.models import OperatingRoom
    """Statsionar yotish hujjatlari sahifasi.

    - Hujjatlashtirish hamshirasi: checklist (nima berildi/qilindi — +/-)
    - Ukol/muolaja hamshirasi: o'z qaydlari (ukol, muolaja, operatsiya, analiz)
    - Oxirida bemor imzosi (ekranda chizib) — hujjatda ko'rinadi
    """
    stay = get_object_or_404(
        InpatientStay.objects.select_related(
            "visit__patient", "bed__room", "doc_nurse", "procedure_nurse",
            "assigned_doctor",
        ),
        id=stay_id,
    )
    # SHU TASHRIFDAGI BARCHA TEKSHIRUVLAR.
    #
    # HAQIQIY XATO: bu yerda `created_at >= admission_date` filtri bor edi,
    # ya'ni faqat YOTQIZILGANDAN KEYIN tayinlanganlari ko'rinardi.
    # Amalda esa oqim teskari: shifokor ambulator ko'rikda tekshiruv
    # buyuradi, natijalar keladi va SHUNDAN KEYIN bemor yotqiziladi.
    # Natijada aynan yotqizishga asos bo'lgan tahlillar statsionar
    # hujjatlarida umuman ko'rinmasdi.
    service_orders = list(
        stay.visit.service_orders.select_related("service")
        .prefetch_related("result_rows")
        .exclude(status=ServiceOrder.Status.CANCELLED)
        .order_by("created_at")
    )
    for o in service_orders:
        # Qaysi biri yotqizishdan oldin bo'lganini ajratib ko'rsatamiz
        o.yotishdan_oldin = bool(
            stay.admission_date and o.created_at < stay.admission_date)

    # Rejalashtirilgan operatsiyalar
    surgeries = stay.visit.surgeries.select_related(
        "surgery_type", "surgeon", "report"
    ).exclude(status="cancelled").order_by("scheduled_time")

    ctx_docs = {
        "stay": stay,
        # Statsionardan turib operatsiya tayinlash uchun (to'liq jamoa + xona)
        **surgery_team_context(),
        "checklist": stay.checklist_items.select_related("done_by").all(),
        "procedures": stay.procedure_records.select_related("nurse").all(),
        "dispenses": stay.visit.dispensed_medicines.filter(
            is_returned=False
        ).exclude(status='cancelled').select_related(
            "batch__medicine"
        ).order_by("-dispensed_at"),
        "service_orders": service_orders,
        "surgeries": surgeries,
        "categories": StayChecklistItem.Category.choices,
        "proc_categories": ProcedureRecord.Category.choices,
        # KLINIK YOZUVLAR — shifokorning dastlabki ko'rigi va tashxislari.
        #
        # Ilgari bu sahifa faqat hamshira yozuvlarini ko'rsatardi
        # (checklist, ukollar, dorilar). Shikoyatlar, anamnez, klinik
        # tashxis va MKB-10 kodlari epizodda saqlanadi va ular bu yerga
        # umuman chiqmasdi — holbuki statsionar hujjati aynan shulardan
        # boshlanadi.
        **_stay_clinical_context(stay),
    }
    # Rasmiy TOZA hujjat (alohida shablon — imzo rasmi bilan, keraksiz UI'siz)
    if request.GET.get("format") == "word":
        from django.template.loader import render_to_string
        from apps.core.exports import export_html_to_word
        ctx_docs["word_export"] = True
        html = render_to_string("clinical/stay_documentation_official.html", ctx_docs, request=request)
        fname = f"Statsionar_hujjati_{stay.visit.patient.last_name}_{stay.visit.patient.first_name}"
        return export_html_to_word(html, fname)
    if request.GET.get("official") == "1":
        # Chop etish uchun toza rasmiy ko'rinish (imzo rasmi ko'rinadi)
        return render(request, "clinical/stay_documentation_official.html", ctx_docs)
    return render(request, "clinical/stay_documentation.html", ctx_docs)


def _stay_locked(stay, user):
    """Bemor IMZO qo'ygan yotish hujjatlari QULFLANADI — o'zgartirib bo'lmaydi.

    Bu o'g'irlik/soxtalashtirishning oldini oladi: imzolangan hujjatga
    keyin hech narsa qo'shib bo'lmaydi. Faqat superadmin ochiq qila oladi.
    Kassa (billing) amallariga bu qulf TA'SIR QILMAYDI.
    """
    is_super = user.is_superuser or user.has_role("super_admin")
    # Yakuniy "qulflash" tugmasi bosilган bo'lsa — faqat superadmin ochadi
    if getattr(stay, "is_locked", False):
        return not is_super
    # Yoki bemor imzo qo'ygan bo'lsa
    if not (stay.patient_signature or "").strip():
        return False
    return not is_super


@role_required(*STAY_DOC_ROLES)
def stay_checklist_add(request, stay_id):
    """Hujjat bandini qo'shish (hujjatlashtirish hamshirasi)."""
    if request.method == "POST":
        stay = get_object_or_404(InpatientStay, id=stay_id)
        if _stay_locked(stay, request.user):
            messages.error(request, "Bemor imzo qo'ygan — hujjat qulflangan, o'zgartirib bo'lmaydi.")
            return redirect("clinical:stay_documentation", stay_id=stay.id)
        title = request.POST.get("title", "").strip()
        category = request.POST.get("category", StayChecklistItem.Category.OTHER)
        if category not in StayChecklistItem.Category.values:
            category = StayChecklistItem.Category.OTHER
        if title:
            StayChecklistItem.objects.create(
                stay=stay, title=title, category=category,
                note=request.POST.get("note", "").strip(),
            )
            messages.success(request, "Band qo'shildi.")
        else:
            messages.error(request, "Band nomini kiriting.")
    return redirect("clinical:stay_documentation", stay_id=stay_id)


@role_required(*STAY_DOC_ROLES)
@require_POST
def stay_checklist_toggle(request, item_id):
    """ServiceOrder yoki SurgerySchedule holatini o'zgartirish.

    DIQQAT: `@require_POST` shart. Busiz GET so'rovda funksiya `None`
    qaytarardi va Django «didn't return an HttpResponse» deb 500 berardi.
    Endi to'g'ri 405 qaytadi.

    Template dan type=service_order yoki type=surgery kelib tushadi.
    - service_order: completed <-> waiting
    - surgery: completed <-> scheduled
    Eski StayChecklistItem toggle ham qo'llab-quvvatlanadi (fallback).
    """
    if request.method == "POST":
        toggle_type = request.POST.get("type", "checklist")
        stay_id = None

        if toggle_type == "service_order":
            order = get_object_or_404(ServiceOrder, id=item_id)
            stay = order.visit.inpatient_stays.filter(
                status=InpatientStay.Status.ACTIVE
            ).first()
            stay_id = stay.id if stay else None

            if order.status == ServiceOrder.Status.COMPLETED:
                order.status = ServiceOrder.Status.WAITING
                order.performed_by = None
            else:
                order.status = ServiceOrder.Status.COMPLETED
                order.performed_by = request.user
            order.save(update_fields=["status", "performed_by"])

            # Mos StayChecklistItem ni ham yangilash (agar mavjud bo'lsa)
            StayChecklistItem.objects.filter(
                reference_id=order.id
            ).update(
                is_done=(order.status == ServiceOrder.Status.COMPLETED),
                done_at=timezone.now() if order.status == ServiceOrder.Status.COMPLETED else None,
                done_by=request.user if order.status == ServiceOrder.Status.COMPLETED else None,
            )

        elif toggle_type == "surgery":
            from apps.clinical.models import SurgerySchedule
            surgery = get_object_or_404(SurgerySchedule, id=item_id)
            stay = surgery.visit.inpatient_stays.filter(
                status=InpatientStay.Status.ACTIVE
            ).first()
            stay_id = stay.id if stay else None

            if surgery.status == SurgerySchedule.Status.COMPLETED:
                surgery.status = SurgerySchedule.Status.SCHEDULED
            else:
                surgery.status = SurgerySchedule.Status.COMPLETED
            surgery.save(update_fields=["status"])

            # Mos StayChecklistItem ni ham yangilash
            StayChecklistItem.objects.filter(
                reference_id=surgery.id
            ).update(
                is_done=(surgery.status == SurgerySchedule.Status.COMPLETED),
                done_at=timezone.now() if surgery.status == SurgerySchedule.Status.COMPLETED else None,
                done_by=request.user if surgery.status == SurgerySchedule.Status.COMPLETED else None,
            )

        else:
            # Eski fallback: StayChecklistItem
            #
            # BU YERDA IKKI XATO BOR EDI (chekinish buzilgan):
            #
            #  1) Qulf tekshiruvi `else` dan TASHQARIDA turardi va
            #     «tekshiruv»/«operatsiya» tarmoqlarida ham ishlab
            #     ketardi — u yerda `item` umuman yo'q, natijada
            #     NameError va oq ekran (500).
            #
            #  2) Belgilash satrlari `return` dan KEYIN yozilgan edi,
            #     ya'ni hech qachon bajarilmasdi: hamshira ptechkani
            #     bosadi, sahifa yangilanadi, belgi esa o'z holicha
            #     qoladi. Hech qanday xato ham chiqmasdi.
            item = get_object_or_404(StayChecklistItem, id=item_id)

            if _stay_locked(item.stay, request.user):
                messages.error(request,
                               "Bemor imzo qo'ygan — hujjat qulflangan.")
                return redirect("clinical:stay_documentation",
                                stay_id=item.stay_id)

            item.is_done = not item.is_done
            item.done_at = timezone.now() if item.is_done else None
            item.done_by = request.user if item.is_done else None
            item.save(update_fields=["is_done", "done_at", "done_by"])
            stay_id = item.stay_id

        if stay_id:
            return redirect("clinical:stay_documentation", stay_id=stay_id)
        return redirect("clinical:inpatient_dashboard")


@role_required(*STAY_DOC_ROLES)
def stay_procedure_add(request, stay_id):
    """Ukol/muolaja hamshirasining qaydini kiritish."""
    if request.method == "POST":
        stay = get_object_or_404(InpatientStay, id=stay_id)
        if _stay_locked(stay, request.user):
            messages.error(request, "Bemor imzo qo'ygan — hujjat qulflangan, o'zgartirib bo'lmaydi.")
            return redirect("clinical:stay_documentation", stay_id=stay.id)
        name = request.POST.get("name", "").strip()
        category = request.POST.get("category", ProcedureRecord.Category.INJECTION)
        if category not in ProcedureRecord.Category.values:
            category = ProcedureRecord.Category.INJECTION
        if name:
            rec = ProcedureRecord.objects.create(
                stay=stay, nurse=request.user, category=category,
                name=name, notes=request.POST.get("notes", "").strip(),
            )
            performed_at = request.POST.get("performed_at")
            if performed_at:
                try:
                    from django.utils.dateparse import parse_datetime
                    from django.utils.timezone import is_aware, make_aware
                    
                    dt = parse_datetime(performed_at)
                    if dt:
                        if not is_aware(dt):
                            dt = make_aware(dt)
                        rec.performed_at = dt
                        rec.save(update_fields=["performed_at"])
                except Exception:
                    pass

            # Hujjatlashtirish hisobotiga ham avtomatik + bo'lib tushadi
            StayChecklistItem.objects.create(
                stay=stay,
                category=(
                    StayChecklistItem.Category.INJECTION
                    if category == ProcedureRecord.Category.INJECTION
                    else StayChecklistItem.Category.PROCEDURE
                    if category == ProcedureRecord.Category.PROCEDURE
                    else StayChecklistItem.Category.SURGERY
                    if category == ProcedureRecord.Category.SURGERY
                    else StayChecklistItem.Category.ANALYSIS
                    if category == ProcedureRecord.Category.ANALYSIS
                    else StayChecklistItem.Category.OTHER
                ),
                title=name,
                is_done=True,
                done_at=timezone.now(),
                done_by=request.user,
            )
            messages.success(request, "Qayd kiritildi.")
        else:
            messages.error(request, "Nomini kiriting.")
    return redirect("clinical:stay_documentation", stay_id=stay_id)


@role_required(*STAY_DOC_ROLES)
def stay_save_signature(request, stay_id):
    """Bemor imzosini (canvas'da chizilgan, base64 PNG) saqlash."""
    if request.method == "POST":
        stay = get_object_or_404(InpatientStay, id=stay_id)
        if _stay_locked(stay, request.user):
            messages.error(request, "Imzo allaqachon qo'yilgan — uni almashtirib bo'lmaydi (faqat superadmin).")
            return redirect("clinical:stay_documentation", stay_id=stay_id)
        signature = request.POST.get("signature", "")
        if signature.startswith("data:image/png;base64,") and len(signature) < 500_000:
            stay.patient_signature = signature
            stay.signed_at = timezone.now()
            stay.save(update_fields=["patient_signature", "signed_at"])
            messages.success(request, "Bemor imzosi saqlandi.")
        else:
            messages.error(request, "Imzo chizilmagan yoki noto'g'ri format.")
    return redirect("clinical:stay_documentation", stay_id=stay_id)


# ==========================================
# OPERATSIYA BAYONNOMASI
# ==========================================

@role_required(
    Role.Code.SURGEON, Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.NURSE,
    Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def surgery_report_save(request, schedule_id):
    """Operatsiya bayonnomasini to'ldirish/yangilash (barcha mayda detallar)."""
    if request.method == "POST":
        schedule = get_object_or_404(SurgerySchedule, id=schedule_id)
        existing = SurgeryReport.objects.filter(surgery=schedule).first()
        if existing and not existing.can_modify(request.user):
            messages.error(request, "Bayonnoma qulflangan — faqat superadmin o'zgartira oladi.")
            return redirect(request.META.get("HTTP_REFERER") or "clinical:surgery_dashboard")
        report, _ = SurgeryReport.objects.update_or_create(
            surgery=schedule,
            defaults={
                "arrival_condition": request.POST.get("arrival_condition", "").strip(),
                "performed_actions": request.POST.get("performed_actions", "").strip(),
                "medications": request.POST.get("medications", "").strip(),
                "injections": request.POST.get("injections", "").strip(),
                "anesthesia": request.POST.get("anesthesia", "").strip(),
                "consumables": request.POST.get("consumables", "").strip(),
                "notes": request.POST.get("notes", "").strip(),
                "filled_by": request.user,
            },
        )
        # "O'zgarmas qilib saqlash" tugmasi bosilган bo'lsa — darhol qulflaymiz
        if request.POST.get("lock") == "1":
            report.lock(request.user)
            messages.success(request, "Bayonnoma o'zgarmas qilib qulflandi.")
        else:
            messages.success(request, "Operatsiya bayonnomasi saqlandi.")
    return redirect(request.META.get("HTTP_REFERER") or "clinical:surgery_dashboard")

# ==============================================================
# MUTAXASSISLAR UCHUN (UZI, EKG, Laba) DASHBORD
# ==============================================================

EXAMINER_ROLES = (
    Role.Code.RADIOLOGY, Role.Code.LAB, Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR,
)


def _examiner_can_touch(user, order) -> bool:
    """Foydalanuvchi shu buyurtma ustida ish qila oladimi?

    Qoida modelda — `ServiceCatalog.can_be_performed_by`. Panelda ko'rinish
    filtri bilan bir xil, aks holda laborant boshqa bo'lim tekshiruvini
    yakunlab qo'yishi mumkin edi.
    """
    return order.service.can_be_performed_by(user)


def _my_orders_filter(user):
    """«Menga tegishli tekshiruvlar» uchun so'rov sharti.

    `ServiceCatalog.can_be_performed_by` bilan aynan bir xil mantiq, faqat
    SQL tilida. IKKALASI BIRGA O'ZGARISHI SHART — aks holda xodim
    ro'yxatda ko'rmagan tekshiruvni ocha oladi (yoki aksincha).

    Ustuvorlik:
      1. Mas'ul xodim (xizmatda yoki guruhda) — faqat o'sha odam
      2. Rol (xizmatda yoki guruhda) — o'sha bo'limdagi hamma
      3. Hech narsa yo'q — hammaga ochiq
    """
    from django.db.models import Q

    if user.is_superuser:
        return Q()

    # «Amaldagi mas'ul xodim» — xizmatdagisi, u bo'lmasa guruhdagisi.
    staff_is_me = (
        Q(service__responsible_staff=user)
        | Q(service__responsible_staff__isnull=True,
            service__category__default_staff=user)
    )
    # Mas'ul xodim umuman yo'q (na xizmatda, na guruhda)
    no_staff = Q(service__responsible_staff__isnull=True) & (
        Q(service__category__isnull=True)
        | Q(service__category__default_staff__isnull=True)
    )
    role_is_mine = (
        Q(service__allowed_role=user.role_id)
        | Q(service__allowed_role__isnull=True,
            service__category__default_role=user.role_id)
    )
    no_role = Q(service__allowed_role__isnull=True) & (
        Q(service__category__isnull=True)
        | Q(service__category__default_role__isnull=True)
    )

    return staff_is_me | (no_staff & (role_is_mine | no_role))


class ExaminerDashboardView(RoleRequiredMixin, TemplateView):
    """UZI, EKG va Laboratoriya shifokorlari uchun o'ziga kelgan navbatlar."""
    allowed_roles = EXAMINER_ROLES
    template_name = "clinical/examiner_dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Asosiy filter: faqat "Kutmoqda" (WAITING), "To'langan" (PAID) va
        # "Bajarilmoqda" (IN_PROGRESS) bo'lganlar
        base_query = ServiceOrder.objects.select_related(
            "visit__patient", "service", "visit__doctor",
            "service__room", "service__responsible_staff", "service__allowed_role",
            "accepted_by", "deferred_by", "called_by",
        ).exclude(
            status__in=[ServiceOrder.Status.COMPLETED, ServiceOrder.Status.CANCELLED]
        )
        # Menga tegishlilari: mas'ul xodim MEN, yoki mas'ul yo'q-u rolim mos
        base_query = base_query.filter(_my_orders_filter(self.request.user))

        # Bajarilganlar (faqat bugungi yoki o'zi bajarganlar)
        completed_query = ServiceOrder.objects.select_related("visit__patient", "service", "performed_by").filter(
            status=ServiceOrder.Status.COMPLETED,
            performed_by=self.request.user
        ).order_by("-updated_at")[:20]

        pending = list(base_query.order_by("created_at"))
        # "Men qabul qilganlar" tepada alohida ko'rinadi
        context["in_progress_orders"] = [
            o for o in pending if o.status == ServiceOrder.Status.IN_PROGRESS
        ]
        context["pending_orders"] = [
            o for o in pending if o.status != ServiceOrder.Status.IN_PROGRESS
        ]
        context["completed_orders"] = completed_query
        return context


@role_required(
    Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR, Role.Code.RECEPTION,
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.NURSE,
)
def service_referral(request, visit_id):
    """Bemorga beriladigan yo'llanma — qaysi xonaga, kimning oldiga borishi.

    Chop etib bemorning qo'liga beriladi.
    """
    visit = get_object_or_404(
        Visit.objects.select_related("patient", "doctor"), id=visit_id
    )
    orders = visit.service_orders.exclude(
        status__in=[ServiceOrder.Status.CANCELLED, ServiceOrder.Status.COMPLETED]
    ).select_related(
        "service__room", "service__responsible_staff", "service__allowed_role"
    ).order_by("created_at")

    total = sum((o.price_snapshot or 0) for o in orders)
    return render(request, "clinical/service_referral.html", {
        "visit": visit,
        "orders": orders,
        "total": total,
        "now": timezone.now(),
    })


class ExaminerOrderCallView(RoleRequiredMixin, View):
    """«Chaqirish» — bemor tabloda e'lon qilinadi (ovoz bilan).

    Tekshiruv tayinlanishi bilan tabloda chiqmaydi — navbatda kutadi.
    Xodim tayyor bo'lgandagina chaqiradi.
    """
    allowed_roles = EXAMINER_ROLES

    def post(self, request, order_id):
        order = get_object_or_404(
            ServiceOrder.objects.select_related(
                "service__room", "service__responsible_staff", "visit__patient"
            ),
            id=order_id,
        )
        blocked = order.payment_blocked_reason
        if not _examiner_can_touch(request.user, order):
            messages.error(request, "Bu tekshiruv sizga biriktirilmagan.")
        elif order.status in (ServiceOrder.Status.COMPLETED, ServiceOrder.Status.CANCELLED):
            messages.error(request, "Bu tekshiruv allaqachon yopilgan.")
        elif blocked:
            # OLDINDAN TO'LOV QOIDASI: tekshiruv puli xizmatdan OLDIN
            # to'lanadi. Bemorni chaqirib, keyin «to'lamagansiz» deyish —
            # eng yomon variant, shuning uchun chaqiruvning o'zi to'siladi.
            messages.error(request, blocked)
        else:
            order.called_at = timezone.now()
            order.called_by = request.user
            order.call_count = (order.call_count or 0) + 1
            order.save(update_fields=["called_at", "called_by", "call_count", "updated_at"])
            joy = order.service.destination or "kabinet ko'rsatilmagan"
            messages.success(
                request,
                f"{order.visit.patient.full_name} tabloda chaqirildi → {joy}",
            )
        return redirect("clinical:examiner_dashboard")


class ExaminerOrderAcceptView(RoleRequiredMixin, View):
    """«Qabul qildim» — bemor ichkarida, tekshiruv boshlandi (IN_PROGRESS)."""
    allowed_roles = EXAMINER_ROLES

    def post(self, request, order_id):
        order = get_object_or_404(
            ServiceOrder.objects.select_related("service", "visit__patient"), id=order_id
        )
        blocked = order.payment_blocked_reason
        if not _examiner_can_touch(request.user, order):
            messages.error(request, "Bu tekshiruv sizning rolingizga tegishli emas.")
        elif order.status in (ServiceOrder.Status.COMPLETED, ServiceOrder.Status.CANCELLED):
            messages.error(request, "Bu tekshiruv allaqachon yopilgan.")
        elif blocked:
            messages.error(request, blocked)
        elif order.status == ServiceOrder.Status.IN_PROGRESS:
            kim = order.accepted_by.get_full_name() if order.accepted_by else "boshqa xodim"
            if order.accepted_by_id == request.user.pk:
                messages.info(request, "Siz buni allaqachon qabul qilgansiz.")
            else:
                # Ikki xodim bir bemorni chaqirib qolmasligi uchun
                messages.warning(request, f"Bu bemorni {kim} allaqachon qabul qilgan.")
        else:
            order.status = ServiceOrder.Status.IN_PROGRESS
            order.accepted_by = request.user
            order.accepted_at = timezone.now()
            order.save(update_fields=["status", "accepted_by", "accepted_at", "updated_at"])
            messages.success(
                request,
                f"{order.visit.patient.full_name} qabul qilindi — "
                f"{order.service.name} bajarilmoqda.",
            )
        return redirect("clinical:examiner_dashboard")


class ExaminerOrderDeferView(RoleRequiredMixin, View):
    """«Kechiktirish» — tekshiruv navbatga qaytadi, sabab saqlanadi."""
    allowed_roles = EXAMINER_ROLES

    def post(self, request, order_id):
        order = get_object_or_404(
            ServiceOrder.objects.select_related("service", "visit__patient"), id=order_id
        )
        reason = request.POST.get("reason", "").strip()

        if not _examiner_can_touch(request.user, order):
            messages.error(request, "Bu tekshiruv sizning rolingizga tegishli emas.")
        elif order.status in (ServiceOrder.Status.COMPLETED, ServiceOrder.Status.CANCELLED):
            messages.error(request, "Yopilgan tekshiruvni kechiktirib bo'lmaydi.")
        elif not reason:
            messages.error(request, "Kechiktirish sababini yozing.")
        else:
            order.status = ServiceOrder.Status.WAITING
            order.accepted_by = None
            order.accepted_at = None
            order.deferred_reason = reason[:255]
            order.deferred_at = timezone.now()
            order.deferred_by = request.user
            order.defer_count = (order.defer_count or 0) + 1
            order.save(update_fields=[
                "status", "accepted_by", "accepted_at", "deferred_reason",
                "deferred_at", "deferred_by", "defer_count", "updated_at",
            ])
            messages.warning(
                request,
                f"{order.service.name} kechiktirildi va navbatga qaytdi. Sabab: {reason}",
            )
        return redirect("clinical:examiner_dashboard")


class ExaminerOrderPerformView(RoleRequiredMixin, View):
    """Mutaxassis tomonidan tekshiruv xulosasini yozish va yakunlash."""
    allowed_roles = EXAMINER_ROLES

    @transaction.atomic
    def post(self, request, order_id):
        order = get_object_or_404(ServiceOrder.objects.select_related("service"), id=order_id)
        result_text = request.POST.get("result_text", "").strip()

        # Jadval ko'rinishidagi ko'rsatkichlar. Uch ro'yxat bir-biriga
        # indeks bo'yicha mos keladi (HTML'da bir qatorda turadi).
        names = request.POST.getlist("row_name")
        values = request.POST.getlist("row_value")
        units = request.POST.getlist("row_unit")
        refs = request.POST.getlist("row_ref")
        abnormals = set(request.POST.getlist("row_abnormal"))

        rows = []
        for i, nm in enumerate(names):
            nm = (nm or "").strip()
            val = (values[i] if i < len(values) else "").strip()
            # Nomi ham, qiymati ham bo'sh qator — shunchaki to'ldirilmagan,
            # xato emas. Uni jimgina tashlab ketamiz.
            if not nm or not val:
                continue
            rows.append({
                "name": nm,
                "value": val,
                "unit": (units[i] if i < len(units) else "").strip(),
                "reference": (refs[i] if i < len(refs) else "").strip(),
                "is_abnormal": str(i) in abnormals,
                "sort_order": (i + 1) * 10,
            })

        blocked = order.payment_blocked_reason
        if not _examiner_can_touch(request.user, order):
            messages.error(request, "Bu tekshiruv sizning rolingizga tegishli emas.")
        elif order.status in (ServiceOrder.Status.COMPLETED, ServiceOrder.Status.CANCELLED):
            messages.error(request, "Bu tekshiruv allaqachon yopilgan.")
        elif blocked:
            messages.error(request, blocked)
        elif not result_text and not rows:
            # UZI/EKG da matn, laboratoriyada jadval bo'ladi — bittasi
            # bo'lsa yetarli, ikkalasini ham talab qilish noto'g'ri.
            messages.error(request, "Natija kiritilmagan: xulosa matni yoki ko'rsatkichlar kerak.")
        else:
            order.result_text = result_text
            order.status = ServiceOrder.Status.COMPLETED
            order.performed_by = request.user
            order.result_at = timezone.now()
            # Qabul qilmasdan to'g'ridan-to'g'ri yakunlangan bo'lsa ham
            # kim qachon boshlagani yozilib qolsin
            if order.accepted_at is None:
                order.accepted_by = request.user
                order.accepted_at = timezone.now()
            order.save(update_fields=[
                "result_text", "status", "performed_by", "result_at",
                "accepted_by", "accepted_at", "updated_at",
            ])

            # Qayta saqlashda eski qatorlar qolib ketmasligi uchun almashtiramiz
            order.result_rows.all().delete()
            ServiceResultRow.objects.bulk_create([
                ServiceResultRow(order=order, **r) for r in rows
            ])
            messages.success(request, f"{order.service.name} tekshiruvi muvaffaqiyatli yakunlandi!")

        return redirect("clinical:examiner_dashboard")

# -----------------------------------------------------------------------------
# SURGERY PROTOCOLS & ZAYAVKA
# -----------------------------------------------------------------------------

# ==========================================================================
# OPERATSIYA PERMISSIONLARI — har amal o'z roliga
# ==========================================================================
# Har doim ruxsat etilganlar (boshqaruv)
_SA = (Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR)

# Anesteziolog qismi: ko'rik, narkoz materiallari (zayavka/yuborish/qaytarish),
# intraoperatsion protokol (davleniye/puls). Narkotik hisobot alohida yuritiladi.
ANESTH_ROLES = _SA + (Role.Code.ANESTHESIOLOGIST,)

# Operatsion hamshira: xona tayyorlash, steril naborlardan FOYDALANISH,
# ishlatilgan/ishlatilmagan belgilash va qolgan sarf-harajatlar.
# OPERATSION BLOK — palata va operatsion hamshiralarga.
#
# Palata hamshirasi bemorni operatsiyaga tayyorlaydi, olib boradi va
# qaytarib oladi — blok unga kerak. Oddiy hamshira esa faqat aniq
# biriktirilganda kiradi: anestiziska va operatsion hamshiraga
# «operatsion hamshira» roli qo'shimcha qilib beriladi. Ilgari bu yerda
# `NURSE` turardi, ya'ni klinikadagi HAMMA hamshira kirardi.
NURSE_ROLES = _SA + (Role.Code.OPERATING_NURSE, Role.Code.WARD_NURSE)

# Bo'lim hamshirasi: bemorni tayyorlash (1-qadam)
WARD_NURSE_ROLES = _SA + (Role.Code.WARD_NURSE,)

# Avtoklav (sterilizatsiya) hamshirasi: asboblarni OLIB KELISH / QAYTARISH
STERIL_ROLES = _SA + (Role.Code.STERILIZATION,)

# Tayyorlash (xona + steril naborlarni biriktirish) —
# bo'lim/operatsion hamshira, avtoklav hamshirasi VA anesteziolog
PREP_ROLES = _SA + (
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.OPERATING_NURSE,
    Role.Code.STERILIZATION,
    Role.Code.ANESTHESIOLOGIST,
)

# Jarrohga tegishli: operatsiyani boshlash / yakunlash / bayonnoma
SURGEON_ROLES = _SA + (
    Role.Code.SURGEON, Role.Code.SURGERY_ADMIN,
    Role.Code.CHIEF_DOCTOR, Role.Code.DIRECTOR,
)

# Jarayon sahifasini KO'RA oladiganlar (hammasi — faqat o'z qismini tahrirlaydi)
PROCESS_ROLES = tuple(set(
    ANESTH_ROLES + NURSE_ROLES + STERIL_ROLES + SURGEON_ROLES
))


@require_POST
@role_required(*ANESTH_ROLES)
def anesthesia_request_create(request, schedule_id):
    schedule = get_object_or_404(SurgerySchedule, id=schedule_id)
    req, created = AnesthesiaRequest.objects.get_or_create(surgery=schedule, defaults={'requested_by': request.user})
    
    # Process items (from a dynamic form, e.g. item_id_1, qty_1)
    # This is a simplified version where we just create the request.
    # We will build a dedicated view or handle it via modal.
    messages.success(request, "Zayavka yaratildi!")
    return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")

@require_POST
@role_required(*SURGEON_ROLES)
def preop_evaluation_save(request, schedule_id):
    schedule = get_object_or_404(SurgerySchedule, id=schedule_id)
    req, _ = AnesthesiaRequest.objects.get_or_create(surgery=schedule)
    req.pre_op_evaluation = request.POST.get('pre_op_evaluation', '')
    req.preparation_notes = request.POST.get('preparation_notes', '')
    req.save(update_fields=['pre_op_evaluation', 'preparation_notes'])
    
    # Move status to PRE_OP if it was SCHEDULED
    if schedule.status == SurgerySchedule.Status.SCHEDULED:
        schedule.status = SurgerySchedule.Status.PRE_OP
        schedule._audit_reason = "Pre-op ko'rik o'tkazildi"
        schedule.save(update_fields=['status'])
        
    messages.success(request, "Pre-Op ko'rik saqlandi.")
    return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")

# ESLATMA: bu yerda ilgari IKKINCHI `surgery_vitals_add` funksiyasi bor edi.
# U pastdagi (@role_required(*ANESTH_ROLES) bilan himoyalangan) versiya
# tomonidan "soyalanib" qolgan — ya'ni hech qachon ishlamasdi, lekin
# `login_required` bilan har qanday foydalanuvchiga ochiqdek ko'rinardi.
# Chalkashlikning oldini olish uchun o'chirildi. Ishlaydigan versiya —
# quyida, "Intraoperatsion protokol" bo'limida.

@require_POST
@role_required(*NURSE_ROLES)
def nurse_usage_add(request, schedule_id):
    schedule = get_object_or_404(SurgerySchedule, id=schedule_id)
    stock_id = request.POST.get('stock_id')
    from decimal import Decimal, InvalidOperation
    try:
        qty = Decimal(request.POST.get('quantity') or "1")
    except (InvalidOperation, TypeError):
        qty = Decimal("1")
    if qty <= 0:
        messages.error(request, "Miqdor 0 dan katta bo'lishi kerak.")
        return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")

    if stock_id:
        stock = _safe_get_stock(stock_id)
        if not stock:
            messages.error(request, "Mahsulot topilmadi.")
            return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")
        # Zayavkada borligini tekshirish
        anesthesia_request = getattr(schedule, 'anesthesia_request', None)
        if not anesthesia_request:
            messages.error(request, "Oldin Zayavka yuborilishi kerak.")
            return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")
        
        req_item = anesthesia_request.items.filter(stock=stock).first()
        if not req_item:
            messages.error(request, "Bu dori Zayavkada yo'q (Olib kelinmagan).")
            return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")
        
        from django.db.models import Sum
        already_used = NurseUsageItem.objects.filter(surgery=schedule, stock=stock).aggregate(t=Sum('quantity'))['t'] or Decimal("0")
        available_to_use = req_item.quantity - req_item.returned_quantity - already_used
        
        if qty > available_to_use:
            messages.error(request, f"Xonadagi qoldiqdan oshib ketdi! Kiritish mumkin: {available_to_use} {stock.unit}")
            return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")

        NurseUsageItem.objects.create(
            surgery=schedule,
            stock=stock,
            quantity=qty,
            price=0,  # Zayavka orqali hisoblanganligi sababli bu yerda narx 0
            recorded_by=request.user
        )
    messages.success(request, "Sarflangan dori qayd etildi.")
    return redirect(request.META.get('HTTP_REFERER') or "clinical:surgery_dashboard")

@login_required
def surgery_dashboard_table(request):
    from apps.clinical.models import SurgerySchedule, SurgeryType, AnesthesiaStock
    from apps.accounts.models import Role
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    surgeries = _with_past_reports(SurgerySchedule.objects.select_related(
        "visit__patient", "surgery_type", "surgeon", "assistant",
        "anesthesiologist", "operating_nurse", "operating_room",
    ).order_by("scheduled_time"))

    context = {
        "surgeries": surgeries,
        "anesthesia_stocks": AnesthesiaStock.objects.filter(is_active=True),
        # Tahrirlash modali uchun jamoa ro'yxatlari — bu yerda ham
        # qo'shimcha rollar hisobga olinishi kerak, aks holda tahrir
        # oynasi tanlash oynasidan boshqacha ro'yxat ko'rsatib qolardi.
        **{k: v for k, v in surgery_team_context().items()
           if k in ("surgeons", "assistants", "anesthesiologists",
                    "operating_nurses", "ward_nurses", "operating_rooms")},
    }
    context.update(_role_flags(request.user))
    return render(request, "clinical/surgery_dashboard_table.html", context)


# ==========================================================================
# OPERATSIYA JARAYONI — 4 qadam (bemor tayyorlash → ko'rik → xona tayyorlash → protokol)
# ==========================================================================
from apps.clinical.models import (  # noqa: E402
    AnesthesiaRequest,
    AnesthesiaRequestItem,
    AnesthesiaStock,
    NurseUsageItem,
    OperatingRoom,
    SurgeryVitals,
)

# Jarayonni ko'ra oladigan jamoa
def _role_flags(user):
    """Foydalanuvchi roliga qarab qaysi bo'limlarni tahrirlashi mumkinligi."""
    su = user.is_superuser or user.has_role("super_admin")
    return {
        "can_anesth": su or user.has_role(*ANESTH_ROLES),
        "can_nurse": su or user.has_role(*NURSE_ROLES),
        "can_ward_nurse": su or user.has_role(*WARD_NURSE_ROLES),
        "can_steril": su or user.has_role(*STERIL_ROLES),
        "can_prep": su or user.has_role(*PREP_ROLES),
        "can_surgeon": su or user.has_role(*SURGEON_ROLES),
        # Bayonnoma yozish: jarroh/shifokor/hamshira/boshqaruv (anesteziolog EMAS)
        "can_report": su or user.has_role(
            Role.Code.SURGEON, Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR,
            Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.NURSE,
            Role.Code.ADMINISTRATOR,
        ),
        # Operatsiyaga yozish (jadval): jarroh/shifokor/boshqaruv (anesteziolog/hamshira EMAS)
        "can_schedule": su or user.has_role(
            Role.Code.SURGEON, Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR,
            Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.ADMINISTRATOR,
        ),
    }


def _safe_get_stock(stock_id):
    """Ombor mahsulotini xavfsiz topish — noto'g'ri ID 500 emas, None qaytaradi."""
    if not stock_id:
        return None
    try:
        return AnesthesiaStock.objects.filter(id=stock_id).first()
    except (ValueError, Exception):
        return None


def _ready_items_for(surgery):
    """Operatsiya turiga mos STERIL asboblar ro'yxati.

    Belyo (LINEN, avtoklav) hamma turda chiqadi. Anjomlar esa:
    ochiq operatsiyada — faqat avtoklavdan o'tganlari,
    endoskopikda — faqat rastvor sterilizatsiyadan o'tganlari.
    """
    from django.db.models import Q
    base = SurgicalItem.objects.filter(status=SurgicalItem.Status.READY)
    kind = getattr(surgery.surgery_type, "kind", "open")
    # Belyo — har turdagi operatsiyada chiqadi
    linen_q = Q(item_type=SurgicalItem.Type.LINEN,
                steril_method=SurgicalItem.SterilMethod.AUTOCLAVE)
    if kind == "endoscopic":
        instr_q = Q(steril_method=SurgicalItem.SterilMethod.SOLUTION) & ~Q(
            item_type=SurgicalItem.Type.LINEN)
    else:
        instr_q = Q(steril_method=SurgicalItem.SterilMethod.AUTOCLAVE) & ~Q(
            item_type=SurgicalItem.Type.LINEN)
    return base.filter(linen_q | instr_q).order_by("item_type", "name")


def _supply_context(surgery):
    """Operatsion hamshiraning asosiy ombor zayavkasi.

    Ombordagi mahsulotlar ro'yxati ham shu yerdan beriladi — oynada
    alohida so'ralsa, ikki joyda ikki xil filtr paydo bo'lardi.
    """
    from apps.clinical.models import SurgerySupplyRequest

    zayavka = getattr(surgery, "supply_request", None)
    return {
        "supply_request": zayavka,
        "supply_items": (zayavka.items.select_related("stock")
                         if zayavka else []),
    }


def _surgery_process_context(surgery, user=None):
    """Jarayon sahifasi uchun umumiy kontekst."""
    from apps.clinical.models import RoomLeftover
    request_obj = getattr(surgery, "anesthesia_request", None)
    all_stocks = AnesthesiaStock.objects.filter(is_active=True).order_by("name")
    
    # Operatsion xonada qolgan qoldiqlar
    room_leftovers = []
    if surgery.operating_room:
        room_leftovers = RoomLeftover.objects.filter(
            room=surgery.operating_room, quantity__gt=0
        ).select_related("stock", "from_surgery")
    
    ctx = {
        "surgery": surgery,
        "anesthesia_types": SurgerySchedule.AnesthesiaType.choices,
        "stock_items": all_stocks,
        "psychotropic_stocks": all_stocks.filter(is_psychotropic=True),
        "non_psychotropic_stocks": all_stocks.filter(is_psychotropic=False),
        "anesthesia_request": request_obj,
        "request_items": request_obj.items.select_related("stock") if request_obj else [],
        "vitals": surgery.vitals.select_related("recorded_by").order_by("recorded_at"),
        "nurse_usages": surgery.nurse_usages.all(),
        # STERILIZATSIYA QOIDASI:
        #   Belyo (avtoklav) — HAMMA operatsiya turida
        #   Ochiq operatsiya  -> avtoklavdan chiqqan anjomlar
        #   Endoskopik        -> rastvor sterilizatsiyadan chiqqan anjomlar
        "ready_items": _ready_items_for(surgery),
        "attached_items": surgery.items_used.all(),
        "anesthesia_total": surgery.anesthesia_expense_total,
        "nurse_total": surgery.nurse_expense_total,
        # Klinika ichki hisobi: bemorga yozilmaydi, operatsiya narxi ichida
        "surgery_profit": (surgery.actual_price or 0)
                          - surgery.anesthesia_expense_total
                          - surgery.nurse_expense_total,
        "room_leftovers": room_leftovers,
        # OPERATSION HAMSHIRA ZAYAVKASI (asosiy ombor)
        **_supply_context(surgery),
    }
    if user is not None:
        ctx.update(_role_flags(user))
    return ctx


@role_required(*PROCESS_ROLES)
def surgery_process(request, schedule_id):
    """Operatsiya jarayoni sahifasi — barcha qadamlar bitta joyda."""
    surgery = get_object_or_404(
        SurgerySchedule.objects.select_related(
            "visit__patient", "surgery_type", "surgeon", "assistant",
            "anesthesiologist", "operating_nurse", "operating_room",
        ),
        id=schedule_id,
    )
    context = _surgery_process_context(surgery, request.user)
    # HTMX bilan avtomatik yangilanish uchun faqat ichki qismni qaytaramiz
    if request.headers.get("HX-Request") and request.GET.get("partial") == "1":
        return render(request, "clinical/_surgery_process_body.html", context)
    return render(request, "clinical/surgery_process.html", context)


@role_required(*ANESTH_ROLES)
def surgery_step_anesthesia(request, schedule_id):
    """2-qadam: anesteziologik ko'rik / punksiya + narkoz turi."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        surgery.anesthesia_type = request.POST.get("anesthesia_type", "")
        surgery.anesthesia_exam_note = request.POST.get("anesthesia_exam_note", "")
        surgery.anesthesia_exam_at = timezone.now()
        if surgery.stage in (SurgerySchedule.Stage.SCHEDULED,
                             SurgerySchedule.Stage.PATIENT_PREP):
            surgery.stage = SurgerySchedule.Stage.ANESTHESIA_EXAM
        surgery.save(update_fields=[
            "anesthesia_type", "anesthesia_exam_note", "anesthesia_exam_at", "stage",
        ])
        messages.success(request, "Anesteziologik ko'rik saqlandi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*PREP_ROLES)
def surgery_step_preparation(request, schedule_id):
    """3-qadam: operatsiyaga tayyorlash (operatsion hamshira).

    Hamshira xonani tayyorlaydi va avtoklavdan chiqqan steril naborlarni
    biriktiradi.
    """
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        surgery.preparation_note = request.POST.get("preparation_note", "")
        surgery.room_prepared = request.POST.get("room_prepared") == "1"
        surgery.preparation_at = timezone.now()

        # Avtoklavdan steril naborlarni biriktirish — ular shu operatsion xonaga
        # "olib kelinadi" (current_room). Operatsiyada bo'lib turadi.
        item_ids = request.POST.getlist("items")
        if item_ids:
            selected = list(SurgicalItem.objects.filter(
                id__in=item_ids, status=SurgicalItem.Status.READY
            ))
            if selected:
                surgery.items_used.add(*selected)
                SurgicalItem.objects.filter(id__in=[i.id for i in selected]).update(
                    status=SurgicalItem.Status.IN_USE,
                    current_room=surgery.operating_room,
                )
                # AUDIT: anjom KIMGA va KIM boshchiligidagi operatsiyaga
                # biriktirilgani shu yerda yoziladi.
                for it in selected:
                    SurgicalItemHistory.log(
                        it, "Operatsiyaga biriktirildi (steril)",
                        user=request.user, surgery=surgery,
                    )

        if surgery.stage in (SurgerySchedule.Stage.SCHEDULED,
                             SurgerySchedule.Stage.PATIENT_PREP,
                             SurgerySchedule.Stage.ANESTHESIA_EXAM):
            surgery.stage = SurgerySchedule.Stage.PREPARATION
        surgery.save(update_fields=[
            "preparation_note", "room_prepared", "preparation_at", "stage",
        ])
        messages.success(request, "Tayyorlash ma'lumotlari saqlandi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*WARD_NURSE_ROLES)
def surgery_patient_prep(request, schedule_id):
    """1-qadam: bo'lim hamshirasi bemorni operatsiyaga tayyorlaydi."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        surgery.patient_prep_note = request.POST.get("patient_prep_note", "")
        prepared = request.POST.get("patient_prepared") == "1"
        surgery.patient_prepared = prepared
        surgery.patient_prepared_at = timezone.now() if prepared else None
        if prepared and surgery.stage == SurgerySchedule.Stage.SCHEDULED:
            surgery.stage = SurgerySchedule.Stage.PATIENT_PREP
        surgery.save(update_fields=[
            "patient_prep_note", "patient_prepared", "patient_prepared_at", "stage",
        ])
        messages.success(request, "Bemor tayyorlash ma'lumotlari saqlandi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*(SURGEON_ROLES + ANESTH_ROLES))
def surgery_start_operation(request, schedule_id):
    """4-qadamga o'tish: operatsiyani boshlash (protokol yuritila boshlaydi)."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        # Foydalanuvchi talabiga asosan qat'iy validatsiyalar olib tashlandi.
        # if not surgery.patient_prepared:
        #     messages.error(request, "Avval bemor tayyorlanishi kerak (1-qadam: Bo'lim hamshirasi).")
        #     return redirect("clinical:surgery_process", schedule_id=surgery.id)
        # if not surgery.anesthesia_exam_at:
        #     messages.error(request, "Avval anesteziologik ko'rik o'tkazilishi kerak (2-qadam).")
        #     return redirect("clinical:surgery_process", schedule_id=surgery.id)
        # if not surgery.room_prepared:
        #     messages.error(request, "Avval operatsion xona tayyorlanishi kerak (3-qadam).")
        #     return redirect("clinical:surgery_process", schedule_id=surgery.id)
        # 
        # req = getattr(surgery, "anesthesia_request", None)
        # if req is None or req.status != AnesthesiaRequest.Status.SENT:
        #     messages.error(
        #         request,
        #         "Anesteziolog materiallarni «Yuborildi» deb belgilamaguncha "
        #         "operatsiyani boshlab bo'lmaydi.",
        #     )
        #     return redirect("clinical:surgery_process", schedule_id=surgery.id)
        # 
        # has_linen = surgery.items_used.filter(
        #     item_type=SurgicalItem.Type.LINEN
        # ).exists()
        # if not has_linen:
        #     messages.error(
        #         request,
        #         "Steril BELYO (material biks) biriktirilmagan — belyo har "
        #         "qanday operatsiyada majburiy. 2-qadamda belyoni tanlang.",
        #     )
        #     return redirect("clinical:surgery_process", schedule_id=surgery.id)
        
        surgery.stage = SurgerySchedule.Stage.OPERATING
        surgery.status = SurgerySchedule.Status.IN_PROGRESS
        surgery.started_at = timezone.now()
        surgery.save(update_fields=["stage", "status", "started_at"])
        messages.success(request, "Operatsiya boshlandi — protokol yuritilmoqda.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*SURGEON_ROLES)
def surgery_finish_operation(request, schedule_id):
    """Operatsiyani yakunlash — asboblar ifloslangan holatga o'tadi."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        # Foydalanuvchi talabiga asosan qat'iy validatsiyalar olib tashlandi
        # (surgery_start_operation bilan bir xil)
            
        surgery.stage = SurgerySchedule.Stage.FINISHED
        surgery.status = SurgerySchedule.Status.COMPLETED
        surgery.finished_at = timezone.now()
        surgery.save(update_fields=["stage", "status", "finished_at"])
        # Faqat hali belgilanmagan (operatsiyada turgan) asboblar ifloslangan bo'ladi.
        # "Ishlatilmadi" deb belgilangan asboblar READY holatida xonada qoladi.
        still_in_use = list(surgery.items_used.filter(status=SurgicalItem.Status.IN_USE))
        if still_in_use:
            SurgicalItem.objects.filter(id__in=[i.id for i in still_in_use]).update(
                status=SurgicalItem.Status.USED
            )
            for it in still_in_use:
                SurgicalItemHistory.log(
                    it, "Operatsiyada ishlatildi — tozalashga qaytarildi",
                    user=request.user, surgery=surgery,
                )
        
        anesthesia_request = getattr(surgery, 'anesthesia_request', None)
        if anesthesia_request:
            from django.db import transaction
            from django.db.models import Sum, F
            from decimal import Decimal
            from apps.clinical.models import RoomLeftover
            with transaction.atomic():
                for req_item in anesthesia_request.items.select_related('stock'):
                    already_used = NurseUsageItem.objects.filter(surgery=surgery, stock=req_item.stock).aggregate(
                        t=Sum(F('quantity') - F('returned_quantity'))
                    )['t'] or Decimal("0")
                    left_in_room = req_item.quantity - (req_item.returned_quantity or Decimal("0")) - already_used
                    if left_in_room > 0:
                        req_item.returned_quantity = (req_item.returned_quantity or Decimal("0")) + left_in_room
                        req_item.save(update_fields=["returned_quantity"])
                        
                        # Qoldiqlarni omborga emas, operatsion xona qoldiqlariga o'tkazish
                        if surgery.operating_room:
                            leftover, created = RoomLeftover.objects.get_or_create(
                                room=surgery.operating_room,
                                stock=req_item.stock,
                                defaults={'quantity': left_in_room, 'from_surgery': surgery},
                            )
                            if not created:
                                leftover.quantity += left_in_room
                                leftover.from_surgery = surgery
                                leftover.save(update_fields=["quantity", "from_surgery"])
                        else:
                            # Agar operatsion xona belgilanmagan bo'lsa, omborga qaytarish
                            stock = req_item.stock
                            stock.quantity = (stock.quantity or 0) + left_in_room
                            stock.save(update_fields=["quantity"])
        messages.success(request, "Operatsiya yakunlandi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*ANESTH_ROLES)
def surgery_vitals_add(request, schedule_id):
    """Intraoperatsion protokol: vaqtli ko'rsatkich qo'shish."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        pulse = request.POST.get("pulse") or None
        spo2 = request.POST.get("spo2") or None
        # Vaqt: anesteziolog o'zi tanlaydi (HH:MM). Bo'sh qoldirsa — hozirgi vaqt.
        rec_time = request.POST.get("recorded_time", "").strip()
        recorded_at = timezone.now()
        if rec_time:
            try:
                import datetime as _dt
                t = _dt.datetime.strptime(rec_time, "%H:%M").time()
                recorded_at = timezone.make_aware(
                    _dt.datetime.combine(timezone.localdate(), t)
                )
            except ValueError:
                pass
        SurgeryVitals.objects.create(
            surgery=surgery,
            recorded_at=recorded_at,
            blood_pressure=request.POST.get("blood_pressure", "").strip(),
            pulse=int(pulse) if pulse and str(pulse).isdigit() else None,
            spo2=int(spo2) if spo2 and str(spo2).isdigit() else None,
            note=request.POST.get("note", "").strip(),
            recorded_by=request.user,
        )
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*NURSE_ROLES)
def surgery_nurse_usage_add(request, schedule_id):
    """Operatsion hamshira: ombordan anjom/dori olish.

    Ombordan tanlanadi — narx o'sha paytdagi sotish narxida qotiriladi
    va ombor qoldig'i shu miqdorga kamayadi.
    """
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        from decimal import Decimal
        stock = _safe_get_stock(request.POST.get("stock_id"))
        if stock is None:
            messages.error(request, "Ombordan mahsulot tanlanmadi.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        try:
            qty = Decimal(request.POST.get("quantity") or "1")
        except Exception:
            qty = Decimal("1")
        if qty <= 0:
            messages.error(request, "Soni noto'g'ri.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        if (stock.quantity or 0) < qty:
            messages.error(
                request,
                f"Omborda yetarli emas: {stock.name} — qoldiq {stock.quantity} {stock.unit}.",
            )
            return redirect("clinical:surgery_process", schedule_id=surgery.id)

        with transaction.atomic():
            NurseUsageItem.objects.create(
                surgery=surgery, stock=stock, quantity=qty,
                price=stock.selling_price, recorded_by=request.user,
            )
            stock.quantity = (stock.quantity or 0) - qty
            stock.save(update_fields=["quantity"])
        messages.success(request, f"{stock.name} × {qty} yozildi (ombordan yechildi).")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*ANESTH_ROLES)
def anesthesia_request_add_item(request, schedule_id):
    """Zayavkaga PSIXOTROP mahsulot qo'shish (faqat Anesteziolog)."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        stock_id = request.POST.get("stock_id")
        stock = _safe_get_stock(stock_id)
        if stock:
            if not stock.is_psychotropic:
                messages.error(request, f"{stock.name} psixotrop dori emas — uni operatsion hamshira zayavka qilishi kerak.")
                return redirect("clinical:surgery_process", schedule_id=surgery.id)
            from decimal import Decimal
            try:
                qty = Decimal(request.POST.get("quantity") or "1")
            except Exception:
                qty = Decimal("1")
            if qty <= 0:
                qty = Decimal("1")
            req, _ = AnesthesiaRequest.objects.get_or_create(
                surgery=surgery, defaults={"requested_by": request.user}
            )
            if req.status == AnesthesiaRequest.Status.SENT:
                messages.error(request, "Zayavka allaqachon yuborilgan — o'zgartirib bo'lmaydi.")
            else:
                AnesthesiaRequestItem.objects.create(
                    request=req, stock=stock, quantity=qty,
                    price_snapshot=stock.selling_price,
                )
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*NURSE_ROLES)
def nurse_request_add_item(request, schedule_id):
    """Zayavkaga ODDIY (psixotrop bo'lmagan) mahsulot qo'shish (Operatsion hamshira)."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        stock_id = request.POST.get("stock_id")
        stock = _safe_get_stock(stock_id)
        if stock:
            if stock.is_psychotropic:
                messages.error(request, f"{stock.name} psixotrop dori — uni faqat Anesteziolog zayavka qilishi kerak.")
                return redirect("clinical:surgery_process", schedule_id=surgery.id)
            from decimal import Decimal
            try:
                qty = Decimal(request.POST.get("quantity") or "1")
            except Exception:
                qty = Decimal("1")
            if qty <= 0:
                qty = Decimal("1")
            req, _ = AnesthesiaRequest.objects.get_or_create(
                surgery=surgery, defaults={"requested_by": request.user}
            )
            if req.status == AnesthesiaRequest.Status.SENT:
                messages.error(request, "Zayavka allaqachon yuborilgan — o'zgartirib bo'lmaydi.")
            else:
                AnesthesiaRequestItem.objects.create(
                    request=req, stock=stock, quantity=qty,
                    price_snapshot=stock.selling_price,
                )
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*ANESTH_ROLES)
def anesthesia_request_send(request, schedule_id):
    """Anesteziolog «Yuborildi» tugmasi — ombordan yechiladi va xarajat qotiriladi."""
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        req = getattr(surgery, "anesthesia_request", None)
        if req is None or not req.items.exists():
            messages.error(request, "Zayavkada mahsulot yo'q.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        if req.status == AnesthesiaRequest.Status.SENT:
            messages.info(request, "Bu zayavka allaqachon yuborilgan.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)

        with transaction.atomic():
            for item in req.items.select_related("stock"):
                stock = item.stock
                # Narxni yuborilgan paytdagi holatda qotiramiz
                item.price_snapshot = stock.selling_price
                item.save(update_fields=["price_snapshot"])
                # Ombordan yechish
                stock.quantity = (stock.quantity or 0) - (item.quantity or 0)
                if stock.quantity < 0:
                    stock.quantity = 0
                stock.save(update_fields=["quantity"])
            req.status = AnesthesiaRequest.Status.SENT
            req.sent_by = request.user
            req.sent_at = timezone.now()
            req.save(update_fields=["status", "sent_by", "sent_at"])
        messages.success(request, "Materiallar yuborildi — ombordan yechildi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*ANESTH_ROLES)
def anesthesia_item_return(request, item_id):
    """Ishlatilmagan materialni anesteziolog omboriga QAYTARISH.

    Qaytarilgan miqdor ombor qoldig'iga qo'shiladi va klinika sarf-harajatidan chiqadi.
    """
    item = get_object_or_404(
        AnesthesiaRequestItem.objects.select_related("stock", "request__surgery"), id=item_id
    )
    surgery = item.request.surgery
    if request.method == "POST":
        from decimal import Decimal
        try:
            qty = Decimal(request.POST.get("quantity") or "0")
        except Exception:
            qty = Decimal("0")
        available = item.used_quantity
        if qty <= 0 or qty > available:
            messages.error(request, f"Qaytarish miqdori noto'g'ri (maksimal {available}).")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        with transaction.atomic():
            item.returned_quantity = (item.returned_quantity or 0) + qty
            item.save(update_fields=["returned_quantity"])
            stock = item.stock
            stock.quantity = (stock.quantity or 0) + qty
            stock.save(update_fields=["quantity"])
        messages.success(request, f"{item.stock.name} × {qty} omborga qaytarildi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*NURSE_ROLES)
def nurse_item_return(request, item_id):
    """Hamshira olgan, lekin ishlatilmagan anjomni omborga qaytarish."""
    item = get_object_or_404(
        NurseUsageItem.objects.select_related("stock", "surgery"), id=item_id
    )
    surgery = item.surgery
    if request.method == "POST":
        from decimal import Decimal
        try:
            qty = Decimal(request.POST.get("quantity") or "0")
        except Exception:
            qty = Decimal("0")
        available = item.used_quantity
        if qty <= 0 or qty > available:
            messages.error(request, f"Qaytarish miqdori noto'g'ri (maksimal {available}).")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        with transaction.atomic():
            item.returned_quantity = (item.returned_quantity or 0) + qty
            item.save(update_fields=["returned_quantity"])
            # Zayavka orqali qilingani uchun omborni to'g'ridan-to'g'ri o'zgartirmaymiz.
            # finish_surgery vaqtida jami hisob-kitob qilinib avtomatik qaytariladi.
        messages.success(request, f"{item.stock.name} × {qty} ro'yxatdan o'chirildi (qaytarildi).")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*ANESTH_ROLES)
def anesthesia_extra_add(request, schedule_id):
    """Operatsiya davomida yoki keyin QO'SHIMCHA material olish.

    Zayavka yuborilgandan keyin ham qo'shish mumkin — darhol ombordan
    yechiladi va "qo'shimcha" deb belgilanadi.
    """
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        from decimal import Decimal
        stock = _safe_get_stock(request.POST.get("stock_id"))
        if stock is None:
            messages.error(request, "Ombordan mahsulot tanlanmadi.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        try:
            qty = Decimal(request.POST.get("quantity") or "1")
        except Exception:
            qty = Decimal("1")
        if qty <= 0:
            messages.error(request, "Soni noto'g'ri.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)
        if (stock.quantity or 0) < qty:
            messages.error(request, f"Omborda yetarli emas: qoldiq {stock.quantity} {stock.unit}.")
            return redirect("clinical:surgery_process", schedule_id=surgery.id)

        with transaction.atomic():
            req, _ = AnesthesiaRequest.objects.get_or_create(
                surgery=surgery, defaults={"requested_by": request.user}
            )
            AnesthesiaRequestItem.objects.create(
                request=req, stock=stock, quantity=qty,
                price_snapshot=stock.selling_price, is_extra=True,
            )
            stock.quantity = (stock.quantity or 0) - qty
            stock.save(update_fields=["quantity"])
        messages.success(request, f"Qo'shimcha: {stock.name} × {qty} olindi (ombordan yechildi).")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*NURSE_ROLES)
def surgery_item_mark(request, item_id):
    """Operatsion hamshira: biriktirilgan asbobni ishlatildi/ishlatilmadi belgilaydi.

    - Ishlatildi  -> USED (ifloslangan), xonada qoladi (avtoklav olib qaytadi)
    - Ishlatilmadi -> READY (toza), operatsion xonada qoladi va ko'rinib turadi
    """
    item = get_object_or_404(SurgicalItem, id=item_id)
    surgery_id = request.POST.get("surgery_id")
    action = request.POST.get("action")
    if request.method == "POST":
        # Asbob qaysi operatsiyaga biriktirilganini aniqlaymiz (xona uchun)
        surgery = SurgerySchedule.objects.filter(
            id=surgery_id
        ).select_related("visit__patient", "surgeon", "surgery_type",
                         "operating_room").first() if surgery_id else None
        room = surgery.operating_room if surgery else item.current_room
        if action == "used":
            item.status = SurgicalItem.Status.USED
            item.current_room = room
            item.save(update_fields=["status", "current_room"])
            SurgicalItemHistory.log(
                item, "Bemorga ishlatildi (ifloslangan)",
                user=request.user, surgery=surgery,
            )
            messages.success(request, f"{item.name}: ishlatildi (ifloslangan).")
        elif action == "unused":
            item.status = SurgicalItem.Status.READY
            item.current_room = room
            item.save(update_fields=["status", "current_room"])
            SurgicalItemHistory.log(
                item, "Ishlatilmadi — steril holida qoldi",
                user=request.user, surgery=surgery,
            )
            # Ishlatilmagan anjom operatsiya hisobotida "ishlatilgan" bo'lib
            # ko'rinmasligi kerak — biriktirilganlar ro'yxatidan chiqariladi.
            # (Iz tarixda saqlanib qoladi.)
            if surgery is not None:
                surgery.items_used.remove(item)
            messages.success(request, f"{item.name}: ishlatilmadi — xonada toza qoldi.")
    if surgery_id:
        return redirect("clinical:surgery_process", schedule_id=surgery_id)
    return redirect("clinical:sterilization_dashboard")


# Operatsion xonalar KO'RINISHI — jarrohlikka doir barcha rollar ko'radi (faqat o'qish)
_ROOMS_VIEW_ROLES = tuple(set(
    SURGEON_ROLES + NURSE_ROLES + STERIL_ROLES + ANESTH_ROLES
    + (Role.Code.SURGERY_ADMIN, Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.RECEPTION)
))


@role_required(*_ROOMS_VIEW_ROLES)
def operating_rooms_overview(request):
    """Operatsion xonalar va ularda HOZIR turgan asboblar + qaytarilmagan materiallar.

    Har xonada: ishlatilmagan (toza) va ifloslangan asboblar ko'rinib turadi —
    ular avtoklav olib qaytmaguncha shu xonada qoladi.
    Bundan tashqari, operatsiyadan keyin qaytarilmagan dori/materiallar ham ko'rsatiladi.
    """
    from apps.clinical.models import OperatingRoom, AnesthesiaRequestItem, NurseUsageItem
    from django.db.models import F
    user = request.user
    _mgr = user.is_superuser or user.has_role(*_OPROOM_MANAGE_ROLES)
    base_qs = OperatingRoom.objects.all() if _mgr else OperatingRoom.objects.filter(is_active=True)
    rooms = base_qs.order_by("name").prefetch_related("current_items", "surgeries")
    room_rows = []
    for r in rooms:
        items = list(r.current_items.all())
        active_surgery = r.surgeries.filter(
            status=SurgerySchedule.Status.IN_PROGRESS
        ).select_related("visit__patient", "surgery_type").first()

        # Qaytarilmagan anesteziolog materiallari (olib kelingan > qaytarilgan)
        unreturned_anesthesia = AnesthesiaRequestItem.objects.filter(
            request__surgery__operating_room=r,
            request__surgery__status=SurgerySchedule.Status.COMPLETED,
        ).filter(
            quantity__gt=F("returned_quantity")
        ).select_related("stock", "request__surgery__visit__patient")

        # Qaytarilmagan hamshira materiallari
        unreturned_nurse = NurseUsageItem.objects.filter(
            surgery__operating_room=r,
            surgery__status=SurgerySchedule.Status.COMPLETED,
        ).filter(
            quantity__gt=F("returned_quantity")
        ).select_related("stock", "surgery__visit__patient")

        room_rows.append({
            "room": r,
            "items": items,
            "clean_count": sum(1 for i in items if i.status == SurgicalItem.Status.READY),
            "dirty_count": sum(1 for i in items if i.status == SurgicalItem.Status.USED),
            "in_use_count": sum(1 for i in items if i.status == SurgicalItem.Status.IN_USE),
            "active_surgery": active_surgery,
            "unreturned_anesthesia": list(unreturned_anesthesia),
            "unreturned_nurse": list(unreturned_nurse),
        })
    can_manage = _mgr
    return render(request, "clinical/operating_rooms_overview.html", {
        "room_rows": room_rows,
        "can_manage": can_manage,
    })


@role_required(*(_SA + (Role.Code.WARD_NURSE, Role.Code.NURSE)))
def surgery_postop_recommendations(request, schedule_id):
    """Operatsiyadan keyingi tavsiyalar — BO'LIM HAMSHIRASI yozadi.

    Bemor operatsiyadan chiqib statsionarga yotganda, statsionar hujjatlari
    sahifasida shu forma paydo bo'ladi.
    """
    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    if request.method == "POST":
        # FAQAT biriktirilgan hamshira (yoki superadmin) yoza oladi
        is_super = request.user.is_superuser or request.user.has_role("super_admin")
        stay = InpatientStay.objects.filter(visit=surgery.visit).order_by("-admission_date").first()
        assigned = stay.doc_nurse_id if stay else None
        if not (is_super or (assigned and request.user.id == assigned)):
            messages.error(request, "Tavsiyani faqat shu bemorga biriktirilgan hamshira yozadi.")
            ref = request.META.get("HTTP_REFERER")
            return redirect(ref) if ref else redirect("clinical:inpatient_dashboard")
        surgery.postop_recommendations = request.POST.get("postop_recommendations", "").strip()
        surgery.save(update_fields=["postop_recommendations"])
        messages.success(request, "Operatsiyadan keyingi tavsiyalar saqlandi.")
    ref = request.META.get("HTTP_REFERER")
    return redirect(ref) if ref else redirect("clinical:inpatient_dashboard")


@role_required(Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN)
def edit_room(request, room_id):
    """Palatani tahrirlash: nom, qavat, mas'ul shifokor."""
    if request.method == "POST":
        room = get_object_or_404(Room, id=room_id)
        name = (request.POST.get("name") or "").strip()
        floor = request.POST.get("floor") or room.floor
        doctor_id = request.POST.get("assigned_doctor_id") or None
        if not name:
            messages.error(request, "Palata nomi bo'sh bo'lishi mumkin emas.")
            return redirect("clinical:rooms_settings")
        # Dublikat nazorati (o'zidan boshqa)
        norm = _norm_room_name(name)
        for r in Room.all_objects.exclude(id=room.id):
            if _norm_room_name(r.name) == norm:
                messages.error(request, f"Bunday nomli palata mavjud: '{r.name}'.")
                return redirect("clinical:rooms_settings")
        room.name = name
        room.floor = floor
        room.assigned_doctor_id = doctor_id
        room.save(update_fields=["name", "floor", "assigned_doctor"])
        messages.success(request, f"'{room.name}' palatasi yangilandi.")
    return redirect("clinical:rooms_settings")


# ==========================================================================
# OPERATSION XONALAR BOSHQARUVI (superadmin/administrator)
# ==========================================================================
_OPROOM_MANAGE_ROLES = (Role.Code.SUPER_ADMIN,)


def _norm_oproom_name(name):
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


@role_required(*_OPROOM_MANAGE_ROLES)
def add_operating_room(request):
    """Operatsion xona qo'shish (dublikat nazorati bilan)."""
    from apps.clinical.models import OperatingRoom
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        description = (request.POST.get("description") or "").strip()
        if not name:
            messages.error(request, "Xona nomi kiritilmadi.")
            return redirect("clinical:operating_rooms_overview")
        norm = _norm_oproom_name(name)
        for r in OperatingRoom.all_objects.all():
            if _norm_oproom_name(r.name) == norm:
                messages.error(request, f"Bunday operatsion xona mavjud: '{r.name}'.")
                return redirect("clinical:operating_rooms_overview")
        OperatingRoom.objects.create(name=name, description=description, is_active=True)
        messages.success(request, f"'{name}' operatsion xonasi qo'shildi.")
    return redirect("clinical:operating_rooms_overview")


@role_required(*_OPROOM_MANAGE_ROLES)
def edit_operating_room(request, room_id):
    """Operatsion xonani tahrirlash: nom, izoh, faollik."""
    from apps.clinical.models import OperatingRoom
    if request.method == "POST":
        room = get_object_or_404(OperatingRoom, id=room_id)
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Xona nomi bo'sh bo'lishi mumkin emas.")
            return redirect("clinical:operating_rooms_overview")
        norm = _norm_oproom_name(name)
        for r in OperatingRoom.all_objects.exclude(id=room.id):
            if _norm_oproom_name(r.name) == norm:
                messages.error(request, f"Bunday nomli xona mavjud: '{r.name}'.")
                return redirect("clinical:operating_rooms_overview")
        room.name = name
        room.description = (request.POST.get("description") or "").strip()
        room.is_active = request.POST.get("is_active") == "1"
        room.save(update_fields=["name", "description", "is_active"])
        messages.success(request, f"'{room.name}' xonasi yangilandi.")
    return redirect("clinical:operating_rooms_overview")


@role_required(*_OPROOM_MANAGE_ROLES)
def delete_operating_room(request, room_id):
    """Operatsion xonani o'chirish — faol operatsiyasi bo'lmasa."""
    from apps.clinical.models import OperatingRoom
    if request.method == "POST":
        room = get_object_or_404(OperatingRoom, id=room_id)
        busy = room.surgeries.filter(
            status__in=[SurgerySchedule.Status.SCHEDULED, SurgerySchedule.Status.IN_PROGRESS]
        ).exists()
        if busy:
            messages.error(
                request,
                f"'{room.name}' xonasida rejalashtirilgan/davom etayotgan operatsiya bor — o'chirib bo'lmaydi.",
            )
        elif room.current_items.exists():
            messages.error(
                request,
                f"'{room.name}' xonasida asboblar turibdi — avval ularni avtoklavga qaytaring.",
            )
        else:
            name = room.name
            room.delete()
            messages.success(request, f"'{name}' operatsion xonasi o'chirildi.")
    return redirect("clinical:operating_rooms_overview")


# ==========================================================================
# ANESTEZIOLOG OMBORI SAHIFASI (anesteziolog o'z omborini boshqaradi)
# ==========================================================================
@role_required(Role.Code.ANESTHESIOLOGIST, Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR)
def anesthesia_stock_page(request):
    """Anesteziolog ombori: qoldiqlar + qo'shish/tahrirlash + yuborilgan zayavkalar bildirgisi."""
    from apps.clinical.models import AnesthesiaRequest, SurgerySupplyRequest
    stocks = AnesthesiaStock.objects.prefetch_related("packages").order_by("name")
    # Excel eksport
    if request.GET.get("format") == "excel":
        from apps.core.exports import export_queryset_to_excel
        columns = [
            ("Mahsulot", "name"),
            ("Qoldiq", "quantity"),
            ("O'lchov birligi", "unit"),
            ("Sotish narxi", "selling_price"),
            ("Psixotrop", "is_psychotropic"),
            ("Faol", "is_active"),
        ]
        return export_queryset_to_excel(stocks, columns, "Anesteziolog_ombori")
    low = [s_ for s_ in stocks if (s_.quantity or 0) <= 5 and s_.is_active]
    # BILDIRGI: yuborilgan zayavkalar jurnali (eng so'nggilari)
    sent_requests = (
        AnesthesiaRequest.objects.filter(status=AnesthesiaRequest.Status.SENT)
        .select_related("surgery__visit__patient", "sent_by")
        .prefetch_related("items__stock")
        .order_by("-sent_at")[:25]
    )
    today = timezone.localdate()
    sent_today = AnesthesiaRequest.objects.filter(
        status=AnesthesiaRequest.Status.SENT, sent_at__date=today
    ).count()
    
    # HAMSHIRA ZAYAVKALARI (Operatsion hamshira so'ragan materiallar)
    nurse_requests = (
        SurgerySupplyRequest.objects.filter(status=SurgerySupplyRequest.Status.SENT)
        .select_related("surgery__visit__patient", "requested_by")
        .prefetch_related("items__stock")
        .order_by("-created_at")[:25]
    )
    nurse_sent_today = SurgerySupplyRequest.objects.filter(
        status=SurgerySupplyRequest.Status.SENT, created_at__date=today
    ).count()
    
    from apps.pharmacy.models import MeasurementUnit
    measurement_units = MeasurementUnit.objects.all().order_by('name')
    return render(request, "clinical/anesthesia_stock.html", {
        "measurement_units": measurement_units,
        "stocks": stocks,
        "low_stock": low,
        "sent_requests": sent_requests,
        "sent_today": sent_today,
        "nurse_requests": nurse_requests,
        "nurse_sent_today": nurse_sent_today,
    })


@role_required(Role.Code.ANESTHESIOLOGIST, Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR)
def anesthesia_stock_add(request):
    """Omborga yangi mahsulot qo'shish."""
    if request.method == "POST":
        from decimal import Decimal, InvalidOperation
        name = (request.POST.get("name") or "").strip()
        if not name:
            messages.error(request, "Mahsulot nomi kiritilmadi.")
            return redirect("clinical:anesthesia_stock_page")
        if AnesthesiaStock.all_objects.filter(name__iexact=name).exists():
            messages.error(request, f"'{name}' allaqachon omborda bor — miqdorini tahrirlang.")
            return redirect("clinical:anesthesia_stock_page")
        def _dec(key, default="0"):
            try:
                return Decimal(request.POST.get(key) or default)
            except InvalidOperation:
                return Decimal(default)
        price = _dec("selling_price")
        unit = (request.POST.get("unit") or "dona").strip()
        qty = _dec("quantity")
        
        stock = AnesthesiaStock.objects.create(
            name=name, unit=unit,
            quantity=qty, selling_price=price, is_active=True,
            is_psychotropic=request.POST.get("is_psychotropic") == "1",
        )
        
        # QADOQ (blok/karobka) YARATILMAYDI — qoldiq faqat asosiy
        # birlikda yuritiladi.

        messages.success(request, f"'{name}' omborga qo'shildi (boshlang'ich: {qty} {unit}).")
    return redirect("clinical:anesthesia_stock_page")


@role_required(Role.Code.ANESTHESIOLOGIST, Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR)
def anesthesia_stock_edit(request, stock_id):
    """Ombor mahsulotini tahrirlash: kirim qo'shish, narx, faollik."""
    if request.method == "POST":
        from decimal import Decimal, InvalidOperation
        stock = get_object_or_404(AnesthesiaStock, id=stock_id)
        try:
            add_qty = Decimal(request.POST.get("add_quantity") or "0")
            price = Decimal(request.POST.get("selling_price") or str(stock.selling_price))
        except InvalidOperation:
            messages.error(request, "Miqdor/narx noto'g'ri.")
            return redirect("clinical:anesthesia_stock_page")

        # KIRIM FAQAT ASOSIY BIRLIKDA.
        #
        # Ilgari «nechta karobka» tanlanib, u ampulaga ko'paytirilardi.
        # Karobka o'lchami noto'g'ri kiritilsa butun qoldiq buzilardi, bir
        # dori turli o'ramlarda kelganda esa hisob chalkashardi.
        # Anesteziolog nechta ampula kelganini o'zi sanab yozadi.
        if add_qty:
            stock.quantity = (stock.quantity or 0) + add_qty
        stock.selling_price = price
        stock.is_active = request.POST.get("is_active") == "1"
        stock.is_psychotropic = request.POST.get("is_psychotropic") == "1"
        stock.save(update_fields=["quantity", "selling_price", "is_active", "is_psychotropic"])
        messages.success(request, f"'{stock.name}' yangilandi (qoldiq: {stock.quantity} {stock.unit}).")
    return redirect("clinical:anesthesia_stock_page")


# QADOQ (blok/pochka) BOSHQARUVI OLIB TASHLANDI.
#
# «1 blok = 50 ampula» iyerarxiyasi hisobni chalkashtirardi: anesteziologga
# nechta ampula borligi kerak, blokni bo'lib hisoblash emas. Ustiga-ustak
# blok o'lchami keyin o'zgartirilsa, eski qoldiqlar boshqacha ko'rinib
# qolardi. Endi qoldiq faqat mahsulotning o'z birligida yuritiladi.


# ==========================================================================
# HUJJATLARNI QULFLASH (o'zgarmas saqlash) — bayonnoma, chek, ko'rik, statsionar
# Qulflangач FAQAT superadmin ocha/tahrirlaydi.
# ==========================================================================
_LOCKABLE_DOCS = {
    "surgery_report": ("clinical", "SurgeryReport"),
    "consultation": ("clinical", "Consultation"),
    "inpatient_stay": ("clinical", "InpatientStay"),
    "invoice": ("billing", "Invoice"),
}


@login_required
@require_POST
def document_lock(request, doc_type, obj_id):
    """Hujjatni qulflash yoki (superadmin) ochish."""
    from django.apps import apps as _apps
    spec = _LOCKABLE_DOCS.get(doc_type)
    if not spec:
        raise Http404("Noma'lum hujjat turi")
    Model = _apps.get_model(*spec)
    obj = get_object_or_404(Model, id=obj_id)
    action = request.POST.get("action", "lock")
    if action == "unlock":
        if obj.unlock(request.user):
            messages.success(request, "Hujjat ochildi — endi tahrirlash mumkin.")
        else:
            messages.error(request, "Hujjatni faqat superadmin ocha oladi.")
    else:
        if obj.is_locked:
            messages.info(request, "Hujjat allaqachon qulflangan.")
        else:
            obj.lock(request.user)
            messages.success(request, "Hujjat o'zgarmas qilib qulflandi (endi hech kim o'zgartira olmaydi).")
    return redirect(request.META.get("HTTP_REFERER") or "core:home")

# ==========================================================================
# AMBULATOR XONALAR (KABINETLAR) SOZLAMALARI
# ==========================================================================
from apps.clinical.models import AmbulatoryRoom

@role_required(Role.Code.SUPER_ADMIN)
def ambulatory_rooms_settings(request):
    """Ambulator xonalar ro'yxati (Faqat Superadmin)."""
    rooms = AmbulatoryRoom.objects.prefetch_related("doctors").order_by("name")
    
    # Barcha shifokorlar (dropdown uchun)
    from apps.accounts.models import User, Role
    doctors = User.objects.filter(role__code__in=[
        Role.Code.DOCTOR, Role.Code.CHIEF_DOCTOR, Role.Code.SURGEON, 
        Role.Code.ANESTHESIOLOGIST, Role.Code.LAB, Role.Code.RADIOLOGY
    ], is_active=True).order_by("last_name")

    return render(request, "clinical/ambulatory_rooms.html", {
        "rooms": rooms,
        "doctors": doctors,
    })


@role_required(Role.Code.SUPER_ADMIN)
@require_POST
def add_ambulatory_room(request):
    """Ambulator xona qo'shish."""
    name = request.POST.get("name", "").strip()
    doctor_ids = request.POST.getlist("doctor_ids")
    is_active = request.POST.get("is_active") == "on"

    if name:
        if AmbulatoryRoom.objects.filter(name=name).exists():
            messages.error(request, f"'{name}' nomli xona allaqachon mavjud.")
        else:
            room = AmbulatoryRoom.objects.create(name=name, is_active=is_active)
            if doctor_ids:
                from apps.accounts.models import User
                docs = User.objects.filter(id__in=doctor_ids)
                room.doctors.set(docs)
                
                # Boshqa xonalardan tozalash
                for doc in docs:
                    other_rooms = doc.ambulatory_rooms.exclude(id=room.id)
                    for r in other_rooms:
                        r.doctors.remove(doc)
                        
            messages.success(request, f"'{name}' xonasi qo'shildi.")
    
    return redirect("clinical:ambulatory_rooms_settings")


@role_required(Role.Code.SUPER_ADMIN)
@require_POST
def edit_ambulatory_room(request, pk):
    """Ambulator xonani tahrirlash."""
    room = get_object_or_404(AmbulatoryRoom, pk=pk)
    name = request.POST.get("name", "").strip()
    doctor_ids = request.POST.getlist("doctor_ids")
    is_active = request.POST.get("is_active") == "on"

    if name:
        if AmbulatoryRoom.objects.filter(name=name).exclude(pk=pk).exists():
            messages.error(request, f"'{name}' nomli xona allaqachon mavjud.")
        else:
            room.name = name
            room.is_active = is_active
            room.save()
            
            if doctor_ids:
                from apps.accounts.models import User
                docs = User.objects.filter(id__in=doctor_ids)
                room.doctors.set(docs)
                
                # Boshqa xonalardan tozalash
                for doc in docs:
                    other_rooms = doc.ambulatory_rooms.exclude(id=room.id)
                    for r in other_rooms:
                        r.doctors.remove(doc)
            else:
                room.doctors.clear()
                
            messages.success(request, f"'{name}' xonasi saqlandi.")
    
    return redirect("clinical:ambulatory_rooms_settings")


@role_required(Role.Code.SUPER_ADMIN)
@require_POST
def delete_ambulatory_room(request, pk):
    """Ambulator xonani o'chirish."""
    room = get_object_or_404(AmbulatoryRoom, pk=pk)
    room_name = room.name
    room.delete()
    messages.success(request, f"'{room_name}' xonasi o'chirildi.")
    return redirect("clinical:ambulatory_rooms_settings")



# ==========================================================================
#  TEKSHIRUV NATIJASINI CHOP ETISH
# --------------------------------------------------------------------------
#  Natija blanki ikki joyda kerak bo'ladi:
#    · shifokor — qabul oynasidan, bemorga ko'rsatish yoki tikish uchun
#    · registratura — bemor «natijamni bering» deb kelganda
#  Shu sababli ruxsat ro'yxatida registratura ham bor. Bu tibbiy sirni
#  buzmaydi: registratura allaqachon bemorning kartasi bilan ishlaydi.
# ==========================================================================

RESULT_PRINT_ROLES = [
    "super_admin", "administrator", "chief_doctor", "doctor",
    "reception", "nurse", "ward_nurse", "director", "lab", "examiner",
]


class ServiceResultPrintView(RoleRequiredMixin, TemplateView):
    """Bitta tekshiruv natijasi — rasmiy blank."""

    allowed_roles = RESULT_PRINT_ROLES
    template_name = "clinical/service_result_print.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = get_object_or_404(
            ServiceOrder.objects.select_related(
                "service", "service__category", "visit", "visit__patient",
                "visit__doctor", "performed_by",
            ).prefetch_related("result_rows"),
            pk=self.kwargs["order_id"],
        )
        ctx["orders"] = [order]
        ctx["visit"] = order.visit
        ctx["patient"] = order.visit.patient
        ctx["single"] = True
        ctx["printed_at"] = timezone.now()
        return ctx


class VisitResultsPrintView(RoleRequiredMixin, TemplateView):
    """Bitta tashrifning BARCHA tayyor natijalari — bitta blankda."""

    allowed_roles = RESULT_PRINT_ROLES
    template_name = "clinical/service_result_print.html"

    def get_context_data(self, **kwargs):
        from apps.clinical import selectors as clinical_selectors

        ctx = super().get_context_data(**kwargs)
        visit = get_object_or_404(
            Visit.objects.select_related("patient", "doctor"),
            pk=self.kwargs["visit_id"],
        )
        orders = [
            o for o in clinical_selectors.visit_exam_orders(visit) if o.has_result
        ]
        ctx["orders"] = orders
        ctx["visit"] = visit
        ctx["patient"] = visit.patient
        ctx["single"] = False
        ctx["printed_at"] = timezone.now()
        return ctx

@role_required(
    Role.Code.ADMINISTRATOR, Role.Code.RECEPTION, Role.Code.DIRECTOR,
    Role.Code.CHIEF_DOCTOR, Role.Code.DOCTOR, Role.Code.SURGEON,
    Role.Code.NURSE, Role.Code.WARD_NURSE, Role.Code.ANESTHESIOLOGIST
)
def inpatient_archive(request):
    """Statsionardan chiqarilgan bemorlar tarixi"""
    from apps.clinical.models import InpatientStay
    stays = InpatientStay.objects.filter(status=InpatientStay.Status.DISCHARGED).select_related(
        "visit__patient", "bed__room", "assigned_doctor", "doc_nurse", "procedure_nurse"
    ).order_by('-discharge_date')[:100]
    return render(request, "clinical/inpatient_archive.html", {"stays": stays})


# ==========================================================================
# OPERATSION HAMSHIRA -> ANESTEZIOLOG OMBORIGA ZAYAVKA
#
# Ombor bitta, lekin so'rovchi va mahsulot turi boshqa: anesteziolog
# psixotrop dorilarni so'raydi, operatsion hamshira esa oddiy
# sarf-materialni (shprits, bint, doka). Ilgari hamshirada so'rashning
# yo'li yo'q edi — u anesteziolog zayavkasidan yozardi va server
# «psixotrop emas» deb rad etardi.
# ==========================================================================

SUPPLY_NURSE_ROLES = _SA + (
    Role.Code.OPERATING_NURSE, Role.Code.WARD_NURSE,
    Role.Code.SURGERY_ADMIN, Role.Code.SURGEON,
)
# Zayavkani ANESTEZIOLOG beradi — ombor uniki.
SUPPLY_WAREHOUSE_ROLES = _SA + (
    Role.Code.ANESTHESIOLOGIST, Role.Code.WAREHOUSE, Role.Code.ADMINISTRATOR,
)


def _supply_qty(raw, default="1"):
    from decimal import Decimal
    try:
        qty = Decimal(str(raw or default).replace(",", "."))
    except Exception:
        return None
    return qty if qty > 0 else None


@role_required(*SUPPLY_NURSE_ROLES)
@require_POST
def supply_request_add_item(request, schedule_id):
    """Zayavkaga ombordagi mahsulot qo'shish."""
    from apps.clinical.models import SurgerySupplyItem, SurgerySupplyRequest

    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    zayavka, _ = SurgerySupplyRequest.objects.get_or_create(
        surgery=surgery, defaults={"requested_by": request.user})

    if not zayavka.is_editable:
        messages.error(request, "Zayavka omborga yuborilgan — o'zgartirib bo'lmaydi.")
        return redirect("clinical:surgery_process", schedule_id=surgery.id)

    dori = AnesthesiaStock.objects.filter(
        pk=request.POST.get("stock_id"), is_active=True).first()
    if dori is None:
        messages.error(request, "Ombordan mahsulot tanlanmadi.")
        return redirect("clinical:surgery_process", schedule_id=surgery.id)

    # PSIXOTROPNI HAMSHIRA SO'RAMAYDI.
    #
    # Ular qat'iy hisobda va faqat anesteziolog zayavka qiladi. Aks
    # holda bitta dori ikki xil yo'ldan yechilib, hisob buzilardi.
    if dori.is_psychotropic:
        messages.error(
            request,
            f"{dori.name} — psixotrop dori. Uni faqat anesteziolog "
            f"zayavka qiladi.")
        return redirect("clinical:surgery_process", schedule_id=surgery.id)

    qty = _supply_qty(request.POST.get("quantity"))
    if qty is None:
        messages.error(request, "Soni musbat son bo'lishi kerak.")
        return redirect("clinical:surgery_process", schedule_id=surgery.id)

    # Bir mahsulot ikki qator bo'lib ketmasin — ombor ro'yxatni o'qiydi.
    qator = zayavka.items.filter(stock=dori).first()
    if qator:
        qator.quantity = qator.quantity + qty
        qator.save(update_fields=["quantity", "updated_at"])
    else:
        SurgerySupplyItem.objects.create(
            request=zayavka, stock=dori, quantity=qty,
            note=(request.POST.get("note") or "").strip()[:200])

    messages.success(request, f"{dori.name} × {qty} zayavkaga qo'shildi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*SUPPLY_NURSE_ROLES)
@require_POST
def supply_request_remove_item(request, item_id):
    from apps.clinical.models import SurgerySupplyItem

    qator = get_object_or_404(
        SurgerySupplyItem.objects.select_related("request__surgery"), pk=item_id)
    surgery_id = qator.request.surgery_id
    if not qator.request.is_editable:
        messages.error(request, "Zayavka yuborilgan — qator o'chirilmaydi.")
    else:
        qator.delete()
        messages.success(request, "Qator o'chirildi.")
    return redirect("clinical:surgery_process", schedule_id=surgery_id)


@role_required(*SUPPLY_NURSE_ROLES)
@require_POST
def supply_request_send(request, schedule_id):
    """Zayavkani omborga yuborish."""
    from apps.clinical.models import SurgerySupplyRequest

    surgery = get_object_or_404(SurgerySchedule, id=schedule_id)
    zayavka = get_object_or_404(SurgerySupplyRequest, surgery=surgery)

    if not zayavka.is_editable:
        messages.info(request, "Zayavka allaqachon yuborilgan.")
    elif not zayavka.items.exists():
        # Bo'sh zayavka omborda «nima kerak edi?» degan savol tug'diradi.
        messages.error(request, "Zayavka bo'sh — avval mahsulot qo'shing.")
    else:
        zayavka.status = SurgerySupplyRequest.Status.SENT
        zayavka.sent_at = timezone.now()
        zayavka.requested_by = zayavka.requested_by or request.user
        zayavka.save(update_fields=["status", "sent_at", "requested_by",
                                    "updated_at"])
        messages.success(request, "Zayavka omborga yuborildi.")
    return redirect("clinical:surgery_process", schedule_id=surgery.id)


@role_required(*SUPPLY_WAREHOUSE_ROLES)
@require_POST
def supply_request_issue(request, pk):
    """Ombor zayavkani berdi deb belgilaydi.

    Har qator uchun berilgan miqdor alohida kiritiladi: omborda
    so'ralgan narsaning hammasi bo'lmasligi mumkin va zayavkani
    «to'liq bajarildi» deb yozib qo'yish haqiqatni yashiradi.
    """
    from apps.clinical.models import SurgerySupplyRequest

    zayavka = get_object_or_404(
        SurgerySupplyRequest.objects.prefetch_related("items"), pk=pk)

    if zayavka.status != SurgerySupplyRequest.Status.SENT:
        messages.error(request, "Faqat yuborilgan zayavkani berish mumkin.")
        return redirect("clinical:supply_requests")

    for qator in zayavka.items.all():
        xom = request.POST.get(f"issued_{qator.pk}")
        berilgan = _supply_qty(xom, default="0")
        qator.issued_quantity = berilgan if berilgan is not None else qator.quantity
        qator.save(update_fields=["issued_quantity", "updated_at"])

    zayavka.status = SurgerySupplyRequest.Status.ISSUED
    zayavka.issued_by = request.user
    zayavka.issued_at = timezone.now()
    zayavka.save(update_fields=["status", "issued_by", "issued_at", "updated_at"])
    messages.success(request, "Zayavka berildi deb belgilandi.")
    return redirect("clinical:supply_requests")


@role_required(*SUPPLY_WAREHOUSE_ROLES)
@require_POST
def supply_request_reject(request, pk):
    from apps.clinical.models import SurgerySupplyRequest

    zayavka = get_object_or_404(SurgerySupplyRequest, pk=pk)
    if zayavka.status != SurgerySupplyRequest.Status.SENT:
        messages.error(request, "Faqat yuborilgan zayavkani rad etish mumkin.")
    else:
        zayavka.status = SurgerySupplyRequest.Status.REJECTED
        zayavka.notes = (request.POST.get("reason") or "").strip()[:500]
        zayavka.save(update_fields=["status", "notes", "updated_at"])
        messages.success(request, "Zayavka rad etildi.")
    return redirect("clinical:supply_requests")


@role_required(*(SUPPLY_WAREHOUSE_ROLES + SUPPLY_NURSE_ROLES))
def supply_requests(request):
    """Ombor uchun operatsion zayavkalar ro'yxati."""
    from apps.clinical.models import SurgerySupplyRequest

    qs = (SurgerySupplyRequest.objects
          .select_related("surgery__visit__patient", "surgery__surgery_type",
                          "requested_by", "issued_by")
          .prefetch_related("items__stock")
          .order_by("-created_at"))

    holat = request.GET.get("status") or ""
    if holat:
        qs = qs.filter(status=holat)

    return render(request, "clinical/supply_requests.html", {
        "requests": qs,
        "current_status": holat,
        "statuses": SurgerySupplyRequest.Status.choices,
        "can_issue": (request.user.is_superuser
                      or request.user.has_role(*SUPPLY_WAREHOUSE_ROLES)),
    })
