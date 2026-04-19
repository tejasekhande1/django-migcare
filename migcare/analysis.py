"""
Migration plan analysis — identifies operations that can cause data loss.

Usage::

    from django.db import connection
    from django.db.migrations.executor import MigrationExecutor
    from migcare.analysis import analyze_plan

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(targets)
    report = analyze_plan(plan)

    if not report.is_safe:
        for risk in report.dangers:
            print(risk.message)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from django.db.migrations import Migration

# ---------------------------------------------------------------------------
# Risk levels
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    SAFE = "safe"
    WARNING = "warning"
    DANGER = "danger"

    def __lt__(self, other: "RiskLevel") -> bool:  # type: ignore[override]
        order = [RiskLevel.SAFE, RiskLevel.WARNING, RiskLevel.DANGER]
        return order.index(self) < order.index(other)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class OperationRisk:
    """A single data-loss risk identified in a migration plan."""

    operation_class: str
    direction: str  # "forward" | "backward"
    risk: RiskLevel
    message: str
    app_label: str
    migration_name: str
    table_name: Optional[str] = None
    column_name: Optional[str] = None

    @property
    def label(self) -> str:
        return f"{self.app_label}.{self.migration_name}"


@dataclass
class PlanReport:
    """Aggregate analysis result for a full migration plan."""

    risks: List[OperationRisk] = field(default_factory=list)

    @property
    def max_risk(self) -> RiskLevel:
        if any(r.risk == RiskLevel.DANGER for r in self.risks):
            return RiskLevel.DANGER
        if any(r.risk == RiskLevel.WARNING for r in self.risks):
            return RiskLevel.WARNING
        return RiskLevel.SAFE

    @property
    def is_safe(self) -> bool:
        return self.max_risk == RiskLevel.SAFE

    @property
    def dangers(self) -> List[OperationRisk]:
        return [r for r in self.risks if r.risk == RiskLevel.DANGER]

    @property
    def warnings(self) -> List[OperationRisk]:
        return [r for r in self.risks if r.risk == RiskLevel.WARNING]

    def has_table_drop(self) -> bool:
        return any(
            r.table_name and not r.column_name and r.risk == RiskLevel.DANGER
            for r in self.risks
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_plan(plan: list) -> PlanReport:
    """
    Analyse a Django migration plan for data-loss risks.

    *plan* is the list of ``(migration, is_backwards)`` tuples returned by
    ``MigrationExecutor.migration_plan()``.
    """
    report = PlanReport()
    for migration, is_backward in plan:
        for operation in migration.operations:
            report.risks.extend(
                _analyze_operation(operation, is_backward, migration)
            )
    return report


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _table(app: str, model_name: str) -> str:
    return f"{app}_{model_name.lower()}"


def _analyze_operation(operation, is_backward: bool, migration) -> list:
    """Return a (possibly empty) list of OperationRisk for one operation."""
    # Import here to avoid module-level django setup requirement in tests.
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

    app = migration.app_label
    name = migration.name
    op_cls = type(operation).__name__
    direction = "backward" if is_backward else "forward"
    risks: list = []

    # ------------------------------------------------------------------
    # RemoveField forward → drops column
    # AddField backward  → drops column  (rollback of an AddField)
    # ------------------------------------------------------------------
    if isinstance(operation, RemoveField) and not is_backward:
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.DANGER,
                message=(
                    f"[DANGER] {app}.{name}: RemoveField will DROP column "
                    f"'{operation.name}' from '{operation.model_name}' — "
                    "all data in that column will be permanently lost."
                ),
                app_label=app,
                migration_name=name,
                table_name=_table(app, operation.model_name),
                column_name=operation.name,
            )
        )

    elif isinstance(operation, AddField) and is_backward:
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.DANGER,
                message=(
                    f"[DANGER] {app}.{name}: Rolling back AddField will DROP column "
                    f"'{operation.name}' from '{operation.model_name}' — "
                    "all data in that column will be permanently lost."
                ),
                app_label=app,
                migration_name=name,
                table_name=_table(app, operation.model_name),
                column_name=operation.name,
            )
        )

    # ------------------------------------------------------------------
    # DeleteModel forward → drops table
    # CreateModel backward → drops table  (rollback of a CreateModel)
    # ------------------------------------------------------------------
    elif isinstance(operation, DeleteModel) and not is_backward:
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.DANGER,
                message=(
                    f"[DANGER] {app}.{name}: DeleteModel will DROP the table "
                    f"for '{operation.name}' — all rows will be permanently lost."
                ),
                app_label=app,
                migration_name=name,
                table_name=_table(app, operation.name),
            )
        )

    elif isinstance(operation, CreateModel) and is_backward:
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.DANGER,
                message=(
                    f"[DANGER] {app}.{name}: Rolling back CreateModel will DROP "
                    f"the table for '{operation.name}' — all rows will be permanently lost."
                ),
                app_label=app,
                migration_name=name,
                table_name=_table(app, operation.name),
            )
        )

    # ------------------------------------------------------------------
    # AlterField — may silently truncate data depending on the DB engine
    # ------------------------------------------------------------------
    elif isinstance(operation, AlterField):
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.WARNING,
                message=(
                    f"[WARNING] {app}.{name}: AlterField on "
                    f"'{operation.model_name}.{operation.name}' may truncate or "
                    "coerce data if the column type is narrowed."
                ),
                app_label=app,
                migration_name=name,
                table_name=_table(app, operation.model_name),
                column_name=operation.name,
            )
        )

    # ------------------------------------------------------------------
    # RenameField / RenameModel — data-preserving but breaks references
    # ------------------------------------------------------------------
    elif isinstance(operation, RenameField):
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.WARNING,
                message=(
                    f"[WARNING] {app}.{name}: RenameField renames "
                    f"'{operation.model_name}.{operation.old_name}' → "
                    f"'{operation.new_name}' — data is preserved but any raw SQL "
                    "or external references using the old name will break."
                ),
                app_label=app,
                migration_name=name,
            )
        )

    elif isinstance(operation, RenameModel):
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.WARNING,
                message=(
                    f"[WARNING] {app}.{name}: RenameModel renames "
                    f"'{operation.old_name}' → '{operation.new_name}' — "
                    "data is preserved but external references will break."
                ),
                app_label=app,
                migration_name=name,
            )
        )

    # ------------------------------------------------------------------
    # RunSQL / RunPython — opaque; always warn
    # ------------------------------------------------------------------
    elif isinstance(operation, RunSQL):
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.WARNING,
                message=(
                    f"[WARNING] {app}.{name}: RunSQL contains raw SQL — "
                    "django-migcare cannot automatically assess its safety."
                ),
                app_label=app,
                migration_name=name,
            )
        )

    elif isinstance(operation, RunPython):
        risks.append(
            OperationRisk(
                operation_class=op_cls,
                direction=direction,
                risk=RiskLevel.WARNING,
                message=(
                    f"[WARNING] {app}.{name}: RunPython contains custom code — "
                    "django-migcare cannot automatically assess its safety."
                ),
                app_label=app,
                migration_name=name,
            )
        )

    return risks
