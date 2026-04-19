"""
Runtime settings for django-migcare, read from settings.MIGCARE dict.

Example::

    MIGCARE = {
        "AUTO_BACKUP": True,
        "REQUIRE_CONFIRMATION": False,
        "BACKUP_ROW_LIMIT": 10_000,
        "MAX_BACKUP_AGE_DAYS": 30,
        "WARN_ON_BRANCH_SWITCH": True,
    }
"""

from django.conf import settings as django_settings

_DEFAULTS: dict = {
    # Automatically snapshot affected rows before any destructive migration.
    "AUTO_BACKUP": True,
    # Interactively prompt the user before running destructive migrations when
    # using the `safe_migrate` command.
    "REQUIRE_CONFIRMATION": False,
    # Maximum rows per table to include in a single snapshot. Tables larger
    # than this limit are partially backed up and a warning is emitted.
    "BACKUP_ROW_LIMIT": 10_000,
    # Automatically purge snapshots older than this many days (0 = never).
    "MAX_BACKUP_AGE_DAYS": 30,
    # Emit a warning after a git branch switch when the DB contains migrations
    # that are absent from the new branch's file tree.
    "WARN_ON_BRANCH_SWITCH": True,
}


class _MigcareSettings:
    """Lazy proxy around settings.MIGCARE with defaults."""

    def __getattr__(self, name: str):
        if name not in _DEFAULTS:
            raise AttributeError(f"django-migcare has no setting '{name}'")
        user = getattr(django_settings, "MIGCARE", {})
        return user.get(name, _DEFAULTS[name])


migcare_settings = _MigcareSettings()