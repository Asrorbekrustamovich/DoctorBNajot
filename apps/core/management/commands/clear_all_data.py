"""TO'LIQ TOZALASH — bemorlar, hisobotlar, dorilar va omborlarni o'chiradi.

Klinikani ishga tushirishdan oldin sinov ma'lumotlarini tozalash uchun.

Ishlatilishi:
    python manage.py clear_all_data --dry-run    # faqat ko'rsatadi, o'chirmaydi
    python manage.py clear_all_data              # ro'yxat -> tasdiq -> zaxira -> o'chirish
    python manage.py clear_all_data --yes        # tasdiqsiz (skript uchun)
    python manage.py clear_all_data --with-storage   # ombor joylari va birliklarni ham
    python manage.py clear_all_data --keep-audit     # audit tarixini saqlab qolish

O'CHIRILADI:
    Bemorlar, tashriflar, navbat, yozilishlar
    Shifokor xulosalari, tayinlangan tekshiruvlar va natijalar
    Statsionar yotishlar, muolajalar, imzolar
    Operatsiyalar, bayonnomalar, protokol yozuvlari, zayavkalar
    Anjomlar TARIXI (anjomlarning o'zi qoladi, holati «Tayyor» ga qaytadi)
    Cheklar, to'lovlar, pul qaytarishlar, shifokor ulushlari
    DORILAR RO'YXATI va partiyalari, berilgan dorilar, so'rovlar
    ANESTEZIOLOG OMBORI to'liq (qoldiqlar bilan)
    Audit tarixi (--keep-audit bilan saqlab qolinadi)

SAQLANADI:
    Xodimlar, rollar, loginlar
    Xizmatlar katalogi va narxlari (mas'ul xodim/kabinet biriktirmalari bilan)
    Palatalar, o'rinlar, operatsion va ambulator xonalar
    Operatsiya turlari va narxlari, jarrohlik anjomlari
    Shifokor shablonlari va qabul narxlari
    Ombor joylari va o'lchov birliklari (--with-storage bilan o'chadi)
"""
from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Bemorlar, hisobotlar, dorilar va omborlarni to'liq tozalaydi."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--yes", action="store_true",
                            help="Tasdiq so'ramasdan bajarish")
        parser.add_argument("--dry-run", action="store_true",
                            help="Hech narsa o'chirmasdan, faqat nima o'chishini ko'rsatadi")
        parser.add_argument("--no-backup", action="store_true",
                            help="Zaxira olmasdan (tavsiya etilmaydi)")
        parser.add_argument("--with-storage", action="store_true",
                            help="Ombor joylari va o'lchov birliklarini ham o'chirish")
        parser.add_argument("--keep-audit", action="store_true",
                            help="Audit tarixini saqlab qolish")

    # ------------------------------------------------------------------
    def handle(self, *args: Any, **opts: Any) -> None:
        M = self._models()

        guruhlar = self._counts(M, opts["with_storage"], opts["keep_audit"])
        jami = sum(n for g in guruhlar.values() for n in g.values())

        # ---------- 1) Nima o'chishini ko'rsatamiz ----------
        self.stdout.write(self.style.MIGRATE_HEADING("\n╔══════════════════════════════════════════════╗"))
        self.stdout.write(self.style.MIGRATE_HEADING("║        TO'LIQ TOZALASH — O'CHIRILADI          ║"))
        self.stdout.write(self.style.MIGRATE_HEADING("╚══════════════════════════════════════════════╝"))

        for guruh, elementlar in guruhlar.items():
            bor = {k: v for k, v in elementlar.items() if v}
            if not bor:
                continue
            self.stdout.write(self.style.WARNING(f"\n  {guruh}"))
            for nom, n in bor.items():
                self.stdout.write(f"    · {nom:<38} {n:>8}")

        # OSILIB QOLGAN HOLATLARNI ALOHIDA SANAYMIZ.
        #
        # Yozuvlar soni nolga teng bo'lsa ham baza «toza» bo'lmasligi mumkin:
        # kravat «band» bo'lib qolgan, anjom «ishlatilgan» holatida turgan
        # bo'lishi mumkin. Ilgari buyruq shu yerda to'xtab qolardi va aynan
        # tuzatish kerak bo'lgan holatda hech nima qilmasdi.
        osilgan = self._stuck(M)

        if jami == 0 and not osilgan:
            self.stdout.write(self.style.SUCCESS("\n  Baza allaqachon toza — o'chiradigan narsa yo'q.\n"))
            return

        if osilgan:
            self.stdout.write(self.style.WARNING("\n  TUZATILADI (yozuv o'chmaydi, holat tiklanadi)"))
            for nom, n in osilgan.items():
                self.stdout.write(f"    · {nom:<38} {n:>8}")

        if jami == 0:
            self.stdout.write(self.style.SUCCESS(
                "\n  Bemor ma'lumoti yo'q — faqat osilib qolgan holat tuzatiladi.\n"))

        self.stdout.write(self.style.ERROR(f"\n  JAMI: {jami} ta yozuv o'chiriladi"))
        self.stdout.write(self.style.SUCCESS(
            "\n  SAQLANADI: xodimlar va rollar, xizmatlar katalogi, palatalar\n"
            "  va xonalar, operatsiya turlari, jarrohlik anjomlari,\n"
            "  shifokor shablonlari va narxlari."
        ))

        if opts["dry_run"]:
            self.stdout.write(self.style.WARNING(
                "\n  --dry-run: hech narsa o'chirilmadi.\n"))
            return

        # ---------- 2) Tasdiq ----------
        if not opts["yes"]:
            if not settings.DEBUG:
                self.stdout.write(self.style.ERROR(
                    "\n  ⚠  BU ISHLAYOTGAN SERVER (DEBUG=False).\n"
                    "     Haqiqiy bemorlar ma'lumoti bo'lishi mumkin!"
                ))
            self.stdout.write(self.style.ERROR(
                "\n  Bu amalni ORQAGA QAYTARIB BO'LMAYDI (faqat zaxiradan tiklash)."
            ))
            javob = input("\n  Davom etish uchun HA deb yozing: ").strip()
            if javob != "HA":
                self.stdout.write(self.style.SUCCESS("\n  Bekor qilindi — hech narsa o'chirilmadi.\n"))
                return

        # ---------- 3) Zaxira ----------
        if not opts["no_backup"]:
            self.stdout.write("\n  Zaxira nusxa olinmoqda...")
            try:
                call_command("backup_db", keep=50, verbosity=0)
                self.stdout.write(self.style.SUCCESS("  ✓ Zaxira olindi (backups/ papkasida)"))
            except Exception as exc:  # noqa: BLE001
                self.stdout.write(self.style.ERROR(f"  ✗ Zaxira olinmadi: {exc}"))
                self.stdout.write("  Xavfsizlik uchun to'xtatildi. Majburlash: --no-backup")
                return

        # ---------- 4) O'chirish ----------
        ochirildi: dict[str, int] = {}
        with transaction.atomic():
            self._wipe_billing(M, ochirildi)
            self._wipe_surgery(M, ochirildi)
            self._wipe_inpatient(M, ochirildi)
            self._wipe_pharmacy(M, ochirildi, opts["with_storage"])
            self._wipe_anesthesia(M, ochirildi)
            self._wipe_patients(M, ochirildi)
            self._reset_state(M, ochirildi, opts["keep_audit"])

        self.stdout.write(self.style.SUCCESS("\n  ══ O'CHIRILDI ══"))
        for nom, n in ochirildi.items():
            if n:
                self.stdout.write(f"    · {nom:<38} {n:>8}")

        self.stdout.write(self.style.SUCCESS(
            "\n  Tayyor. Baza toza, sozlamalar joyida.\n"
            "  Xato bo'lsa tiklash:  python manage.py restore_db --latest\n"
        ))

    # ------------------------------------------------------------------
    #  Modellarni bir joyda yig'amiz
    # ------------------------------------------------------------------
    @staticmethod
    def _models():
        from apps.audit.models import AuditLog
        from apps.billing.models import DoctorShare, Invoice, InvoiceItem, Refund
        from apps.clinical.models import (
            Bed,
            AnesthesiaRequest, AnesthesiaRequestItem, AnesthesiaStock,
            AnesthesiaStockPackage, Consultation, InpatientStay, NurseUsageItem,
            ProcedureRecord, RoomLeftover, ServiceOrder, StayChecklistItem,
            SurgeryReport, SurgerySchedule, SurgeryVitals, SurgicalItem,
            SurgicalItemHistory,
            # Statsionar epizodi va vipiska (keyinroq qo'shilgan modellar).
            # Bularsiz «tozalash» yarim ish bo'lardi: bemor o'chib ketardi-yu,
            # uning epizodi bazada qolib, keyingi safar chalkashlik berardi.
            AdmissionEpisode, DischargeSummary, EpisodeDiagnosis,
            ServiceResultRow,
        )
        from apps.patients.models import Patient
        from apps.pharmacy.models import (
            MeasurementUnit, Medicine, MedicineBatch, MedicineDispense,
            MedicinePackaging, MedicinePriceHistory, MedicineRequest,
            MedicineRequestItem, StorageLocation,
        )
        from apps.registration.models import Appointment, Visit
        return locals()

    def _counts(self, M, with_storage: bool, keep_audit: bool):
        c = self._count
        guruhlar = {
            "BEMORLAR VA TASHRIFLAR": {
                "Bemorlar": c(M["Patient"]),
                "Tashriflar": c(M["Visit"]),
                "Yozilishlar": c(M["Appointment"]),
                "Shifokor xulosalari": c(M["Consultation"]),
                "Tayinlangan tekshiruvlar": c(M["ServiceOrder"]),
                "Tekshiruv natijalari": c(M["ServiceResultRow"]),
                "Statsionar epizodlari": c(M["AdmissionEpisode"]),
                "Epizod tashxislari": c(M["EpisodeDiagnosis"]),
                "Vipiskalar": c(M["DischargeSummary"]),
            },
            "STATSIONAR": {
                "Yotishlar": c(M["InpatientStay"]),
                "Muolajalar": c(M["ProcedureRecord"]),
                "Hujjat ro'yxatlari": c(M["StayChecklistItem"]),
            },
            "OPERATSIYALAR": {
                "Operatsiyalar": c(M["SurgerySchedule"]),
                "Bayonnomalar": c(M["SurgeryReport"]),
                "Protokol yozuvlari": c(M["SurgeryVitals"]),
                "Hamshira ishlatgan anjomlar": c(M["NurseUsageItem"]),
                "Anjomlar tarixi": c(M["SurgicalItemHistory"]),
            },
            "MOLIYA": {
                "Cheklar": c(M["Invoice"]),
                "Chek bandlari": c(M["InvoiceItem"]),
                "Pul qaytarishlar": c(M["Refund"]),
                "Shifokor ulushlari": c(M["DoctorShare"]),
            },
            "DORILAR VA UMUMIY OMBOR": {
                "Dorilar ro'yxati": c(M["Medicine"]),
                "Dori partiyalari": c(M["MedicineBatch"]),
                "Berilgan dorilar": c(M["MedicineDispense"]),
                "Dori qadoqlari": c(M["MedicinePackaging"]),
                "Narx tarixi": c(M["MedicinePriceHistory"]),
                "Dori so'rovlari": c(M["MedicineRequest"]),
                "So'rov qatorlari": c(M["MedicineRequestItem"]),
            },
            "ANESTEZIOLOG OMBORI": {
                "Ombor mahsulotlari": c(M["AnesthesiaStock"]),
                "Qadoqlar": c(M["AnesthesiaStockPackage"]),
                "Zayavkalar": c(M["AnesthesiaRequest"]),
                "Zayavka qatorlari": c(M["AnesthesiaRequestItem"]),
                "Xonadagi qoldiqlar": c(M["RoomLeftover"]),
            },
        }
        if with_storage:
            guruhlar["OMBOR TUZILMASI"] = {
                "Ombor joylari": c(M["StorageLocation"]),
                "O'lchov birliklari": c(M["MeasurementUnit"]),
            }
        if not keep_audit:
            guruhlar["AUDIT"] = {"Audit yozuvlari": M["AuditLog"].objects.count()}
        return guruhlar

    # ------------------------------------------------------------------
    #  O'chirish bosqichlari — bog'liqlik tartibida (bolalardan ota-onaga)
    # ------------------------------------------------------------------
    def _wipe_billing(self, M, out):
        out["Chek bandlari"] = self._wipe(M["InvoiceItem"])
        out["Pul qaytarishlar"] = self._wipe(M["Refund"])
        out["Shifokor ulushlari"] = self._wipe(M["DoctorShare"])
        out["Cheklar"] = self._wipe(M["Invoice"])

    def _wipe_surgery(self, M, out):
        out["Protokol yozuvlari"] = self._wipe(M["SurgeryVitals"])
        out["Hamshira ishlatgan anjomlar"] = self._wipe(M["NurseUsageItem"])
        out["Bayonnomalar"] = self._wipe(M["SurgeryReport"])
        out["Anjomlar tarixi"] = self._wipe(M["SurgicalItemHistory"])
        out["Operatsiyalar"] = self._wipe(M["SurgerySchedule"])

    def _wipe_inpatient(self, M, out):
        out["Muolajalar"] = self._wipe(M["ProcedureRecord"])
        out["Hujjat ro'yxatlari"] = self._wipe(M["StayChecklistItem"])
        out["Yotishlar"] = self._wipe(M["InpatientStay"])

    def _wipe_pharmacy(self, M, out, with_storage: bool):
        out["Berilgan dorilar"] = self._wipe(M["MedicineDispense"])
        out["So'rov qatorlari"] = self._wipe(M["MedicineRequestItem"])
        out["Dori so'rovlari"] = self._wipe(M["MedicineRequest"])
        out["Narx tarixi"] = self._wipe(M["MedicinePriceHistory"])
        out["Dori qadoqlari"] = self._wipe(M["MedicinePackaging"])
        out["Dori partiyalari"] = self._wipe(M["MedicineBatch"])
        out["Dorilar ro'yxati"] = self._wipe(M["Medicine"])
        if with_storage:
            out["Ombor joylari"] = self._wipe(M["StorageLocation"])
            out["O'lchov birliklari"] = self._wipe(M["MeasurementUnit"])

    def _wipe_anesthesia(self, M, out):
        out["Xonadagi qoldiqlar"] = self._wipe(M["RoomLeftover"])
        out["Zayavka qatorlari"] = self._wipe(M["AnesthesiaRequestItem"])
        out["Zayavkalar"] = self._wipe(M["AnesthesiaRequest"])
        out["Qadoqlar"] = self._wipe(M["AnesthesiaStockPackage"])
        out["Ombor mahsulotlari"] = self._wipe(M["AnesthesiaStock"])

    def _wipe_patients(self, M, out):
        # TARTIB MUHIM: epizod bemorga PROTECT bilan bog'langan, shuning
        # uchun u bemordan OLDIN o'chirilishi shart. Vipiska va tashxislar
        # esa epizodga bog'langan — ular ham undan oldin.
        out["Vipiskalar"] = self._wipe(M["DischargeSummary"])
        out["Epizod tashxislari"] = self._wipe(M["EpisodeDiagnosis"])
        out["Statsionar epizodlari"] = self._wipe(M["AdmissionEpisode"])
        out["Tekshiruv natijalari"] = self._wipe(M["ServiceResultRow"])
        out["Tayinlangan tekshiruvlar"] = self._wipe(M["ServiceOrder"])
        out["Shifokor xulosalari"] = self._wipe(M["Consultation"])
        out["Yozilishlar"] = self._wipe(M["Appointment"])
        out["Tashriflar"] = self._wipe(M["Visit"])
        out["Bemorlar"] = self._wipe(M["Patient"])

    def _reset_state(self, M, out, keep_audit: bool):
        # Anjomlar qoladi, lekin tarixi o'chgani uchun holati «Tayyor» ga qaytadi
        n = M["SurgicalItem"].objects.exclude(
            status=M["SurgicalItem"].Status.READY
        ).update(status=M["SurgicalItem"].Status.READY, current_room=None)
        if n:
            out["Anjomlar «Tayyor» ga qaytarildi"] = n

        # KRAVATLAR BO'SHATILADI.
        #
        # `Bed.is_occupied` — yotishlardan ALOHIDA saqlanadigan bayroq. U faqat
        # bemorga javob berilganda o'chadi. Yotishlarni to'g'ridan-to'g'ri
        # o'chirsak, bayroq «band» bo'lib qolib ketadi va statsionar butunlay
        # to'silib qoladi: bemor yo'q, lekin kravat ham berilmaydi.
        n = M["Bed"].all_objects.filter(is_occupied=True).update(is_occupied=False)
        if n:
            out["Kravatlar bo'shatildi"] = n

        if not keep_audit:
            out["Audit yozuvlari"] = M["AuditLog"].objects.all().delete()[0]

        # Kunlik navbat raqamlari 1 dan boshlansin
        from apps.core.models import Sequence
        out["Navbat hisoblagichlari"] = Sequence.objects.filter(
            name__startswith="visit_queue:"
        ).delete()[0]

    @staticmethod
    def _stuck(M) -> dict[str, int]:
        """Yozuv emas, HOLAT bo'lib osilib qolgan narsalar."""
        natija: dict[str, int] = {}

        n = M["Bed"].all_objects.filter(is_occupied=True).count()
        if n:
            natija["«Band» bo'lib qolgan kravatlar"] = n

        n = M["SurgicalItem"].objects.exclude(
            status=M["SurgicalItem"].Status.READY).count()
        if n:
            natija["«Tayyor» emas anjomlar"] = n

        return natija

    # ------------------------------------------------------------------
    @staticmethod
    def _count(model) -> int:
        mgr = getattr(model, "all_objects", None) or model._default_manager
        return mgr.count()

    @staticmethod
    def _wipe(model) -> int:
        """Modelni JISMONAN tozalaydi (soft delete emas — iz qolmaydi)."""
        mgr = getattr(model, "all_objects", None) or model._default_manager
        qs = mgr.all()
        result = qs.hard_delete() if hasattr(qs, "hard_delete") else qs.delete()
        return result[0] if isinstance(result, tuple) else (result or 0)
