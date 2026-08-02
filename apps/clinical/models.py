"""Klinik jarayonlar va xizmatlar modellar."""
from django.conf import settings
from django.db import models

from apps.accounts.models import Role
from apps.audit.mixins import Auditable
from apps.core.models import BaseModel, LockableMixin
from apps.registration.models import Visit


class ServiceCatalog(Auditable, BaseModel):
    """Narxli xizmatlar katalogi (Shifokor ko'rigi, UZI, EKG, Analizlar)."""

    name = models.CharField("Xizmat nomi", max_length=200, unique=True)
    price = models.DecimalField("Narxi", max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField("Faolmi?", default=True)
    
    # Qaysi roldagi shifokor buni bajara oladi (masalan, faqat radiolog, yoki faqat shifokor)
    allowed_role = models.ForeignKey(
        Role, verbose_name="Bajaruvchi rol", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="services"
    )

    # --- BEMOR QAYERGA BORADI ---
    # Tayinlanganda bemorga "qaysi xonaga, kimning oldiga" borish kerakligi
    # ko'rsatilishi uchun. Ikkalasi ham ixtiyoriy.
    room = models.ForeignKey(
        "AmbulatoryRoom", verbose_name="Kabinet (qaysi xona)",
        null=True, blank=True, on_delete=models.SET_NULL, related_name="services",
    )
    responsible_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Mas'ul xodim",
        null=True, blank=True, on_delete=models.SET_NULL, related_name="responsible_services",
        help_text="Shu xizmatni odatda bajaradigan xodim. Bo'sh qoldirilsa — rol bo'yicha kim bo'sh bo'lsa.",
    )

    class Meta:
        verbose_name = "Xizmat"
        verbose_name_plural = "Xizmatlar katalogi"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.price} so'm)"

    @property
    def destination(self) -> str:
        """Bemorga ko'rsatiladigan "qayerga borish" matni.

        Masalan: "3-Xona — Karimov Aziz (Radiologiya)".
        Ma'lumot bo'lmasa bo'sh qaytaradi (interfeys o'zi ogohlantiradi).
        """
        parts = []
        if self.room_id:
            parts.append(self.room.name)
        if self.responsible_staff_id:
            xodim = self.responsible_staff.get_full_name() or self.responsible_staff.username
            parts.append(xodim)
        elif self.allowed_role_id:
            parts.append(self.allowed_role.name)
        return " — ".join(parts)


class Consultation(Auditable, LockableMixin, BaseModel):
    """Shifokor qabuli natijasi (Tashxis, Retsept).

    Bitta Visit ichida har bir shifokor o'z xulosasini yozadi —
    yo'naltirilganda yangi Visit ochilmaydi, xulosalar shu yerda to'planadi.
    """

    visit = models.ForeignKey(
        Visit, verbose_name="Qabul", on_delete=models.CASCADE, related_name="consultations"
    )
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor", on_delete=models.PROTECT,
        related_name="consultations"
    )
    complaint = models.TextField("Shikoyat", blank=True)
    anamnesis = models.TextField("Kasallik tarixi (Anamnez)", blank=True)
    objective_status = models.TextField("Obyektiv holat", blank=True)
    diagnosis = models.TextField("Yakuniy tashxis", blank=True, null=True)
    prescription = models.TextField("Dori-darmonlar (Retsept)", blank=True)
    recommendations = models.TextField("Tavsiyalar", blank=True)
    report_html = models.TextField("Tibbiy xulosa (HTML)", blank=True, null=True)
    # Qabul paytidagi narx SNAPSHOTI — keyin shifokor narxi o'zgarsa ham
    # bu yozuv (va uning cheki) o'zgarmaydi.
    fee = models.DecimalField(
        "Qabul narxi (o'sha paytdagi)", max_digits=12, decimal_places=2, default=0
    )

    class Meta:
        verbose_name = "Shifokor xulosasi"
        verbose_name_plural = "Shifokor xulosalari"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["visit", "doctor"], name="uniq_consultation_per_visit_doctor"
            )
        ]

    def __str__(self) -> str:
        return f"{self.visit.patient.full_name} - {self.doctor.get_full_name()}"


class ConsultationTemplate(Auditable, BaseModel):
    """Shifokorning shaxsiy tashxis shabloni.

    Har bir shifokor o'z shablonlarini yaratadi va qabul paytida
    shulardan birini tanlab, maydonlarni avtomatik to'ldiradi.
    """

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor", on_delete=models.CASCADE,
        related_name="consultation_templates",
    )
    name = models.CharField("Shablon nomi", max_length=150)
    complaint = models.TextField("Shikoyat", blank=True)
    anamnesis = models.TextField("Anamnez", blank=True)
    objective_status = models.TextField("Obyektiv holat", blank=True)
    diagnosis = models.TextField("Tashxis", blank=True)
    prescription = models.TextField("Retsept", blank=True)
    recommendations = models.TextField("Tavsiyalar", blank=True)
    report_html = models.TextField("Shablon matni (HTML)", blank=True, null=True)

    class Meta:
        verbose_name = "Tashxis shabloni"
        verbose_name_plural = "Tashxis shablonlari"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["doctor", "name"], name="uniq_template_per_doctor_name"
            )
        ]

    def __str__(self) -> str:
        return f"{self.doctor.get_full_name()}: {self.name}"


