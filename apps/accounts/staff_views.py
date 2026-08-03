"""Xodimlar boshqaruvi (web UI) — shifokorlar va xodimlarni qo'shish, tahrirlash, o'chirish."""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q as models_Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.accounts.models import Role, User
from apps.accounts.permissions import role_required


# ──────────────────────────────────────────────────────────────────────────────
#   XODIMLAR RO'YXATI
# ──────────────────────────────────────────────────────────────────────────────

@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def staff_list(request):
    """Barcha xodimlar va shifokorlar ro'yxati."""
    role_filter = request.GET.get("role", "")
    search = request.GET.get("q", "").strip()

    users = User.objects.select_related("role").order_by("last_name", "first_name")

    if role_filter:
        users = users.filter(role__code=role_filter)
    if search:
        users = users.filter(
            models_Q(first_name__icontains=search)
            | models_Q(last_name__icontains=search)
            | models_Q(username__icontains=search)
        )

    roles = Role.objects.order_by("name")
    return render(request, "staff/list.html", {
        "users": users,
        "roles": roles,
        "selected_role": role_filter,
        "search": search,
    })


@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def staff_create(request):
    """Yangi xodim / shifokor qo'shish."""
    from apps.accounts.forms import StaffCreateForm
    if request.method == "POST":
        form = StaffCreateForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password"])
            user.save()
            messages.success(request, f"'{user.get_full_name() or user.username}' muvaffaqiyatli qo'shildi.")
            return redirect("staff:list")
    else:
        form = StaffCreateForm()
    return render(request, "staff/form.html", {"form": form, "action": "Yangi xodim qo'shish"})


@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def staff_edit(request, user_id):
    """Xodim ma'lumotlarini tahrirlash."""
    from apps.accounts.forms import StaffEditForm
    staff = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        form = StaffEditForm(request.POST, instance=staff)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{staff.get_full_name() or staff.username}' ma'lumotlari yangilandi.")
            return redirect("staff:list")
    else:
        form = StaffEditForm(instance=staff)
    return render(request, "staff/form.html", {"form": form, "action": "Tahrirlash", "staff": staff})


@role_required(Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN)
def staff_delete(request, user_id):
    """Xodimni o'chirish (Soft-delete) — eski hisobotlarga ta'sir qilmaydi."""
    staff = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        name = staff.get_full_name() or staff.username
        staff.delete()  # User.delete() — soft delete: is_deleted=True, is_active=False
        messages.success(request, f"'{name}' tizimdan o'chirildi (hisobotlar saqlanib qoldi).")
        return redirect("staff:list")
    return render(request, "staff/confirm_delete.html", {"staff": staff})


@role_required(Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN, Role.Code.ADMINISTRATOR)
def staff_restore(request, user_id):
    """O'chirilgan xodimni tiklash."""
    staff = get_object_or_404(User.all_objects, id=user_id)
    if request.method == "POST":
        staff.is_deleted = False
        staff.is_active = True
        staff.deleted_at = None
        staff.save(update_fields=["is_deleted", "is_active", "deleted_at"])
        messages.success(request, f"'{staff.get_full_name() or staff.username}' tiklandi.")
        return redirect("staff:list")
    return render(request, "staff/confirm_restore.html", {"staff": staff})


@role_required(Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN)
def staff_reset_password(request, user_id):
    """Xodim parolini yangilash."""
    staff = get_object_or_404(User, id=user_id)
    if request.method == "POST":
        new_password = request.POST.get("password", "").strip()
        if len(new_password) < 6:
            messages.error(request, "Parol kamida 6 ta belgidan iborat bo'lishi kerak.")
        else:
            staff.set_password(new_password)
            staff.save(update_fields=["password"])
            messages.success(request, f"'{staff.get_full_name() or staff.username}' paroli yangilandi.")
            return redirect("staff:list")
    return render(request, "staff/reset_password.html", {"staff": staff})


# ──────────────────────────────────────────────────────────────────────────────
#   XIZMATLAR KATALOGI
# ──────────────────────────────────────────────────────────────────────────────

