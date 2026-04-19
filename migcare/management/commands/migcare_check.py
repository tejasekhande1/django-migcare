"""
``migcare_check`` — inspect the current migration and snapshot state.

Usage::

    python manage.py migcare_check
    python manage.py migcare_check --app myapp
    python manage.py migcare_check --json
    python manage.py migcare_check --git-post-checkout <prev_ref> <new_ref>
"""

from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = (
        "Inspect migration state and detect data-loss risks. "
        "Also called automatically by the django-migcare git post-checkout hook."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--app",
            dest="app_label",
            metavar="APP",
            help="Limit analysis to a specific app.",
        )
        parser.add_argument(
            "--database",
            default="default",
            help="Database alias to inspect (default: 'default').",
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Emit results as machine-readable JSON.",
        )
        parser.add_argument(
            "--git-post-checkout",
            nargs=2,
            metavar=("PREV_REF", "NEW_REF"),
            dest="git_refs",
            help=(
                "Internal: called by the git post-checkout hook with the "
                "previous and new HEAD refs."
            ),
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        db = options["database"]
        app_label = options.get("app_label")
        as_json = options["as_json"]
        git_refs = options.get("git_refs")

        result: dict = {}

        # ------------------------------------------------------------------
        # 1. Unapplied / pending migrations
        # ------------------------------------------------------------------
        try:
            pending = self._get_pending(db, app_label)
            result["pending"] = pending
        except Exception as exc:
            self.stderr.write(f"django-migcare: could not read migration state: {exc}")
            pending = []
            result["pending"] = []

        # ------------------------------------------------------------------
        # 2. Risk analysis of pending plan
        # ------------------------------------------------------------------
        try:
            risk_summary = self._get_risk_summary(db, app_label)
            result["risks"] = risk_summary
        except Exception as exc:
            self.stderr.write(f"django-migcare: could not analyse plan: {exc}")
            risk_summary = {"dangers": [], "warnings": [], "max_risk": "safe"}
            result["risks"] = risk_summary

        # ------------------------------------------------------------------
        # 3. Existing snapshots
        # ------------------------------------------------------------------
        try:
            snapshots = self._get_snapshot_summary(app_label)
            result["snapshots"] = snapshots
        except Exception as exc:
            self.stderr.write(f"django-migcare: could not read snapshots: {exc}")
            result["snapshots"] = []

        # ------------------------------------------------------------------
        # 4. Ghost-migration detection (post-checkout mode)
        # ------------------------------------------------------------------
        if git_refs:
            from migcare.git_hooks import detect_ghost_migrations

            prev_ref, new_ref = git_refs
            try:
                ghosts = detect_ghost_migrations(prev_ref, new_ref)
                result["ghost_migrations"] = [
                    {"app": a, "name": n} for a, n in ghosts
                ]
            except Exception as exc:
                self.stderr.write(f"django-migcare: ghost-migration check failed: {exc}")
                result["ghost_migrations"] = []
        else:
            result["ghost_migrations"] = []

        # ------------------------------------------------------------------
        # Output
        # ------------------------------------------------------------------
        if as_json:
            self.stdout.write(json.dumps(result, indent=2, default=str))
            return

        self._print_human(result, git_refs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_pending(self, db: str, app_label=None) -> list:
        from django.db.migrations.executor import MigrationExecutor

        conn = connections[db]
        executor = MigrationExecutor(conn)
        loader = executor.loader
        targets = loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)

        pending = []
        for migration, is_backward in plan:
            if app_label and migration.app_label != app_label:
                continue
            pending.append(
                {
                    "app": migration.app_label,
                    "migration": migration.name,
                    "direction": "backward" if is_backward else "forward",
                }
            )
        return pending

    def _get_risk_summary(self, db: str, app_label=None) -> dict:
        from django.db.migrations.executor import MigrationExecutor

        from migcare.analysis import analyze_plan

        conn = connections[db]
        executor = MigrationExecutor(conn)
        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)

        if app_label:
            plan = [(m, b) for m, b in plan if m.app_label == app_label]

        report = analyze_plan(plan)
        return {
            "max_risk": report.max_risk.value,
            "dangers": [
                {
                    "app": r.app_label,
                    "migration": r.migration_name,
                    "message": r.message,
                    "table": r.table_name,
                    "column": r.column_name,
                }
                for r in report.dangers
            ],
            "warnings": [
                {
                    "app": r.app_label,
                    "migration": r.migration_name,
                    "message": r.message,
                }
                for r in report.warnings
            ],
        }

    def _get_snapshot_summary(self, app_label=None) -> list:
        from migcare.models import MigrationSnapshot

        qs = MigrationSnapshot.objects.all()
        if app_label:
            qs = qs.filter(app_label=app_label)
        qs = qs.order_by("-created_at")[:20]
        return [
            {
                "id": s.pk,
                "app": s.app_label,
                "migration": s.migration_name,
                "table": s.table_name,
                "column": s.column_name or "(full table)",
                "rows": s.row_count,
                "created_at": str(s.created_at),
                "restored_at": str(s.restored_at) if s.restored_at else None,
                "branch": s.git_branch,
            }
            for s in qs
        ]

    # ------------------------------------------------------------------

    def _print_human(self, result: dict, git_refs) -> None:
        style = self.style

        # --- Pending migrations ---
        pending = result["pending"]
        if pending:
            self.stdout.write(style.MIGRATE_HEADING(f"\nPending migrations ({len(pending)}):"))
            for p in pending:
                direction = "(rollback)" if p["direction"] == "backward" else ""
                self.stdout.write(f"  {p['app']}.{p['migration']} {direction}")
        else:
            self.stdout.write(style.SUCCESS("\nNo pending migrations."))

        # --- Risk analysis ---
        risks = result["risks"]
        if risks["dangers"]:
            self.stdout.write(
                style.ERROR(f"\nDANGER — {len(risks['dangers'])} destructive operation(s):")
            )
            for d in risks["dangers"]:
                self.stdout.write(style.ERROR(f"  • {d['message']}"))
        if risks["warnings"]:
            self.stdout.write(
                style.WARNING(f"\nWARNING — {len(risks['warnings'])} caution item(s):")
            )
            for w in risks["warnings"]:
                self.stdout.write(style.WARNING(f"  • {w['message']}"))
        if not risks["dangers"] and not risks["warnings"]:
            self.stdout.write(style.SUCCESS("\nNo data-loss risks in pending plan."))

        # --- Snapshots ---
        snaps = result["snapshots"]
        if snaps:
            self.stdout.write(style.MIGRATE_HEADING(f"\nRecent snapshots ({len(snaps)} shown):"))
            for s in snaps:
                restored = " [RESTORED]" if s["restored_at"] else ""
                self.stdout.write(
                    f"  #{s['id']:>4}  {s['app']}.{s['migration']}  "
                    f"{s['table']}.{s['column']}  "
                    f"{s['rows']} rows  {s['created_at']}{restored}"
                )
        else:
            self.stdout.write("\nNo snapshots on record.")

        # --- Ghost migrations (post-checkout) ---
        ghosts = result.get("ghost_migrations", [])
        if ghosts:
            self.stdout.write(
                style.ERROR(
                    f"\nGHOST MIGRATIONS — {len(ghosts)} migration(s) applied in DB "
                    "but missing from the current branch:"
                )
            )
            for g in ghosts:
                self.stdout.write(style.ERROR(f"  • {g['app']}.{g['name']}"))
            self.stdout.write(
                style.WARNING(
                    "\n  To resolve: run `python manage.py migrate` to reconcile, "
                    "or switch back to the branch where these migrations were created."
                )
            )
        elif git_refs:
            self.stdout.write(style.SUCCESS("\nNo ghost migrations detected after branch switch."))

        self.stdout.write("")
