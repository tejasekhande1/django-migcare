from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=255)
    body = models.TextField()
    # legacy_tag was removed in migration 0002_remove_legacy_tag

    class Meta:
        app_label = "testapp"