class ServiceOrder(Auditable, BaseModel):
    """Tavsiya etilgan qo'shimcha xizmat (UZI, EKG) navbati.

    price_snapshot — tayinlanish paytidagi narx. Keyinchalik katalog narxi
    o'zgarsa ham, bu yozuv va uning cheki o'zgarmaydi.
    """

    class Status(models.TextChoices):
        WAITING = "waiting", "Kutmoqda (To'lanmagan)"
        PAID = "paid", "To'langan"
        IN_PROGRESS = "in_progress", "Bajarilmoqda"
        COMPLETED = "completed", "Yakunlangan"
        CANCELLED = "cancelled", "Bekor qilingan"

    visit = models.ForeignKey(
        Visit, verbose_name="Asosiy Qabul", on_delete=models.CASCADE, related_name="service_orders"
    )
    service = models.ForeignKey(
        ServiceCatalog, verbose_name="Xizmat", on_delete=models.PROTECT, related_name="orders"
    )
    price_snapshot = models.DecimalField(
        "Narxi (tayinlanish paytidagi)", max_digits=12, decimal_places=2, default=0,
        help_text="Tayinlangan paytdagi xizmat narxi. Keyin katalog narxi o'zgarsa ham bu o'zgarmaydi.",
    )
    status = models.CharField(
        "Status", max_length=20, choices=Status.choices, default=Status.WAITING
    )
    result_text = models.TextField("Natija (Xulosa)", blank=True)
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Bajardi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="performed_services"
    )

    # --- QABUL QILISH (bemor ichkarida) ---
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Qabul qildi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="accepted_service_orders",
    )
    accepted_at = models.DateTimeField("Qabul qilingan vaqt", null=True, blank=True)

    # --- KECHIKTIRISH (navbatga qaytadi, sabab saqlanadi) ---
    defer_count = models.PositiveIntegerField("Necha marta kechiktirilgan", default=0)
    deferred_reason = models.CharField("Kechiktirish sababi", max_length=255, blank=True)
    deferred_at = models.DateTimeField("Kechiktirilgan vaqt", null=True, blank=True)
    deferred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Kechiktirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="deferred_service_orders",
    )

    class Meta:
        verbose_name = "Xizmat buyurtmasi"
        verbose_name_plural = "Xizmat buyurtmalari"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.service.name} - {self.visit.patient.full_name}"

    def save(self, *args, **kwargs):
        # MUHIM: pk UUID bo'lgani uchun "not self.pk" ishlamaydi (pk oldindan
        # to'ldirilgan bo'ladi) — yangi yozuvni _state.adding aniqlaydi.
        if self._state.adding and (self.price_snapshot or 0) == 0:
            self.price_snapshot = self.service.price
        super().save(*args, **kwargs)


class ServiceCatalogPriceHistory(BaseModel):
    """Xizmat narxining o'zgarish tarixi."""
    service = models.ForeignKey(
        ServiceCatalog, on_delete=models.CASCADE, related_name="price_history",
        verbose_name="Xizmat",
    )
    old_price = models.DecimalField("Eski narx", max_digits=12, decimal_places=2, default=0)
    new_price = models.DecimalField("Yangi narx", max_digits=12, decimal_places=2, default=0)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="O'zgartirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="service_price_changes",
    )

    class Meta:
        verbose_name = "Xizmat narxi o'zgarishi"
        verbose_name_plural = "Xizmat narxi o'zgarishlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.service.name}: {self.old_price} -> {self.new_price}"


class DoctorPrice(Auditable, BaseModel):
    """Har bir shifokor qabulining joriy narxi.

    Narx o'zgartirilganda faqat SHU model yangilanadi — avvalgi qabullar
    (Consultation.fee snapshoti) va cheklar o'zgarmaydi. O'zgarishlar
    DoctorPriceHistory da saqlanadi.
    """

    doctor = models.OneToOneField(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor",
        on_delete=models.CASCADE, related_name="consultation_price",
    )
    price = models.DecimalField("Qabul narxi", max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField("Faolmi?", default=True)

    class Meta:
        verbose_name = "Shifokor qabul narxi"
        verbose_name_plural = "Shifokor qabul narxlari"
        ordering = ["doctor__last_name"]

    def __str__(self) -> str:
        return f"{self.doctor.get_full_name()} — {self.price} so'm"

    @staticmethod
    def current_fee_for(doctor) -> "models.DecimalField":
        """Shifokorning joriy qabul narxi (yo'q/nofaol bo'lsa 0)."""
        from decimal import Decimal
        dp = DoctorPrice.objects.filter(doctor=doctor, is_active=True).first()
        return dp.price if dp else Decimal(0)


class DoctorPriceHistory(BaseModel):
    """Qabul narxi o'zgarishlari tarixi (audit)."""

    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor",
        on_delete=models.CASCADE, related_name="price_history",
    )
    old_price = models.DecimalField("Eski narx", max_digits=12, decimal_places=2, default=0)
    new_price = models.DecimalField("Yangi narx", max_digits=12, decimal_places=2, default=0)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="O'zgartirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="price_changes",
    )

    class Meta:
        verbose_name = "Narx o'zgarishi"
        verbose_name_plural = "Narx o'zgarishlari tarixi"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.doctor.get_full_name()}: {self.old_price} → {self.new_price}"


# ==========================================
# STASIONAR (INPATIENT) MODELLARI
# ==========================================

class AmbulatoryRoom(Auditable, BaseModel):
    """Ambulator (poliklinika) xonasi (kabinet)."""
    name = models.CharField("Xona raqami/nomi", max_length=50, unique=True)
    is_active = models.BooleanField("Faolmi?", default=True)
    doctors = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True,
        related_name="ambulatory_rooms", verbose_name="Mas'ul shifokorlar",
        limit_choices_to={"role__code__in": ["doctor", "chief_doctor", "surgeon", "anesthesiologist", "lab", "radiology"]}
    )

    class Meta:
        verbose_name = "Ambulator xona"
        verbose_name_plural = "Ambulator xonalar"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Room(Auditable, BaseModel):
    """Palata (Xona)."""
    name = models.CharField("Xona raqami/nomi", max_length=50)
    floor = models.IntegerField("Qavat", default=1)
    is_active = models.BooleanField("Faolmi?", default=True)
    assigned_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assigned_rooms", verbose_name="Mas'ul shifokor",
        limit_choices_to={"role__code__in": ["doctor", "chief_doctor", "surgeon"]}
    )

    class Meta:
        verbose_name = "Palata"
        verbose_name_plural = "Palatalar"
        ordering = ["floor", "name"]
        
    def __str__(self):
        return f"{self.name} ({self.floor}-qavat)"