@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def services_list(request):
    """Xizmatlar katalogi ro'yxati (UZI, EKG, Tahlillar va h.k.)."""
    from apps.clinical.models import ServiceCatalog
    services = ServiceCatalog.objects.select_related(
        "allowed_role", "room", "responsible_staff"
    ).order_by("name")
    return render(request, "staff/services_list.html", {"services": services})


@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def services_bulk_assign(request):
    """Bir nechta xizmatni bitta xodimga / kabinetga birdan biriktirish.

    22 ta UZI va Rentgenni bittalab tahrirlash o'rniga — belgilab, bitta
    tugma bilan biriktiriladi.
    """
    from apps.clinical.models import AmbulatoryRoom, ServiceCatalog

    if request.method == "POST":
        ids = request.POST.getlist("services")
        staff_id = request.POST.get("responsible_staff") or None
        room_id = request.POST.get("room") or None
        tozalash = request.POST.get("clear_staff") == "1"

        if not ids:
            messages.error(request, "Hech qanday xizmat belgilanmadi.")
            return redirect("staff:services_bulk_assign")

        yangi = {}
        if tozalash:
            yangi["responsible_staff"] = None
        elif staff_id:
            xodim = User.objects.filter(id=staff_id, is_active=True).first()
            if not xodim:
                messages.error(request, "Xodim topilmadi.")
                return redirect("staff:services_bulk_assign")
            yangi["responsible_staff"] = xodim
            # Xizmat roli xodim roliga moslashtiriladi — aks holda xizmat
            # xodim navbatida ko'rinmay qolishi mumkin.
            if xodim.role_id:
                yangi["allowed_role_id"] = xodim.role_id

        if room_id:
            xona = AmbulatoryRoom.objects.filter(id=room_id).first()
            if xona:
                yangi["room"] = xona

        if not yangi:
            messages.error(request, "Xodim yoki kabinet tanlanmadi.")
            return redirect("staff:services_bulk_assign")

        n = ServiceCatalog.objects.filter(id__in=ids).update(**yangi)
        messages.success(request, f"{n} ta xizmat yangilandi.")
        return redirect("staff:services")

    services = ServiceCatalog.objects.select_related(
        "allowed_role", "room", "responsible_staff"
    ).order_by("allowed_role__name", "name")
    return render(request, "staff/services_bulk_assign.html", {
        "services": services,
        "staff": User.objects.filter(is_active=True, role__isnull=False)
                     .select_related("role").order_by("first_name", "last_name"),
        "rooms": AmbulatoryRoom.objects.filter(is_active=True).order_by("name"),
    })


@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def service_create(request):
    """Yangi xizmat qo'shish."""
    from apps.accounts.forms import ServiceForm
    if request.method == "POST":
        form = ServiceForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Yangi xizmat qo'shildi.")
            return redirect("staff:services")
    else:
        form = ServiceForm()
    return render(request, "staff/service_form.html", {"form": form, "action": "Yangi xizmat"})


@role_required(
    Role.Code.DIRECTOR, Role.Code.CHIEF_DOCTOR, Role.Code.ADMINISTRATOR, Role.Code.SUPER_ADMIN,
)
def service_edit(request, service_id):
    """Xizmatni tahrirlash."""
    from apps.accounts.forms import ServiceForm
    from apps.clinical.models import ServiceCatalog
    service = get_object_or_404(ServiceCatalog, id=service_id)
    if request.method == "POST":
        form = ServiceForm(request.POST, instance=service)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{service.name}' yangilandi.")
            return redirect("staff:services")
    else:
        form = ServiceForm(instance=service)
    return render(request, "staff/service_form.html", {"form": form, "action": "Tahrirlash", "service": service})


@role_required(Role.Code.DIRECTOR, Role.Code.SUPER_ADMIN)
def service_delete(request, service_id):
    """Xizmatni o'chirish (bazadan o'chirmaydi, is_active=False qiladi)."""
    from apps.clinical.models import ServiceCatalog
    service = get_object_or_404(ServiceCatalog, id=service_id)
    if request.method == "POST":
        service.is_active = False
        service.save(update_fields=["is_active"])
        messages.success(request, f"'{service.name}' o'chirildi (xizmatlar hisobi saqlanib qoldi).")
        return redirect("staff:services")
    return render(request, "staff/service_confirm_delete.html", {"service": service})
