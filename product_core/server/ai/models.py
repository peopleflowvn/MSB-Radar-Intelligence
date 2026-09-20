# -*- coding: utf-8 -*-
"""Nhật ký các lượt gọi LLM.

Ba lý do bảng này tồn tại:

1. **Chi phí.** Token là tiền. Không đo thì đến cuối tháng mới biết.
2. **Quan sát.** Agent chạy chậm hay trả sai — cần biết provider/model nào.
3. **Giải "Best Use of Green Node".** Ban giám khảo hỏi hệ thống dùng GreenNode
   ra sao thì đây là câu trả lời có số liệu, không phải lời kể.
"""
from django.conf import settings
from django.db import models

from . import crypto


class ProviderConfig(models.Model):
    """Cấu hình một nhà cung cấp LLM, sửa được từ trang cài đặt trên Hub.

    Vì sao cần bảng này bên cạnh biến môi trường:

        biến môi trường   tốt cho triển khai — nằm trong .env, đi cùng Docker,
                          nhưng đổi thì phải khởi động lại container
        bảng này          tốt cho vận hành — đổi khoá, đổi model, bật/tắt một
                          nhà cung cấp ngay trên giao diện, có hiệu lực tức thì

    Thứ tự ưu tiên: **bảng này thắng biến môi trường.** Biến môi trường đóng vai
    trò giá trị khởi tạo cho lần triển khai đầu; sau đó người vận hành làm chủ.

    Khoá API được mã hoá (xem crypto.py) và **không bao giờ** trả về trình duyệt
    ở dạng đầy đủ.
    """

    GREENNODE = "greennode"
    OPENAI = "openai"
    GEMINI = "gemini"
    DEEPSEEK = "deepseek"
    PROVIDER_CHOICES = [
        (GREENNODE, "GreenNode"),
        (OPENAI, "OpenAI"),
        (GEMINI, "Google Gemini"),
        (DEEPSEEK, "DeepSeek"),
    ]

    provider = models.CharField("Nhà cung cấp", max_length=40, unique=True,
                                choices=PROVIDER_CHOICES)
    enabled = models.BooleanField("Đang bật", default=True)
    priority = models.PositiveIntegerField(
        "Thứ tự ưu tiên", default=100,
        help_text="Số nhỏ được thử trước. GreenNode nên để nhỏ nhất.")

    api_key_encrypted = models.TextField(blank=True, default="", editable=False)
    api_key_hint = models.CharField("Khoá (che)", max_length=60, blank=True, default="",
                                    editable=False)

    base_url = models.CharField("Base URL", max_length=300, blank=True, default="",
                                help_text="Để trống = dùng mặc định của nhà cung cấp")
    model = models.CharField("Mã model", max_length=120, blank=True, default="")
    timeout = models.PositiveIntegerField("Thời gian chờ (giây)", default=60)

    # Kết quả lần kiểm tra kết nối gần nhất — để trang cài đặt hiển thị được
    # trạng thái mà không phải gọi nhà cung cấp mỗi lần mở trang.
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_check_ok = models.BooleanField(null=True, blank=True)
    last_check_detail = models.CharField(max_length=400, blank=True, default="")

    updated_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cấu hình nhà cung cấp AI"
        verbose_name_plural = "Cấu hình nhà cung cấp AI"
        ordering = ["priority", "provider"]

    def __str__(self):
        return f"{self.get_provider_display()} ({'bật' if self.enabled else 'tắt'})"

    # ---------- khoá API ----------

    # Nhiều khoá được nối bằng ký tự này TRƯỚC khi mã hoá, nên chỉ có một bản mã
    # duy nhất trong CSDL. Ký tự đơn vị (U+001F) không bao giờ xuất hiện trong
    # khoá API nên không thể trùng.
    KEY_SEPARATOR = "\x1f"

    def set_api_key(self, raw_key):
        """Đặt khoá. Nhận một khoá hoặc nhiều khoá; chuỗi rỗng nghĩa là xoá hết.

        Nhiều khoá cho cùng một nhà cung cấp là cách chữa hạn mức tốc độ: hạn mức
        tính theo từng khoá, nên ba khoá là hạn mức gấp ba.
        """
        from .keypool import split_keys
        keys = raw_key if isinstance(raw_key, (list, tuple)) else split_keys(raw_key)
        keys = [str(k).strip() for k in keys if str(k).strip()]
        if not keys:
            self.api_key_encrypted = ""
            self.api_key_hint = ""
            return
        self.api_key_encrypted = crypto.encrypt(self.KEY_SEPARATOR.join(keys))
        hints = ", ".join(crypto.mask(k, keep=6) for k in keys[:3])
        if len(keys) > 3:
            hints += f" (+{len(keys) - 3})"
        self.api_key_hint = hints[:60]

    def get_api_keys(self):
        """Danh sách khoá dạng rõ. Rỗng nếu chưa có hoặc không giải mã được."""
        if not self.api_key_encrypted:
            return []
        try:
            plain = crypto.decrypt(self.api_key_encrypted)
        except crypto.DecryptError:
            return []
        return [k for k in plain.split(self.KEY_SEPARATOR) if k]

    def get_api_key(self):
        """Khoá đầu tiên. Giữ lại cho chỗ nào chỉ cần một khoá."""
        keys = self.get_api_keys()
        return keys[0] if keys else ""

    @property
    def key_count(self):
        return len(self.get_api_keys())

    @property
    def has_api_key(self):
        return bool(self.api_key_encrypted)

    @property
    def key_readable(self):
        """False nghĩa là có khoá lưu nhưng không giải mã được — cần nhập lại."""
        return not self.api_key_encrypted or bool(self.get_api_keys())