class Bed(Auditable, BaseModel):
    """Kravat."""
    room = models.ForeignKey(Room, on_delete=models.CASCADE, related_name="beds", verbose_name="Xona")
    number = models.CharField("Kravat raqami", max_length=20)
    price_per_day = models.DecimalField("Bemor uchun kunlik narxi", max_digits=12, decimal_places=2, default=0)
    companion_price_per_day = models.DecimalField("Hamroh uchun kunlik narxi", max_digits=12, decimal_places=2, default=0)
    # Paketli statsionar: dori-darmon narxi yotish ichida — bemor faqat
    # shu kunlik narxni to'laydi, dorilar klinika ombordan beriladi.
    package_price_per_day = models.DecimalField(
        "Paketli (dori ichida) kunlik narx", max_digits=12, decimal_places=2, default=0
    )
    is_occupied = models.BooleanField("Bandmi?", default=False)
    
    class Meta:
        verbose_name = "Kravat"
        verbose_name_plural = "Kravatlar"
        ordering = ["room", "number"]
        
    def get_active_stay(self):
        # Asosiy bemor sifatida yotgan bo'lsa (faqat bemor)
        return self.stays.filter(status='active', is_companion=False).first()
        
    def get_active_companion_stays(self):
        # Bemor bilan shu kravatni o'zida yotgan yoki alohida ajratilgan kravatda yotgan hamrohlar
        return self.stays.filter(status='active', is_companion=True)
        
    def __str__(self):
        return f"{self.room.name} - {self.number}"


class InpatientStay(Auditable, LockableMixin, BaseModel):
    """Yotib davolanish tarixi."""
    class Status(models.TextChoices):
        ACTIVE = "active", "Yotibdi (Faol)"
        DISCHARGED = "discharged", "Javob berilgan"
        CANCELLED = "cancelled", "Bekor qilingan"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="inpatient_stays", verbose_name="Asosiy qabul")
    bed = models.ForeignKey(Bed, on_delete=models.PROTECT, related_name="stays", verbose_name="Kravat")
    assigned_nurse = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_patients", verbose_name="Mas'ul hamshira")
    is_companion = models.BooleanField("Hamrohmi?", default=False)
    companion_name = models.CharField("Hamroh ismi", max_length=150, blank=True)
    companion_bed = models.ForeignKey(Bed, on_delete=models.SET_NULL, null=True, blank=True, related_name="companion_stays", verbose_name="Hamroh kravati")
    admission_date = models.DateTimeField("Yotqizilgan vaqt", auto_now_add=True)
    discharge_date = models.DateTimeField("Javob berilgan vaqt", null=True, blank=True)
    status = models.CharField("Status", max_length=20, choices=Status.choices, default=Status.ACTIVE)
    total_days = models.IntegerField("Kunlar soni", default=0)
    total_amount = models.DecimalField("Jami summa", max_digits=12, decimal_places=2, default=0)
    daily_price = models.DecimalField("Bemor uchun narx (qotirilgan)", max_digits=12, decimal_places=2, default=0)
    companion_daily_price = models.DecimalField("Hamroh uchun narx (qotirilgan)", max_digits=12, decimal_places=2, default=0)

    # ---- Statsionar turi ----
    class StayType(models.TextChoices):
        STANDARD = "standard", "Oddiy (dori alohida to'lanadi)"
        PACKAGE = "package", "Paketli (dori narxi yotish ichida)"

    stay_type = models.CharField(
        "Statsionar turi", max_length=20, choices=StayType.choices,
        default=StayType.STANDARD,
    )

    # ---- Biriktirilgan hamshiralar ----
    # Hujjatlashtirish hamshirasi: nima berildi/qilindi-qilinmadi hisobotini yuritadi
    doc_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Hujjatlashtirish hamshirasi",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="doc_stays",
    )
    # Ukol/muolaja hamshirasi: bajarilgan muolajalarni o'z hisobotiga kiritadi
    procedure_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Ukol/muolaja hamshirasi",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="procedure_stays",
    )
    # Mas'ul shifokor: Dori yozish faqat unga ko'rinadi
    assigned_doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Mas'ul shifokor",
        on_delete=models.SET_NULL, null=True, blank=True, related_name="doctor_stays",
    )

    # ---- Bemor imzosi (hujjatlar oxirida, ekranda chizib) ----
    patient_signature = models.TextField("Bemor imzosi (rasm, base64)", blank=True)
    signed_at = models.DateTimeField("Imzolangan vaqt", null=True, blank=True)
    
    class Meta:
        verbose_name = "Stasionar yotish"
        verbose_name_plural = "Stasionar yotishlar"
        ordering = ["-admission_date"]

    def __str__(self):
        patient_name = self.companion_name if self.is_companion else self.visit.patient.full_name
        return f"{patient_name} ({self.bed})"


