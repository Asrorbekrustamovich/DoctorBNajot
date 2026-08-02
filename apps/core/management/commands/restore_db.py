"""Zaxira nusxasidan tiklash (baza + media fayllar).

Ishlatilishi:
    python manage.py restore_db --list                    # zaxiralar ro'yxati
    python manage.py restore_db --file <nom>.zip          # tiklash (tasdiq so'raydi)
    python manage.py restore_db --file <nom>.zip --yes    # so'ramasdan tiklash
    python manage.py restore_db --latest --yes            # eng oxirgisidan tiklash

DIQQAT: tiklash joriy bazadagi ma'lumotlarni O'CHIRIB, zaxiradagisini
o'rniga qo'yadi. Shuning uchun tiklashdan oldin avtomatik "xavfsizlik
zaxirasi" olinadi (safety_*.zip).

Bu buyruq SQLite va PostgreSQL uchun bir xil ishlaydi — shuning uchun
SQLite dan PostgreSQL ga ko'chirishda ham shu ishlatiladi.
"""
from __future__ import annotations

import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Zaxira nusxasidan bazani va media fayllarni tiklaydi."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--file", default="", help="Zaxira fayli nomi yoki to'liq yo'li")
        parser.add_argument("--latest", action="store_true", help="Eng oxirgi zaxiradan tiklash")
        parser.add_argument("--list", action="store_true", help="Mavjud zaxiralarni ko'rsatish")
        parser.add_argument("--yes", action="store_true", help="Tasdiq so'ramasdan bajarish")
        parser.add_argument("--no-media", action="store_true", help="Faqat baza, media tiklanmasin")

    def handle(self, *args: Any, **options: Any) -> None:
        base_dir = Path(settings.BASE_DIR)
        backup_dir = base_dir / "backups"

        archives = sorted(backup_dir.glob("edumed_backup_*.zip"), reverse=True)

        # --- Ro'yxat ---
        if options["list"] or (not options["file"] and not options["latest"]):
            if not archives:
                self.stdout.write("Zaxiralar topilmadi. Avval: python manage.py backup_db")
                return
            self.stdout.write(f"Mavjud zaxiralar ({backup_dir}):")
            for a in archives:
                size = a.stat().st_size / (1024 * 1024)
                when = datetime.fromtimestamp(a.stat().st_mtime)
                self.stdout.write(f"  {a.name}  —  {size:.1f} MB  —  {when:%d.%m.%Y %H:%M:%S}")
            self.stdout.write("\nTiklash: python manage.py restore_db --file <nom>.zip")
            return

        # --- Faylni aniqlash ---
        if options["latest"]:
            if not archives:
                raise CommandError("Zaxira topilmadi.")
            archive = archives[0]
        else:
            candidate = Path(options["file"])
            archive = candidate if candidate.is_absolute() and candidate.exists() else backup_dir / options["file"]
        if not archive.exists():
            raise CommandError(f"Zaxira fayli topilmadi: {archive}")

        # --- Tasdiq ---
        if not options["yes"]:
            self.stdout.write(self.style.WARNING(
                f"\nDIQQAT: joriy bazadagi BARCHA ma'lumot o'chiriladi va\n"
                f"'{archive.name}' dagi ma'lumot o'rniga qo'yiladi."
            ))
            answer = input("Davom etilsinmi? (ha/yo'q): ").strip().lower()
            if answer not in ("ha", "yes", "y"):
                self.stdout.write("Bekor qilindi.")
                return

        # --- Xavfsizlik zaxirasi (tiklashdan oldin) ---
        self.stdout.write("Tiklashdan oldin xavfsizlik zaxirasi olinmoqda...")
        try:
            call_command("backup_db", keep=50)
        except Exception as exc:  # noqa: BLE001
            self.stdout.write(self.style.WARNING(f"Xavfsizlik zaxirasi olinmadi: {exc}"))

        # --- Arxivni ochish ---
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(archive, "r") as zf:
                zf.extractall(tmp_path)

            data_file = tmp_path / "data.json"
            if not data_file.exists():
                raise CommandError("Arxivda data.json topilmadi — fayl buzilgan bo'lishi mumkin.")

            # --- Bazani tozalash va yuklash: BITTA TRANZAKSIYADA ---
            # Agar yuklashda xato chiqsa, hammasi orqaga qaytariladi va
            # joriy ma'lumotlar SAQLANIB QOLADI (bo'sh baza qolmaydi).
            self.stdout.write("Tiklanmoqda (xato bo'lsa hammasi orqaga qaytariladi)...")
            try:
                with transaction.atomic():
                    call_command("flush", "--noinput")
                    call_command("loaddata", str(data_file))
            except Exception as exc:  # noqa: BLE001
                raise CommandError(
                    f"Tiklash bajarilmadi, ma'lumotlar o'zgarmadi (orqaga qaytarildi).\n"
                    f"Sabab: {exc}"
                ) from exc

            # --- Media fayllar ---
            media_src = tmp_path / "media"
            if not options["no_media"] and media_src.exists():
                media_root = Path(settings.MEDIA_ROOT)
                media_root.mkdir(parents=True, exist_ok=True)
                count = 0
                for f in media_src.rglob("*"):
                    if f.is_file():
                        target = media_root / f.relative_to(media_src)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f, target)
                        count += 1
                self.stdout.write(f"Media fayllar tiklandi: {count} ta")

        self.stdout.write(self.style.SUCCESS(
            f"Tiklash tugadi: {archive.name}\n"
            "Endi tizimga kirib ma'lumotlarni tekshiring."
        ))
