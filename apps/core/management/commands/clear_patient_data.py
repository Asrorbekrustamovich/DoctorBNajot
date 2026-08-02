"""Bemorlarga oid BARCHA ma'lumotni bazadan o'chirish (toza boshlash uchun).

Ishlatilishi:
    python manage.py clear_patient_data              # tasdiq so'raydi
    python manage.py clear_patient_data --yes        # so'ramasdan
    python manage.py clear_patient_data --yes --restore-stock   # dori qoldig'ini ham tiklaydi

O'CHIRILADI (bemorga oid hamma narsa):
    - Bemorlar kartotekasi
    - Tashriflar, navbat, yozilishlar
    - Shifokor xulosalari, tayinlangan xizmatlar va natijalar
    - Statsionar yotishlar, muolajalar, hujjat ro'yxatlari, imzolar
    - Operatsiyalar, bayonnomalar, protokol (davleniye/puls), zayavkalar
    - Berilgan dorilar (dispense)
    - Cheklar, chek bandlari, to'lovlar, pul qaytarishlar
    - Bemorlarga oid audit tarixi

SAQLANADI (sozlamalar — qayta kiritish shart emas):
    - Xodimlar va rollar
    - Xizmatlar katalogi va narxlari, shifokor qabul narxlari
    - Palatalar, o'rinlar, operatsion xonalar
    - Operatsiya turlari, jarrohlik anjomlari
    - Dori katalogi va partiyalari (ombor), anesteziolog ombori
    - Shifokor shablonlari
"""
from __future__ import annotations

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Bemorlarga oid barcha ma'lumotni o'chiradi (sozlamalar saqlanadi)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--yes", action="store_true", help="Tasdiq so'ramasdan bajarish")
        parser.add_argument("--no-backup", action="store_true", help="Zaxira olmasdan (tavsiya etilmaydi)")
        parser.add_argument(
            "--restore-stock", action="store_true",
            help="Berilgan dorilar miqdorini ombor qoldig'iga qaytarish",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        from apps.audit.models import AuditLog
        from apps.billing.models import Invoice, InvoiceItem, Refund
        from apps.clinical.models import (
            AnesthesiaRequest, AnesthesiaRequestItem, Consultation, InpatientStay,
            NurseUsageItem, ProcedureRecord, ServiceOrder, StayChecklistItem,
            SurgeryReport, SurgerySchedule, SurgicalItemHistory, SurgeryVitals,
        )
        from apps.patients.models import Patient
        from apps.pharmacy.models import MedicineDispense
        from apps.registration.models import Appointment, Visit

        # --- Nima o'chirilishini oldindan ko'rsatamiz ---
        counts = {
            "Bemorlar": Patient.all_objects.count(),
            "Tashriflar": Visit.all_objects.count(),
            "Yozilishlar": Appointment.all_objects.count(),
            "Shifokor xulosalari": Consultation.all_objects.count(),
            "Tayinlangan xizmatlar": ServiceOrder.all_objects.count(),
            "Statsionar yotishlar": InpatientStay.all_objects.count(),
            "Muolajalar": ProcedureRecord.all_objects.count(),
            "Hujjat ro'yxatlari": StayChecklistItem.all_objects.count(),
            "Operatsiyalar": SurgerySchedule.all_objects.count(),
            "Operatsiya bayonnomalari": SurgeryReport.all_objects.count(),
            "Protokol yozuvlari": SurgeryVitals.all_objects.count(),
            "Anesteziolog zayavkalari": AnesthesiaRequest.all_objects.count(),
            "Hamshira anjomlari": NurseUsageItem.all_objects.count(),
            "Berilgan dorilar": MedicineDispense.all_objects.count(),
            "Cheklar": Invoice.all_objects.count(),
            "Chek bandlari": InvoiceItem.all_objects.count(),
            "Pul qaytarishlar": Refund.all_objects.count(),
        }

        self.stdout.write(self.style.WARNING("\nO'CHIRILADI:"))
        for name, n in counts.items():
            if n:
                self.stdout.write(f"   {name}: {n} ta")
        if not any(counts.values()):
            self.stdout.write("   (bemorga oid ma'lumot topilmadi)")
            return

        self.stdout.write(self.style.SUCCESS(
            "\nSAQLANADI: xodimlar, rollar, xizmatlar katalogi, narxlar, "
            "palatalar, operatsion xonalar, operatsiya turlari, "
            "dori katalogi va ombor qoldiqlari, shifokor shablonlari."
        ))

        if not options["yes"]:
            self.stdout.write(self.style.ERROR(
                "\nDIQQAT: bu amalni orqaga qaytarib bo'lmaydi "
                "(faqat zaxiradan tiklash mumkin)."
            ))
            answer = input("Rostdan ham o'chirilsinmi? (ha/yo'q): ").strip().lower()
            if answer not in ("ha", "yes", "y"):
                self.stdout.write("Bekor qilindi.")
                return

        # --- Xavfsizlik zaxirasi ---
        if not options["no_backup"]:
            self.stdout.write("\nZaxira nusxa olinmoqda (o'chirishdan oldin)...")
            try:
                call_command("backup_db", keep=50)
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"Zaxira olinmadi: {exc}"))
                self.stdout.write("Xavfsizlik uchun to'xtatildi. --no-backup bilan majburlash mumkin.")
                return

        # --- Dori qoldig'ini tiklash (ixtiyoriy) ---
        restored = 0
        restored_qty = 0
        if options["restore_stock"]:
            for d in MedicineDispense.all_objects.select_related("batch"):
                # Allaqachon qaytarilganlar ombor qoldig'iga qayta qo'shilmaydi
                if getattr(d, "is_returned", False):
                    continue
                batch = getattr(d, "batch", None)
                if batch is None:
                    continue
                # MedicineBatch da qoldiq maydoni: quantity_available
                batch.quantity_available = (batch.quantity_available or 0) + (d.quantity or 0)
                batch.save(update_fields=["quantity_available"])
                restored += 1
                restored_qty += (d.quantity or 0)

        # --- O'chirish: bog'liqlik tartibida (bolalardan ota-onaga) ---
        deleted = {}
        with transaction.atomic():
            # Moliya
            deleted["Chek bandlari"] = InvoiceItem.all_objects.all().hard_delete()[0] \
                if hasattr(InvoiceItem.all_objects.all(), "hard_delete") else InvoiceItem.all_objects.all().delete()[0]
            deleted["Pul qaytarishlar"] = self._wipe(Refund)
            deleted["Cheklar"] = self._wipe(Invoice)

            # Operatsiya
            deleted["Protokol yozuvlari"] = self._wipe(SurgeryVitals)
            deleted["Hamshira anjomlari"] = self._wipe(NurseUsageItem)
            deleted["Zayavka qatorlari"] = self._wipe(AnesthesiaRequestItem)
            deleted["Anesteziolog zayavkalari"] = self._wipe(AnesthesiaRequest)
            deleted["Operatsiya bayonnomalari"] = self._wipe(SurgeryReport)
            SurgicalItemHistory.objects.update(surgery=None)
            deleted["Operatsiyalar"] = self._wipe(SurgerySchedule)

            # Statsionar
            deleted["Muolajalar"] = self._wipe(ProcedureRecord)
            deleted["Hujjat ro'yxatlari"] = self._wipe(StayChecklistItem)
            deleted["Statsionar yotishlar"] = self._wipe(InpatientStay)

            # Dorilar va xizmatlar
            deleted["Berilgan dorilar"] = self._wipe(MedicineDispense)
            deleted["Tayinlangan xizmatlar"] = self._wipe(ServiceOrder)
            deleted["Shifokor xulosalari"] = self._wipe(Consultation)

            # Tashriflar va bemorlar
            deleted["Yozilishlar"] = self._wipe(Appointment)
            deleted["Tashriflar"] = self._wipe(Visit)
            deleted["Bemorlar"] = self._wipe(Patient)

            # Bemorlarga oid audit tarixi
            deleted["Audit yozuvlari"] = AuditLog.objects.filter(
                model_name__in=[
                    "patients.patient", "clinic_registration.visit",
                    "clinic_registration.appointment", "clinical.consultation",
                    "clinical.serviceorder", "clinical.inpatientstay",
                    "clinical.procedurerecord", "clinical.staychecklistitem",
                    "clinical.surgeryschedule", "clinical.surgeryreport",
                    "clinical.surgeryvitals", "clinical.nurseusageitem",
                    "clinical.anesthesiarequest", "clinical.anesthesiarequestitem",
                    "billing.invoice", "billing.invoiceitem", "billing.refund",
                    "pharmacy.medicinedispense",
                ]
            ).delete()[0]

            # Kunlik navbat raqamlarini nolga qaytaramiz
            from apps.core.models import Sequence
            Sequence.objects.filter(name__startswith="visit_queue:").delete()

        self.stdout.write(self.style.SUCCESS("\nO'CHIRILDI:"))
        for name, n in deleted.items():
            if n:
                self.stdout.write(f"   {name}: {n} ta")
        if restored:
            self.stdout.write(self.style.SUCCESS(
                f"\nOmborga qaytarildi: {restored} ta yozuv, jami {restored_qty} birlik dori"
            ))

        self.stdout.write(self.style.SUCCESS(
            "\nTayyor. Baza bemorlardan tozalandi, sozlamalar joyida.\n"
            "Xato bo'lsa: python manage.py restore_db --latest"
        ))

    @staticmethod
    def _wipe(model) -> int:
        """Modelni to'liq (jismonan) tozalaydi — soft delete emas."""
        qs = model.all_objects.all() if hasattr(model, "all_objects") else model._default_manager.all()
        if hasattr(qs, "hard_delete"):
            result = qs.hard_delete()
        else:
            result = qs.delete()
        return result[0] if isinstance(result, tuple) else (result or 0)