class TaskModelRoute(models.Model):
    """Route model theo tác vụ do người vận hành sở hữu.

    Không dùng các biến `MSB_AI_*_MODEL_<TASK>` như nguồn cấu hình thường trực:
    chúng làm `/settings` hiển thị một model nhưng runtime lại gọi model khác.
    ENV chỉ còn bootstrap/fallback hoặc emergency override có chủ đích.
    """

    task = models.CharField(max_length=60, unique=True, db_index=True)
    provider = models.CharField(max_length=40, choices=ProviderConfig.PROVIDER_CHOICES)
    model = models.CharField(max_length=120, blank=True, default="")
    enabled = models.BooleanField(default=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["task"]
        verbose_name = "Điều hướng model theo tác vụ"
        verbose_name_plural = "Điều hướng model theo tác vụ"

    def __str__(self):
        return f"{self.task}: {self.provider}/{self.model or 'default'}"


class LLMCall(models.Model):
    provider = models.CharField(max_length=40, db_index=True)
    model = models.CharField(max_length=100, blank=True, default="")
    task = models.CharField(max_length=60, blank=True, default="", db_index=True)

    prompt_tokens = models.PositiveIntegerField(default=0)
    completion_tokens = models.PositiveIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(default=0)

    ok = models.BooleanField(default=True, db_index=True)
    error = models.CharField(max_length=500, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Lượt gọi LLM"
        verbose_name_plural = "Lượt gọi LLM"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["provider", "-created_at"])]

    def __str__(self):
        trang_thai = "OK" if self.ok else "LỖI"
        return f"{self.provider}/{self.model} {self.total_tokens}tok [{trang_thai}]"

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens


