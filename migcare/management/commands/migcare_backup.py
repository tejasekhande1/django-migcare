"""
``migcare_backup`` — manually snapshot a table or column.

Usage::

    python manage.py migcare_backup myapp 0003_remove_email
    python manage.py migcare_backup myapp 0003_remove_email --table myapp_user --column email
    python manage.py migcare_backup myapp 0003_remove_email --table myapp_user
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Manually create a data snapshot before running a risky migration."

    def add_arguments(self, parser):
        parser.add_argument("app_label", help="The app label for the migration.")
        parser.add_argument(
            "migration_name",
            help="The migration name this snapshot is associated with.",
        )
        parser.add_argument(
            "--table",
            dest="table_name",
            required=True,
            help="Database table to snapshot (e.g. myapp_user).",
        )
        parser.add_argument(
            "--column",
            dest="column_name",
            default="",
            help="If given, only this column (plus the PK) is captured.",
        )
        parser.add_argument(
            "--notes",
            default="",
            help="Optional free-text note attached to the snapshot.",
        )

    def handle(self, *args, **options):
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        app_label = options["app_label"]
        migration_name = options["migration_name"]
        table_name = options["table_name"]
        column_name = options.get("column_name") or ""
        notes = options.get("notes") or ""

        self.stdout.write(
            f"django-migcare: snapshotting "
            f"{'column ' + column_name + ' in ' if column_name else ''}"
            f"table {table_name} …"
        )

        try:
            snap = create_snapshot(
                app_label=app_label,
                migration_name=migration_name,
                operation_type=MigrationSnapshot.MANUAL,
                table_name=table_name,
                column_name=column_name,
                notes=notes,
            )
        except LookupError as exc:
            raise CommandError(str(exc)) from exc

        target = f"{table_name}.{column_name}" if column_name else table_name
        self.stdout.write(
            self.style.SUCCESS(
                f"Snapshot #{snap.pk} created: {target} — {snap.row_count} rows captured."
            )
        )
