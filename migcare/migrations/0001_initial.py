from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="MigrationSnapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("app_label", models.CharField(max_length=255)),
                ("migration_name", models.CharField(max_length=255)),
                (
                    "operation_type",
                    models.CharField(
                        choices=[
                            ("forward", "Forward migration"),
                            ("rollback", "Rollback"),
                            ("manual", "Manual backup"),
                        ],
                        max_length=20,
                    ),
                ),
                ("table_name", models.CharField(max_length=255)),
                (
                    "column_name",
                    models.CharField(
                        blank=True,
                        help_text="Empty means the entire table was captured.",
                        max_length=255,
                    ),
                ),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("data", models.JSONField(default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("git_branch", models.CharField(blank=True, max_length=255)),
                ("git_commit", models.CharField(blank=True, max_length=40)),
                ("restored_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
            ],
            options={
                "verbose_name": "Migration Snapshot",
                "verbose_name_plural": "Migration Snapshots",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="migrationsnapshot",
            index=models.Index(
                fields=["app_label", "migration_name"],
                name="migcare_mig_app_lab_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="migrationsnapshot",
            index=models.Index(
                fields=["table_name", "column_name"],
                name="migcare_mig_table_n_idx",
            ),
        ),
    ]