class AssistantThread(models.Model):
    """Server-side conversation state shared by Talent and Growth assistants."""
    SURFACE_CHOICES = [("talent", "Talent"), ("prospect", "Growth")]

    thread_id = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="assistant_threads")
    surface = models.CharField(max_length=20, choices=SURFACE_CHOICES)
    summary = models.TextField(blank=True, default="")
    state = models.JSONField(default=dict, blank=True)
    turns = models.JSONField(default=list, blank=True)
    title = models.CharField(max_length=160, blank=True, default="")
    archived = models.BooleanField(default=False, db_index=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        constraints = [models.UniqueConstraint(
            fields=["user", "surface", "thread_id"], name="uq_assistant_thread")]
        indexes = [models.Index(fields=["user", "surface", "-updated_at"])]


class AssistantMessage(models.Model):
    """Một tin nhắn bền; tách khỏi JSON để phân trang và mở lại hội thoại."""

    ROLE_CHOICES = [("user", "User"), ("assistant", "Radar"), ("system", "System")]
    thread = models.ForeignKey(AssistantThread, on_delete=models.CASCADE,
                               related_name="messages")
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    content = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    provider = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=120, blank=True, default="")
    # Khoá chống ghi trùng khi client retry cùng một lượt (Master Plan §21.5).
    # Gắn trên message role="user"; rỗng = lượt cũ chưa có khoá.
    client_turn_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["thread", "created_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["thread", "client_turn_id"],
                condition=models.Q(client_turn_id__gt=""),
                name="uq_assistant_msg_client_turn"),
        ]


class AssistantEvent(models.Model):
    """Nhật ký sự kiện append-only theo lượt hội thoại (Master Plan §15, Giai đoạn 1).

    Đây là **nguồn sự thật**: `AssistantMessage`, rolling summary, `AssistantThread.state`
    và context projection đều dựng lại được từ đây. Trong luồng thường chỉ thêm,
    không sửa/xoá. Ghi hỏng không được làm hỏng phản hồi — xem `ai/events.py`.
    """

    KIND_TURN_STARTED = "turn.started"
    KIND_USER_MESSAGE = "user.message"
    KIND_INTENT_CLASSIFIED = "intent.classified"
    KIND_MODEL_REQUESTED = "model.requested"
    KIND_MODEL_RESPONDED = "model.responded"
    KIND_SEARCH_EXECUTED = "search.executed"
    KIND_SEARCH_RESULTS_RANKED = "search.results_ranked"
    KIND_WEB_SEARCHED = "web.searched"
    KIND_TOOL_CALLED = "tool.called"
    KIND_TURN_COMPLETED = "turn.completed"
    KIND_TURN_FAILED = "turn.failed"
    KIND_CHOICES = [
        (KIND_TURN_STARTED, "Bắt đầu lượt"),
        (KIND_USER_MESSAGE, "Tin nhắn người dùng"),
        (KIND_INTENT_CLASSIFIED, "Đã phân loại ý định"),
        (KIND_MODEL_REQUESTED, "Gửi model"),
        (KIND_MODEL_RESPONDED, "Model trả lời"),
        (KIND_SEARCH_EXECUTED, "Đã tìm kiếm"),
        (KIND_SEARCH_RESULTS_RANKED, "Đã xếp hạng kết quả"),
        (KIND_WEB_SEARCHED, "Đã tra Google"),
        (KIND_TOOL_CALLED, "Đã gọi tool"),
        (KIND_TURN_COMPLETED, "Kết thúc lượt"),
        (KIND_TURN_FAILED, "Lượt lỗi"),
    ]

    thread = models.ForeignKey(AssistantThread, on_delete=models.CASCADE,
                               related_name="events")
    turn_id = models.CharField(max_length=64, db_index=True)
    seq = models.PositiveIntegerField(default=0)
    kind = models.CharField(max_length=40, choices=KIND_CHOICES, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["thread_id", "turn_id", "seq", "pk"]
        indexes = [models.Index(fields=["thread", "turn_id", "seq"])]
        constraints = [
            models.UniqueConstraint(fields=["thread", "turn_id", "seq"],
                                    name="uq_assistant_event_seq"),
        ]

    def __str__(self):
        return f"{self.turn_id}#{self.seq} {self.kind}"


class LongTermMemory(models.Model):
    """Fact/preference ổn định mà người dùng CHO PHÉP Radar nhớ (Master Plan §11.2, §15 GĐ5).

    Hai store tách biệt (§15 GĐ5):
      * `profile`     — User Profile Memory: tên, cách xưng hô, sở thích giao tiếp.
      * `operational` — Radar Operational Memory: quy ước nghiệp vụ đã duyệt.

    Memory do AI đề xuất vào ở `pending_review`; người dùng duyệt mới `active`.
    Không tự lưu thông tin ứng viên/khách hàng như preference của người dùng.
    """

    SCOPE_PROFILE = "profile"
    SCOPE_OPERATIONAL = "operational"
    SCOPE_CHOICES = [(SCOPE_PROFILE, "Hồ sơ người dùng"),
                     (SCOPE_OPERATIONAL, "Quy ước vận hành Radar")]

    KIND_PREFERENCE = "preference"
    KIND_FACT = "fact"
    KIND_CHOICES = [(KIND_PREFERENCE, "Sở thích trình bày"), (KIND_FACT, "Sự việc")]

    STATUS_ACTIVE = "active"
    STATUS_PENDING = "pending_review"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [(STATUS_ACTIVE, "Đang dùng"),
                      (STATUS_PENDING, "Chờ người dùng duyệt"),
                      (STATUS_REJECTED, "Đã bỏ")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="assistant_memories")
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES,
                             default=SCOPE_OPERATIONAL, db_index=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_FACT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_ACTIVE, db_index=True)
    key = models.CharField(max_length=80, blank=True, default="")
    value = models.TextField()
    source = models.CharField(max_length=40, blank=True, default="user",
                              help_text="user | admin | radar_ai")
    version = models.PositiveIntegerField(default=1)
    surface = models.CharField(max_length=20, blank=True, default="")
    #: Lần gần nhất memory được đưa vào context — để retention nhắm memory chết.
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Ghi nhớ dài hạn"
        verbose_name_plural = "Ghi nhớ dài hạn"
        ordering = ["-updated_at"]
        constraints = [
            models.UniqueConstraint(fields=["user", "scope", "key"],
                                    condition=models.Q(key__gt=""),
                                    name="uq_longterm_memory_key"),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.scope}:{self.key or self.value[:30]}"


