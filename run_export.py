
import json
from apps.accounts.models import User

data = []
for u in User.objects.all():
    if u.username == 'admin': continue
    roles = [r.code for r in getattr(u, 'extra_roles').all()] if hasattr(u, 'extra_roles') else []
    data.append({
        'username': u.username,
        'password': u.password,
        'first_name': u.first_name,
        'last_name': u.last_name,
        'is_superuser': u.is_superuser,
        'is_staff': u.is_staff,
        'role_code': u.role.code if getattr(u, 'role', None) else None,
        'extra_roles': roles,
        'specialty': u.specialty,
        'room': u.room.name if getattr(u, 'room', None) else None,
        'consultation_fee': str(u.consultation_fee) if getattr(u, 'consultation_fee', None) else None,
        'is_ambulatory': getattr(u, 'is_ambulatory', False)
    })

with open('transfer_staff.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print('Muvaffaqiyatli:', len(data), 'ta xodim eksport qilindi.')
