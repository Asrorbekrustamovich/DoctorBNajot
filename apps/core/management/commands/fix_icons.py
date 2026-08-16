from django.core.management.base import BaseCommand
from apps.clinical.models import ServiceCategory

class Command(BaseCommand):
    help = 'Fixes broken icons in ServiceCategory'

    def handle(self, *args, **options):
        # We will just clear the icon field because it got mangled with ????
        ServiceCategory.objects.all().update(icon="")
        self.stdout.write(self.style.SUCCESS("All icons cleared successfully."))
