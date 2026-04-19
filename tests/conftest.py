import django
import pytest
from django.conf import settings


def pytest_configure(config):
    if not settings.configured:
        settings.configure(
            **{
                k: v
                for k, v in __import__("tests.settings", fromlist=["*"]).__dict__.items()
                if k.isupper()
            }
        )
