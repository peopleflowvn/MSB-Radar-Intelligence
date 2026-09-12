# -*- coding: utf-8 -*-
"""People Intelligence — Canonical Registry, Extracted Facts, extraction runs.

Master Plan §5, §6, §7, §21.1, §21.2, §21.6, §21.7. Ba lớp:

* **Canonical Registry** (`CanonicalNamespace`, `CanonicalEntry`, `CanonicalAlias`)
  — code/registry quyết định mã chuẩn; AI chỉ được ĐỀ XUẤT alias (§21.2).
* **Extracted Facts** (`ExtractionRun`, `ExtractedFact`, `ReviewItem`) — mỗi giá
  trị AI/Edge suy ra là một fact có nguồn, bitemporal, idempotent (§5, §21.1).
* **Materialized projection** (`MaterializedProfile`) — chỉ fact `accepted` mới
  vào index tìm kiếm, có version + rebuild (§21.7).
"""
from django.db import models
from django.utils import timezone


# --------------------------------------------------------------------------- #
# Canonical Registry
# --------------------------------------------------------------------------- #
class CanonicalNamespace(models.Model):
    """Một danh mục chuẩn hoá: location, skill, job_title, education_level, …"""

    key = models.SlugField(max_length=40, unique=True)
    label = models.CharField(max_length=120)
    #: Tăng khi đổi thuật toán chuẩn hoá — fact ghi kèm version để chạy lại đúng.
    normalization_version = models.PositiveIntegerField(default=1)
    #: Có nên bỏ dấu khi so khớp alias (đúng cho địa danh/skill; sai cho tên riêng).
    fold_diacritics = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Danh mục chuẩn"
        verbose_name_plural = "Danh mục chuẩn"
        ordering = ["key"]

    def __str__(self):
        return self.key


class CanonicalEntry(models.Model):
    """Một giá trị chuẩn trong một namespace. `code` ổn định, `label` để hiển thị."""

    namespace = models.ForeignKey(CanonicalNamespace, on_delete=models.CASCADE,
                                  related_name="entries")
    code = models.CharField(max_length=64)
    label = models.CharField(max_length=200)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="children")
    #: Dữ liệu phụ theo namespace (vd country cho location, family cho job_title).
    attrs = models.JSONField(default=dict, blank=True)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Mã chuẩn"
        verbose_name_plural = "Mã chuẩn"
        constraints = [
            models.UniqueConstraint(fields=["namespace", "code"], name="uq_canonical_entry"),
        ]
        indexes = [models.Index(fields=["namespace", "active"])]
        ordering = ["namespace__key", "code"]

    def __str__(self):
        return f"{self.namespace.key}:{self.code}"


class CanonicalAlias(models.Model):
    """Một cách viết thô → một `CanonicalEntry`, kèm governance & lineage (§21.2).

    AI chỉ tạo alias `status=proposed`. Chỉ người quản trị (hoặc seed/code tất
    định) mới `accepted`. Alias chưa nối entry = hàng chờ nhận diện.
    """

    STATUS_PROPOSED = "proposed"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Đề xuất — chờ duyệt"),
        (STATUS_ACCEPTED, "Đã duyệt"),
        (STATUS_REJECTED, "Đã bác"),
    ]

    namespace = models.ForeignKey(CanonicalNamespace, on_delete=models.CASCADE,
                                  related_name="aliases")
    alias_norm = models.CharField(max_length=200, db_index=True,
                                  help_text="Đã chuẩn hoá theo namespace")
    alias_raw = models.CharField(max_length=200, blank=True, default="")
    entry = models.ForeignKey(CanonicalEntry, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="aliases")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_PROPOSED, db_index=True)
    source = models.CharField(max_length=40, blank=True, default="",
                              help_text="seed | code | radar_ai | admin")
    version = models.PositiveIntegerField(default=1)
    note = models.CharField(max_length=300, blank=True, default="")

    created_by = models.CharField(max_length=150, blank=True, default="")
    approved_by = models.CharField(max_length=150, blank=True, default="")
    effective_at = models.DateTimeField(null=True, blank=True)
    #: Bản trước khi thay đổi — để rollback.
    previous = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Alias chuẩn"
        verbose_name_plural = "Alias chuẩn"
        constraints = [
            models.UniqueConstraint(fields=["namespace", "alias_norm"],
                                    name="uq_canonical_alias"),
        ]
        indexes = [models.Index(fields=["namespace", "status"])]
        ordering = ["namespace__key", "alias_norm"]

    def __str__(self):
        target = self.entry.code if self.entry_id else "(chưa nối)"
        return f"{self.alias_norm} → {target}"

    def accept(self, entry, *, by="", note=""):
        self.previous = {"status": self.status, "entry_id": self.entry_id,
                         "version": self.version}
        self.entry = entry
        self.status = self.STATUS_ACCEPTED
        self.approved_by = str(by)[:150]
        self.effective_at = timezone.now()
        self.version += 1
        if note:
            self.note = note[:300]
        self.save()

    def reject(self, *, by="", note=""):
        self.previous = {"status": self.status, "entry_id": self.entry_id,
                         "version": self.version}
        self.status = self.STATUS_REJECTED
        self.approved_by = str(by)[:150]
        self.effective_at = timezone.now()
        self.version += 1
        if note:
            self.note = note[:300]
        self.save(update_fields=["status", "approved_by", "effective_at",
                                 "version", "note", "previous", "updated_at"])


