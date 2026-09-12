# -*- coding: utf-8 -*-
from django.apps import AppConfig


class TalentConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "talent"
    verbose_name = "Talent Radar"

    def ready(self):
        from . import signals  # noqa: F401
