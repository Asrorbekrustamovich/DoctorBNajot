from django.contrib import admin
from .models import MeasurementUnit, Medicine, MedicineBatch, MedicineDispense

@admin.register(MeasurementUnit)
class MeasurementUnitAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name")
    search_fields = ("name", "short_name")

@admin.register(Medicine)
class MedicineAdmin(admin.ModelAdmin):
    list_display = ("name", "unit", "total_available")
    search_fields = ("name",)
    list_filter = ("unit",)

@admin.register(MedicineBatch)
class MedicineBatchAdmin(admin.ModelAdmin):
    list_display = ("medicine", "batch_number", "quantity_received", "quantity_available", "selling_price", "received_date")
    search_fields = ("medicine__name", "batch_number")
    list_filter = ("received_date", "medicine")

@admin.register(MedicineDispense)
class MedicineDispenseAdmin(admin.ModelAdmin):
    list_display = ("visit", "batch", "quantity", "price_at_dispense", "dispensed_at")
    search_fields = ("visit__patient__full_name", "batch__medicine__name")
    list_filter = ("dispensed_at",)