class StayChecklistItem(Auditable, BaseModel):
    """Statsionar hujjatlashtirish hisoboti bandi (shablon tarzda + qo'yiladi).

    Hujjatlashtirish hamshirasi yuritadi: nima berildi/qilindi —
    bajarilgan/bajarilmagani belgilanadi. Analizga yo'naltirilgan bo'lsa,
    operatsiya belgilangan bo'lsa — avtomatik shu ro'yxatga tushadi.
    """

    class Category(models.TextChoices):
        MEDICINE = "medicine", "Dori berish"
        INJECTION = "injection", "Ukol"
        PROCEDURE = "procedure", "Muolaja"
        ANALYSIS = "analysis", "Analiz/Tekshiruv"
        SURGERY = "surgery", "Operatsiya"
        OTHER = "other", "Boshqa"

    stay = models.ForeignKey(
        "InpatientStay", verbose_name="Statsionar yotish", on_delete=models.CASCADE,
        related_name="checklist_items",
    )
    category = models.CharField(
        "Turi", max_length=20, choices=Category.choices, default=Category.OTHER
    )
    title = models.CharField("Nomi/tavsifi", max_length=255)
    # Avtomatik import qilingan manba (ServiceOrder/SurgerySchedule/Dispense id)
    reference_id = models.UUIDField("Manba ID", null=True, blank=True)
    is_done = models.BooleanField("Bajarildimi? (+)", default=False)
    done_at = models.DateTimeField("Bajarilgan vaqt", null=True, blank=True)
    done_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Belgiladi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="checklist_marks",
    )
    note = models.CharField("Izoh", max_length=255, blank=True)

    class Meta:
        verbose_name = "Hujjat bandi (statsionar)"
        verbose_name_plural = "Hujjat bandlari (statsionar)"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.get_category_display()}: {self.title} ({'+' if self.is_done else '-'})"


class ProcedureRecord(Auditable, BaseModel):
    """Ukol/muolaja hamshirasining shaxsiy hisoboti.

    Hamshira o'zi bajargan ukol/muolajalarni, qatnashgan operatsiya va
    analiz olishlarni shu yerga kiritib boradi (hujjatlashtirishdan alohida).
    """

    class Category(models.TextChoices):
        INJECTION = "injection", "Ukol"
        PROCEDURE = "procedure", "Muolaja"
        SURGERY = "surgery", "Operatsiyada qatnashish"
        ANALYSIS = "analysis", "Analiz olish"
        OTHER = "other", "Boshqa"

    stay = models.ForeignKey(
        "InpatientStay", verbose_name="Statsionar yotish", on_delete=models.CASCADE,
        related_name="procedure_records",
    )
    nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Hamshira", on_delete=models.PROTECT,
        related_name="procedure_records",
    )
    category = models.CharField(
        "Turi", max_length=20, choices=Category.choices, default=Category.INJECTION
    )
    name = models.CharField("Nomi (dori/muolaja/operatsiya)", max_length=255)
    notes = models.CharField("Izoh (doza, natija va h.k.)", max_length=255, blank=True)
    performed_at = models.DateTimeField("Bajarilgan vaqt", auto_now_add=True)

    class Meta:
        verbose_name = "Muolaja qaydi (hamshira)"
        verbose_name_plural = "Muolaja qaydlari (hamshira)"
        ordering = ["-performed_at"]

    def __str__(self):
        return f"{self.get_category_display()}: {self.name} — {self.nurse.get_full_name()}"


class BedPriceHistory(BaseModel):
    """Kravat narxining o'zgarish tarixi."""
    bed = models.ForeignKey(Bed, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.DecimalField("Eski bemor narxi", max_digits=12, decimal_places=2, default=0)
    new_price = models.DecimalField("Yangi bemor narxi", max_digits=12, decimal_places=2, default=0)
    old_companion_price = models.DecimalField("Eski hamroh narxi", max_digits=12, decimal_places=2, default=0)
    new_companion_price = models.DecimalField("Yangi hamroh narxi", max_digits=12, decimal_places=2, default=0)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="O'zgartirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="bed_price_changes",
    )

    class Meta:
        verbose_name = "Kravat narxi o'zgarishi"
        verbose_name_plural = "Kravat narxi o'zgarishlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.bed}: {self.old_price} -> {self.new_price}"


# ==========================================
# JARROHLIK (SURGERY) MODELLARI
# ==========================================

class SurgeryType(Auditable, BaseModel):
    """Operatsiya turi va bazaviy narxi."""

    class Kind(models.TextChoices):
        OPEN = "open", "Ochiq operatsiya"
        ENDOSCOPIC = "endoscopic", "Endoskopik operatsiya"

    name = models.CharField("Operatsiya nomi", max_length=200, unique=True)
    kind = models.CharField(
        "Operatsiya usuli", max_length=20, choices=Kind.choices, default=Kind.OPEN,
        help_text="Ochiq: avtoklav anjomlar + belyo. Endoskopik: rastvor anjomlar + belyo.",
    )
    price = models.DecimalField("Narxi", max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField("Faolmi?", default=True)
    
    class Meta:
        verbose_name = "Operatsiya turi"
        verbose_name_plural = "Operatsiya turlari"
        ordering = ["name"]
        
    def __str__(self):
        return f"{self.name} ({self.price} so'm)"

class SurgeryTypePriceHistory(BaseModel):
    """Operatsiya narxi o'zgarish tarixi."""
    surgery_type = models.ForeignKey(SurgeryType, on_delete=models.CASCADE, related_name="price_history")
    old_price = models.DecimalField("Eski narxi", max_digits=12, decimal_places=2, default=0)
    new_price = models.DecimalField("Yangi narxi", max_digits=12, decimal_places=2, default=0)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="O'zgartirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="surgery_price_changes",
    )

    class Meta:
        verbose_name = "Operatsiya narxi o'zgarishi"
        verbose_name_plural = "Operatsiya narxi o'zgarishlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.surgery_type.name}: {self.old_price} -> {self.new_price}"


