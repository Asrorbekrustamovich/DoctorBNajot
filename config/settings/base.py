"""Base settings shared by all environments."""
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    TIME_ZONE=(str, "Asia/Tashkent"),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY", default="insecure-dev-key-change-in-production")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "django_htmx",
    "django_celery_beat",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.core",
    "apps.audit",
    "apps.accounts",
    "apps.patients",
    "apps.registration",
    "apps.clinical",
    "apps.billing",
    "apps.pharmacy",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "apps.core.middleware.CurrentRequestMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.clinical.context_processors.notifications",
                "apps.clinical.context_processors.clinic_info",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgres://postgres:postgres@localhost:5432/edumed_his",
    )
}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
# Ulanishni qayta ishlatish. Masofadagi (internetdagi) baza uchun kattaroq
# qiymat foydali — har so'rovda yangi ulanish ochilmaydi.
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)

# --- Masofadagi PostgreSQL uchun SSL va kutish vaqti ---
# Baza internet orqali ulansa, trafik shifrlangan bo'lishi kerak.
# Agar server SSL'ni qo'llab-quvvatlamasa: .env da DB_SSLMODE=disable
if DATABASES["default"].get("ENGINE", "").endswith("postgresql"):
    _db_opts = DATABASES["default"].setdefault("OPTIONS", {})
    _sslmode = env("DB_SSLMODE", default="")
    if _sslmode:
        _db_opts["sslmode"] = _sslmode
    _db_opts.setdefault("connect_timeout", env.int("DB_CONNECT_TIMEOUT", default=10))

# ==========================================================================
# CORS (Cross-Origin) — API'ni tashqi frontend/mobil ilovadan chaqirish uchun
# .env da: CORS_ALLOWED_ORIGINS=https://app.example.com,https://m.example.com
# ==========================================================================
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = True
# Rivojlanish (DEBUG) rejimida hamma origin'ga ruxsat (qulaylik uchun)
CORS_ALLOW_ALL_ORIGINS = env.bool("CORS_ALLOW_ALL_ORIGINS", default=DEBUG)

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"
LOGOUT_REDIRECT_URL = "accounts:login"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "uz"

# ==========================================================================
# KLINIKA REKVIZITLARI — rasmiy hujjatlarda (chek, bayonnoma, xulosa) chiqadi.
# O'zgartirish uchun FAQAT shu yerni tahrirlang — hamma joyga avtomatik tarqaladi.
# ==========================================================================
CLINIC_NAME = "Doctor B Najot"
CLINIC_ADDRESS = "Qoraqalpog'iston Respublikasi, Bo'ston shahri, Shifokor ko'chasi, 231600"
CLINIC_PHONE = "+998 99 426 40 15"

# Vaqt HAMMA joyda 24 soatlik formatda (AM/PM emas)
TIME_FORMAT = "H:i"
DATETIME_FORMAT = "d.m.Y H:i:s"
SHORT_DATETIME_FORMAT = "d.m.Y H:i"
DATE_FORMAT = "d.m.Y"
SHORT_DATE_FORMAT = "d.m.Y"
TIME_ZONE = env("TIME_ZONE")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "EXCEPTION_HANDLER": "apps.core.exceptions.drf_exception_handler",
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TIME_LIMIT = 300
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

SESSION_COOKIE_AGE = 60 * 60 * 8  # 8 soatlik ish smenasi
SESSION_SAVE_EVERY_REQUEST = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {"format": "{levelname} {asctime} {module} {message}", "style": "{"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root":  {"handlers": ["console"], "level": "INFO"},
}
