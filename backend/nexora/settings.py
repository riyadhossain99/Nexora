import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BASE_DIR.parent
FRONTEND_DIR = PROJECT_DIR / "frontend"


def _load_env(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_env(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-insecure-nexora-poc-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",") if o
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
]
try:
    import whitenoise  # noqa: F401
    MIDDLEWARE.append("whitenoise.middleware.WhiteNoiseMiddleware")
except ImportError:
    pass
MIDDLEWARE.extend([
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
])

ROOT_URLCONF = "nexora.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [FRONTEND_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "nexora.wsgi.application"

# A 4 MiB WhatsApp photo expands to about 5.34 MiB in the JSON webhook.
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024

import pymysql

pymysql.install_as_MySQLdb()
from django.db.backends.mysql.base import DatabaseWrapper
from django.db.backends.mysql.features import DatabaseFeatures


class XamppFeatures(DatabaseFeatures):
    # shortcut: tested with this app on XAMPP's MariaDB 10.4; remove after a server upgrade.
    @property
    def minimum_database_version(self):
        return (10, 4) if self.connection.mysql_is_mariadb else (8, 0)

    can_return_columns_from_insert = False  # INSERT ... RETURNING needs MariaDB 10.5+.


DatabaseWrapper.features_class = XamppFeatures
_db_options = {"charset": "utf8mb4", "init_command": "SET sql_mode='STRICT_TRANS_TABLES'"}
if os.environ.get("DB_SSL", "0") in ("1", "true", "True"):
    _db_options["ssl"] = {"ssl_mode": "REQUIRED"}

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("DB_NAME", "nexora_app"),
        "USER": os.environ.get("DB_USER", "root"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": int(os.environ.get("DB_PORT", "3306")),
        "OPTIONS": _db_options,
    }
}

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [FRONTEND_DIR / "static"]
STATIC_ROOT = PROJECT_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = FRONTEND_DIR / "media"
LOGIN_URL = "/login/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

WA_BRIDGE_URL = os.environ.get("WA_BRIDGE_URL", "http://127.0.0.1:3001")

EMAIL_OTP_BACKEND = os.environ.get("EMAIL_OTP_BACKEND", "stytch")
STYTCH_PROJECT_ID = os.environ.get("STYTCH_PROJECT_ID", "")
STYTCH_SECRET = os.environ.get("STYTCH_SECRET", "")
STYTCH_ENV = os.environ.get("STYTCH_ENV", "test")
STYTCH_BASE_URL = "https://api.stytch.com" if STYTCH_ENV == "live" else "https://test.stytch.com"
STYTCH_ORGANIZATION_ID = os.environ.get("STYTCH_ORGANIZATION_ID", "")
