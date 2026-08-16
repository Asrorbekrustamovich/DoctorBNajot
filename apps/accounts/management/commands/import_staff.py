
import json
import os
from django.core.management.base import BaseCommand
from apps.accounts.models import User, Role
from apps.clinical.models import Room

class Command(BaseCommand):
    help = 'Xodimlar va shifokorlarni JSON fayldan import qilish'

    def handle(self, *args, **options):
        file_path = 'transfer_staff.json'
        if not os.path.exists(file_path):
            self.stdout.write(self.style.ERROR(f'Fayl topilmadi: {file_path}'))
            return
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        count_created = 0
        count_updated = 0
        
        for item in data:
            u, created = User.objects.get_or_create(username=item['username'])
            
            # Asosiy maydonlar
            if created or u.password != item['password']:
                u.password = item['password']  # Parol xesh sifatida keladi
            u.first_name = item['first_name']
            u.last_name = item['last_name']
            u.is_superuser = item['is_superuser']
            u.is_staff = item['is_staff']
            u.specialty = item['specialty']
            if item['consultation_fee']:
                u.consultation_fee = item['consultation_fee']
            u.is_ambulatory = item.get('is_ambulatory', False)
            
            # Asosiy rol
            if item['role_code']:
                r, _ = Role.objects.get_or_create(code=item['role_code'])
                u.role = r
                
            # Xona (agar bo\'lsa)
            if item['room']:
                room, _ = Room.objects.get_or_create(name=item['room'])
                u.room = room
                
            u.save()
            
            # Qo\'shimcha rollar
            if hasattr(u, 'extra_roles') and item['extra_roles']:
                u.extra_roles.clear()
                for rc in item['extra_roles']:
                    r, _ = Role.objects.get_or_create(code=rc)
                    u.extra_roles.add(r)
                    
            if created:
                count_created += 1
            else:
                count_updated += 1
                
        self.stdout.write(self.style.SUCCESS(f'Muvaffaqiyatli: {count_created} ta yangi qo\'shildi, {count_updated} ta yangilandi.'))
