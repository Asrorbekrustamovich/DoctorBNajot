"""Ma'lumotlar bazasi va fayllarning zaxira nusxasi.

Ishlatilishi:
    python manage.py backup_db                 # oddiy zaxira
    python manage.py backup_db --keep 60       # oxirgi 60 tasini saqlash
    python manage.py backup_db --no-media      # faqat baza (rasmlarsiz)

Natija: backups/edumed_backup_YYYYmmdd_HHMMSS.zip
Ichida: data.json (butun baza) + media/ (yuklangan fayllar) + info.txt

Baza turi (SQLite yoki PostgreSQL) ahamiyatsiz — zaxira universal JSON
formatida, shuning uchun SQLite -> PostgreSQL ko'chirish uchun ham ishlaydi.
"""
from __future__ import annotations

import gzip
import io
import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

# Bu jadvallar zaxiraga kirmaydi — ular migratsiyada qayta yaratiladi
# yoki vaqtinchalik (sessiyalar).
EXCLUDED = [
    "contenttypes",
    "auth.permission",
    "sessions.session",
    "admin.logentry",
]


class Command(BaseCommand):
    help = "Bazani va media fayllarni zaxiralaydi (backups/ papkasiga)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--keep", type=int, default=30,
                            help="Nechta oxirgi zaxira saqlansin (default: 30)")
        parser.add_argument("--no-media", action="store_true",
                            help="Media fayllarsiz, faqat baza")
        parser.add_argument("--out", default="", help="Zaxira papkasi (default: backups/)")

    def handle(self, *args: Any, **options: Any) -> None:
        base_dir = Path(settings.BASE_DIR)
        backup_dir = Path(options["out"]) if options["out"] else base_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archive_path = backup_dir / f"edumed_backup_{stamp}.zip"

        # 1) Bazani JSON ga chiqaramiz (xotirada)
        self.stdout.write("Baza zaxiralanmoqda...")
        buf = io.StringIO()
        # MUHIM: natural_primary ISHLATILMAYDI — loyihada UUID birlamchi kalit,
        # u barcha bazalarda bir xil ishlaydi. natural_primary kalitlarni
        # tashlab yuborib, bog'lanishlarni buzadi va UNIQUE xatolarga olib keladi.
        call_command(
            "dumpdata",
            exclude=EXCLUDED,
            indent=2,
            stdout=buf,
        )
        data_json = buf.getvalue()
        record_count = data_json.count('"model":')

        # 2) Arxivga yozamiz
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("data.json", data_json)

            info = (
                f"EduMed / Doctor B Najot zaxira nusxasi\n"
                f"Sana: {datetime.now():%d.%m.%Y %H:%M:%S}\n"
                f"Yozuvlar soni: ~{record_count}\n"
                f"Baza: {settings.DATABASES['default']['ENGINE']}\n"
                f"Tiklash: python manage.py restore_db --file {archive_path.name}\n"
            )
            zf.writestr("info.txt", info)

            # 3) Media fayllar
            media_root = Path(settings.MEDIA_ROOT)
            media_count = 0
            if not options["no_media"] and media_root.exists():
                self.stdout.write("Media fayllar zaxiralanmoqda...")
                for f in media_root.rglob("*"):
                    if f.is_file():
                        zf.write(f, f"media/{f.relative_to(media_root)}")
                        media_count += 1

        size_mb = archive_path.stat().st_size / (1024 * 1024)
        self.stdout.write(self.style.SUCCESS(
            f"Zaxira tayyor: {archive_path.name} "
            f"({size_mb:.1f} MB, ~{record_count} yozuv, {media_count} fayl)"
        ))

        # 4) Eskilarini tozalash
        keep = options["keep"]
        archives = sorted(backup_dir.glob("edumed_backup_*.zip"), reverse=True)
        removed = 0
        for old in archives[keep:]:
            old.unlink()
            removed += 1
        if removed:
            self.stdout.write(f"Eski zaxiralardan {removed} tasi o'chirildi (oxirgi {keep} ta saqlandi).")
