from django.core.management.base import BaseCommand
from apps.clinical.models import SurgicalItem

class Command(BaseCommand):
    help = 'Seeds surgical items (naborlar) into the database'

    def handle(self, *args, **options):
        items = [
            # Naborlar
            {"name": "Umumiy jarrohlik nabori (Katta)", "item_type": "nabor", "status": "ready", "serial_number": "N-001"},
            {"name": "Umumiy jarrohlik nabori (Kichik)", "item_type": "nabor", "status": "ready", "serial_number": "N-002"},
            {"name": "Ginekologik nabor", "item_type": "nabor", "status": "ready", "serial_number": "N-003"},
            {"name": "LOR nabor", "item_type": "nabor", "status": "ready", "serial_number": "N-004"},
            {"name": "Tomir jarrohligi nabori", "item_type": "nabor", "status": "ready", "serial_number": "N-005"},
            {"name": "Travmatologiya nabori", "item_type": "nabor", "status": "ready", "serial_number": "N-006"},
            
            # Belyolar (Material)
            {"name": "Katta operatsion belyo (Biks)", "item_type": "linen", "status": "ready", "serial_number": "L-001"},
            {"name": "Kichik operatsion belyo (Biks)", "item_type": "linen", "status": "ready", "serial_number": "L-002"},
            {"name": "Xalatlar to'plami (Biks)", "item_type": "linen", "status": "ready", "serial_number": "L-003"},
            
            # Endoskopik
            {"name": "Laparoskopik nabor", "item_type": "endo_instrument", "status": "ready", "serial_number": "E-001"},
        ]
        
        count = 0
        for item in items:
            obj, created = SurgicalItem.objects.get_or_create(
                serial_number=item["serial_number"],
                defaults={
                    "name": item["name"],
                    "item_type": item["item_type"],
                    "status": item["status"],
                }
            )
            if created:
                count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Baza to'ldirildi. {count} ta steril anjom qo'shildi."))