class SurgicalItem(Auditable, BaseModel):
    """Jarrohlik anjomlari va klapanlar."""
    class Status(models.TextChoices):
        READY = "ready", "Tozalandi / Tayyor"
        IN_USE = "in_use", "Operatsiyada"
        USED = "used", "Ishlatilgan / Ifloslangan"
        
    class Type(models.TextChoices):
        NABOR = "nabor", "Jarrohlik nabori"
        MECHANICAL_VALVE = "mechanical_valve", "Mexanik klapan"
        SYNTHETIC_VALVE = "synthetic_valve", "Sintetik klapan"
        IMPLANT = "implant", "Boshqa implant/uskuna"
        LINEN = "linen", "Belyo (material biks)"
        ENDO_INSTRUMENT = "endo_instrument", "Endoskopik anjom"

    class SterilMethod(models.TextChoices):
        AUTOCLAVE = "autoclave", "Avtoklav"
        SOLUTION = "solution", "Rastvor (eritma) sterilizatsiya"

    name = models.CharField("Nomi", max_length=200)
    item_type = models.CharField("Turi", max_length=50, choices=Type.choices)
    steril_method = models.CharField(
        "Sterilizatsiya usuli", max_length=20, choices=SterilMethod.choices,
        default=SterilMethod.AUTOCLAVE,
        help_text="Belyo va ochiq operatsiya anjomlari — avtoklav; endoskopik anjomlar — rastvor.",
    )
    status = models.CharField("Status", max_length=20, choices=Status.choices, default=Status.USED)
    serial_number = models.CharField("Seriya raqami", max_length=100, blank=True)
    # Asbob hozir qaysi operatsion xonada turibdi (ishlatilmagan/ifloslangan
    # asboblar avtoklavga qaytmaguncha shu xonada qoladi). NULL = sterilizatsiya/ombor.
    current_room = models.ForeignKey(
        "OperatingRoom", verbose_name="Joriy xona", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="current_items",
    )

    class Meta:
        verbose_name = "Jarrohlik uskunasi"
        verbose_name_plural = "Jarrohlik uskunalari"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.get_item_type_display()}) - {self.serial_number}"

    @property
    def use_log(self):
        """Tarix ro'yxati — agar view oldindan yuklagan bo'lsa, o'shani beradi."""
        cached = getattr(self, "full_history", None)
        if cached is not None:
            return cached
        return list(self.history.select_related(
            "changed_by", "patient", "surgeon"
        ).order_by("-used_at"))

    @property
    def last_use(self):
        """Oxirgi marta KIMGA / KIM boshchiligida ishlatilgani.

        Sterilizatsiya xodimi anjomni qo'liga olganda kimdan kelganini
        ko'rishi uchun kerak (epidemiologik nazorat).
        """
        for h in self.use_log:
            if h.patient_snapshot or h.surgery_id:
                return h
        return None

    def save(self, *args, **kwargs):
        # QOIDA: Belyo (material biks) FAQAT avtoklavda sterillanadi —
        # formada xato tanlansa ham majburan avtoklav qilinadi.
        if self.item_type == self.Type.LINEN:
            self.steril_method = self.SterilMethod.AUTOCLAVE
        # Endoskopik anjom esa faqat rastvorda tozalanadi
        elif self.item_type == self.Type.ENDO_INSTRUMENT:
            self.steril_method = self.SterilMethod.SOLUTION
        super().save(*args, **kwargs)


class OperatingRoom(Auditable, BaseModel):
    """Operatsion xona (tizimga kiritiladi va jadvalda tanlanadi)."""

    name = models.CharField("Xona nomi", max_length=120, unique=True)
    description = models.CharField("Izoh", max_length=255, blank=True)
    is_active = models.BooleanField("Faolmi?", default=True)

    class Meta:
        verbose_name = "Operatsion xona"
        verbose_name_plural = "Operatsion xonalar"
        ordering = ["name"]

    def __str__(self):
        return self.name


