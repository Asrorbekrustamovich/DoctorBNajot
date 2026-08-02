from apps.clinical.models import Consultation, ServiceOrder, InpatientStay, SurgerySchedule, SurgicalItemHistory
from apps.billing.models import Invoice, Refund
from apps.pharmacy.models import MedicineDispense
from apps.registration.models import Visit

print("Deleting MedicineDispenses...")
MedicineDispense.objects.all().delete()

print("Deleting Invoices and Refunds...")
Invoice.objects.all().delete()
Refund.objects.all().delete()

print("Deleting SurgicalItemHistories and SurgerySchedules...")
SurgicalItemHistory.objects.all().delete()
SurgerySchedule.objects.all().delete()

print("Deleting InpatientStays...")
InpatientStay.objects.all().delete()

print("Deleting Consultations and ServiceOrders...")
Consultation.objects.all().delete()
ServiceOrder.objects.all().delete()

print("Resetting Visit statuses...")
# Reset completed/in_progress visits back to WAITING or ACCEPTED
for v in Visit.objects.all():
    if v.status in ['in_progress', 'completed', 'archived']:
        v.status = 'accepted'
        v.save(update_fields=['status'])

print("All patient-related clinical and billing data cleared successfully.")
