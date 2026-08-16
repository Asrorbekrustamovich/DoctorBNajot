from django.core.management.base import BaseCommand
from apps.clinical.models import AnesthesiaStock

class Command(BaseCommand):
    help = 'Seeds anesthesia/OR stock with standard supplies'

    def handle(self, *args, **options):
        items = [
            # Dori va suyuqliklar
            {"name": "Fiz. rastvor (Natriy xlorid) 0.9% 500ml", "unit": "flakon", "qty": 100, "price": 5000, "is_psychotropic": False},
            {"name": "Spirt 70% 100ml", "unit": "flakon", "qty": 50, "price": 4000, "is_psychotropic": False},
            {"name": "Betadin eritmasi 10% 1000ml", "unit": "flakon", "qty": 10, "price": 120000, "is_psychotropic": False},
            {"name": "Novokain 0.5% 200ml", "unit": "flakon", "qty": 30, "price": 7000, "is_psychotropic": False},
            {"name": "Lidokain 2% 2ml", "unit": "ampula", "qty": 200, "price": 1500, "is_psychotropic": False},
            
            # Sarf materiallari (Zayavka uchun)
            {"name": "Shprits 5ml", "unit": "dona", "qty": 500, "price": 800, "is_psychotropic": False},
            {"name": "Shprits 10ml", "unit": "dona", "qty": 300, "price": 1000, "is_psychotropic": False},
            {"name": "Shprits 20ml", "unit": "dona", "qty": 200, "price": 1500, "is_psychotropic": False},
            {"name": "Sistema (tomizg'ich)", "unit": "dona", "qty": 400, "price": 2500, "is_psychotropic": False},
            {"name": "Periferik vena kateteri (G18 - yashil)", "unit": "dona", "qty": 100, "price": 3000, "is_psychotropic": False},
            {"name": "Periferik vena kateteri (G20 - pushti)", "unit": "dona", "qty": 100, "price": 3000, "is_psychotropic": False},
            {"name": "Foley kateteri (siydik kateteri) 16CH", "unit": "dona", "qty": 50, "price": 15000, "is_psychotropic": False},
            {"name": "Siydik qabul qilgich (Mochepriyomnik)", "unit": "dona", "qty": 50, "price": 6000, "is_psychotropic": False},
            
            # Bog'lov materiallari
            {"name": "Bint steril 7x14", "unit": "o'ram", "qty": 300, "price": 3500, "is_psychotropic": False},
            {"name": "Doka (Marlya) 10 metr", "unit": "o'ram", "qty": 20, "price": 25000, "is_psychotropic": False},
            {"name": "Paxta tibbiy 100 gr", "unit": "o'ram", "qty": 100, "price": 4000, "is_psychotropic": False},
            {"name": "Leykoplastir 5x500", "unit": "o'ram", "qty": 30, "price": 12000, "is_psychotropic": False},
            {"name": "Steril salfetka 16x14", "unit": "qadoq", "qty": 150, "price": 2000, "is_psychotropic": False},
            
            # Himoya
            {"name": "Xirurgik qo'lqop (Steril perchatka) 7.5", "unit": "juft", "qty": 200, "price": 4500, "is_psychotropic": False},
            {"name": "Xirurgik qo'lqop (Steril perchatka) 8.0", "unit": "juft", "qty": 200, "price": 4500, "is_psychotropic": False},
            {"name": "Tibbiy niqob (maska)", "unit": "dona", "qty": 1000, "price": 500, "is_psychotropic": False},
            {"name": "Baxila", "unit": "juft", "qty": 1000, "price": 300, "is_psychotropic": False},
            
            # Psixotroplar (Anesteziolog ishlatadi)
            {"name": "Fentanil 0.005% 2ml", "unit": "ampula", "qty": 50, "price": 25000, "is_psychotropic": True},
            {"name": "Promedol 1% 1ml", "unit": "ampula", "qty": 50, "price": 20000, "is_psychotropic": True},
            {"name": "Propofol 1% 20ml", "unit": "ampula", "qty": 100, "price": 45000, "is_psychotropic": False},
            {"name": "Mydocalm 1ml", "unit": "ampula", "qty": 100, "price": 8000, "is_psychotropic": False},
        ]
        
        count = 0
        for item in items:
            obj, created = AnesthesiaStock.objects.get_or_create(
                name=item["name"],
                defaults={
                    "unit": item["unit"],
                    "quantity": item["qty"],
                    "selling_price": item["price"],
                    "is_psychotropic": item["is_psychotropic"],
                    "is_active": True
                }
            )
            if created:
                count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Ombor to'ldirildi. {count} ta sarf-material qo'shildi."))
