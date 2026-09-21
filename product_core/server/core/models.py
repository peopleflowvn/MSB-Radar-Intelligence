# -*- coding: utf-8 -*-
"""Model lõi của Hub cho Phase 3: định danh Edge, khoá API, và bàn nhận dữ liệu.

Chưa có Person/Identity/Signal ở đây — đó là Phase 4 (People Core). Phase 3 chỉ
dựng đủ để một Edge tự khai báo, xác thực được, và gửi dữ liệu lên một nơi bền
vững.
"""
import hashlib
import secrets

from django.db import models
from django.utils import timezone

API_KEY_PREFIX_LENGTH = 8


def hash_api_key(raw_key):
    """Băm khoá API. Hub không bao giờ lưu khoá thô — giống nguyên tắc với mật khẩu.

    Dùng sha256 trần chứ không phải PBKDF2/bcrypt một cách có chủ đích: khoá API
    là 32 byte ngẫu nhiên từ secrets.token_urlsafe, không phải mật khẩu người
    nghĩ ra, nên không có gì để tấn công từ điển. Ngược lại, hàm băm chậm sẽ
    phải chạy trên MỌI yêu cầu đồng bộ.
    """
    return hashlib.sha256(str(raw_key or "").encode("utf-8")).hexdigest()


class Edge(models.Model):
    """Một bản cài MSB Radar Edge trên máy của đơn vị.

    Bản ghi được quản trị viên tạo trước và cấp khoá; edge_id do chính ứng dụng
    Edge sinh ra và gắn vào lần gọi /register/ đầu tiên.
    """

    label = models.CharField("Tên gọi", max_length=120,
                             help_text="Ví dụ: Máy phòng Tuyển dụng — tầng 12")
    edge_id = models.CharField("Mã Edge", max_length=64, unique=True, null=True, blank=True,
                               help_text="Do ứng dụng Edge sinh, gắn khi đăng ký lần đầu")
    hostname = models.CharField("Tên máy", max_length=200, blank=True, default="")
    app_version = models.CharField("Phiên bản Edge", max_length=40, blank=True, default="")
    is_active = models.BooleanField("Đang hoạt động", default=True)
    retired_at = models.DateTimeField("Đã gỡ kết nối lúc", null=True, blank=True)
    registered_at = models.DateTimeField("Đăng ký lúc", null=True, blank=True)
    last_seen_at = models.DateTimeField("Lần cuối liên lạc", null=True, blank=True)
    data_report = models.JSONField("Báo cáo dữ liệu Edge", default=dict, blank=True)
    data_reported_at = models.DateTimeField("Báo cáo dữ liệu lúc", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Edge"
        verbose_name_plural = "Các Edge"
        ordering = ["label"]

    def __str__(self):
        return self.label

    def touch(self, hostname="", app_version=""):
        """Ghi nhận vừa có liên lạc. Chỉ ghi những cột thật sự đổi."""
        fields = ["last_seen_at"]
        self.last_seen_at = timezone.now()
        if hostname and hostname != self.hostname:
            self.hostname = hostname
            fields.append("hostname")
        if app_version and app_version != self.app_version:
            self.app_version = app_version
            fields.append("app_version")
        self.save(update_fields=fields + ["updated_at"])


class EdgeApiKey(models.Model):
    """Khoá API cấp cho một Edge.

    Một Edge có thể có nhiều khoá cùng lúc: đó là cách xoay khoá mà không phải
    dừng đồng bộ — cấp khoá mới, cập nhật Edge, rồi thu hồi khoá cũ.
    """

    edge = models.ForeignKey(Edge, on_delete=models.CASCADE, related_name="api_keys",
                             verbose_name="Edge")
    name = models.CharField("Ghi chú", max_length=120, blank=True, default="")
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    prefix = models.CharField("Đầu khoá", max_length=16, editable=False,
                              help_text="Vài ký tự đầu, chỉ để nhận diện")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField("Lần cuối sử dụng", null=True, blank=True)
    revoked_at = models.DateTimeField("Thu hồi lúc", null=True, blank=True)

    class Meta:
        verbose_name = "Khoá API Edge"
        verbose_name_plural = "Khoá API Edge"
        ordering = ["-created_at"]

    def __str__(self):
        trang_thai = "đã thu hồi" if self.revoked_at else "còn hiệu lực"
        return f"{self.edge.label} — {self.prefix}… ({trang_thai})"

    @property
    def is_active(self):
        return self.revoked_at is None

    @classmethod
    def issue(cls, edge, name=""):
        """Cấp khoá mới. Trả (bản ghi, khoá thô).

        Khoá thô chỉ tồn tại ở lần trả về này và không thể lấy lại — mất thì cấp
        khoá khác.
        """
        raw_key = secrets.token_urlsafe(32)
        record = cls.objects.create(
            edge=edge, name=name,
            key_hash=hash_api_key(raw_key),
            prefix=raw_key[:API_KEY_PREFIX_LENGTH],
        )
        return record, raw_key

    def revoke(self):
        if self.revoked_at is None:
            self.revoked_at = timezone.now()
            self.save(update_fields=["revoked_at"])


class SourceRecord(models.Model):
    """Bản ghi thô Edge gửi lên, lưu nguyên trạng.

    Đây là BÀN NHẬN, không phải mô hình miền. Nó cố ý ngu ngốc: nhận, khử trùng
    lặp, lưu bền vững. Việc phân giải Person, gộp định danh, sinh Signal thuộc
    Phase 4–5 và sẽ đọc từ bảng này.

    Tách như vậy để Edge có thể đồng bộ ngay bây giờ, và để khi logic phân giải
    thay đổi thì chạy lại được trên dữ liệu đã nhận, không phải xin Edge gửi lại.
    """

    STATUS_PENDING = "pending"
    STATUS_RESOLVED = "resolved"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Chờ phân giải"),
        (STATUS_RESOLVED, "Đã phân giải"),
    ]

    edge = models.ForeignKey(Edge, on_delete=models.CASCADE, related_name="source_records")
    entity_type = models.CharField(max_length=40)
    entity_key = models.CharField(max_length=300)
    payload = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, db_index=True)

    # Vài trường được nhấc ra khỏi payload để tra cứu và hiển thị không phải
    # quét JSON. Payload vẫn là nguồn sự thật.
    source = models.CharField(max_length=40, blank=True, default="", db_index=True)
    account = models.CharField(max_length=200, blank=True, default="")
    fullname = models.CharField(max_length=200, blank=True, default="")
    email = models.CharField(max_length=200, blank=True, default="", db_index=True)
    phone = models.CharField(max_length=40, blank=True, default="", db_index=True)
    position = models.CharField(max_length=200, blank=True, default="")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING,
                              db_index=True)
    # Kết quả phân giải. SET_NULL chứ không CASCADE: xoá một Person không được
    # phép làm mất bản ghi nguồn — bàn nhận phải giữ nguyên trạng những gì Edge
    # đã gửi, để phân giải lại được khi logic thay đổi.
    person = models.ForeignKey("people.Person", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="source_records")
    revision = models.PositiveIntegerField(default=1,
                                           help_text="Tăng mỗi lần Edge gửi nội dung khác")
    #: Lần gần nhất đã THỬ phân giải. `None` = chưa thử lần nào.
    #:
    #: Cần thiết vì `CONFLICT` và `SKIPPED` cố ý ở lại `pending` (xem
    #: `people/ingest.py`): thiếu email/điện thoại hôm nay thì lần đồng bộ sau
    #: Edge có thể gửi thêm. Nhưng nếu chọn bản ghi để phân giải theo `pk` thì
    #: những bản ghi không phân giải được sẽ mãi mãi đứng đầu hàng — sau khoảng
    #: 500 bản ghi như vậy, KHÔNG bản ghi mới nào còn được xử lý nữa.
    #:
    #: Xếp theo trường này (chưa thử trước, thử lâu nhất sau) khiến hàng đợi
    #: xoay vòng: bản ghi mới luôn được ưu tiên, bản ghi cũ vẫn được thử lại.
    resolve_attempted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bản ghi nguồn"
        verbose_name_plural = "Bản ghi nguồn"
        ordering = ["-last_seen_at"]
        constraints = [
            # Khử trùng lặp nằm ở đây, trong CSDL. Cùng một Edge gửi lại cùng
            # một thực thể là cập nhật, không phải thêm mới — kể cả khi hai
            # yêu cầu chạy song song.
            models.UniqueConstraint(fields=["edge", "entity_type", "entity_key"],
                                    name="uq_source_record_entity"),
        ]
        indexes = [models.Index(fields=["status", "last_seen_at"])]

    def __str__(self):
        return f"{self.entity_key} ({self.fullname or 'chưa rõ tên'})"


