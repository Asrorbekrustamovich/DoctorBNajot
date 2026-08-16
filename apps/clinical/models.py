"""Klinik jarayonlar va xizmatlar modellar."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.accounts.models import Role
from apps.audit.mixins import Auditable
from apps.core.models import BaseModel, LockableMixin
from apps.registration.models import Visit


class ServiceCategory(Auditable, BaseModel):
    """Tekshiruvlar guruhi — ikki bosqichli daraxt.

    NEGA KERAK: katalog tekis ro'yxat edi va shifokor 100+ tekshiruv ichidan
    kerakligini qidirib topishi kerak bo'lardi. Amalda tekshiruvlar tabiiy
    guruhlarga bo'linadi:

        Laboratoriya
            ├── Klinik tahlillar     (qon ivish vaqti, leykoformula, najas…)
            ├── Biokimyoviy tahlillar
            ├── Gormonlar
            ├── Gepatit
            ├── Koagulogramma
            ├── Markazlashgan serologiya va PZR-diagnostika
            └── Sitologiya
        EKG      ·  UZI  ·  Endoskopiya  ·  Rentgen

    Ikki bosqich yetarli: bundan chuqurroq daraxt interfeysda chalkashtiradi,
    shuning uchun `parent` faqat bitta daraja pastga ruxsat etadi
    (clean() da tekshiriladi).
    """

    class Kind(models.TextChoices):
        LAB = "lab", "Laboratoriya"
        DIAGNOSTIC = "diagnostic", "Instrumental diagnostika"
        OTHER = "other", "Boshqa"

    name = models.CharField("Guruh nomi", max_length=150)
    parent = models.ForeignKey(
        "self", verbose_name="Yuqori guruh", null=True, blank=True,
        on_delete=models.PROTECT, related_name="children",
    )
    kind = models.CharField(
        "Turi", max_length=20, choices=Kind.choices, default=Kind.LAB,
        help_text="Modalda qaysi tugma ostida chiqishini belgilaydi.",
    )
    # Modalda tugma yorlig'i: «+Analiz», «+EKG», «+UZI»…
    button_label = models.CharField(
        "Tugma yozuvi", max_length=50, blank=True,
        help_text="Faqat yuqori darajadagi guruhlarda. Bo'sh bo'lsa nom ishlatiladi.",
    )
    icon = models.CharField("Belgi (emoji)", max_length=8, blank=True)
    sort_order = models.PositiveSmallIntegerField("Tartib", default=100)
    is_active = models.BooleanField("Faolmi?", default=True)

    # --- KIM BAJARADI (guruh darajasidagi standart) ---
    # «Radiolog» degan alohida rol yo'q, shuning uchun kim javobgar ekani
    # superadmin tomonidan shu yerda yoki har bir tekshiruvda belgilanadi.
    # Tekshiruvda ko'rsatilmagan bo'lsa — guruhdagisi ishlatiladi.
    default_role = models.ForeignKey(
        Role, verbose_name="Standart bajaruvchi rol", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="default_service_categories",
    )
    default_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Standart mas'ul xodim",
        null=True, blank=True, on_delete=models.SET_NULL,
        related_name="default_service_categories",
    )
    default_room = models.ForeignKey(
        "AmbulatoryRoom", verbose_name="Standart kabinet", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="default_service_categories",
    )

    class Meta:
        verbose_name = "Tekshiruvlar guruhi"
        verbose_name_plural = "Tekshiruvlar guruhlari"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"], name="uniq_category_name_per_parent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent.name} · {self.name}" if self.parent_id else self.name

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.parent_id and self.parent_id == self.pk:
            raise ValidationError({"parent": "Guruh o'zini o'ziga bo'ysundira olmaydi."})
        if self.parent_id and self.parent.parent_id:
            raise ValidationError(
                {"parent": "Daraxt ikki bosqichdan chuqur bo'lmasligi kerak."}
            )

    @property
    def label(self) -> str:
        return self.button_label or self.name

    @property
    def is_root(self) -> bool:
        return self.parent_id is None


class ServiceCatalog(Auditable, BaseModel):
    """Narxli xizmatlar katalogi (Shifokor ko'rigi, UZI, EKG, Analizlar)."""

    name = models.CharField("Xizmat nomi", max_length=200, unique=True)
    category = models.ForeignKey(
        ServiceCategory, verbose_name="Guruh", null=True, blank=True,
        on_delete=models.PROTECT, related_name="services",
        help_text="Bo'sh bo'lsa tekshiruv tayinlash modalida ko'rinmaydi "
                  "(masalan «Shifokor ko'rigi» kabi xizmatlar).",
    )
    sort_order = models.PositiveSmallIntegerField("Tartib", default=100)
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
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.price} so'm)"

    # ------------------------------------------------------------------
    # KIM BAJARADI — xizmat darajasi, keyin guruh darajasi
    # ------------------------------------------------------------------
    # «Radiolog» degan alohida rol yo'q. Shuning uchun har bir tekshiruvda
    # kim javobgar ekani superadmin tomonidan belgilanadi. Har bir tekshiruvni
    # alohida sozlash zerikarli bo'lgani uchun guruh darajasida standart
    # qiymat beriladi va tekshiruv uni «meros» qilib oladi.

    @property
    def effective_staff(self):
        return self.responsible_staff or (
            self.category.default_staff if self.category_id else None
        )

    @property
    def effective_role(self):
        return self.allowed_role or (
            self.category.default_role if self.category_id else None
        )

    @property
    def effective_room(self):
        return self.room or (self.category.default_room if self.category_id else None)

    def can_be_performed_by(self, user) -> bool:
        """Shu xodim ushbu tekshiruvni bajara oladimi?

        Marshrutlash tartibi (yuqoridan pastga):
          1. Mas'ul xodim tanlangan  -> FAQAT o'sha xodim
          2. Rol tanlangan           -> o'sha roldagi hamma
          3. Hech narsa tanlanmagan  -> mutaxassis roliga ega hamma
        Xizmatda ko'rsatilmagan bo'lsa, guruhdagi standart qiymat ishlaydi.
        """
        if getattr(user, "is_superuser", False):
            return True
        staff = self.effective_staff
        if staff is not None:
            return staff.pk == user.pk
        role = self.effective_role
        if role is not None:
            return role.pk == getattr(user, "role_id", None)
        return True

    @property
    def owner_label(self) -> str:
        """Kim bajaradi — qisqa yozuv (ro'yxatlarda ko'rsatish uchun)."""
        staff = self.effective_staff
        if staff is not None:
            return staff.get_full_name() or staff.username
        role = self.effective_role
        if role is not None:
            return f"{role.name} (bo'lim)"
        return "Biriktirilmagan"

    @property
    def destination(self) -> str:
        """Bemorga ko'rsatiladigan "qayerga borish" matni.

        Masalan: "3-Xona — Karimov Aziz (Radiologiya)".
        Ma'lumot bo'lmasa bo'sh qaytaradi (interfeys o'zi ogohlantiradi).
        """
        parts = []
        room = self.effective_room
        if room is not None:
            parts.append(room.name)
        staff = self.effective_staff
        role = self.effective_role
        if staff is not None:
            parts.append(staff.get_full_name() or staff.username)
        elif role is not None:
            parts.append(role.name)
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
    # Natija qachon yozildi — blankda «Natija sanasi» sifatida chiqadi va
    # shifokor natija yangimi yoki eskimi ekanini ko'radi.
    result_at = models.DateTimeField("Natija vaqti", null=True, blank=True)

    # --- CHAQIRISH (tabloda e'lon qilinadi) ---
    # Tekshiruv tayinlanishi bilan tabloda chiqmaydi — navbatda kutadi.
    # Xodim tayyor bo'lganda «Chaqirish» tugmasini bosadi, shundagina
    # bemor tabloda ko'rinadi va ovoz bilan chaqiriladi.
    called_at = models.DateTimeField("Chaqirilgan vaqt", null=True, blank=True)
    called_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Chaqirdi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="called_service_orders",
    )
    call_count = models.PositiveIntegerField("Necha marta chaqirilgan", default=0)

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

    # ------------------------------------------------------------------
    @property
    def has_result(self) -> bool:
        """Natija yozilganmi — matn yoki ko'rsatkichlar bo'lsa."""
        return bool(self.result_text.strip()) or len(self.result_rows.all()) > 0

    @property
    def is_paid(self) -> bool:
        """Bemor shu tekshiruv uchun to'laganmi.

        HAQIQAT MANBAI — CHEK BANDI, status emas. Status xodim tomonidan
        qo'lda o'zgartirilishi mumkin; pul esa faqat kassada tushadi.
        Ikkalasini chalkashtirsak, to'lanmagan tekshiruv «to'langan» bo'lib
        ko'rinib qoladi.

        Chek bandi topilmasa (masalan narxi 0 bo'lgan xizmat) — to'lov
        talab qilinmaydi.
        """
        item = self.invoice_item
        if item is None:
            return True
        return item.is_paid

    @property
    def invoice_item(self):
        """Shu tekshiruvga tegishli chek bandi."""
        from apps.billing.models import InvoiceItem
        return InvoiceItem.objects.filter(reference_id=self.id).first()

    @property
    def payment_blocked_reason(self) -> str:
        """Tekshiruvni bajarishga to'lov to'sqinlik qilyaptimi.

        Bo'sh satr — to'siq yo'q.
        """
        if (self.price_snapshot or 0) <= 0:
            return ""
        if self.is_paid:
            return ""
        return ("Bemor bu tekshiruv uchun to'lov qilmagan. "
                "Avval registraturada to'lansin.")


