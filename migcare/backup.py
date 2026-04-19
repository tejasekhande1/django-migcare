
"""
Snapshot and restore logic for MigrationSnapshot records.

Public API
----------
create_snapshot(...)  → MigrationSnapshot
restore_snapshot(snapshot) → int  (rows affected)
purge_old_snapshots() → int  (deleted count)
"""

from __future__ import annotations

import subprocess
from typing import List, Optional

from django.db import connection, transaction

from .conf import migcare_settings


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------


def _git_info() -> tuple[str, str]:
    """Return (branch, commit_sha).  Both are empty strings on failure."""
    try:
        branch = subprocess.check_output(
            ["git", "branch", "--show-current"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return branch, commit
    except Exception:
        return "", ""


# ---------------------------------------------------------------------------
# Low-level DB helpers
# ---------------------------------------------------------------------------


def _table_exists(table_name: str) -> bool:
    return table_name in connection.introspection.table_names()


def _column_exists(table_name: str, column_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    with connection.cursor() as cursor:
        columns = [
            col.name
            for col in connection.introspection.get_table_description(
                cursor, table_name
            )
        ]
    return column_name in columns


def _fetch_table(table_name: str, limit: int) -> tuple[list, bool]:
    """
    Fetch up to *limit* rows from *table_name*.

    Returns (rows, truncated) where rows is a list of dicts.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {table_name} LIMIT %s", [limit + 1])  # nosec
        cols = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return [dict(zip(cols, row)) for row in rows], truncated


def _fetch_column(
    table_name: str, column_name: str, pk_col: str, limit: int
) -> tuple[list, bool]:
    """Fetch id + column_name from *table_name* up to *limit* rows."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT {pk_col}, {column_name} FROM {table_name} LIMIT %s",  # nosec
            [limit + 1],
        )
        rows = cursor.fetchall()

    truncated = len(rows) > limit
    if truncated:
        rows = rows[:limit]

    return [{pk_col: r[0], column_name: r[1]} for r in rows], truncated


def _detect_pk(table_name: str) -> str:
    """Return the primary-key column name, defaulting to 'id'."""
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table_name)
    for info in constraints.values():
        if info.get("primary_key"):
            cols = info.get("columns") or []
            if cols:
                return cols[0]
    return "id"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_snapshot(
    *,
    app_label: str,
    migration_name: str,
    operation_type: str,
    table_name: str,
    column_name: str = "",
    notes: str = "",
) -> "MigrationSnapshot":  # type: ignore[name-defined]  # noqa: F821
    """
    Capture a snapshot of *table_name* (optionally scoped to *column_name*)
    and persist it as a MigrationSnapshot record.

    Raises ``LookupError`` if the table or column does not exist.
    Emits a ``UserWarning`` (does not raise) if the row limit is exceeded.
    """
    from .models import MigrationSnapshot

    if not _table_exists(table_name):
        raise LookupError(
            f"django-migcare: cannot snapshot table '{table_name}' — it does not exist."
        )

    limit = migcare_settings.BACKUP_ROW_LIMIT
    branch, commit = _git_info()

    if column_name:
        if not _column_exists(table_name, column_name):
            raise LookupError(
                f"django-migcare: column '{column_name}' not found in '{table_name}'."
            )
        pk = _detect_pk(table_name)
        data, truncated = _fetch_column(table_name, column_name, pk, limit)
    else:
        data, truncated = _fetch_table(table_name, limit)

    if truncated:
        import warnings

        warnings.warn(
            f"django-migcare: table '{table_name}' has more than {limit} rows. "
            "Only the first {limit} rows were backed up. Increase MIGCARE['BACKUP_ROW_LIMIT'] "
            "to capture the full table.",
            stacklevel=3,
        )

    snap = MigrationSnapshot.objects.create(
        app_label=app_label,
        migration_name=migration_name,
        operation_type=operation_type,
        table_name=table_name,
        column_name=column_name,
        row_count=len(data),
        data=data,
        git_branch=branch,
        git_commit=commit,
        notes=notes,
    )
    return snap


def restore_snapshot(snapshot: "MigrationSnapshot") -> int:  # type: ignore[name-defined]  # noqa: F821
    """
    Restore the data stored in *snapshot* back into the database.

    For column-level snapshots the existing row is updated (UPDATE … SET …).
    For full-table snapshots rows are inserted; duplicate PKs are skipped.

    Returns the number of rows written.
    """
    from django.utils import timezone

    data: List[dict] = snapshot.data
    if not data:
        return 0

    table = snapshot.table_name
    col = snapshot.column_name

    if not _table_exists(table):
        raise LookupError(
            f"django-migcare: table '{table}' does not exist. "
            "Roll back the migration first, then run migcare_restore."
        )

    count = 0
    with transaction.atomic():
        with connection.cursor() as cursor:
            if col:
                # Column-level restore: UPDATE existing rows
                if not _column_exists(table, col):
                    raise LookupError(
                        f"django-migcare: column '{col}' does not exist in '{table}'. "
                        "Roll back the migration first, then run migcare_restore."
                    )
                pk = _detect_pk(table)
                for row in data:
                    cursor.execute(
                        f"UPDATE {table} SET {col} = %s WHERE {pk} = %s",  # nosec
                        [row.get(col), row.get(pk)],
                    )
                    count += cursor.rowcount
            else:
                # Full-table restore: INSERT, ignore duplicate PKs
                columns = list(data[0].keys())
                placeholders = ", ".join(["%s"] * len(columns))
                col_str = ", ".join(columns)
                for row in data:
                    try:
                        cursor.execute(
                            f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})",  # nosec
                            [row[c] for c in columns],
                        )
                        count += 1
                    except Exception:
                        # Skip duplicate / constraint violations
                        pass

    snapshot.restored_at = timezone.now()
    snapshot.save(update_fields=["restored_at"])
    return count


def purge_old_snapshots() -> int:
    """Delete snapshots older than MIGCARE['MAX_BACKUP_AGE_DAYS'] days."""
    from datetime import timedelta

    from django.utils import timezone

    from .models import MigrationSnapshot

    days = migcare_settings.MAX_BACKUP_AGE_DAYS
    if not days:
        return 0

    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = MigrationSnapshot.objects.filter(created_at__lt=cutoff).delete()
    return deleted


def list_snapshots(
    app_label: Optional[str] = None,
    migration_name: Optional[str] = None,
    table_name: Optional[str] = None,
) -> "QuerySet":  # type: ignore[name-defined]  # noqa: F821
    """Return a filtered QuerySet of MigrationSnapshot records."""
    from .models import MigrationSnapshot

    qs = MigrationSnapshot.objects.all()
    if app_label:
        qs = qs.filter(app_label=app_label)
    if migration_name:
        qs = qs.filter(migration_name=migration_name)
    if table_name:
        qs = qs.filter(table_name=table_name)
    return qs
