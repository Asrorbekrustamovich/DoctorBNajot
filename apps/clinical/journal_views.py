from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from apps.accounts.permissions import role_required
from apps.accounts.models import Role
from .models import SimultaneousSurgeryLog, HistologyLog, MinorSurgeryLog, OutpatientSurgeryLog, SterilizationLog

JOURNAL_ROLES = (
    Role.Code.OPERATING_NURSE,
    Role.Code.WARD_NURSE,
    Role.Code.NURSE,
    Role.Code.SURGERY_ADMIN,
    Role.Code.CHIEF_DOCTOR,
    Role.Code.SUPER_ADMIN,
)

@role_required(*JOURNAL_ROLES)
def journal_list(request):
    journal_type = request.GET.get('type', 'simultaneous')
    q = request.GET.get('q', '').strip()
    
    logs = []
    
    if journal_type == 'simultaneous':
        logs = SimultaneousSurgeryLog.objects.all()
    elif journal_type == 'histology':
        logs = HistologyLog.objects.all()
    elif journal_type == 'minor':
        logs = MinorSurgeryLog.objects.all()
    elif journal_type == 'outpatient':
        logs = OutpatientSurgeryLog.objects.all()
    elif journal_type.startswith('sterilization_'):
        s_type = journal_type.replace('sterilization_', '')
        logs = SterilizationLog.objects.filter(log_type=s_type)
    else:
        journal_type = 'simultaneous'
        logs = SimultaneousSurgeryLog.objects.all()
    
    if q and journal_type != 'sterilization':
        if hasattr(logs.model, 'patient_name'):
            logs = logs.filter(
                Q(patient_name__icontains=q) |
                Q(jshshir__icontains=q) |
                Q(metric_number__icontains=q) |
                Q(date__icontains=q)
            )
    elif q and journal_type.startswith('sterilization_'):
        logs = logs.filter(date__icontains=q)
        
    context = {
        'journal_type': journal_type,
        'logs': logs,
        'q': q,
        'sterilization_types': SterilizationLog.Type.choices,
    }
    return render(request, 'clinical/journals/journal_list.html', context)


@role_required(*JOURNAL_ROLES)
def journal_add(request, journal_type):
    if request.method == 'POST':
        date_str = request.POST.get('date') or timezone.now().date()
        
        if journal_type == 'simultaneous':
            SimultaneousSurgeryLog.objects.create(
                patient_name=request.POST.get('patient_name'),
                jshshir=request.POST.get('jshshir'),
                metric_number=request.POST.get('metric_number'),
                date=date_str,
                diagnosis=request.POST.get('diagnosis'),
                primary_surgery=request.POST.get('primary_surgery'),
                simultaneous_surgery=request.POST.get('simultaneous_surgery'),
                surgeon=request.POST.get('surgeon'),
                assistants=request.POST.get('assistants'),
                anesthesiologist=request.POST.get('anesthesiologist'),
            )
        elif journal_type == 'histology':
            HistologyLog.objects.create(
                patient_name=request.POST.get('patient_name'),
                jshshir=request.POST.get('jshshir'),
                metric_number=request.POST.get('metric_number'),
                date=date_str,
                room_number=request.POST.get('room_number'),
                diagnosis=request.POST.get('diagnosis'),
                material=request.POST.get('material'),
                result=request.POST.get('result'),
            )
        elif journal_type == 'minor':
            MinorSurgeryLog.objects.create(
                patient_name=request.POST.get('patient_name'),
                jshshir=request.POST.get('jshshir'),
                metric_number=request.POST.get('metric_number'),
                date=date_str,
                diagnosis=request.POST.get('diagnosis'),
                surgery_name=request.POST.get('surgery_name'),
                surgeon=request.POST.get('surgeon'),
            )
        elif journal_type == 'outpatient':
            OutpatientSurgeryLog.objects.create(
                patient_name=request.POST.get('patient_name'),
                jshshir=request.POST.get('jshshir'),
                metric_number=request.POST.get('metric_number'),
                date=date_str,
                diagnosis=request.POST.get('diagnosis'),
                intervention=request.POST.get('intervention'),
                doctor=request.POST.get('doctor'),
            )
        elif journal_type.startswith('sterilization_'):
            s_type = journal_type.replace('sterilization_', '')
            SterilizationLog.objects.create(
                log_type=s_type,
                date=date_str,
                equipment=request.POST.get('equipment', 'Laparoskop va uning tarkibiy qismlari'),
                cleaning_start=request.POST.get('cleaning_start'),
                cleaning_end=request.POST.get('cleaning_end'),
                sterilization_start=request.POST.get('sterilization_start'),
                sterilization_end=request.POST.get('sterilization_end'),
                chemical_used=request.POST.get('chemical_used'),
                nurse_name=request.POST.get('nurse_name'),
            )
            
        messages.success(request, "Yangi yozuv muvaffaqiyatli saqlandi.")
        return redirect(f"/clinical/journals/?type={journal_type}")
        
    return redirect('clinical:journal_list')


@role_required(*JOURNAL_ROLES)
def journal_delete(request, journal_type, pk):
    if request.method == 'POST':
        if journal_type == 'simultaneous':
            log = get_object_or_404(SimultaneousSurgeryLog, pk=pk)
        elif journal_type == 'histology':
            log = get_object_or_404(HistologyLog, pk=pk)
        elif journal_type == 'minor':
            log = get_object_or_404(MinorSurgeryLog, pk=pk)
        elif journal_type == 'outpatient':
            log = get_object_or_404(OutpatientSurgeryLog, pk=pk)
        elif journal_type.startswith('sterilization_'):
            log = get_object_or_404(SterilizationLog, pk=pk)
        else:
            return redirect('clinical:journal_list')
            
        log.delete()
        messages.success(request, "Yozuv o'chirildi.")
        
    return redirect(f"/clinical/journals/?type={journal_type}")