class ServiceResultRow(Auditable, BaseModel):
    """Tekshiruv natijasining bitta ko'rsatkichi.

    NEGA ALOHIDA JADVAL: laboratoriya natijasi «matn» emas, jadval —
    ko'rsatkich / qiymat / o'lchov birligi / norma. Erkin matnga yozilsa
    blankni chiroyli chop etib bo'lmaydi va normadan chetlanishni tizim
    ajrata olmaydi. UZI/EKG kabi tavsifiy tekshiruvlarda esa jadval bo'sh
    qoladi va `result_text` ishlatiladi — ikkalasi birga yashaydi.
    """

    order = models.ForeignKey(
        ServiceOrder, verbose_name="Tekshiruv", on_delete=models.CASCADE,
        related_name="result_rows",
    )
    name = models.CharField("Ko'rsatkich", max_length=150)
    value = models.CharField("Natija", max_length=100, blank=True)
    unit = models.CharField("O'lchov birligi", max_length=40, blank=True)
    reference = models.CharField("Norma", max_length=100, blank=True)
    is_abnormal = models.BooleanField(
        "Normadan chetda", default=False,
        help_text="Blankda qalin va rangli ko'rsatiladi.",
    )
    sort_order = models.PositiveSmallIntegerField("Tartib", default=100)

    class Meta:
        verbose_name = "Natija ko'rsatkichi"
        verbose_name_plural = "Natija ko'rsatkichlari"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return f"{self.name}: {self.value} {self.unit}".strip()


