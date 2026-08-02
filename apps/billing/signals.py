from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from apps.clinical.models import ServiceOrder, SurgerySchedule, InpatientStay, Consultation
from apps.pharmacy.models import MedicineDispense

@receiver(post_save, sender=ServiceOrder)
@receiver(post_delete, sender=ServiceOrder)
@receiver(post_save, sender=SurgerySchedule)
@receiver(post_delete, sender=SurgerySchedule)
@receiver(post_save, sender=InpatientStay)
@receiver(post_delete, sender=InpatientStay)
@receiver(post_save, sender=Consultation)
@receiver(post_delete, sender=Consultation)
@receiver(post_save, sender=MedicineDispense)
@receiver(post_delete, sender=MedicineDispense)
def sync_invoice_on_visit_item_change(sender, instance, **kwargs):
    """
    Klinika yoki Omborda bemorga tegishli qandaydir xizmat, operatsiya,
    stasionar yotish yoki dori o'zgarsa, avtomat tarzda Moliya Cheki (Invoice)
    qayta hisoblanadi.
    """
    # MUHIM: fixture/zaxira yuklanayotganda (loaddata) signal ISHLAMASLIGI kerak.
    # Aks holda yuklash paytida chek qayta yaratilib, zaxiradagi asl chek bilan
    # to'qnashadi (UNIQUE xatosi) — zaxiradan tiklash va PostgreSQL ga
    # ko'chirish buziladi.
    if kwargs.get("raw", False):
        return

    # Import ichkarida chaqiriladi (circular import oldini olish uchun)
    from apps.billing.services import generate_invoice_for_visit

    # Har bir obyektda 'visit' xossasi bor
    visit = getattr(instance, 'visit', None)
    if visit:
        generate_invoice_for_visit(visit)
