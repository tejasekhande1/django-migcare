"""
Minimal Django settings used by the test suite.
"""

SECRET_KEY = "migcare-test-secret-key-not-for-production"

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "migcare",
    "tests.testapp",
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Disable auto-backup during tests so individual tests control it explicitly.
MIGCARE = {
    "AUTO_BACKUP": False,
    "REQUIRE_CONFIRMATION": False,
    "BACKUP_ROW_LIMIT": 500,
    "MAX_BACKUP_AGE_DAYS": 30,
}

USE_TZ = True
