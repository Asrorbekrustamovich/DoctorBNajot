from django.core.management.base import BaseCommand
from django.db import connection
from django.apps import apps

class Command(BaseCommand):
    help = 'Hard deletes all patient and clinical data bypassing FK constraints'

    def handle(self, *args, **options):
        apps_to_wipe = ['patients', 'registration', 'clinical', 'billing', 'pharmacy']
        
        tables_to_wipe = []
        for app_label in apps_to_wipe:
            try:
                app_config = apps.get_app_config(app_label)
                for model in app_config.get_models():
                    # Skip specific models if needed (like standard settings)
                    # For clinical apps, we just want to wipe them all.
                    # But wait, DischargeTemplate is created by doctor, maybe keep it?
                    # The user said "bemorlarga doir hamma narsani", "vipska", "amblator", etc.
                    # DischargeTemplate might be fine to keep, but let's just wipe data.
                    if model.__name__ in ['DischargeTemplate', 'ICD10Code', 'Room', 'Bed', 'Service', 'SurgeryType']:
                        continue
                    tables_to_wipe.append(model._meta.db_table)
            except Exception:
                pass
        
        # RoomLeftover, SurgicalItemHistory might be related to inventory, but we'll wipe them if they are in clinical.
        
        with connection.cursor() as cursor:
            # Disable FK checks in SQLite
            cursor.execute("PRAGMA foreign_keys = OFF;")
            
            for table in tables_to_wipe:
                try:
                    cursor.execute(f"DELETE FROM {table};")
                    self.stdout.write(f"Wiped table {table}")
                except Exception as e:
                    self.stdout.write(f"Failed to wipe {table}: {e}")
                    
            cursor.execute("PRAGMA foreign_keys = ON;")
            cursor.execute("VACUUM;")

        self.stdout.write(self.style.SUCCESS("All patient and clinical data permanently wiped from the database."))
