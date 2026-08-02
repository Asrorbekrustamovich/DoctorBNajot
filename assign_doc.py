from apps.clinical.models import InpatientStay
from django.contrib.auth import get_user_model

User = get_user_model()
doctor = User.objects.filter(role__code='doctor').first()
stay = InpatientStay.objects.filter(status='active').first()

if doctor and stay:
    stay.assigned_doctor = doctor
    stay.save()
    print(f'DOCTOR_ASSIGNED: {doctor.username}')
else:
    print('COULD NOT ASSIGN')
