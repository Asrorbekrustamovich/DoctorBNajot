import django
django.setup()
from django.contrib.auth import get_user_model
from apps.accounts.models import Role

User = get_user_model()

nurse_role = Role.objects.get(code='nurse')
ward_nurse_role = Role.objects.get(code='ward_nurse')

nurses_data = [
    {'username': 'dilnoza', 'first_name': 'Dilnoza', 'last_name': 'Karimova', 'role': nurse_role},
    {'username': 'shahnoza', 'first_name': 'Shahnoza', 'last_name': 'Aliyeva', 'role': ward_nurse_role},
    {'username': 'malika', 'first_name': 'Malika', 'last_name': 'Tursunova', 'role': nurse_role},
    {'username': 'nilufar', 'first_name': 'Nilufar', 'last_name': 'Qosimova', 'role': ward_nurse_role},
]

created_users = []
for data in nurses_data:
    user, created = User.objects.get_or_create(username=data['username'])
    user.first_name = data['first_name']
    user.last_name = data['last_name']
    user.role = data['role']
    user.set_password('1')
    user.save()
    status = "Created" if created else "Updated"
    created_users.append(f"{data['first_name']} {data['last_name']} (Login: {data['username']} | Parol: 1) - {data['role'].name}")
    print(f"{status}: {data['username']}")

print("All done!")