class SurgerySchedule(Auditable, BaseModel):
    """Operatsiya jadvali va qaydi + jamoa, xona va jarayon bosqichi."""
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Rejalashtirilgan'
        PRE_OP = 'pre_op', 'Tayyorgarlik (Pre-Op)'
        IN_PROGRESS = 'in_progress', 'Jarayonda'
        COMPLETED = 'completed', 'Bajarildi'
        CANCELLED = 'cancelled', 'Bekor qilingan'

    class Stage(models.TextChoices):
        """Operatsiya jarayonining ketma-ket bosqichlari."""
        SCHEDULED = "scheduled", "Rejalashtirilgan"
        PATIENT_PREP = "patient_prep", "1. Bemorni tayyorlash (Bo'lim hamshirasi)"
        ANESTHESIA_EXAM = "anesthesia_exam", "2. Anesteziologik ko'rik / punksiya"
        PREPARATION = "preparation", "3. Operatsiyaga tayyorlash (Xona)"
        OPERATING = "operating", "4. Operatsiya jarayoni (protokol)"
        FINISHED = "finished", "Yakunlandi"

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="surgeries", verbose_name="Asosiy qabul")
    surgery_type = models.ForeignKey(SurgeryType, on_delete=models.PROTECT, related_name="schedules", verbose_name="Operatsiya turi")
    # --- Jamoa (hammasi tanlash / dropdown) ---
    surgeon = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="performed_surgeries", verbose_name="Jarroh")
    assistant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="assisted_surgeries", verbose_name="Operatsion asistent",
    )
    anesthesiologist = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="anesthetized_surgeries", verbose_name="Anesteziolog",
    )
    operating_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="nursed_surgeries", verbose_name="Operatsion hamshira",
    )
    ward_nurse = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ward_nursed_surgeries", verbose_name="Bo'lim hamshirasi",
    )
    operating_room = models.ForeignKey(
        OperatingRoom, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="surgeries", verbose_name="Operatsion xona",
    )
    scheduled_time = models.DateTimeField("Belgilangan vaqt")
    status = models.CharField("Status", max_length=20, choices=Status.choices, default=Status.SCHEDULED)
    stage = models.CharField("Jarayon bosqichi", max_length=20, choices=Stage.choices, default=Stage.SCHEDULED)
    actual_price = models.DecimalField("Qotirilgan narx", max_digits=12, decimal_places=2, default=0)
    notes = models.TextField("Izoh/Xulosa", blank=True)
    items_used = models.ManyToManyField(SurgicalItem, related_name="surgeries", blank=True, verbose_name="Ishlatilgan uskunalar")
    # --- Bosqich ma'lumotlari ---
    class AnesthesiaType(models.TextChoices):
        GENERAL = "general", "Umumiy narkoz (intubatsiya)"
        SPINAL = "spinal", "Spinal / epidural"
        LOCAL = "local", "Mahalliy og'riqsizlantirish"
        SEDATION = "sedation", "Sedatsiya (yuza uyqu)"

    anesthesia_type = models.CharField(
        "Narkoz turi", max_length=20, choices=AnesthesiaType.choices, blank=True,
    )
    anesthesia_exam_note = models.TextField("Anesteziologik ko'rik natijasi", blank=True)
    anesthesia_exam_at = models.DateTimeField("Ko'rik vaqti", null=True, blank=True)
    # --- 1-qadam: Bo'lim hamshirasi ---
    patient_prepared = models.BooleanField("Bemor tayyorlandi", default=False)
    patient_prepared_at = models.DateTimeField("Bemor tayyorlangan vaqti", null=True, blank=True)
    patient_prep_note = models.TextField("Bemor tayyorlash bayoni", blank=True)
    # --- 3-qadam: Operatsion hamshira ---
    preparation_note = models.TextField("Tayyorlash bayoni (xona/asbob)", blank=True)
    preparation_at = models.DateTimeField("Tayyorlash vaqti", null=True, blank=True)
    room_prepared = models.BooleanField("Xona tayyorlandi", default=False)
    started_at = models.DateTimeField("Operatsiya boshlandi", null=True, blank=True)
    finished_at = models.DateTimeField("Operatsiya tugadi", null=True, blank=True)
    postop_recommendations = models.TextField(
        "Operatsiyadan keyingi tavsiyalar (bo'lim hamshirasi)", blank=True,
    )

    class Meta:
        verbose_name = "Operatsiya jadvali"
        verbose_name_plural = "Operatsiya jadvallari"
        ordering = ["scheduled_time"]

    def __str__(self):
        return f"{self.visit.patient.full_name} - {self.surgery_type.name} ({self.scheduled_time.strftime('%Y-%m-%d %H:%M')})"

    @property
    def anesthesia_expense_total(self):
        """Anesteziolog materiallari (yuborilgan) bo'yicha jami xarajat."""
        from decimal import Decimal
        total = Decimal("0")
        req = getattr(self, "anesthesia_request", None)
        if req:
            for it in req.items.all():
                total += it.line_total
        return total

    @property
    def nurse_expense_total(self):
        """Operatsion hamshira ishlatgan anjomlar bo'yicha jami xarajat."""
        from decimal import Decimal
        total = Decimal("0")
        for it in self.nurse_usages.all():
            total += it.line_total
        return total


class SurgeryReport(Auditable, LockableMixin, BaseModel):
    """Operatsiya bayonnomasi — jarayonning barcha mayda detallari."""

    surgery = models.OneToOneField(
        SurgerySchedule, verbose_name="Operatsiya", on_delete=models.CASCADE,
        related_name="report",
    )
    arrival_condition = models.TextField("Bemor ahvoli (qanday keldi)", blank=True)
    performed_actions = models.TextField("Nimalar qilindi (jarayon tavsifi)", blank=True)
    medications = models.TextField("Yozilgan/berilgan dorilar", blank=True)
    injections = models.TextField("Qilingan ukollar", blank=True)
    anesthesia = models.TextField("Narkoz (turi, dozasi, anesteziolog)", blank=True)
    consumables = models.TextField("Sarflangan materiallar (perchatka, bint va h.k.)", blank=True)
    notes = models.TextField("Qo'shimcha izohlar", blank=True)
    filled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="To'ldirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="surgery_reports",
    )

    class Meta:
        verbose_name = "Operatsiya bayonnomasi"
        verbose_name_plural = "Operatsiya bayonnomalari"

    def __str__(self):
        return f"Bayonnoma: {self.surgery}"


