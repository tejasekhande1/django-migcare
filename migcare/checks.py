"""
Django system checks for django-migcare.

Registers checks that run during ``manage.py check`` or at startup.
"""

from django.core.checks import Error, Warning, register


@register()
def check_json_field_support(app_configs, **kwargs):
    """Ensure the database backend supports JSONField."""
    from django.db import connection

    errors = []
    vendor = connection.vendor
    supported = {"postgresql", "sqlite", "mysql", "oracle"}
    if vendor not in supported:
        errors.append(
            Warning(
                f"django-migcare: database vendor '{vendor}' may not support "
                "JSONField, which is required for snapshot storage.",
                hint="Snapshot storage requires a backend with native JSON support.",
                id="migcare.W001",
            )
        )
    return errors


@register()
def check_migcare_in_installed_apps(app_configs, **kwargs):
    from django.conf import settings

    errors = []
    if "migcare" not in settings.INSTALLED_APPS:
        errors.append(
            Error(
                "'migcare' is not in INSTALLED_APPS.",
                hint="Add 'migcare' to your INSTALLED_APPS setting.",
                id="migcare.E001",
            )
        )
    return errors


@register()
def check_migcare_settings(app_configs, **kwargs):
    from django.conf import settings as django_settings

    errors = []
    user = getattr(django_settings, "MIGCARE", {})
    if not isinstance(user, dict):
        errors.append(
            Error(
                "settings.MIGCARE must be a dictionary.",
                id="migcare.E002",
            )
        )
        return errors

    valid_keys = {
        "AUTO_BACKUP",
        "REQUIRE_CONFIRMATION",
        "BACKUP_ROW_LIMIT",
        "MAX_BACKUP_AGE_DAYS",
        "WARN_ON_BRANCH_SWITCH",
    }
    unknown = set(user.keys()) - valid_keys
    for key in unknown:
        errors.append(
            Warning(
                f"settings.MIGCARE contains unknown key '{key}'.",
                hint=f"Valid keys are: {', '.join(sorted(valid_keys))}",
                id="migcare.W002",
            )
        )
    return errors