# --------------------------------------------------------------------------- #
# Extracted Facts + provenance
# --------------------------------------------------------------------------- #
class ExtractionRun(models.Model):
    """Một lượt chạy trích xuất cho một Person (Master Plan §7.1, §21.6)."""

    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_RUNNING, "Đang chạy"), (STATUS_DONE, "Xong"),
                      (STATUS_FAILED, "Lỗi")]

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="extraction_runs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_RUNNING, db_index=True)
    extractor = models.CharField(max_length=40, default="edge_first")
    schema_version = models.PositiveIntegerField(default=1)
    provider = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    dry_run = models.BooleanField(default=False)

    #: Coverage report (§21.6): edge / reuse / parsed_text / ai / missing / tokens.
    coverage = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=500, blank=True, default="")

    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Lượt trích xuất"
        verbose_name_plural = "Lượt trích xuất"
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["person", "-started_at"])]

    def finish(self, status=STATUS_DONE, error=""):
        self.status = status
        self.error = str(error)[:500]
        self.finished_at = timezone.now()
        self.save(update_fields=["status", "error", "finished_at", "coverage"])


class ExtractedFact(models.Model):
    """Một giá trị có nguồn. AI/Edge không ghi thẳng vào trường chính (§5)."""

    SOURCE_EDGE = "edge"
    SOURCE_CV_TEXT = "cv_text"
    SOURCE_PROFILE = "profile"
    SOURCE_AI = "ai"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_EDGE, "Edge payload"), (SOURCE_CV_TEXT, "Text CV đã parsing"),
        (SOURCE_PROFILE, "Hồ sơ hiện có"), (SOURCE_AI, "AI suy luận"),
        (SOURCE_MANUAL, "Người nhập/sửa tay"),
    ]

    STATUS_PROPOSED = "proposed"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CONFLICT = "conflict"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Đề xuất"), (STATUS_ACCEPTED, "Đã chấp nhận"),
        (STATUS_REJECTED, "Đã bác"), (STATUS_CONFLICT, "Mâu thuẫn"),
    ]

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="facts")
    run = models.ForeignKey(ExtractionRun, null=True, blank=True,
                            on_delete=models.SET_NULL, related_name="facts")
    field = models.CharField(max_length=60, db_index=True)

    raw_value = models.CharField(max_length=500, blank=True, default="")
    normalized_value = models.CharField(max_length=500, blank=True, default="")
    canonical_code = models.CharField(max_length=64, blank=True, default="", db_index=True)
    canonical_label = models.CharField(max_length=200, blank=True, default="")

    confidence = models.FloatField(default=0.0, help_text="0..1")
    source_kind = models.CharField(max_length=20, choices=SOURCE_CHOICES, db_index=True)
    source_record = models.ForeignKey("core.SourceRecord", null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name="facts")
    document = models.ForeignKey("people.Document", null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="facts")
    evidence = models.TextField(blank=True, default="",
                                help_text="Trích dẫn đủ để người dùng kiểm tra")
    extractor = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    schema_version = models.PositiveIntegerField(default=1)

    #: Idempotency — cùng nguồn + field + schema_version + giá trị ⇒ một hàng.
    fingerprint = models.CharField(max_length=64, db_index=True)

    #: Thời gian (§21.1). observed_at = lúc quan sát; valid_* = hiệu lực nghiệp vụ.
    observed_at = models.DateTimeField(default=timezone.now, db_index=True)
    valid_from = models.DateTimeField(null=True, blank=True)
    valid_to = models.DateTimeField(null=True, blank=True)
    is_current = models.BooleanField(default=True, db_index=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_PROPOSED, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fact có nguồn"
        verbose_name_plural = "Fact có nguồn"
        ordering = ["person_id", "field", "-observed_at"]
        constraints = [
            models.UniqueConstraint(fields=["fingerprint"], name="uq_extracted_fact_fp"),
        ]
        indexes = [
            models.Index(fields=["person", "field", "status"]),
            models.Index(fields=["person", "field", "is_current"]),
        ]

    def __str__(self):
        return f"{self.field}={self.canonical_code or self.normalized_value or self.raw_value}"


class ReviewItem(models.Model):
    """Hàng chờ người xem: fact nhạy cảm / confidence thấp / mâu thuẫn (§5)."""

    REASON_SENSITIVE = "sensitive"
    REASON_LOW_CONFIDENCE = "low_confidence"
    REASON_CONFLICT = "conflict"
    REASON_ALIAS = "unknown_alias"
    REASON_CHOICES = [
        (REASON_SENSITIVE, "Trường nhạy cảm"),
        (REASON_LOW_CONFIDENCE, "Độ tin cậy thấp"),
        (REASON_CONFLICT, "Giá trị mâu thuẫn"),
        (REASON_ALIAS, "Alias chưa nhận diện"),
    ]

    STATUS_OPEN = "open"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [(STATUS_OPEN, "Chờ xử lý"), (STATUS_ACCEPTED, "Đã nhận"),
                      (STATUS_REJECTED, "Đã bác")]

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="review_items")
    fact = models.ForeignKey(ExtractedFact, null=True, blank=True,
                             on_delete=models.CASCADE, related_name="review_items")
    alias = models.ForeignKey(CanonicalAlias, null=True, blank=True,
                              on_delete=models.CASCADE, related_name="review_items")
    field = models.CharField(max_length=60, blank=True, default="")
    reason = models.CharField(max_length=20, choices=REASON_CHOICES, db_index=True)
    detail = models.CharField(max_length=300, blank=True, default="")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_OPEN, db_index=True)
    resolved_by = models.CharField(max_length=150, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Mục chờ duyệt"
        verbose_name_plural = "Mục chờ duyệt"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "reason", "-created_at"])]

    def resolve(self, status, by=""):
        self.status = status
        self.resolved_by = str(by)[:150]
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "resolved_by", "resolved_at"])