class SurgicalItemHistory(BaseModel):
    """Jarrohlik uskunasi tarixi (sterilizatsiya audit izi).

    Epidemiologik nazorat uchun FAQAT "qachon" emas, "KIMGA" va "KIM
    boshchiligidagi operatsiyada" ishlatilgani ham yozib boriladi.
    Operatsiya yoki bemor keyinchalik o'chirilsa ham iz yo'qolmasligi uchun
    nomlar matn ko'rinishida ham saqlanadi (snapshot).
    """
    item = models.ForeignKey(SurgicalItem, on_delete=models.CASCADE, related_name="history")
    surgery = models.ForeignKey(SurgerySchedule, on_delete=models.SET_NULL, null=True, blank=True, related_name="item_history")
    used_at = models.DateTimeField("Vaqti", auto_now_add=True)
    action = models.CharField("Harakat", max_length=100) # e.g. "Tozalandi", "Ifloslandi"
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Kim o'zgartirdi")

    # --- Kimga / kim boshchiligida ishlatilgani ---
    patient = models.ForeignKey(
        "patients.Patient", verbose_name="Bemor", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="surgical_item_uses",
    )
    surgeon = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Jarroh (boshchiligida)",
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="surgical_item_uses",
    )
    patient_snapshot = models.CharField("Bemor (nusxa)", max_length=200, blank=True)
    surgeon_snapshot = models.CharField("Jarroh (nusxa)", max_length=200, blank=True)
    surgery_snapshot = models.CharField("Operatsiya (nusxa)", max_length=200, blank=True)
    room_snapshot = models.CharField("Operatsion xona (nusxa)", max_length=120, blank=True)

    class Meta:
        verbose_name = "Uskuna tarixi"
        verbose_name_plural = "Uskuna tarixlari"
        ordering = ["-used_at"]
        indexes = [
            models.Index(fields=["item", "-used_at"]),
        ]

    def __str__(self):
        who = self.patient_snapshot or "—"
        return f"{self.item.name} → {who} ({self.action})"

    @property
    def has_surgery_context(self):
        """Yozuv operatsiya bilan bog'liqmi (bemor/jarroh ma'lum)."""
        return bool(self.patient_snapshot or self.surgeon_snapshot or self.surgery_snapshot)

    @classmethod
    def log(cls, item, action, user=None, surgery=None):
        """Tarixga yozuv qo'shadi va operatsiya kontekstini avtomatik to'ldiradi.

        Bitta joyda yozilgani uchun barcha oqimlarda (tayyorlash, yakunlash,
        avtoklav, qo'lda o'zgartirish) tarix bir xil to'liqlikda bo'ladi.
        """
        data = {
            "item": item,
            "action": action[:100],
            "changed_by": user if (user is not None and getattr(user, "pk", None)) else None,
            "surgery": surgery,
        }
        if surgery is not None:
            patient = getattr(getattr(surgery, "visit", None), "patient", None)
            surgeon = getattr(surgery, "surgeon", None)
            room = getattr(surgery, "operating_room", None)
            stype = getattr(surgery, "surgery_type", None)
            data["patient"] = patient
            data["surgeon"] = surgeon
            data["patient_snapshot"] = (getattr(patient, "full_name", "") or "")[:200]
            data["surgeon_snapshot"] = (
                (surgeon.get_full_name() or surgeon.username) if surgeon else ""
            )[:200]
            data["surgery_snapshot"] = (getattr(stype, "name", "") or "")[:200]
            data["room_snapshot"] = (getattr(room, "name", "") or "")[:120]
        return cls.objects.create(**data)


class AnesthesiaStock(Auditable, BaseModel):
    """Anesteziologning ALOHIDA ombori (operatsiya sarf-materiallari).

    Bahosi — SOTISH narxi (kelgan narx emas). Qo'lda kiritiladi.
    """

    name = models.CharField("Nomi", max_length=200)
    unit = models.CharField("O'lchov birligi", max_length=30, default="dona")
    quantity = models.DecimalField("Qoldiq soni", max_digits=12, decimal_places=2, default=0)
    selling_price = models.DecimalField("Sotish narxi (birlik)", max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField("Faolmi?", default=True)
    is_psychotropic = models.BooleanField(
        "Psixotrop dori", default=False,
        help_text="Psixotrop/narkotik dori-darmon (faqat Anesteziolog zayavka qiladi).",
    )

    class Meta:
        verbose_name = "Anesteziolog ombori (mahsulot)"
        verbose_name_plural = "Anesteziolog ombori"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} — {self.quantity} {self.unit} ({self.selling_price} so'm)"


class AnesthesiaRequest(Auditable, BaseModel):
    """Operatsiyaga oldindan anesteziologga yuborilgan zayavka (so'rovnoma)."""

    class Status(models.TextChoices):
        REQUESTED = "requested", "Zayavka berildi"
        SENT = "sent", "Yuborildi"

    surgery = models.OneToOneField(
        SurgerySchedule, on_delete=models.CASCADE, related_name="anesthesia_request",
        verbose_name="Operatsiya",
    )
    status = models.CharField("Holati", max_length=20, choices=Status.choices, default=Status.REQUESTED)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="anesthesia_requests_made", verbose_name="So'ragan",
    )
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="anesthesia_requests_sent", verbose_name="Yuborgan (anesteziolog)",
    )
    sent_at = models.DateTimeField("Yuborilgan vaqt", null=True, blank=True)
    
    pre_op_evaluation = models.TextField("Operatsiyagacha ko'rik (Pre-Op)", blank=True)
    preparation_notes = models.TextField("Tayyorgarlik (Preparation)", blank=True)

    class Meta:
        verbose_name = "Anesteziolog zayavkasi"
        verbose_name_plural = "Anesteziolog zayavkalari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Zayavka: {self.surgery} ({self.get_status_display()})"


class AnesthesiaRequestItem(Auditable, BaseModel):
    """Zayavka qatori — qaysi mahsulot, qancha, qanday narxda (snapshot)."""

    request = models.ForeignKey(
        AnesthesiaRequest, on_delete=models.CASCADE, related_name="items",
        verbose_name="Zayavka",
    )
    stock = models.ForeignKey(
        AnesthesiaStock, on_delete=models.PROTECT, related_name="request_items",
        verbose_name="Ombor mahsuloti",
    )
    quantity = models.DecimalField("Soni", max_digits=12, decimal_places=2, default=1)
    price_snapshot = models.DecimalField(
        "Narx (yuborilgandagi)", max_digits=12, decimal_places=2, default=0,
        help_text="Yuborilgan paytdagi sotish narxi — keyin o'zgarsa ham bu o'zgarmaydi.",
    )
    returned_quantity = models.DecimalField(
        "Qaytarilgan soni", max_digits=12, decimal_places=2, default=0,
        help_text="Ishlatilmay omborga qaytarilgan miqdor — hisobdan chiqadi.",
    )
    is_extra = models.BooleanField(
        "Qo'shimcha (operatsiya davomida olingan)", default=False,
        help_text="Boshida olib kelinganidan tashqari, jarayonda qo'shimcha olingan.",
    )

    class Meta:
        verbose_name = "Zayavka qatori"
        verbose_name_plural = "Zayavka qatorlari"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.stock.name} × {self.quantity}"

    @property
    def used_quantity(self):
        """Haqiqatda ishlatilgan miqdor (qaytarilgani ayirilgan)."""
        return (self.quantity or 0) - (self.returned_quantity or 0)

    @property
    def line_total(self):
        return (self.price_snapshot or 0) * self.used_quantity