class ResultTemplateRow(Auditable, BaseModel):
    """Tekshiruv uchun oldindan tayyor ko'rsatkichlar ro'yxati.

    Laborant «Umumiy qon tahlili» ni ochganda gemoglobin, eritrotsit,
    leykotsit… qatorlari o'zi chiqadi — har safar qo'lda yozilmaydi.
    Norma ham shu yerda saqlanadi va superadmin uni bir joydan boshqaradi.
    """

    service = models.ForeignKey(
        ServiceCatalog, verbose_name="Tekshiruv", on_delete=models.CASCADE,
        related_name="result_template",
    )
    name = models.CharField("Ko'rsatkich", max_length=150)
    unit = models.CharField("O'lchov birligi", max_length=40, blank=True)
    reference = models.CharField("Norma", max_length=100, blank=True)
    sort_order = models.PositiveSmallIntegerField("Tartib", default=100)

    class Meta:
        verbose_name = "Natija shabloni qatori"
        verbose_name_plural = "Natija shabloni qatorlari"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["service", "name"], name="uniq_template_row_per_service",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.service.name} · {self.name}"


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


class SurgerySupplyRequest(Auditable, BaseModel):
    """Operatsion hamshiraning ANESTEZIOLOG OMBORIGA zayavkasi.

    Nega alohida
    ------------
    Ombor bitta — anesteziologniki, lekin so'rovchi va mahsulot turi
    boshqa:

      · anesteziolog PSIXOTROP dorilarni so'raydi (qat'iy hisob);
      · operatsion hamshira oddiy sarf-materialni (shprits, bint, doka).

    Ilgari hamshirada so'rashning umuman yo'li yo'q edi: u anesteziolog
    zayavkasidan yozardi, server esa «psixotrop emas» deb rad etardi.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Tayyorlanmoqda"
        SENT = "sent", "Omborga yuborildi"
        ISSUED = "issued", "Ombor berdi"
        REJECTED = "rejected", "Rad etildi"

    surgery = models.OneToOneField(
        SurgerySchedule, on_delete=models.CASCADE,
        related_name="supply_request", verbose_name="Operatsiya",
    )
    status = models.CharField("Holati", max_length=20,
                              choices=Status.choices, default=Status.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="surgery_supply_requests", verbose_name="So'ragan hamshira",
    )
    sent_at = models.DateTimeField("Yuborilgan vaqt", null=True, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="surgery_supplies_issued", verbose_name="Ombordan bergan",
    )
    issued_at = models.DateTimeField("Berilgan vaqt", null=True, blank=True)
    notes = models.TextField("Izoh", blank=True)

    class Meta:
        verbose_name = "Operatsion hamshira zayavkasi"
        verbose_name_plural = "Operatsion hamshira zayavkalari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Ombor zayavkasi: {self.surgery} ({self.get_status_display()})"

    @property
    def is_editable(self) -> bool:
        """Yuborilgach o'zgartirib bo'lmaydi — ombor shu ro'yxatga qaraydi."""
        return self.status == self.Status.DRAFT


