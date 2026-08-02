"""Sidebar bildirgilari (badge) uchun kontekst protsessorlari."""
from django.conf import settings
from django.utils import timezone


def clinic_info(request):
    """Klinika rekvizitlari — rasmiy hujjatlarда (chek, bayonnoma, xulosa) chiqadi."""
    return {
        "clinic_name": getattr(settings, "CLINIC_NAME", "Doctor B Najot"),
        "clinic_address": getattr(settings, "CLINIC_ADDRESS", ""),
        "clinic_phone": getattr(settings, "CLINIC_PHONE", ""),
    }


def notifications(request):
    """Anesteziolog/boshqaruv uchun bugun yuborilgan zayavkalar soni (bildirgi badge)."""
    user = getattr(request, "user", None)
    if not (user and user.is_authenticated):
        return {}
    role_code = getattr(getattr(user, "role", None), "code", None)
    if not (user.is_superuser or role_code in ("super_admin", "administrator", "anesthesiologist")):
        return {}
    try:
        from apps.clinical.models import AnesthesiaRequest
        today = timezone.localdate()
        count = AnesthesiaRequest.objects.filter(
            status=AnesthesiaRequest.Status.SENT, sent_at__date=today
        ).count()
    except Exception:
        count = 0
    return {"anesthesia_sent_today": count}
