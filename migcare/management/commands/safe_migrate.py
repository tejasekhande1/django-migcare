"""
``safe_migrate`` — a drop-in replacement for ``manage.py migrate`` that adds
data-loss analysis and interactive confirmation before applying any destructive
database operation.

Usage::

    python manage.py safe_migrate [same args as migrate]

Options added on top of the standard ``migrate`` options:

    --no-backup      Skip snapshot creation even if AUTO_BACKUP is True.
    --no-confirm     Skip interactive confirmation prompts.
    --dry-run        Only show the risk analysis; do not apply any migrations.
"""

from __future__ import annotations

from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connections

from migcare.analysis import RiskLevel, analyze_plan
from migcare.conf import migcare_settings


class Command(MigrateCommand):
    help = (
        "Runs Django migrations with data-loss protection provided by "
        "django-migcare. Accepts all the same arguments as `migrate`."
    )

    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--no-backup",
            action="store_true",
            dest="no_backup",
            help="Disable automatic snapshot creation for this run.",
        )
        parser.add_argument(
            "--no-confirm",
            action="store_true",
            dest="no_confirm",
            help="Skip interactive confirmation prompts.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Show the risk analysis only; do not apply any migrations.",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_plan(self, app_labels, options):
        """Return the migration plan for *app_labels* without side effects."""
        from django.db.migrations.executor import MigrationExecutor
        from django.db.migrations.loader import MigrationLoader

        db = options["database"]
        conn = connections[db]

        executor = MigrationExecutor(conn)
        loader: MigrationLoader = executor.loader

        if not app_labels:
            targets = loader.graph.leaf_nodes()
        else:
            targets = []
            for app_label in app_labels:
                app_leaf_nodes = [
                    node for node in loader.graph.leaf_nodes() if node[0] == app_label
                ]
                targets.extend(app_leaf_nodes)

        return executor.migration_plan(targets)

    def _print_report(self, report, style):
        """Pretty-print the risk report to stdout."""
        if report.is_safe:
            self.stdout.write(style.SUCCESS("  django-migcare: no data-loss risks detected."))
            return

        if report.dangers:
            self.stdout.write(style.ERROR(f"\n  django-migcare — {len(report.dangers)} DANGER operation(s):"))
            for risk in report.dangers:
                self.stdout.write(style.ERROR(f"    • {risk.message}"))

        if report.warnings:
            self.stdout.write(style.WARNING(f"\n  django-migcare — {len(report.warnings)} WARNING operation(s):"))
            for risk in report.warnings:
                self.stdout.write(style.WARNING(f"    • {risk.message}"))

        self.stdout.write("")

    def _create_backups(self, report, options):
        """Snapshot all DANGER-level table/column targets before migrating."""
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        verbosity = options.get("verbosity", 1)

        for risk in report.dangers:
            if risk.table_name is None:
                continue

            # Avoid double-snapshotting across signal + command paths.
            already = MigrationSnapshot.objects.filter(
                app_label=risk.app_label,
                migration_name=risk.migration_name,
                table_name=risk.table_name,
                column_name=risk.column_name or "",
            ).exists()
            if already:
                if verbosity >= 2:
                    self.stdout.write(
                        f"  django-migcare: snapshot already exists for "
                        f"{risk.table_name}{'.' + risk.column_name if risk.column_name else ''} — skipping."
                    )
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
                    notes=f"safe_migrate auto-backup: {risk.message}",
                )
                if verbosity >= 1:
                    target = (
                        f"{risk.table_name}.{risk.column_name}"
                        if risk.column_name
                        else risk.table_name
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  django-migcare: snapshot #{snap.pk} created — "
                            f"{target} ({snap.row_count} rows)"
                        )
                    )
            except LookupError as exc:
                self.stderr.write(f"  django-migcare WARNING: {exc}")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def handle(self, *app_labels, **options):
        verbosity = options.get("verbosity", 1)
        dry_run = options.get("dry_run", False)
        skip_backup = options.get("no_backup", False)
        skip_confirm = options.get("no_confirm", False)

        # --- Compute plan and analyse ---
        try:
            plan = self._compute_plan(app_labels, options)
        except Exception as exc:
            self.stderr.write(
                f"django-migcare: could not compute migration plan ({exc}). "
                "Falling back to standard migrate."
            )
            if not dry_run:
                super().handle(*app_labels, **options)
            return

        if plan:
            report = analyze_plan(plan)

            if verbosity >= 1:
                self.stdout.write(self.style.MIGRATE_HEADING("\ndjango-migcare risk analysis:"))
                self._print_report(report, self.style)

            if dry_run:
                self.stdout.write(
                    self.style.WARNING("  --dry-run: no migrations applied.\n")
                )
                return

            # --- Auto-backup ---
            should_backup = (
                migcare_settings.AUTO_BACKUP
                and not skip_backup
                and not report.is_safe
            )
            if should_backup:
                self._create_backups(report, options)

            # --- Confirmation prompt ---
            needs_confirm = (
                migcare_settings.REQUIRE_CONFIRMATION
                and not skip_confirm
                and report.max_risk == RiskLevel.DANGER
            )
            if needs_confirm:
                self.stdout.write(
                    self.style.ERROR(
                        "  The migration plan contains DANGER-level operations that "
                        "may permanently destroy data."
                    )
                )
                answer = input("  Type 'yes' to continue, or anything else to abort: ")
                if answer.strip().lower() != "yes":
                    self.stdout.write("  Aborted by user.")
                    return

        # --- Delegate to Django's standard migrate ---
        super().handle(*app_labels, **options)