class SurgerySupplyItem(Auditable, BaseModel):
    """Zayavka qatori: qaysi material, qancha so'ralgan va berilgan."""

    request = models.ForeignKey(
        SurgerySupplyRequest, on_delete=models.CASCADE, related_name="items",
        verbose_name="Zayavka",
    )
    stock = models.ForeignKey(
        "AnesthesiaStock", on_delete=models.PROTECT,
        related_name="surgery_supply_items",
        verbose_name="Anesteziolog omboridagi material",
    )
    quantity = models.DecimalField("So'ralgan soni", max_digits=12,
                                   decimal_places=2, default=1)
    issued_quantity = models.DecimalField("Berilgan soni", max_digits=12,
                                          decimal_places=2, default=0)
    note = models.CharField("Izoh", max_length=200, blank=True)

    class Meta:
        verbose_name = "Zayavka qatori"
        verbose_name_plural = "Zayavka qatorlari"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.stock.name} × {self.quantity}"


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


# ==========================================================================
#  STATSIONAR EPIZODI (DMED uslubidagi «murojaat epizodi»)
# --------------------------------------------------------------------------
#  Bemor bir necha marta yotishi mumkin. Har bir yotish — alohida EPIZOD:
#  o'z sababi, o'z tashxislari, o'z dastlabki ko'rigi bilan. Ilgari faqat
#  `InpatientStay` (kravat bilan bog'liq yozuv) bor edi va u yotqizish
#  QARORI bilan yotqizish FAKTINI ajratmasdi. Ambulator shifokor esa
#  bemorni kravat tanlanmasdan oldin yo'llaydi.
#
#  Shuning uchun epizod kravatdan mustaqil yaratiladi:
#      ambulator shifokor epizod ochadi  →  qabulxona hamshirasi ko'radi
#      →  hamshira kravat beradi (InpatientStay)  →  davolash  →  vipiska
# ==========================================================================


