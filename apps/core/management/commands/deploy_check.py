"""Serverga chiqarishdan oldingi va keyingi tekshiruv.

    python manage.py deploy_check

Har bir band uchun: OK / OGOHLANTIRISH / XATO va nima qilish kerakligi.
Chiqish kodi: 0 — hammasi joyida, 1 — xato bor (skriptda ishlatsa bo'ladi).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

OK, WARN, ERR = "OK", "OGOHLANTIRISH", "XATO"


class Command(BaseCommand):
    help = "Serverga chiqarishga tayyorlikni tekshiradi (edge-tts ham)"

    def add_arguments(self, parser):
        parser.add_argument("--tts-only", action="store_true",
                            help="Faqat ovozni tekshiradi")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        self.problems = 0
        self.warnings = 0

        if opts["tts_only"]:
            self._section("OVOZ (edge-tts)")
            self._check_tts()
        else:
            self._section("ASOSIY SOZLAMALAR")
            self._check_settings()
            self._section("MA'LUMOTLAR BAZASI")
            self._check_db()
            self._section("FAYLLAR")
            self._check_files()
            self._section("OVOZ (edge-tts)")
            self._check_tts()

        self.stdout.write("")
        if self.problems:
            self.stdout.write(self.style.ERROR(
                f"  {self.problems} ta XATO — tuzatmasdan chiqarmang."))
        elif self.warnings:
            self.stdout.write(self.style.WARNING(
                f"  {self.warnings} ta ogohlantirish — ishlaydi, lekin ko'rib chiqing."))
        else:
            self.stdout.write(self.style.SUCCESS("  Hammasi joyida."))
        sys.exit(1 if self.problems else 0)

    # ------------------------------------------------------------------
    def _section(self, title):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(f"== {title} =="))

    def _say(self, level, name, detail="", fix=""):
        style = {OK: self.style.SUCCESS, WARN: self.style.WARNING,
                 ERR: self.style.ERROR}[level]
        mark = {OK: "  [OK]   ", WARN: "  [OGOH] ", ERR: "  [XATO] "}[level]
        self.stdout.write(style(mark + name) + (f" — {detail}" if detail else ""))
        if fix:
            for line in fix.strip().split("\n"):
                self.stdout.write(f"          → {line}")
        if level == ERR:
            self.problems += 1
        elif level == WARN:
            self.warnings += 1

    # ------------------------------------------------------------------
    def _check_settings(self):
        if settings.DEBUG:
            self._say(ERR, "DEBUG yoqilgan", "ishlab chiqarishda o'chirilishi shart",
                      ".env faylida: DEBUG=False")
        else:
            self._say(OK, "DEBUG o'chirilgan")

        key = settings.SECRET_KEY or ""
        if len(key) < 40 or "insecure" in key:
            self._say(ERR, "SECRET_KEY zaif",
                      "sessiya va parollar xavf ostida",
                      'python -c "import secrets; print(secrets.token_urlsafe(64))"\n'
                      "natijani .env dagi SECRET_KEY ga yozing")
        else:
            self._say(OK, "SECRET_KEY yetarli uzunlikda")

        hosts = list(settings.ALLOWED_HOSTS)
        if not hosts or "*" in hosts:
            self._say(ERR, "ALLOWED_HOSTS ochiq", str(hosts),
                      ".env: ALLOWED_HOSTS=doctorbnajot.uz,www.doctorbnajot.uz")
        else:
            self._say(OK, "ALLOWED_HOSTS", ", ".join(hosts))

        if getattr(settings, "SESSION_COOKIE_SECURE", False):
            self._say(OK, "Cookie'lar faqat HTTPS orqali")
        else:
            self._say(WARN, "SESSION_COOKIE_SECURE o'chiq",
                      "sertifikat o'rnatilgach yoqing", ".env: SESSION_COOKIE_SECURE=True")

    def _check_db(self):
        try:
            with connection.cursor() as cur:
                cur.execute("SELECT 1")
            engine = connection.settings_dict["ENGINE"].rsplit(".", 1)[-1]
            self._say(OK, "Bazaga ulanish", engine)
            if engine == "sqlite3":
                self._say(WARN, "SQLite ishlatilyapti",
                          "ko'p foydalanuvchida sekinlashadi",
                          "PostgreSQL ga o'ting: POSTGRESQL-KOCHIRISH.md")
        except Exception as exc:  # noqa: BLE001
            self._say(ERR, "Bazaga ulanib bo'lmadi", str(exc)[:160],
                      ".env dagi DATABASE_URL ni tekshiring")
            return

        from django.db.migrations.executor import MigrationExecutor
        plan = MigrationExecutor(connection).migration_plan(
            MigrationExecutor(connection).loader.graph.leaf_nodes())
        if plan:
            self._say(ERR, f"{len(plan)} ta migratsiya qo'llanmagan", "",
                      "python manage.py migrate")
        else:
            self._say(OK, "Migratsiyalar to'liq qo'llangan")

    def _check_files(self):
        static_root = getattr(settings, "STATIC_ROOT", None)
        if static_root and os.path.isdir(static_root) and os.listdir(static_root):
            self._say(OK, "Statik fayllar yig'ilgan", static_root)
        else:
            self._say(ERR, "Statik fayllar yig'ilmagan",
                      "CSS/JS yuklanmaydi, sayt buzuq ko'rinadi",
                      "python manage.py collectstatic --noinput")

        media = settings.MEDIA_ROOT
        try:
            os.makedirs(media, exist_ok=True)
            probe = os.path.join(media, ".probe")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            self._say(OK, "media/ papkasiga yozish mumkin")
        except OSError as exc:
            self._say(ERR, "media/ ga yozib bo'lmaydi", str(exc)[:120],
                      "sudo chown -R www-data:www-data /opt/edumed-his/media")

    # ------------------------------------------------------------------
    def _check_tts(self):
        """Ovoz uch bosqichda tekshiriladi: modul → papka → HAQIQIY generatsiya.

        Uchtasini ajratish shart, chunki tashqaridan ular bir xil
        ko'rinadi — tabloda shunchaki jimlik bo'ladi.
        """
        has_module = False
        try:
            import edge_tts  # noqa: F401
            has_module = True
            self._say(OK, "edge-tts kutubxonasi o'rnatilgan")
        except Exception:  # noqa: BLE001
            self._say(ERR, "edge-tts o'rnatilmagan", "tabloda ovoz umuman chiqmaydi",
                      "source .venv/bin/activate\n"
                      "pip install -r requirements.txt")

        if shutil.which("edge-tts"):
            self._say(OK, "edge-tts buyrug'i PATH da")
        else:
            self._say(WARN, "edge-tts buyrug'i PATH da yo'q",
                      "muhim emas — modul orqali ishlatiladi")

        tts_dir = os.path.join(settings.MEDIA_ROOT, "tts")
        try:
            os.makedirs(tts_dir, exist_ok=True)
            probe = os.path.join(tts_dir, ".probe")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            self._say(OK, "Ovoz keshi papkasiga yozish mumkin", tts_dir)
        except OSError as exc:
            self._say(ERR, "Ovoz keshiga yozib bo'lmaydi", str(exc)[:120],
                      f"sudo chown -R www-data:www-data {tts_dir}")
            return

        if not has_module:
            return

        # ENG MUHIM TEKSHIRUV: edge-tts Microsoft xizmatiga ulanadi.
        # Ko'p VPS'da chiquvchi trafik yopiq bo'ladi va aynan shu yerda
        # jim xato beradi — tabloda hech narsa eshitilmaydi.
        out = os.path.join(tts_dir, "_deploy_check.mp3")
        try:
            res = subprocess.run(
                [sys.executable, "-m", "edge_tts", "--voice", "uz-UZ-MadinaNeural",
                 "--text", "Sinov ovozi", "--write-media", out],
                capture_output=True, timeout=40, text=True,
            )
            size = os.path.getsize(out) if os.path.exists(out) else 0
            if size > 0:
                self._say(OK, "O'zbekcha ovoz generatsiya qilindi", f"{size} bayt")
                os.remove(out)
            else:
                self._say(ERR, "Ovoz fayli yaratilmadi",
                          (res.stderr or res.stdout or "")[:200],
                          "Sabab odatda: serverdan tashqariga chiqish yopiq.\n"
                          "Tekshiring:  curl -I https://speech.platform.bing.com\n"
                          "Yopiq bo'lsa — 443-portga chiquvchi ruxsat bering,\n"
                          "yoki proksi qo'ying: .env ga HTTPS_PROXY=... yozing.")
        except subprocess.TimeoutExpired:
            self._say(ERR, "Ovoz generatsiyasi muddatdan oshdi",
                      "server internetga chiqa olmayapti",
                      "Chiquvchi 443-portni oching yoki HTTPS_PROXY sozlang.")
        except Exception as exc:  # noqa: BLE001
            self._say(ERR, "Ovoz generatsiyasida xato", str(exc)[:200])
