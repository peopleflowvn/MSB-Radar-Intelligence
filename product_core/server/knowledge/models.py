# -*- coding: utf-8 -*-
"""Tài liệu tri thức nội bộ — quy trình, quyết định, hướng dẫn.

Khác hẳn `people.models.Document`: đây KHÔNG phải hồ sơ của một `Person`.
`Person` (xem people/models.py) đại diện một CON NGƯỜI thật — dùng nó để đại
diện cho một tài liệu chính sách sẽ làm hỏng ý nghĩa của bảng đó (phát hiện
trùng lặp theo tên, gộp hồ sơ, thống kê ứng viên...). Nên `KnowledgeDocument`
là một model độc lập, không FK tới `Person`.

Hiển thị theo module (`accounts.roles.MODULE_KNOWLEDGE`), cùng cơ chế Group
đang dùng cho mọi module khác — không phải hệ phân quyền riêng.

Nạp vào Radar Intelligence qua `talent/intelligence_views.py::document_feed`,
với `person_id`/`document_id` là SỐ ÂM: `-pk` của chính tài liệu này. Không gian
số âm không bao giờ trùng với `Person.pk`/`Document.pk` (luôn dương, tự tăng),
nên feed, `evidence_document` và `intelligence_client.py` phân biệt được hai
loại bản ghi chỉ bằng dấu của số nguyên — không cần đổi kiểu dữ liệu ở phía
radar_intelligence (nó vẫn chỉ thấy một chuỗi `person_id` như mọi khi).
"""
from django.conf import settings
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.storage import content_key, get_storage, sha256_of


class KnowledgeDocument(models.Model):
    PARSE_PENDING = "pending"
    PARSE_DONE = "done"
    PARSE_FAILED = "failed"
    PARSE_CHOICES = [
        (PARSE_PENDING, "Chờ xử lý"),
        (PARSE_DONE, "Đã xử lý"),
        (PARSE_FAILED, "Lỗi"),
    ]

    CATEGORY_HR_POLICY = "hr_policy"
    CATEGORY_RECRUITMENT_PROCESS = "recruitment_process"
    CATEGORY_LEADERSHIP_DECISION = "leadership_decision"
    CATEGORY_GUIDELINE = "guideline"
    CATEGORY_OTHER = "other"
    CATEGORY_CHOICES = [
        (CATEGORY_HR_POLICY, "Chính sách nhân sự"),
        (CATEGORY_RECRUITMENT_PROCESS, "Quy trình tuyển dụng"),
        (CATEGORY_LEADERSHIP_DECISION, "Quyết định lãnh đạo"),
        (CATEGORY_GUIDELINE, "Hướng dẫn nội bộ"),
        (CATEGORY_OTHER, "Khác"),
    ]

    title = models.CharField("Tiêu đề", max_length=300)
    category = models.CharField("Danh mục", max_length=40, choices=CATEGORY_CHOICES,
                                default=CATEGORY_OTHER, db_index=True)

    filename = models.CharField(max_length=300, blank=True, default="")
    mime_type = models.CharField(max_length=100, blank=True, default="")
    file_size = models.PositiveIntegerField(default=0)
    sha256 = models.CharField(max_length=64, blank=True, default="", db_index=True,
                              help_text="Khử trùng lặp: cùng một file")
    storage_key = models.CharField(max_length=500, blank=True, default="",
                                   help_text="Khoá trong kho file; trống = chỉ có văn bản nhập tay")

    parsed_text = models.TextField(
        "Nội dung", blank=True, default="",
        help_text="Văn bản Radar sẽ đọc. Nhập tay, hoặc dán lại nội dung trích từ file.")
    parse_status = models.CharField(max_length=20, choices=PARSE_CHOICES, default=PARSE_DONE)

    is_active = models.BooleanField(
        "Đang hiệu lực", default=True, db_index=True,
        help_text="Tắt để rút khỏi Radar ngay mà không phải xoá tài liệu")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="knowledge_documents")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        verbose_name = "Tài liệu tri thức"
        verbose_name_plural = "Tài liệu tri thức"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.title or f"Tài liệu tri thức #{self.pk}"

    @property
    def best_text(self):
        return self.parsed_text or ""

    @property
    def radar_entity_id(self):
        """Số âm ổn định dùng làm cả person_id lẫn document_id phía Intelligence.

        Chỉ có nghĩa sau khi bản ghi đã được lưu (có `pk`).
        """
        if self.pk is None:
            raise ValueError("KnowledgeDocument must be saved before it has a radar_entity_id")
        return -self.pk

    def store_file(self, data, *, filename=""):
        """Lưu nội dung file qua kho lưu trữ nội dung-địa-chỉ dùng chung với CV."""
        digest = sha256_of(data)
        key = content_key(digest, filename)
        get_storage().save(key, data)
        self.sha256 = digest
        self.storage_key = key
        self.file_size = len(data)
        if filename:
            self.filename = filename


class KnowledgeFeedEvent(models.Model):
    """Sổ ghi chỉ-thêm để feed Intelligence không bao giờ sót một thay đổi.

    **Vì sao không phân trang thẳng trên `KnowledgeDocument.updated_at`:** con
    trỏ dạng `(updated_at, pk)` bỏ sót thay đổi khi một tài liệu được sửa lại
    trong cùng một tick đồng hồ — hàng đó không lớn hơn chính nó, nên lần sửa
    thứ hai không bao giờ được phát. Trên Windows tick có thể tới ~15ms và bài
    kiểm thử bắt được đúng lỗi này. Khoá tự tăng ở đây luôn tăng nghiêm ngặt
    nên không có khe hở đó.

    Và vì hàng sự kiện tồn tại độc lập với tài liệu, XOÁ CỨNG một tài liệu vẫn
    phát được sự kiện `delete` — điều mà phân trang trên chính bảng tài liệu
    không làm được (hàng biến mất thì không còn gì để duyệt).
    """

    OPERATION_UPSERT = "upsert"
    OPERATION_DELETE = "delete"

    document = models.ForeignKey(
        KnowledgeDocument, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="feed_events")
    #: Giữ lại kể cả khi tài liệu đã bị xoá — đây là thứ suy ra id âm phía Intelligence.
    document_pk = models.BigIntegerField(db_index=True)
    operation = models.CharField(max_length=10)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sự kiện tri thức"
        verbose_name_plural = "Sự kiện tri thức"
        ordering = ["pk"]

    def __str__(self):
        return f"{self.operation} #{self.document_pk} (event {self.pk})"


@receiver(post_save, sender=KnowledgeDocument, dispatch_uid="knowledge_feed_upsert")
def _record_save(sender, instance, **kwargs):
    KnowledgeFeedEvent.objects.create(
        document=instance, document_pk=instance.pk,
        operation=(KnowledgeFeedEvent.OPERATION_UPSERT
                   if instance.is_active and (instance.parsed_text or "").strip()
                   else KnowledgeFeedEvent.OPERATION_DELETE))


@receiver(post_delete, sender=KnowledgeDocument, dispatch_uid="knowledge_feed_delete")
def _record_delete(sender, instance, **kwargs):
    KnowledgeFeedEvent.objects.create(
        document=None, document_pk=instance.pk,
        operation=KnowledgeFeedEvent.OPERATION_DELETE)