class ICD10Code(BaseModel):
    """MKB-10 (XKT-10) tashxis kodlari ma'lumotnomasi.

    Alohida jadval: kodni qo'lda yozdirsak har kim har xil yozadi
    («Z99.9», «z99,9», «Z 99.9») va statistika yig'ilmaydi. Superadmin
    ro'yxatni to'ldiradi, shifokor esa qidirib tanlaydi.
    """

    code = models.CharField("Kod", max_length=10, unique=True, db_index=True)
    name = models.CharField("Tashxis nomi", max_length=300)
    chapter = models.CharField("Bo'lim", max_length=150, blank=True)
    is_active = models.BooleanField("Faolmi?", default=True)

    class Meta:
        verbose_name = "MKB-10 kodi"
        verbose_name_plural = "MKB-10 kodlari"
        ordering = ["code"]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"


class AdmissionEpisode(Auditable, LockableMixin, BaseModel):
    """Statsionarga yotqizish epizodi."""

    class DocumentType(models.TextChoices):
        JSHSHIR = "jshshir", "JSHSHIR"
        BIRTH_CERT = "metrika", "Metrika (tug'ilganlik guvohnomasi)"

    class Purpose(models.TextChoices):
        TREATMENT = "treatment", "Davolash uchun"
        SURGERY = "surgery", "Operatsiya uchun"
        OTHER = "other", "Boshqa"

    class Status(models.TextChoices):
        DRAFT = "draft", "Rasmiylashtirilmoqda"
        SENT = "sent", "Qabulxonaga yuborildi"
        ADMITTED = "admitted", "Yotqizildi"
        DISCHARGED = "discharged", "Vipiska berildi"
        CANCELLED = "cancelled", "Bekor qilindi"

    patient = models.ForeignKey(
        "patients.Patient", verbose_name="Bemor", on_delete=models.PROTECT,
        related_name="episodes",
    )
    visit = models.ForeignKey(
        Visit, verbose_name="Ambulator qabul", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="episodes",
    )
    stay = models.OneToOneField(
        InpatientStay, verbose_name="Yotish yozuvi", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="episode",
    )

    # --- Kim yubordi ---
    # «Qaysi shifokor yuborgani ham bo'lishi kerak» — talab shu.
    referred_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Yo'llagan shifokor",
        null=True, blank=True, on_delete=models.PROTECT,
        related_name="referred_episodes",
    )

    document_type = models.CharField(
        "Hujjat turi", max_length=20, choices=DocumentType.choices,
        default=DocumentType.JSHSHIR,
    )
    document_number = models.CharField("Hujjat raqami", max_length=30, blank=True)

    reason = models.CharField(
        "Murojaat epizodi (kasallik sababi)", max_length=300, blank=True)
    purpose = models.CharField(
        "Yotqizish maqsadi", max_length=20, choices=Purpose.choices,
        default=Purpose.TREATMENT,
    )
    purpose_note = models.CharField("Maqsad izohi", max_length=255, blank=True)

    # Bemorni birlamchi ko'rik bilan ham, ko'riksiz ham yotqizish mumkin —
    # shoshilinch holatda ko'rikni keyin yozadilar.
    with_primary_exam = models.BooleanField("Birlamchi ko'rik bilan", default=True)

    department = models.CharField("Bo'lim", max_length=150, blank=True)
    room = models.ForeignKey(
        Room, verbose_name="Palata", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="episodes",
    )

    # --- Dastlabki ko'rik (statsionarda yoziladi) ---
    complaints = models.TextField("Shikoyatlar", blank=True)
    anamnesis_morbi = models.TextField("Kasallik tarixi (Anamnesis morbi)", blank=True)
    anamnesis_vitae = models.TextField("Hayot anamnezi (Anamnesis vitae)", blank=True)
    status_localis = models.TextField("Mahalliy holat (Status localis)", blank=True)
    epid_anamnesis = models.TextField("Epidemiologik anamnez", blank=True)
    status_praesens = models.TextField("Obyektiv holat (Status praesens)", blank=True)
    allergo_anamnesis = models.TextField("Allergoanamnez", blank=True)
    neuro_status = models.TextField("Nevrologik holati", blank=True)
    clinical_diagnosis = models.TextField("Klinik tashxis", blank=True)

    status = models.CharField(
        "Holati", max_length=20, choices=Status.choices,
        default=Status.DRAFT, db_index=True,
    )
    sent_at = models.DateTimeField("Qabulxonaga yuborilgan", null=True, blank=True)
    cancel_reason = models.CharField("Bekor qilish sababi", max_length=255, blank=True)

    # VIPISKAGA QO'SHILADIGAN TEKSHIRUVLAR.
    #
    # Shifokor bemorning tekshiruv tarixini ko'rib turib, qaysilari
    # vipiskaga kirishini shu yerda belgilaydi — vipiska yozilishini
    # kutmasdan, bemor hali yotgan paytda.
    #
    # NULL va bo'sh ro'yxat BOSHQA-BOSHQA ma'noni bildiradi:
    #   None  — shifokor hali tanlamagan → shu epizodникilar avtomatik
    #   []    — shifokor ataylab hammasini olib tashlagan → hech biri
    # Ikkalasini bir xil qilsak, «hammasini bekor qilish» ishlamay,
    # belgilar o'z-o'zidan qaytib kelaverardi.
    selected_order_ids = models.JSONField(
        "Vipiskaga tanlangan tekshiruvlar", null=True, blank=True, default=None,
    )

    class Meta:
        verbose_name = "Statsionar epizodi"
        verbose_name_plural = "Statsionar epizodlari"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["patient", "status"])]

    def __str__(self) -> str:
        return f"{self.patient.full_name} — {self.get_purpose_display()} ({self.created_at:%d.%m.%Y})"

    @property
    def needs_anesthesiologist(self) -> bool:
        """Operatsiya uchun yotqizilsa, istoriyaga anesteziolog qo'shiladi."""
        return self.purpose == self.Purpose.SURGERY

    @property
    def is_open(self) -> bool:
        return self.status in (self.Status.DRAFT, self.Status.SENT, self.Status.ADMITTED)

    @property
    def patient_left(self) -> bool:
        """Bemor palatadan chiqib bo'lganmi.

        Statsionardan javob berish (kravatni bo'shatish) va vipiska
        yozish — IKKI ALOHIDA amal. Shifokor javob berganda yotish
        yopiladi, lekin epizod «yotibdi» holatida qolaveradi: vipiska
        hali yozilmagan.

        Natijada ro'yxatda bemor «Yotibdi» deb turaverardi — kravati
        bo'shatilgan, o'zi uyiga ketgan bo'lsa ham.
        """
        return bool(
            self.stay_id
            and self.stay
            and self.stay.status == InpatientStay.Status.DISCHARGED
        )

    @property
    def display_status(self) -> str:
        """Ro'yxatlarda ko'rsatiladigan HAQIQIY holat.

        `get_status_display()` faqat epizod maydonini o'qiydi va
        yotishdan xabari yo'q.
        """
        if self.status == self.Status.ADMITTED and self.patient_left:
            return "Chiqdi — vipiska kutilmoqda"
        return self.get_status_display()

    @property
    def main_diagnosis(self):
        return self.diagnoses.filter(kind=EpisodeDiagnosis.Kind.MAIN).first()


