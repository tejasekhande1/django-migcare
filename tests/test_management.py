"""
Tests for management commands.
"""

import pytest
from django.core.management import call_command
from io import StringIO

pytestmark = pytest.mark.django_db


class TestMigcareCheck:
    def test_runs_without_error(self):
        out = StringIO()
        call_command("migcare_check", stdout=out, stderr=StringIO())
        # Should not raise

    def test_json_output_is_valid(self):
        import json

        out = StringIO()
        call_command("migcare_check", json=True, stdout=out, stderr=StringIO())
        data = json.loads(out.getvalue())
        assert "pending" in data
        assert "risks" in data
        assert "snapshots" in data
        assert "ghost_migrations" in data

    def test_app_filter(self):
        out = StringIO()
        call_command("migcare_check", app_label="testapp", stdout=out, stderr=StringIO())
        # Should not raise


class TestMigcareBackup:
    def test_backup_creates_snapshot(self):
        from tests.testapp.models import Article
        from migcare.models import MigrationSnapshot

        Article.objects.create(title="T", body="B")
        initial_count = MigrationSnapshot.objects.count()

        call_command(
            "migcare_backup",
            "testapp",
            "0001_initial",
            table_name="testapp_article",
            column_name="body",
            stdout=StringIO(),
            stderr=StringIO(),
        )

        assert MigrationSnapshot.objects.count() == initial_count + 1

    def test_backup_bad_table_errors(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            call_command(
                "migcare_backup",
                "testapp",
                "0002",
                table="does_not_exist",
                stdout=StringIO(),
                stderr=StringIO(),
            )


class TestMigcareRestore:
    def test_list_shows_snapshots(self):
        from migcare.models import MigrationSnapshot

        MigrationSnapshot.objects.create(
            app_label="testapp",
            migration_name="0002",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="testapp_article",
            column_name="legacy_tag",
            row_count=3,
            data=[],
        )

        out = StringIO()
        call_command("migcare_restore", list_mode=True, stdout=out, stderr=StringIO())
        output = out.getvalue()
        assert "testapp" in output

    def test_restore_missing_snapshot_errors(self):
        from django.core.management.base import CommandError

        with pytest.raises(CommandError, match="not found"):
            call_command(
                "migcare_restore",
                snapshot_id=999999,
                force=True,
                stdout=StringIO(),
                stderr=StringIO(),
            )


class TestMigcareInstallHooks:
    def test_install_and_remove(self, tmp_path):
        """install_hooks should work in a temporary git repo."""
        import subprocess

        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)

        hook_path = tmp_path / ".git" / "hooks" / "post-checkout"

        out = StringIO()
        call_command(
            "migcare_install_hooks",
            project_root=str(tmp_path),
            stdout=out,
            stderr=StringIO(),
        )
        assert hook_path.exists()
        assert "migcare" in hook_path.read_text()

        out2 = StringIO()
        call_command(
            "migcare_install_hooks",
            project_root=str(tmp_path),
            remove=True,
            stdout=out2,
            stderr=StringIO(),
        )
        assert not hook_path.exists()

    def test_install_preserves_existing_hook(self, tmp_path):
        import stat
        import subprocess

        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        hooks_dir = tmp_path / ".git" / "hooks"
        hooks_dir.mkdir(exist_ok=True)
        hook_path = hooks_dir / "post-checkout"
        hook_path.write_text("#!/bin/bash\n# existing hook\nexit 0\n")
        hook_path.chmod(hook_path.stat().st_mode | stat.S_IEXEC)

        call_command(
            "migcare_install_hooks",
            project_root=str(tmp_path),
            stdout=StringIO(),
            stderr=StringIO(),
        )

        content = hook_path.read_text()
        assert "# existing hook" in content
        assert "migcare" in content
