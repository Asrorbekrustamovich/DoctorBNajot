"""Bazaga ulanishni va sozlamalarni tekshiradi.

Ishlatilishi:
    python manage.py check_db
    python manage.py check_db --full     # jadvallar va yozuvlar sonini ham

Serverga chiqishdan oldin ENG BIRINCHI shu buyruq ishga tushiriladi:
ulanish bormi, parol to'g'rimi, SSL ishlayaptimi — hammasi ko'rinadi.
"""
from __future__ import annotations

import socket
import time
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, connections
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Ma'lumotlar bazasiga ulanishni tekshiradi"

    def add_arguments(self, parser):
        parser.add_argument("--full", action="store_true",
                            help="Jadvallar va yozuvlar sonini ham ko'rsatadi")

    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  ✓ {msg}"))

    def _bad(self, msg):
        self.stdout.write(self.style.ERROR(f"  ✗ {msg}"))

    def _warn(self, msg):
        self.stdout.write(self.style.WARNING(f"  ! {msg}"))

    def handle(self, *args, **opts):
        db = settings.DATABASES["default"]
        engine = db.get("ENGINE", "")
        host = db.get("HOST") or "localhost"
        port = int(db.get("PORT") or (5432 if "postgres" in engine else 0))

        self.stdout.write(self.style.MIGRATE_HEADING("\n1) Sozlamalar"))
        self.stdout.write(f"  Settings : {settings.SETTINGS_MODULE}")
        self.stdout.write(f"  DEBUG    : {settings.DEBUG}")
        self.stdout.write(f"  Engine   : {engine.rsplit('.', 1)[-1]}")
        self.stdout.write(f"  Host     : {host}:{port}")
        self.stdout.write(f"  Baza     : {db.get('NAME')}")
        self.stdout.write(f"  User     : {db.get('USER')}")
        parol = db.get("PASSWORD") or ""
        self.stdout.write(f"  Parol    : {'*' * len(parol)} ({len(parol)} belgi)")
        if db.get("OPTIONS"):
            self.stdout.write(f"  OPTIONS  : {db['OPTIONS']}")

        if settings.DEBUG:
            self._warn("DEBUG=True — productionda False bo'lishi SHART!")
        if "insecure" in settings.SECRET_KEY or "ALMASHTIR" in settings.SECRET_KEY.upper():
            self._bad("SECRET_KEY almashtirilmagan!")

        # --- 2) Tarmoq ---
        if "postgres" in engine and host not in ("localhost", "127.0.0.1", ""):
            self.stdout.write(self.style.MIGRATE_HEADING("\n2) Tarmoq (port ochiqmi)"))
            t0 = time.time()
            try:
                with socket.create_connection((host, port), timeout=10):
                    self._ok(f"{host}:{port} ochiq ({(time.time() - t0) * 1000:.0f} ms)")
            except OSError as e:
                self._bad(f"{host}:{port} ga ulanib bo'lmadi — {e}")
                self._warn("Sabablari: server o'chiq / firewall / IP oq ro'yxatda emas")
                return

        # --- 3) Baza ---
        self.stdout.write(self.style.MIGRATE_HEADING("\n3) Bazaga ulanish"))
        t0 = time.time()
        try:
            connections["default"].ensure_connection()
        except OperationalError as e:
            self._bad(f"Ulanmadi: {e}")
            txt = str(e).lower()
            if "password authentication" in txt:
                self._warn("Parol xato. DATABASE_URL da /, +, = belgilari "
                           "%2F, %2B, %3D deb kodlanganini tekshiring.")
            elif "ssl" in txt:
                self._warn("SSL muammosi. .env da DB_SSLMODE=disable qilib ko'ring.")
            elif "does not exist" in txt:
                self._warn("Bunday nomli baza yo'q — DATABASE_URL oxiridagi nomni tekshiring.")
            return
        self._ok(f"Ulanish muvaffaqiyatli ({(time.time() - t0) * 1000:.0f} ms)")

        with connection.cursor() as cur:
            if "postgres" in engine:
                cur.execute("SELECT version()")
                self._ok(cur.fetchone()[0].split(",")[0])
                cur.execute("SHOW server_encoding")
                enc = cur.fetchone()[0]
                (self._ok if enc.upper() in ("UTF8", "UTF-8") else self._bad)(
                    f"Kodlash: {enc}" + ("" if enc.upper().startswith("UTF") else " — UTF8 bo'lishi kerak!")
                )
                cur.execute("SHOW TIME ZONE")
                self._ok(f"Baza vaqt mintaqasi: {cur.fetchone()[0]}")
                try:
                    cur.execute("SELECT ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid()")
                    row = cur.fetchone()
                    if row and row[0]:
                        self._ok("Ulanish SSL bilan shifrlangan")
                    else:
                        self._warn("Ulanish SHIFRLANMAGAN — .env da DB_SSLMODE=require qiling")
                except Exception:
                    pass

        # --- 4) Migratsiyalar ---
        self.stdout.write(self.style.MIGRATE_HEADING("\n4) Migratsiyalar"))
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connections["default"])
        plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        if plan:
            self._warn(f"{len(plan)} ta migratsiya qo'llanmagan — `manage.py migrate` kerak")
            for mig, _ in plan[:10]:
                self.stdout.write(f"      · {mig.app_label}.{mig.name}")
        else:
            self._ok("Barcha migratsiyalar qo'llangan")

        # --- 5) Ma'lumotlar ---
        if opts["full"]:
            self.stdout.write(self.style.MIGRATE_HEADING("\n5) Ma'lumotlar"))
            from django.apps import apps as django_apps
            for model in sorted(django_apps.get_models(), key=lambda m: m._meta.label):
                if not model._meta.label.startswith(("apps.", "accounts", "patients",
                                                     "clinical", "registration",
                                                     "billing", "pharmacy", "audit")):
                    continue
                try:
                    n = model._default_manager.count()
                except Exception:
                    continue
                if n:
                    self.stdout.write(f"  {model._meta.label:<45} {n:>7}")

        self.stdout.write(self.style.SUCCESS("\nTayyor.\n"))