class EpisodeDiagnosis(Auditable, BaseModel):
    """Epizoddagi tashxis. Bitta epizodda bir nechta bo'lishi mumkin."""

    class Stage(models.TextChoices):
        PRELIMINARY = "preliminary", "Dastlabki tashxis"
        FINAL = "final", "Yakuniy tashxis"

    class Kind(models.TextChoices):
        MAIN = "main", "Asosiy"
        CONCOMITANT = "concomitant", "Hamroh"
        COMPLICATION = "complication", "Asorat"
        BACKGROUND = "background", "Fon"
        COMPETING = "competing", "Raqobatdosh"

    class Course(models.TextChoices):
        UNSPECIFIED = "unspecified", "Belgilanmagan"
        ACUTE = "acute", "O'tkir"
        SUBACUTE = "subacute", "O'tkir osti"
        FIRST_CHRONIC = "first_chronic", "Hayotda birinchi marta surunkali kasallik aniqlandi"
        CHRONIC = "chronic", "Surunkali"

    episode = models.ForeignKey(
        AdmissionEpisode, verbose_name="Epizod", on_delete=models.CASCADE,
        related_name="diagnoses",
    )
    icd = models.ForeignKey(
        ICD10Code, verbose_name="MKB-10", null=True, blank=True,
        on_delete=models.PROTECT, related_name="diagnoses",
    )
    # Ma'lumotnomada topilmagan holat uchun — lekin kod bo'lsa `icd` afzal.
    free_text = models.CharField("Tashxis (matn)", max_length=300, blank=True)

    stage = models.CharField(
        "Tashxis turi", max_length=20, choices=Stage.choices, default=Stage.PRELIMINARY)
    kind = models.CharField(
        "Xili", max_length=20, choices=Kind.choices, default=Kind.MAIN)
    course = models.CharField(
        "Kasallik kechishi", max_length=20, choices=Course.choices,
        default=Course.UNSPECIFIED)
    note = models.CharField("Izoh", max_length=255, blank=True)

    class Meta:
        verbose_name = "Epizod tashxisi"
        verbose_name_plural = "Epizod tashxislari"
        ordering = ["kind", "created_at"]

    def __str__(self) -> str:
        return f"{self.label} ({self.get_kind_display()})"

    @property
    def label(self) -> str:
        if self.icd_id:
            return f"{self.icd.code} — {self.icd.name}"
        return self.free_text or "—"


