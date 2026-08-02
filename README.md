# Doctor B Najot — Hospital Information System (HIS)

Xususiy klinika uchun enterprise darajadagi tizim. Django 5 + PostgreSQL + DRF + HTMX.

## Arxitektura tamoyillari

- **Service layer**: barcha yozish amallari `services.py` da, o'qish `selectors.py` da. View/serializer model bilan to'g'ridan-to'g'ri ishlamaydi.
- **UUID PK, Soft Delete, Audit**: `apps.core.models.BaseModel` + `apps.audit.mixins.Auditable`.
- **RBAC**: `apps.accounts` — Role + permission sinflari (`HasRole`, `DenyWriteForReadOnlyRoles`, `RoleRequiredMixin`).
- **Price Snapshot**: xizmat/dori narxlari invoice qatorida muzlatiladi (billing modulida).
- **Pul**: faqat `DecimalField`. **Tranzaksiya**: `transaction.atomic` + `ATOMIC_REQUESTS=True`.

## O'rnatish

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
cp .env.example .env             # sozlamalarni to'ldiring
createdb edumed_his              # PostgreSQL bazasi
python manage.py migrate
python manage.py seed_roles      # standart 16 rol
python manage.py createsuperuser
python manage.py runserver
```

Celery (bildirishnomalar/fon ishlari uchun):

```bash
celery -A config worker -l info
celery -A config beat -l info
```

## Testlar

```bash
python manage.py test --settings=config.settings.test
```

## App tuzilmasi

| App | Vazifa |
|---|---|
| `apps.core` | BaseModel (UUID, soft delete, stamping), middleware, exceptions |
| `apps.audit` | AuditLog, Auditable mixin, login/logout auditi |
| `apps.accounts` | User, Role, RBAC permissionlar, seed_roles |

Keyingi modullar: `patients`, `registration`, `admission` (palata/o'rin), `consultation`,
`services_catalog` (narxlar), `laboratory`, `radiology`, `pharmacy` (LOT/FEFO), `warehouse`,
`operations`, `autoclave`, `billing`, `cashier`, `accounting`, `reports`, `notifications`.
