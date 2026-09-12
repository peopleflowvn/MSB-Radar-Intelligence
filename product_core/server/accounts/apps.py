# -*- coding: utf-8 -*-
from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _create_role_groups(sender, **kwargs):
    from .roles import ensure_groups
    ensure_groups()


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Người dùng & Nhật ký truy cập"

    def ready(self):
        # post_migrate chứ KHÔNG truy vấn thẳng trong ready(): Django cấm chạm
        # CSDL lúc nạp app — làm vậy sẽ hỏng `migrate` trên CSDL trắng và làm
        # chậm mọi lệnh quản trị.
        post_migrate.connect(_create_role_groups, sender=self)
