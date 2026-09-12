# -*- coding: utf-8 -*-
"""Báo cáo & vận hành (Master Plan mục 15, PHASE 15).

`SavedView` là toàn bộ mô hình dữ liệu của phần "Saved views" — cố ý mỏng.
Không có bảng riêng cho từng loại bộ lọc (`TalentSavedView`, `RBSavedView`...):
cả Talent Radar lẫn RB Radar đều lọc bằng query string (`?skills=SQL&location=...`),
nên một `filters` JSON dùng chung được — thêm bảng riêng cho từng module là
nhân bản không cần thiết cho đúng một khái niệm.

Không lưu SẴN kết quả (danh sách người/cơ hội tại thời điểm lưu) — chỉ lưu BỘ
LỌC. Mở lại một view đã lưu nghĩa là chạy lại đúng bộ lọc đó trên dữ liệu MỚI
NHẤT, không phải xem ảnh chụp cũ. Một "view đã lưu" mà không cập nhật theo dữ
liệu mới thì vô dụng hơn cả không lưu.
"""
from django.conf import settings
from django.db import models

MODULE_TALENT = "talent"
MODULE_RB = "rb"
MODULE_CHOICES = [
    (MODULE_TALENT, "Talent Radar"),
    (MODULE_RB, "RB Radar"),
]


class SavedView(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="saved_views")
    module = models.CharField(max_length=20, choices=MODULE_CHOICES, db_index=True)
    name = models.CharField(max_length=150)
    # Đúng bộ query param mà `talent.search()` / `rb.opportunity_list()` nhận —
    # không có định dạng thứ hai, giống nguyên tắc đã áp dụng cho AI Search
    # (mục 22): tìm bằng AI, tìm thủ công, và giờ thêm "mở lại view đã lưu" đều
    # đi qua đúng một ngôn ngữ bộ lọc.
    filters = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Bộ lọc đã lưu"
        verbose_name_plural = "Bộ lọc đã lưu"
        ordering = ["-last_used_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "module", "name"],
                                    name="uq_savedview_owner_module_name"),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_module_display()})"


class FilterHistory(models.Model):
    """Một bộ lọc đã thực sự chạy, riêng theo người dùng và module."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="filter_history")
    module = models.CharField(max_length=20, choices=MODULE_CHOICES, db_index=True)
    signature = models.CharField(max_length=64)
    filters = models.JSONField(default=dict)
    used_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lịch sử lọc"
        verbose_name_plural = "Lịch sử lọc"
        ordering = ["-used_at"]
        constraints = [models.UniqueConstraint(
            fields=["owner", "module", "signature"],
            name="uq_filterhistory_owner_module_signature")]
