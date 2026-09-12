# -*- coding: utf-8 -*-
"""Seed Canonical Registry cho các namespace ưu tiên (Master Plan §6.2).

    python manage.py seed_canonical

Idempotent — chạy lại chỉ cập nhật, không nhân đôi.
"""
from django.core.management.base import BaseCommand

from intel import seeds


class Command(BaseCommand):
    help = "Seed location/skill/job_title/seniority/education/industry vào Canonical Registry."

    def handle(self, *args, **options):
        seeds.seed_all(stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS("Đã seed Canonical Registry."))
