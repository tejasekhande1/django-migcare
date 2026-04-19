"""
Integration tests for migcare.backup — require a real (in-memory SQLite) DB.
"""

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_article(**kwargs):
    from tests.testapp.models import Article

    defaults = {"title": "Hello", "body": "World"}
    defaults.update(kwargs)
    return Article.objects.create(**defaults)


# ---------------------------------------------------------------------------
# create_snapshot
# ---------------------------------------------------------------------------


class TestCreateSnapshot:
    def test_full_table_snapshot(self):
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        _create_article(title="Article A")
        _create_article(title="Article B")

        snap = create_snapshot(
            app_label="testapp",
            migration_name="0001_initial",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="testapp_article",
        )

        assert snap.pk is not None
        assert snap.row_count == 2
        assert snap.column_name == ""
        assert len(snap.data) == 2
        assert "title" in snap.data[0]
        assert "body" in snap.data[0]

    def test_column_only_snapshot(self):
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        _create_article(body="important_content")

        snap = create_snapshot(
            app_label="testapp",
            migration_name="0001_initial",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="testapp_article",
            column_name="body",
        )

        assert snap.column_name == "body"
        assert snap.row_count == 1
        # Column snapshot stores id + column_name only
        row = snap.data[0]
        assert "body" in row
        assert "id" in row
        assert "title" not in row

    def test_nonexistent_table_raises(self):
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        with pytest.raises(LookupError, match="does not exist"):
            create_snapshot(
                app_label="testapp",
                migration_name="0002",
                operation_type=MigrationSnapshot.MANUAL,
                table_name="nonexistent_table_xyz",
            )

    def test_nonexistent_column_raises(self):
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        with pytest.raises(LookupError, match="column"):
            create_snapshot(
                app_label="testapp",
                migration_name="0002",
                operation_type=MigrationSnapshot.MANUAL,
                table_name="testapp_article",
                column_name="ghost_column",
            )

    def test_row_limit_truncates(self, settings):
        from migcare.backup import create_snapshot
        from migcare.models import MigrationSnapshot

        settings.MIGCARE = {"BACKUP_ROW_LIMIT": 1, "AUTO_BACKUP": False,
                             "REQUIRE_CONFIRMATION": False, "MAX_BACKUP_AGE_DAYS": 30}

        for i in range(3):
            _create_article(title=f"Article {i}")

        import warnings

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            snap = create_snapshot(
                app_label="testapp",
                migration_name="0001",
                operation_type=MigrationSnapshot.MANUAL,
                table_name="testapp_article",
            )
        assert snap.row_count == 1
        assert any("BACKUP_ROW_LIMIT" in str(warning.message) for warning in w)


# ---------------------------------------------------------------------------
# restore_snapshot — column level
# ---------------------------------------------------------------------------


class TestRestoreSnapshot:
    def test_column_restore(self):
        from migcare.backup import create_snapshot, restore_snapshot
        from migcare.models import MigrationSnapshot
        from tests.testapp.models import Article

        article = _create_article(body="original_body")

        snap = create_snapshot(
            app_label="testapp",
            migration_name="0001",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="testapp_article",
            column_name="body",
        )

        # Simulate data loss by clearing the column
        Article.objects.filter(pk=article.pk).update(body="")

        rows = restore_snapshot(snap)
        assert rows == 1

        article.refresh_from_db()
        assert article.body == "original_body"

        snap.refresh_from_db()
        assert snap.restored_at is not None

    def test_restore_nonexistent_table_raises(self):
        from migcare.backup import restore_snapshot
        from migcare.models import MigrationSnapshot

        snap = MigrationSnapshot(
            app_label="x",
            migration_name="0001",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="ghost_table_xyz",
            column_name="",
            row_count=1,
            data=[{"id": 1, "foo": "bar"}],
        )
        snap.save()

        with pytest.raises(LookupError, match="does not exist"):
            restore_snapshot(snap)


# ---------------------------------------------------------------------------
# purge_old_snapshots
# ---------------------------------------------------------------------------


class TestPurgeOldSnapshots:
    def test_purges_old(self):
        from datetime import timedelta

        from django.utils import timezone

        from migcare.backup import purge_old_snapshots
        from migcare.models import MigrationSnapshot

        old = MigrationSnapshot.objects.create(
            app_label="testapp",
            migration_name="0001",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="testapp_article",
            data=[],
        )
        # Force the created_at to be 40 days ago
        MigrationSnapshot.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=40)
        )

        deleted = purge_old_snapshots()
        assert deleted >= 1
        assert not MigrationSnapshot.objects.filter(pk=old.pk).exists()

    def test_skips_recent(self):
        from migcare.backup import purge_old_snapshots
        from migcare.models import MigrationSnapshot

        recent = MigrationSnapshot.objects.create(
            app_label="testapp",
            migration_name="0001",
            operation_type=MigrationSnapshot.MANUAL,
            table_name="testapp_article",
            data=[],
        )

        purge_old_snapshots()
        assert MigrationSnapshot.objects.filter(pk=recent.pk).exists()