# --------------------------------------------------------------------------- #
# Extraction queue (§21.3) — DB-backed, độc lập với Download/Parsing
# --------------------------------------------------------------------------- #
class ExtractionJob(models.Model):
    """Việc cần trích xuất, worker claim theo batch nhỏ, có lease/retry/safe-stop.

    Cố ý KHÔNG dùng Celery/Redis ở bước này — bảng + lệnh `run_extraction_worker`
    là đủ, và có thể chuyển sang broker sau mà không đổi `intel.extraction`.
    """

    STATUS_QUEUED = "queued"
    STATUS_LEASED = "leased"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [(STATUS_QUEUED, "Chờ"), (STATUS_LEASED, "Đang xử lý"),
                      (STATUS_DONE, "Xong"), (STATUS_FAILED, "Lỗi")]

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="extraction_jobs")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_QUEUED, db_index=True)
    batch = models.CharField(max_length=64, blank=True, default="", db_index=True)
    use_ai = models.BooleanField(default=True)

    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    lease_until = models.DateTimeField(null=True, blank=True, db_index=True)
    worker = models.CharField(max_length=80, blank=True, default="")

    last_run = models.ForeignKey(ExtractionRun, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    error = models.CharField(max_length=500, blank=True, default="")

    enqueued_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Việc trích xuất"
        verbose_name_plural = "Việc trích xuất"
        ordering = ["enqueued_at", "pk"]
        constraints = [
            # Một Person chỉ có một job chưa hoàn tất tại một thời điểm.
            models.UniqueConstraint(
                fields=["person"], condition=models.Q(status__in=["queued", "leased"]),
                name="uq_extraction_job_pending"),
        ]
        indexes = [models.Index(fields=["status", "enqueued_at"])]


# --------------------------------------------------------------------------- #
# Materialized search projection (§21.7)
# --------------------------------------------------------------------------- #
class MaterializedProfile(models.Model):
    """Ảnh phẳng của một Person dựng từ **fact đã accepted** — để search không
    join động hàng nghìn fact. Có version + rebuild command."""

    person = models.OneToOneField("people.Person", on_delete=models.CASCADE,
                                  related_name="materialized")
    projection_version = models.PositiveIntegerField(default=1, db_index=True)
    #: {field: {code, label, value, confidence, source_kind, observed_at}}
    data = models.JSONField(default=dict, blank=True)
    #: Mã canonical phẳng để lọc nhanh: {"skill": [...codes], "location": [...]}
    codes = models.JSONField(default=dict, blank=True)
    fact_count = models.PositiveIntegerField(default=0)
    built_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = "Ảnh tìm kiếm"
        verbose_name_plural = "Ảnh tìm kiếm"

    def __str__(self):
        return f"proj v{self.projection_version} person={self.person_id}"