class SurgeryVitals(Auditable, BaseModel):
    """Intraoperatsion protokol — vaqt bo'yicha bemor ko'rsatkichlari.

    Anesteziolog operatsiya davomida davleniye, puls, SpO2 va qilingan
    ishlarni vaqt bilan yozib boradi.
    """

    surgery = models.ForeignKey(
        SurgerySchedule, on_delete=models.CASCADE, related_name="vitals",
        verbose_name="Operatsiya",
    )
    # Vaqtni anesteziolog O'ZI tanlaydi (default: hozirgi vaqt)
    recorded_at = models.DateTimeField("Vaqt", default=None, null=True, blank=True)
    blood_pressure = models.CharField("Qon bosimi (davleniye)", max_length=20, blank=True)
    pulse = models.PositiveIntegerField("Puls (impuls)", null=True, blank=True)
    spo2 = models.PositiveIntegerField("SpO₂ (%)", null=True, blank=True)
    note = models.CharField("Qilingan ish / dori", max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="surgery_vitals", verbose_name="Kiritdi",
    )

    class Meta:
        verbose_name = "Operatsiya ko'rsatkichi"
        verbose_name_plural = "Operatsiya ko'rsatkichlari (protokol)"
        ordering = ["recorded_at"]

    def __str__(self):
        # recorded_at NULL bo'lishi mumkin (default=None) — formatlash
        # xatolik bermasligi kerak, aks holda audit yozuvi 500 beradi.
        vaqt = f"{self.recorded_at:%H:%M}" if self.recorded_at else "—"
        return f"{self.surgery} — {vaqt} BP:{self.blood_pressure} P:{self.pulse}"


class NurseUsageItem(Auditable, BaseModel):
    """Operatsion hamshira ishlatgan anjom/material va uning xarajati."""

    surgery = models.ForeignKey(
        SurgerySchedule, on_delete=models.CASCADE, related_name="nurse_usages",
        verbose_name="Operatsiya",
    )
    stock = models.ForeignKey(
        'AnesthesiaStock', on_delete=models.PROTECT, related_name="nurse_usages",
        verbose_name="Anesteziolog omboridan anjom", null=True
    )
    quantity = models.DecimalField("Soni", max_digits=12, decimal_places=2, default=1)
    price = models.DecimalField("Narxi (birlik, sotish)", max_digits=12, decimal_places=2, default=0)
    returned_quantity = models.DecimalField(
        "Qaytarilgan soni", max_digits=12, decimal_places=2, default=0,
        help_text="Ishlatilmay omborga qaytarilgan miqdor — hisobdan chiqadi.",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="nurse_usage_items", verbose_name="Kiritdi",
    )

    class Meta:
        verbose_name = "Hamshira ishlatgan anjom"
        verbose_name_plural = "Hamshira ishlatgan anjomlar"
        ordering = ["created_at"]

    @property
    def display_name(self) -> str:
        """Anjom nomi (ombordan tanlangan bo'lsa — o'sha nom)."""
        return self.stock.name if self.stock_id and self.stock else "Anjom"

    @property
    def used_quantity(self):
        """Haqiqatda ishlatilgan miqdor (qaytarilgani ayirilgan)."""
        return (self.quantity or 0) - (self.returned_quantity or 0)

    def __str__(self):
        return f"{self.display_name} × {self.quantity}"

    @property
    def line_total(self):
        return (self.price or 0) * self.used_quantity


class AnesthesiaStockPackage(Auditable, BaseModel):
    """Anesteziolog ombori uchun qadoq iyerarxiyasi.

    Masalan: 1 Blok = 50 Ampula, 1 Pochka = 10 Ampula.
    Asosiy birlik AnesthesiaStock.unit da saqlanadi.
    """

    stock = models.ForeignKey(
        AnesthesiaStock, on_delete=models.CASCADE, related_name="packages",
        verbose_name="Ombor mahsuloti",
    )
    name = models.CharField("O'ram nomi (Blok, Pochka...)", max_length=100)
    quantity_in_base_unit = models.DecimalField(
        "Ichida nechta asosiy birlik bor?", max_digits=10, decimal_places=2,
    )

    class Meta:
        verbose_name = "Anesteziolog ombori qadog'i"
        verbose_name_plural = "Anesteziolog ombori qadoqlari"
        ordering = ["-quantity_in_base_unit"]

    def __str__(self):
        return f"{self.name} (={self.quantity_in_base_unit} {self.stock.unit})"


class RoomLeftover(Auditable, BaseModel):
    """Operatsion xonada qolgan qoldiqlar.

    Operatsiya yakunlanganda ishlatilmay qolgan dori/anjomlar
    bu yerga yoziladi. Keyingi operatsiyalarda shu xona uchun
    ishlatish mumkin (yangi zayavka qilmasdan).
    """

    room = models.ForeignKey(
        OperatingRoom, on_delete=models.CASCADE, related_name="leftovers",
        verbose_name="Operatsion xona",
    )
    stock = models.ForeignKey(
        AnesthesiaStock, on_delete=models.PROTECT, related_name="room_leftovers",
        verbose_name="Mahsulot",
    )
    quantity = models.DecimalField("Qoldiq soni", max_digits=12, decimal_places=2, default=0)
    from_surgery = models.ForeignKey(
        SurgerySchedule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="leftovers_created", verbose_name="Qaysi operatsiyadan qolgan",
    )

    class Meta:
        verbose_name = "Xona qoldig'i"
        verbose_name_plural = "Xona qoldiqlari"
        ordering = ["room", "stock"]

    def __str__(self):
        return f"{self.room} | {self.stock.name} — {self.quantity} {self.stock.unit}"