class AnswerRun(models.Model):
    """Durable idempotency claim for Talent background generation, without PII text."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    client_turn_id = models.CharField(max_length=64)
    state = models.CharField(max_length=12, default="running")
    deadline = models.DateTimeField()
    #: Bản coverage của lượt (`method/candidate_total/judged/unknown/not_read/
    #: complete/retrieval_degraded`) — KHÔNG có nội dung CV hay liên hệ. Trước
    #: đây coverage chỉ tồn tại trong response, nên không cách nào rà lại "lượt
    #: nào từng nói sai phạm vi" sau khi người dùng đóng tab.
    coverage = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "client_turn_id"],
                                               name="uq_answer_run_user_turn")]


class AssistantFeedback(models.Model):
    """👍/👎 + lý do cho một câu trả lời — nguyên liệu benchmark (Master Plan §11.3, §15 GĐ5)."""

    RATING_UP = "up"
    RATING_DOWN = "down"
    RATING_CHOICES = [(RATING_UP, "Hữu ích"), (RATING_DOWN, "Chưa tốt")]

    message = models.ForeignKey(AssistantMessage, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="feedback")
    thread = models.ForeignKey(AssistantThread, null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="feedback")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="assistant_feedback")
    rating = models.CharField(max_length=8, choices=RATING_CHOICES, db_index=True)
    reason = models.CharField(max_length=500, blank=True, default="")
    #: Ảnh chụp để eval không phụ thuộc message còn tồn tại.
    question = models.TextField(blank=True, default="")
    answer = models.TextField(blank=True, default="")
    surface = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Phản hồi trợ lý"
        verbose_name_plural = "Phản hồi trợ lý"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["message", "user"],
                                    condition=models.Q(message__isnull=False),
                                    name="uq_assistant_feedback_msg_user"),
        ]
