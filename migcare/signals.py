"""
Django signal handlers.

Hooks into ``pre_migrate`` to analyse the upcoming migration plan and
auto-create snapshots for any DANGER-level operations when
``MIGCARE['AUTO_BACKUP']`` is True.
"""

from __future__ import annotations

import logging

from django.db.models.signals import pre_migrate
from django.dispatch import receiver

logger = logging.getLogger("migcare")


@receiver(pre_migrate)
def _on_pre_migrate(sender, app_config, verbosity, interactive, using, **kwargs):  # noqa: ANN
    """
    Triggered once per app before Django applies its migrations.

    We re-compute the plan for *all* pending/rolling-back migrations (not just
    the current app) so we have a complete picture.  Snapshots are deduplicated
    by (migration_name, table_name, column_name) within a single migrate run.
    """
    from .conf import migcare_settings

    if not migcare_settings.AUTO_BACKUP:
        return

    # Only run the analysis for the first app signal to avoid redundant work.
    # We store a flag on the sender class to track this within the process.
    sentinel = "_migcare_analysed"
    if getattr(sender, sentinel, False):
        return
    setattr(sender, sentinel, True)

    try:
        _run_auto_backup(using=using, verbosity=verbosity)
    except Exception as exc:  # Never crash the migrate command
        logger.warning("django-migcare: auto-backup failed: %s", exc)
    finally:
        # Reset sentinel so subsequent migrate calls in the same process work.
        setattr(sender, sentinel, False)


def _run_auto_backup(using: str, verbosity: int) -> None:
    from django.db import connections
    from django.db.migrations.executor import MigrationExecutor

    from .analysis import RiskLevel, analyze_plan
    from .backup import create_snapshot
    from .models import MigrationSnapshot

    conn = connections[using]

    # Skip non-migratable databases (e.g. test fixtures db)
    if not conn.settings_dict.get("ENGINE") or conn.settings_dict[
        "ENGINE"
    ].endswith("dummy"):
        return

    executor = MigrationExecutor(conn)
    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)

    if not plan:
        return

    report = analyze_plan(plan)
    if report.is_safe:
        return

    if verbosity >= 1:
        logger.info(
            "django-migcare: detected %d DANGER and %d WARNING operation(s) — "
            "creating snapshots before migration proceeds.",
            len(report.dangers),
            len(report.warnings),
        )

    seen: set = set()  # (migration_name, table_name, column_name)

    for risk in report.dangers:
        if risk.table_name is None:
            continue

        key = (risk.migration_name, risk.table_name, risk.column_name or "")
        if key in seen:
            continue
        seen.add(key)

        # Don't duplicate snapshots that were already created for this migration.
        already_exists = MigrationSnapshot.objects.filter(
            app_label=risk.app_label,
            migration_name=risk.migration_name,
            table_name=risk.table_name,
            column_name=risk.column_name or "",
        ).exists()
        if already_exists:
            continue

        try:
            snap = create_snapshot(
                app_label=risk.app_label,
                migration_name=risk.migration_name,
                operation_type=(
                    MigrationSnapshot.ROLLBACK
                    if risk.direction == "backward"
                    else MigrationSnapshot.FORWARD
                ),
                table_name=risk.table_name,
                column_name=risk.column_name or "",
                notes=f"Auto-backup: {risk.message}",
            )
            if verbosity >= 1:
                target = (
                    f"{risk.table_name}.{risk.column_name}"
                    if risk.column_name
                    else risk.table_name
                )
                logger.info(
                    "django-migcare: snapshot #%d created for %s (%d rows).",
                    snap.pk,
                    target,
                    snap.row_count,
                )
        except LookupError as exc:
            logger.warning("django-migcare: could not snapshot: %s", exc)
