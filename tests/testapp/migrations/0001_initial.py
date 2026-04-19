from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies: list = []

    operations = [
        migrations.CreateModel(
            name="Article",
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
                ("title", models.CharField(max_length=255)),
                ("body", models.TextField()),
                ("legacy_tag", models.CharField(blank=True, max_length=50)),
            ],
        ),
    ]
