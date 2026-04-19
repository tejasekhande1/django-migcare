from django.db import models


class MigrationSnapshot(models.Model):
    """Stores a data snapshot taken before a destructive migration operation."""

    FORWARD = "forward"
    ROLLBACK = "rollback"
    MANUAL = "manual"
    OPERATION_CHOICES = [
        (FORWARD, "Forward migration"),
        (ROLLBACK, "Rollback"),
        (MANUAL, "Manual backup"),
    ]

    # --- What triggered this snapshot ---
    app_label = models.CharField(max_length=255)
    migration_name = models.CharField(max_length=255)
    operation_type = models.CharField(max_length=20, choices=OPERATION_CHOICES)

    # --- What was captured ---
    # table_name is always set; column_name is set only for column-level backups.
    table_name = models.CharField(max_length=255)
    column_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Empty means the entire table was captured.",
    )
    row_count = models.PositiveIntegerField(default=0)

    # --- Serialized data ---
    # List of dicts, e.g. [{"id": 1, "email": "a@b.com"}, ...]
    data = models.JSONField(default=list)

    # --- Context ---
    created_at = models.DateTimeField(auto_now_add=True)
    git_branch = models.CharField(max_length=255, blank=True)
    git_commit = models.CharField(max_length=40, blank=True)

    # --- Restore tracking ---
    restored_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        app_label = "migcare"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["app_label", "migration_name"]),
            models.Index(fields=["table_name", "column_name"]),
        ]
        verbose_name = "Migration Snapshot"
        verbose_name_plural = "Migration Snapshots"

    def __str__(self) -> str:
        target = (
            f"{self.table_name}.{self.column_name}"
            if self.column_name
            else self.table_name
        )
        return (
            f"Snapshot({self.app_label}.{self.migration_name} → {target} "
            f"@ {self.created_at:%Y-%m-%d %H:%M})"
        )
