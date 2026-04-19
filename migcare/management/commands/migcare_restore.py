"""
``migcare_restore`` — restore data from a MigrationSnapshot.

Usage::

    python manage.py migcare_restore 42          # restore snapshot with pk=42
    python manage.py migcare_restore --list      # list available snapshots
    python manage.py migcare_restore --list --app myapp
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Restore data from a MigrationSnapshot created by django-migcare."

    def add_arguments(self, parser):
        parser.add_argument(
            "snapshot_id",
            nargs="?",
            type=int,
            help="Primary key of the MigrationSnapshot to restore.",
        )
        parser.add_argument(
            "--list",
            action="store_true",
            dest="list_mode",
            help="List available snapshots instead of restoring.",
        )
        parser.add_argument(
            "--app",
            dest="app_label",
            help="Filter snapshot listing by app label.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt.",
        )

    def handle(self, *args, **options):
        if options["list_mode"]:
            self._list(options.get("app_label"))
            return

        snapshot_id = options.get("snapshot_id")
        if snapshot_id is None:
            raise CommandError(
                "Provide a snapshot ID to restore, or use --list to see available snapshots."
            )

        self._restore(snapshot_id, options)

    # ------------------------------------------------------------------

    def _list(self, app_label=None):
        from migcare.backup import list_snapshots

        qs = list_snapshots(app_label=app_label).select_related()
        if not qs.exists():
            self.stdout.write("No snapshots found.")
            return

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\n{'ID':>6}  {'App.Migration':<40}  {'Table/Column':<35}  "
                f"{'Rows':>6}  {'Created':>20}  {'Restored'}"
            )
        )
        self.stdout.write("-" * 120)
        for s in qs:
            target = f"{s.table_name}.{s.column_name}" if s.column_name else s.table_name
            restored = str(s.restored_at)[:19] if s.restored_at else "-"
            self.stdout.write(
                f"{s.pk:>6}  {s.app_label + '.' + s.migration_name:<40}  "
                f"{target:<35}  {s.row_count:>6}  "
                f"{str(s.created_at)[:19]:>20}  {restored}"
            )
        self.stdout.write("")

    def _restore(self, snapshot_id: int, options: dict):
        from migcare.backup import restore_snapshot
        from migcare.models import MigrationSnapshot

        try:
            snapshot = MigrationSnapshot.objects.get(pk=snapshot_id)
        except MigrationSnapshot.DoesNotExist:
            raise CommandError(
                f"Snapshot #{snapshot_id} not found. Use --list to see available snapshots."
            )

        target = (
            f"{snapshot.table_name}.{snapshot.column_name}"
            if snapshot.column_name
            else snapshot.table_name
        )

        self.stdout.write(
            f"\nAbout to restore snapshot #{snapshot.pk}:\n"
            f"  App/migration : {snapshot.app_label}.{snapshot.migration_name}\n"
            f"  Target        : {target}\n"
            f"  Rows          : {snapshot.row_count}\n"
            f"  Captured at   : {snapshot.created_at}\n"
            f"  Git branch    : {snapshot.git_branch or 'unknown'}\n"
        )

        if not options.get("force"):
            answer = input("Proceed with restore? [yes/N] ")
            if answer.strip().lower() != "yes":
                self.stdout.write("Aborted.")
                return

        try:
            rows_written = restore_snapshot(snapshot)
        except LookupError as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Restore complete — {rows_written} row(s) written to {target}."
            )
        )
