"""
A deliberately destructive migration used by the test suite to exercise
the analysis and backup pipelines.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("testapp", "0001_initial")]

    operations = [
        migrations.RemoveField(model_name="article", name="legacy_tag"),
    ]
