from django.db import models
from django.conf import settings
from apps.core.models import BaseModel
from apps.registration.models import Visit

class MeasurementUnit(BaseModel):
    """O'lchov birligi (Masalan: Ampula, Flakon, Quti, Dona, ml, mg)"""
    name = models.CharField("O'lchov birligi", max_length=50, unique=True)
    short_name = models.CharField("Qisqartma", max_length=20, blank=True)

    class Meta:
        verbose_name = "O'lchov birligi"
        verbose_name_plural = "O'lchov birliklari"
        ordering = ["name"]

    def __str__(self):
        return self.name

class StorageLocation(BaseModel):
    """Klinika ichidagi omborlar (Asosiy, Anesteziologiya)"""
    class Type(models.TextChoices):
        MAIN = "main", "Asosiy Ombor"
        ANESTHESIA = "anesthesia", "Anesteziologiya Ombori"
        DEPARTMENT = "department", "Bo'lim Ombori"
    
    name = models.CharField("Nomi", max_length=100)
    location_type = models.CharField("Turi", max_length=20, choices=Type.choices, default=Type.MAIN)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Ombor/Joylashuv"
        verbose_name_plural = "Omborlar"

    def __str__(self):
        return f"{self.name} ({self.get_location_type_display()})"

class Medicine(BaseModel):
    """Dori-darmon yoki tibbiy vosita (katalog)"""
    name = models.CharField("Nomi", max_length=200)
    unit = models.ForeignKey(MeasurementUnit, on_delete=models.PROTECT, related_name="medicines", verbose_name="O'lchov birligi (Asosiy)")
    description = models.TextField("Tavsif", blank=True)

    class Meta:
        verbose_name = "Dori-darmon"
        verbose_name_plural = "Dori-darmonlar"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.unit.short_name or self.unit.name})"

    @property
    def total_available(self):
        """Asosiy ombordagi (yoki barcha) qoldiq. Hozircha orqaga moslik uchun barchasi."""
        return sum(batch.quantity_available for batch in self.batches.filter(quantity_available__gt=0))
        
    def total_available_in(self, location=None):
        qs = self.batches.filter(quantity_available__gt=0)
        if location:
            qs = qs.filter(location=location)
        return sum(batch.quantity_available for batch in qs)
        
    def format_quantity(self, quantity):
        """Kiritilgan asosiy miqdorni (masalan: 54) o'ramlarga bo'lib matnga aylantiradi (Masalan: 1 Blok, 4 Dona)."""
        if quantity is None or quantity <= 0:
            return f"0 {self.unit.short_name or self.unit.name}"
            
        packages = list(self.packages.all().order_by('-quantity_in_base_unit'))
        if not packages:
            return f"{quantity:g} {self.unit.short_name or self.unit.name}"
            
        result = []
        remaining = quantity
        
        for pkg in packages:
            count = int(remaining // pkg.quantity_in_base_unit)
            if count > 0:
                result.append(f"{count} {pkg.name}")
                remaining = remaining % pkg.quantity_in_base_unit
                
        if remaining > 0:
            result.append(f"{remaining:g} {self.unit.short_name or self.unit.name}")
            
        return ", ".join(result)
        
    @property
    def formatted_total_available(self):
        return self.format_quantity(self.total_available)


class MedicinePackaging(BaseModel):
    """Dori qadoqlari iyerarxiyasi (Masalan: 1 Blok = 50 Dona, 1 Pochka = 5 Dona)"""
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name="packages", verbose_name="Dori-darmon")
    name = models.CharField("O'ram nomi (Pochka, Blok...)", max_length=100)
    quantity_in_base_unit = models.DecimalField("Ichida nechta asosiy birlik bor?", max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "Dori qadog'i"
        verbose_name_plural = "Dori qadoqlari"
        ordering = ["-quantity_in_base_unit"]

    def __str__(self):
        return f"{self.name} (={self.quantity_in_base_unit} {self.medicine.unit.short_name or self.medicine.unit.name})"


class MedicineBatch(BaseModel):
    """
    Dorining bitta partiyasi (Kirim qilinganda).
    Har bir kirimning o'zining narxi va qoldig'i bo'ladi.
    """
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, related_name="batches", verbose_name="Dori-darmon")
    location = models.ForeignKey(StorageLocation, on_delete=models.CASCADE, related_name="batches", null=True, blank=True, verbose_name="Ombor")
    batch_number = models.CharField("Partiya raqami", max_length=100, blank=True, help_text="Avto-generatsiya qilinishi mumkin yoki zavod raqami")
    
    quantity_received = models.DecimalField("Kirim qilingan miqdor", max_digits=12, decimal_places=2)
    quantity_available = models.DecimalField("Qoldiq miqdor", max_digits=12, decimal_places=2)
    
    selling_price = models.DecimalField("Sotish narxi (shu partiya uchun)", max_digits=12, decimal_places=2)
    purchase_price = models.DecimalField("Kelish narxi", max_digits=12, decimal_places=2, default=0)
    
    expiry_date = models.DateField("Yaroqlilik muddati", null=True, blank=True)
    received_date = models.DateTimeField("Kirim qilingan vaqt", auto_now_add=True)
    
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="received_batches", verbose_name="Kirim qiluvchi")

    class Meta:
        verbose_name = "Dori kirimi (Partiya)"
        verbose_name_plural = "Dori kirimlari (Partiyalar)"
        ordering = ["received_date"]

    def __str__(self):
        return f"{self.medicine.name} | Qoldiq: {self.formatted_quantity_available} | Narx: {self.selling_price}"

    @property
    def formatted_quantity_available(self):
        return self.medicine.format_quantity(self.quantity_available)

    def save(self, *args, **kwargs):
        if self._state.adding and self.quantity_available is None:
            self.quantity_available = self.quantity_received
        super().save(*args, **kwargs)

