import django
django.setup()
from apps.registration.models import Visit, Appointment
from apps.billing.models import Invoice

print("Deleting all visits, appointments and related items...")
Invoice.objects.all().delete()
Visit.objects.all().delete()
Appointment.objects.all().delete()

print("Barcha qabullar va navbatlar o'chirildi!")