class WorkflowStage(models.Model):
    """Cấu hình hiển thị/vận hành cho pipeline; `code` ổn định để bảo toàn dữ liệu."""

    DOMAIN_TALENT = "talent"
    DOMAIN_RB = "rb"
    DOMAIN_CHOICES = [(DOMAIN_TALENT, "Tuyển dụng"), (DOMAIN_RB, "Khách hàng")]

    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES, db_index=True)
    code = models.CharField(max_length=40)
    label = models.CharField(max_length=100)
    position = models.PositiveIntegerField(default=0)
    color = models.CharField(max_length=20, blank=True, default="#64748b")
    is_terminal = models.BooleanField(default=False)
    requires_reason = models.BooleanField(default=False)
    sla_hours = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    allowed_next = models.JSONField(default=list, blank=True,
                                    help_text="Mã bước được phép chuyển tới; rỗng là không giới hạn")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["domain", "position", "id"]
        constraints = [models.UniqueConstraint(fields=["domain", "code"],
                                                name="uq_workflowstage_domain_code")]

    def __str__(self):
        return f"{self.domain}: {self.label}"


class DatabaseBackupLog(models.Model):
    """Lịch sử sao lưu cơ sở dữ liệu PostgreSQL lên Cloudflare R2 / Local."""

    STATUS_PENDING = "pending"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Chờ xử lý"),
        (STATUS_IN_PROGRESS, "Đang sao lưu"),
        (STATUS_COMPLETED, "Hoàn thành"),
        (STATUS_FAILED, "Thất bại"),
    ]

    TRIGGER_SCHEDULED = "scheduled"
    TRIGGER_MANUAL = "manual"
    TRIGGER_CHOICES = [
        (TRIGGER_SCHEDULED, "Tự động định kỳ (2 lần/ngày)"),
        (TRIGGER_MANUAL, "Thủ công (Admin kích hoạt)"),
    ]

    filename = models.CharField("Tên tệp nén", max_length=255)
    storage_key = models.CharField("Đường dẫn lưu trữ", max_length=500)
    storage_backend = models.CharField("Nơi lưu trữ", max_length=32, default="r2")
    size_bytes = models.BigIntegerField("Dung lượng (bytes)", default=0)
    sha256 = models.CharField("Mã băm SHA-256", max_length=64, blank=True, default="")
    status = models.CharField("Trạng thái", max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error_message = models.TextField("Thông báo lỗi", blank=True, default="")
    trigger_type = models.CharField("Loại kích hoạt", max_length=32, choices=TRIGGER_CHOICES, default=TRIGGER_MANUAL)
    created_by = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="triggered_backups")
    duration_ms = models.IntegerField("Thời gian thực thi (ms)", default=0)
    created_at = models.DateTimeField("Thời điểm tạo", default=timezone.now, db_index=True)
    updated_at = models.DateTimeField("Cập nhật lúc", auto_now=True)

    class Meta:
        verbose_name = "Nhật ký sao lưu CSDL"
        verbose_name_plural = "Nhật ký sao lưu CSDL"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.filename} ({self.status}) - {self.created_at.strftime('%Y-%m-%d %H:%M')}"

