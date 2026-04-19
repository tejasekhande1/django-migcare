"""
Unit tests for migcare.analysis — no database required.
"""

import pytest
from django.db.migrations import Migration
from django.db.migrations.operations.fields import (
    AddField,
    AlterField,
    RemoveField,
    RenameField,
)
from django.db.migrations.operations.models import (
    CreateModel,
    DeleteModel,
    RenameModel,
)
from django.db.migrations.operations.special import RunPython, RunSQL
from django.db.models import CharField, TextField

from migcare.analysis import RiskLevel, analyze_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_migration(app_label: str, name: str, operations: list) -> Migration:
    m = Migration(name, app_label)
    m.operations = operations
    return m


def plan(migration, is_backward=False):
    return [(migration, is_backward)]


# ---------------------------------------------------------------------------
# Forward migrations
# ---------------------------------------------------------------------------


class TestForwardDestructive:
    def test_remove_field_is_danger(self):
        m = make_migration("myapp", "0002", [RemoveField("mymodel", "email")])
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.DANGER
        assert len(report.dangers) == 1
        assert "email" in report.dangers[0].message

    def test_delete_model_is_danger(self):
        m = make_migration("myapp", "0002", [DeleteModel("OldModel")])
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.DANGER
        assert "OldModel" in report.dangers[0].message

    def test_alter_field_is_warning(self):
        m = make_migration(
            "myapp",
            "0002",
            [AlterField("mymodel", "title", TextField())],
        )
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.WARNING
        assert len(report.dangers) == 0

    def test_run_sql_is_warning(self):
        m = make_migration("myapp", "0002", [RunSQL("DROP INDEX foo")])
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.WARNING

    def test_run_python_is_warning(self):
        m = make_migration("myapp", "0002", [RunPython(lambda apps, schema: None)])
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.WARNING

    def test_rename_field_is_warning(self):
        m = make_migration("myapp", "0002", [RenameField("mymodel", "old_name", "new_name")])
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.WARNING

    def test_rename_model_is_warning(self):
        m = make_migration("myapp", "0002", [RenameModel("OldModel", "NewModel")])
        report = analyze_plan(plan(m, is_backward=False))
        assert report.max_risk == RiskLevel.WARNING

    def test_create_model_forward_is_safe(self):
        m = make_migration(
            "myapp",
            "0001",
            [CreateModel("Brand", [("id", CharField(primary_key=True, max_length=10))])],
        )
        report = analyze_plan(plan(m, is_backward=False))
        assert report.is_safe

    def test_add_field_forward_is_safe(self):
        m = make_migration(
            "myapp", "0002", [AddField("mymodel", "new_col", CharField(max_length=10))]
        )
        report = analyze_plan(plan(m, is_backward=False))
        assert report.is_safe


# ---------------------------------------------------------------------------
# Backward (rollback) migrations
# ---------------------------------------------------------------------------


class TestRollbackDestructive:
    def test_add_field_backward_is_danger(self):
        m = make_migration(
            "myapp", "0002", [AddField("mymodel", "email", CharField(max_length=255))]
        )
        report = analyze_plan(plan(m, is_backward=True))
        assert report.max_risk == RiskLevel.DANGER
        assert "email" in report.dangers[0].message

    def test_create_model_backward_is_danger(self):
        m = make_migration(
            "myapp",
            "0001",
            [CreateModel("Brand", [("id", CharField(primary_key=True, max_length=10))])],
        )
        report = analyze_plan(plan(m, is_backward=True))
        assert report.max_risk == RiskLevel.DANGER
        assert "Brand" in report.dangers[0].message

    def test_remove_field_backward_is_safe(self):
        # Backwards of RemoveField just re-adds the column — no data loss.
        m = make_migration("myapp", "0002", [RemoveField("mymodel", "email")])
        report = analyze_plan(plan(m, is_backward=True))
        assert report.is_safe

    def test_delete_model_backward_is_safe(self):
        # Backwards of DeleteModel re-creates the table — no data loss.
        m = make_migration("myapp", "0002", [DeleteModel("OldModel")])
        report = analyze_plan(plan(m, is_backward=True))
        assert report.is_safe


# ---------------------------------------------------------------------------
# Multi-operation plans
# ---------------------------------------------------------------------------


class TestMultiOperationPlan:
    def test_mixed_plan_max_risk_is_danger(self):
        m1 = make_migration("myapp", "0002", [AlterField("m", "f", TextField())])
        m2 = make_migration("myapp", "0003", [RemoveField("m", "secret")])
        report = analyze_plan([(m1, False), (m2, False)])
        assert report.max_risk == RiskLevel.DANGER
        assert len(report.warnings) == 1
        assert len(report.dangers) == 1

    def test_empty_plan_is_safe(self):
        report = analyze_plan([])
        assert report.is_safe

    def test_table_name_inferred(self):
        m = make_migration("myapp", "0002", [RemoveField("UserProfile", "bio")])
        report = analyze_plan(plan(m, is_backward=False))
        risk = report.dangers[0]
        assert risk.table_name == "myapp_userprofile"
        assert risk.column_name == "bio"
