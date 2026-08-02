"""Production settings: security hardened.

Ishga tushirish:
    DJANGO_SETTINGS_MODULE=config.settings.production
Qiymatlar `.env` faylidan olinadi — kodda hech qanday parol yozilmaydi.
"""
from .base import *  # noqa: F403
from .base import env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")  # majburiy, default yo'q
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

# --- HTTPS ---
# Domensiz (faqat IP orqali) ishlatilsa .env da SECURE_SSL_REDIRECT=False
# qilinadi, aks holda sayt umuman ochilmaydi.
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=60 * 60 * 24 * 30)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"


def _origins_from_hosts(hosts):
    """ALLOWED_HOSTS'dan to'liq manzillar yasaydi.

    CSRF_TRUSTED_ORIGINS Django 4+ da sxema (https://) bilan yozilishi SHART.
    Buni yozishni unutish — serverda "CSRF verification failed" xatosining
    eng ko'p uchraydigan sababi.
    """
    out = []
    for h in hosts:
        h = (h or "").strip()
        if not h or h == "*":
            continue
        out.append(f"https://{h}")
        if not SECURE_SSL_REDIRECT:
            out.append(f"http://{h}")
    return out


# .env da aniq yozilsa — o'sha ishlatiladi, bo'lmasa ALLOWED_HOSTS'dan yasaladi
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS", default=_origins_from_hosts(ALLOWED_HOSTS)
)

# --- CORS ---
# Productionda hamma origin'ga ruxsat berish MUMKIN EMAS.
CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS", default=_origins_from_hosts(ALLOWED_HOSTS)
)
CORS_ALLOW_CREDENTIALS = True

# --- Sessiya ---
SESSION_COOKIE_AGE = env.int("SESSION_COOKIE_AGE", default=60 * 60 * 12)  # 12 soat
SESSION_EXPIRE_AT_BROWSER_CLOSE = env.bool(
    "SESSION_EXPIRE_AT_BROWSER_CLOSE", default=False
)
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SAMESITE = "Lax"

# --- Statik fayllar (whitenoise siqib, keshlab beradi) ---
STORAGES["staticfiles"] = {  # noqa: F405
    "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
}

# --- Fayl yuklash chegarasi ---
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int(
    "DATA_UPLOAD_MAX_MEMORY_SIZE", default=10 * 1024 * 1024
)
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE

LOGGING["root"]["level"] = env("LOG_LEVEL", default="WARNING")  # noqa: F405