class DischargeSummary(Auditable, LockableMixin, BaseModel):
    """VIPISKA — statsionar epizodining yakuniy hujjati.

    Bemor 5 kun yotib, hamma xizmatdan foydalangan bo'lsa, chiqishda unga
    bitta hujjat beriladi: qachon kelgan, nima bilan kelgan, nima
    qilingan, qanday chiqqan. Ilgari tizimda faqat «javob berildi» degan
    status bor edi — hujjatning o'zi shakllanmasdi.

    Hujjat tarkibining KATTA QISMI AVTOMATIK yig'iladi (tashxislar,
    tekshiruv natijalari, dorilar, operatsiya, yotgan kunlar). Shifokor
    faqat xulosa qismini yozadi: davolash natijasi va tavsiyalar.
    Shu sababli vipiska tayyorlash bir necha daqiqa vaqt oladi, soatlar
    emas.
    """

    class Outcome(models.TextChoices):
        RECOVERED = "recovered", "Sog'aydi"
        IMPROVED = "improved", "Yaxshilandi"
        UNCHANGED = "unchanged", "O'zgarishsiz"
        WORSENED = "worsened", "Yomonlashdi"
        TRANSFERRED = "transferred", "Boshqa muassasaga o'tkazildi"
        DIED = "died", "Vafot etdi"

    class WorkCapacity(models.TextChoices):
        FIT = "fit", "Mehnatga layoqatli"
        SICK_LEAVE = "sick_leave", "Kasallik varaqasi berildi"
        LIGHT = "light", "Yengil mehnatga tavsiya"
        UNFIT = "unfit", "Mehnatga layoqatsiz"
        NOT_APPLICABLE = "n_a", "Tegishli emas"

    episode = models.OneToOneField(
        AdmissionEpisode, verbose_name="Epizod", on_delete=models.CASCADE,
        related_name="discharge",
    )
    discharged_at = models.DateTimeField("Chiqarilgan vaqt", default=timezone.now)
    discharged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Vipiskani yozgan shifokor",
        null=True, blank=True, on_delete=models.PROTECT,
        related_name="discharge_summaries",
    )

    outcome = models.CharField(
        "Davolash natijasi", max_length=20, choices=Outcome.choices,
        default=Outcome.IMPROVED,
    )
    work_capacity = models.CharField(
        "Mehnat qobiliyati", max_length=20, choices=WorkCapacity.choices,
        default=WorkCapacity.NOT_APPLICABLE,
    )
    sick_leave_from = models.DateField("Kasallik varaqasi (dan)", null=True, blank=True)
    sick_leave_to = models.DateField("Kasallik varaqasi (gacha)", null=True, blank=True)

    treatment_given = models.TextField("O'tkazilgan davolash", blank=True)
    condition_at_discharge = models.TextField("Chiqishdagi holati", blank=True)
    recommendations = models.TextField("Tavsiyalar", blank=True)
    follow_up = models.CharField("Nazorat ko'rigi", max_length=255, blank=True)
    surgery_text = models.TextField("Operatsiya bayoni", blank=True)
    selected_order_ids = models.JSONField("Tanlangan tekshiruvlar", default=list, blank=True)
    selected_procedure_ids = models.JSONField("Tanlangan muolajalar", default=list, blank=True)
    # OPERATSIYALAR — vipiskaga qaysi biri kirishini shifokor belgilaydi.
    # Bemor bir yotishda ikki marta operatsiya bo'lishi mumkin, ikkalasi
    # ham hujjatga kerak bo'lmasligi mumkin.
    selected_surgery_ids = models.JSONField(
        "Tanlangan operatsiyalar", default=list, blank=True)

    # Bemor bir necha marta yotgan bo'lishi mumkin. Surunkali kasallik
    # oldingi yotishda qo'yilgan bo'lsa ham vipiskada ko'rsatilishi kerak,
    # lekin HAMMASINI qo'shsak hujjat cho'zilib ketadi. Shuning uchun
    # shifokor ptechka bilan tanlaydi va tanlovi shu yerda saqlanadi.
    selected_diagnosis_ids = models.JSONField(
        "Tanlangan tashxislar", default=list, blank=True)

    # Tanlangan hisobot/tekshiruvning VIPISKADAGI matni.
    #
    # Kalit — element id'si, qiymat — shifokor qisqartirgan matn. Asl
    # hisobot O'ZGARMAYDI: laboratoriya yozgan natija tibbiy hujjat va
    # unga tegib bo'lmaydi. Bu yerda faqat vipiskaga tushadigan nusxa
    # saqlanadi.
    item_texts = models.JSONField(
        "Vipiskadagi matnlar (element bo'yicha)", default=dict, blank=True)

    class Meta:
        verbose_name = "Vipiska"
        verbose_name_plural = "Vipiskalar"
        ordering = ["-discharged_at"]

    def __str__(self) -> str:
        return f"Vipiska — {self.episode.patient.full_name} ({self.discharged_at:%d.%m.%Y})"

    @property
    def admitted_at(self):
        """Qachon yotqizilgan. Kravat berilgan bo'lsa — o'sha vaqt."""
        stay = self.episode.stay
        return stay.admission_date if stay else self.episode.created_at

    @property
    def bed_days(self) -> int:
        """Yotgan kunlar soni. Bir kun yotgan ham 1 kun deb hisoblanadi."""
        start, end = self.admitted_at, self.discharged_at
        if not start or not end:
            return 0
        return max(1, (end.date() - start.date()).days)


class DischargeTemplate(Auditable, BaseModel):
    """Shifokorning vipiska uchun qayta ishlatiladigan shabloni."""
    doctor = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Shifokor",
        on_delete=models.CASCADE, related_name="discharge_templates",
    )
    name = models.CharField("Shablon nomi", max_length=255)
    content = models.TextField("Shablon matni")

    class Meta:
        verbose_name = "Vipiska shabloni"
        verbose_name_plural = "Vipiska shablonlari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.doctor.get_full_name()})"
