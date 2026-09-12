# -*- coding: utf-8 -*-
"""Bàn dựng (staging) cho luồng nhập liệu ứng viên thủ công.

Master Plan §2 (Edge-first), §21.3 (extraction qua queue vận hành): dữ liệu người
dùng nhập KHÔNG được ghi thẳng vào bàn nhận `SourceRecord`. Nó dừng ở đây trước —
người dùng xem lưới, sửa lỗi, bỏ qua dòng — rồi mới `commit` sang `SourceRecord`
qua đúng pipeline Edge (bàn nhận → phân giải Person → derive TalentProfile).

`ImportBatch`/`ImportRow` là bản nháp có thể xoá; sau khi commit chúng chỉ còn giá
trị lịch sử ("lô này ai nhập, lúc nào, kết quả ra sao"). Nguồn sự thật vẫn là
`SourceRecord`.

**Metadata "ai nhập / lô nào" nằm ở đây, KHÔNG vào `SourceRecord.payload`** — nếu
lọt vào payload thì `content_hash` đổi theo từng lô và phá tính idempotent khi
cùng một người được nhập lại ở lô khác.
"""
from django.conf import settings
from django.db import models


class ImportBatch(models.Model):
    """Một lần người dùng nạp một tệp Excel/CSV, hoặc một mớ CV."""

    KIND_EXCEL = "excel"
    KIND_BULK_CV = "bulk_cv"
    KIND_CHOICES = [
        (KIND_EXCEL, "Excel/CSV"),
        (KIND_BULK_CV, "Nhiều CV"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_COMMITTING = "committing"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Nháp — chờ xác nhận"),
        (STATUS_COMMITTING, "Đang ghi"),
        (STATUS_DONE, "Đã ghi"),
        (STATUS_FAILED, "Ghi lỗi"),
    ]

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="import_batches")
    created_by_name = models.CharField(max_length=150, blank=True, default="")

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_EXCEL)
    source_label = models.CharField(
        max_length=40, blank=True, default="",
        help_text="Nguồn thu nhận gán cho cả lô; từng dòng có thể ghi đè bằng cột Nguồn.")
    original_filename = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT, db_index=True)

    row_count = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    duplicate_count = models.PositiveIntegerField(default=0)
    invalid_count = models.PositiveIntegerField(default=0)
    committed_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    notes = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Lô nhập liệu"
        verbose_name_plural = "Lô nhập liệu"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"Lô #{self.pk} ({self.get_kind_display()}, {self.row_count} dòng)"

    def save(self, *args, **kwargs):
        if self.created_by_id and not self.created_by_name:
            self.created_by_name = str(self.created_by)[:150]
        return super().save(*args, **kwargs)

    def recount(self):
        """Đếm lại các bộ đếm từ `rows`. Gọi sau validate/commit."""
        rows = self.rows.all()
        self.row_count = len(rows)
        self.valid_count = sum(r.validation_status == ImportRow.STATUS_VALID for r in rows)
        self.duplicate_count = sum(r.validation_status == ImportRow.STATUS_DUPLICATE for r in rows)
        self.invalid_count = sum(r.validation_status == ImportRow.STATUS_INVALID for r in rows)
        self.committed_count = sum(r.validation_status == ImportRow.STATUS_COMMITTED for r in rows)
        self.error_count = sum(r.validation_status == ImportRow.STATUS_ERROR for r in rows)
        self.save(update_fields=["row_count", "valid_count", "duplicate_count",
                                 "invalid_count", "committed_count", "error_count",
                                 "updated_at"])


class ImportRow(models.Model):
    """Một dòng của lô — một ứng viên chờ ghi vào hệ thống."""

    STATUS_VALID = "valid"
    STATUS_DUPLICATE = "duplicate"
    STATUS_INVALID = "invalid"
    STATUS_SKIPPED = "skipped"
    STATUS_COMMITTED = "committed"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_VALID, "Hợp lệ"),
        (STATUS_DUPLICATE, "Trùng — đã có trong hệ thống"),
        (STATUS_INVALID, "Lỗi dữ liệu"),
        (STATUS_SKIPPED, "Bỏ qua"),
        (STATUS_COMMITTED, "Đã ghi"),
        (STATUS_ERROR, "Ghi thất bại"),
    ]

    batch = models.ForeignKey(ImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField(default=0)

    raw = models.JSONField(default=dict, blank=True,
                           help_text="Ô gốc đọc từ tệp, chưa chuẩn hoá")
    fields = models.JSONField(default=dict, blank=True,
                              help_text="Trường nghiệp vụ đã chuẩn hoá — phần lõi của SourceRecord.payload")
    entity_key = models.CharField(max_length=300, blank=True, default="")

    validation_status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                         default=STATUS_INVALID, db_index=True)
    errors = models.JSONField(default=dict, blank=True)

    # Kết quả dedupe lúc validate; gợi ý cho người dùng, không tự động gộp.
    matched_person = models.ForeignKey("people.Person", null=True, blank=True,
                                       on_delete=models.SET_NULL, related_name="+")
    # Set khi commit thành công.
    source_record = models.ForeignKey("core.SourceRecord", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="+")

    # CV đính kèm (ghép theo tên file với dòng Excel, hoặc một file cho luồng bulk_cv).
    cv_filename = models.CharField(max_length=300, blank=True, default="")
    cv_sha256 = models.CharField(max_length=64, blank=True, default="")
    cv_tmp_path = models.CharField(max_length=500, blank=True, default="",
                                   help_text="Đường dẫn file tạm tới khi commit")
    ai_extracted = models.BooleanField(default=False,
                                       help_text="Trường do AI bóc từ CV, không phải người gõ")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Dòng nhập liệu"
        verbose_name_plural = "Dòng nhập liệu"
        ordering = ["batch", "row_number", "pk"]
        indexes = [models.Index(fields=["batch", "validation_status"])]

    def __str__(self):
        return f"Dòng {self.row_number} lô #{self.batch_id}"

    @property
    def eligible_for_commit(self):
        return self.validation_status in (self.STATUS_VALID, self.STATUS_DUPLICATE)