class MedicineDispense(BaseModel):
    """
    Bemorga dori ishlatilishi (Chiqim yoki Tayinlov).
    """
    class Status(models.TextChoices):
        PENDING = 'pending', 'Topshirilmadi'
        DELIVERED = 'delivered', 'Topshirildi'
        CANCELLED = 'cancelled', 'Bekor qilindi'

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name="dispensed_medicines", verbose_name="Bemor qabuli")
    batch = models.ForeignKey(MedicineBatch, on_delete=models.PROTECT, related_name="dispenses", verbose_name="Dori partiyasi (Kirim)")
    
    status = models.CharField("Holat", max_length=20, choices=Status.choices, default=Status.PENDING)
    
    quantity = models.DecimalField("Ishlatilgan miqdor", max_digits=12, decimal_places=2)
    price_at_dispense = models.DecimalField("Berilgan paytdagi narxi", max_digits=12, decimal_places=2, help_text="Tarix uchun partiya narxining nushasi")
    
    dispensed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="dispensed_medicines", verbose_name="Beruvchi xodim")
    dispensed_at = models.DateTimeField("Berilgan vaqt", auto_now_add=True)

    # Dori qaytarilishi (otmen yoki Sklad bekor qilganda)
    is_returned = models.BooleanField("Qaytarilganmi?", default=False)
    returned_at = models.DateTimeField("Qaytarilgan vaqt", null=True, blank=True)
    returned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="returned_dispenses", verbose_name="Qaytarib oldi")
    return_reason = models.CharField("Qaytarish sababi", max_length=255, blank=True)

    # Paketli statsionar dorisi
    is_package = models.BooleanField("Paket ichida (chekka tushmaydi)", default=False)

    class Meta:
        verbose_name = "Dori tayinlovi (Bemorga)"
        verbose_name_plural = "Dori tayinlovlari"
        ordering = ["-dispensed_at"]

    def __str__(self):
        return f"{self.visit.patient.full_name} - {self.batch.medicine.name} (x{self.quantity})"


class MedicinePriceHistory(BaseModel):
    """
    Dori partiyasining (Kirimning) sotish narxi o'zgarish tarixi.
    """
    batch = models.ForeignKey(MedicineBatch, on_delete=models.CASCADE, related_name="price_history", verbose_name="Dori partiyasi")
    old_price = models.DecimalField("Eski narx", max_digits=12, decimal_places=2)
    new_price = models.DecimalField("Yangi narx", max_digits=12, decimal_places=2)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="O'zgartirgan xodim")
    changed_at = models.DateTimeField("O'zgartirilgan vaqt", auto_now_add=True)

    class Meta:
        verbose_name = "Narx o'zgarish tarixi"
        verbose_name_plural = "Narx o'zgarishlari"
        ordering = ["-changed_at"]

    def __str__(self):
        return f"{self.batch.medicine.name} | {self.old_price} -> {self.new_price}"

class MedicineRequest(BaseModel):
    """Zayavka (Talabnoma) - Ombordan omborga dori so'rash yoki ko'chirish"""
    class Status(models.TextChoices):
        DRAFT = "draft", "Qoralama"
        PENDING = "pending", "Kutilmoqda"
        APPROVED = "approved", "Tasdiqlandi (Yuborildi)"
        REJECTED = "rejected", "Rad etildi"
        
    from_location = models.ForeignKey(StorageLocation, on_delete=models.CASCADE, related_name="outgoing_requests", verbose_name="Qaysi ombordan")
    to_location = models.ForeignKey(StorageLocation, on_delete=models.CASCADE, related_name="incoming_requests", verbose_name="Qaysi omborga")
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="medicine_requests", verbose_name="Zayavka beruvchi")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_medicine_requests", verbose_name="Tasdiqlovchi")
    status = models.CharField("Holati", max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField("Izoh", blank=True)

    class Meta:
        verbose_name = "Dori Zayavkasi"
        verbose_name_plural = "Dori Zayavkalari"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Zayavka #{self.id} | {self.from_location.name} -> {self.to_location.name}"

class MedicineRequestItem(BaseModel):
    """Zayavka ichidagi ma'lum bir dori va uning miqdori"""
    request = models.ForeignKey(MedicineRequest, on_delete=models.CASCADE, related_name="items")
    medicine = models.ForeignKey(Medicine, on_delete=models.CASCADE, verbose_name="Dori-darmon")
    quantity = models.DecimalField("So'ralgan miqdor", max_digits=12, decimal_places=2)
    approved_quantity = models.DecimalField("Tasdiqlangan miqdor", max_digits=12, decimal_places=2, default=0)

    class Meta:
        verbose_name = "Zayavka bandi"
        verbose_name_plural = "Zayavka bandlari"

    def __str__(self):
        return f"{self.medicine.name} - {self.quantity}"
