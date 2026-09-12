# -*- coding: utf-8 -*-
"""Social Radar — nghe mạng xã hội, dùng chung cho Talent và RB.

Master Plan mục 26–35. Provider đầu tiên là Facebook, nhưng **không có gì trong
file này biết Facebook là gì**: `provider` chỉ là một chuỗi. Zalo, LinkedIn hay
một diễn đàn nội bộ đều gắn vào được mà không phải sửa mô hình.

```text
SocialAccount   tài khoản dùng để nghe (đăng nhập nằm ở Edge, không ở đây)
Community       nhóm/trang đang theo dõi
SocialPost      một bài đã bắt được, kèm điểm ý định do AI chấm
SocialComment   bình luận — bằng chứng thêm cho ý định
SocialAction    việc MSB làm với bài đó (bình luận, nhắn tin, đăng tuyển)
```

**Không có `SocialSignal` riêng.** Master Plan liệt kê cái tên đó, nhưng
`people.Signal` đã là hạ tầng tín hiệu dùng chung cho mọi nghiệp vụ (mục 15), và
Nguyên tắc 2 nói một People Database dùng chung. Đẻ thêm một bảng tín hiệu song
song nghĩa là màn hình Person 360 phải hợp nhất hai nguồn, và sớm muộn sẽ có chỗ
chỉ đọc một trong hai. Bài viết trên mạng sinh ra `people.Signal` như mọi tín
hiệu khác; `SocialPost` giữ phần bằng chứng thô.

Ranh giới với Edge giữ nguyên như phần tuyển dụng: **Edge lo trình duyệt, Hub lo
trí tuệ.** Hub không bao giờ giữ cookie hay mật khẩu Facebook — `SocialAccount`
ở đây chỉ là cái tên và trạng thái để người vận hành biết máy nào đang nghe gì.
"""
from django.conf import settings
from django.db import models

PROVIDER_FACEBOOK = "facebook"
PROVIDER_CHOICES = [
    (PROVIDER_FACEBOOK, "Facebook"),
    ("zalo", "Zalo"),
    ("linkedin", "LinkedIn"),
]


class SocialAccount(models.Model):
    """Tài khoản mạng xã hội dùng để nghe.

    Đăng nhập, cookie và profile trình duyệt nằm ở Edge. Bảng này chỉ để người
    vận hành nhìn thấy: máy nào đang dùng tài khoản nào, cho mục đích gì, lần
    cuối còn sống là khi nào.
    """

    PURPOSE_LISTEN = "listen"
    PURPOSE_ENGAGE = "engage"
    PURPOSE_CHOICES = [
        (PURPOSE_LISTEN, "Chỉ nghe"),
        (PURPOSE_ENGAGE, "Nghe và tương tác"),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES,
                                default=PROVIDER_FACEBOOK)
    label = models.CharField("Tên gợi nhớ", max_length=150)
    handle = models.CharField("Tên tài khoản", max_length=200, blank=True, default="")
    edge = models.ForeignKey("core.Edge", null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="social_accounts")
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES,
                               default=PURPOSE_LISTEN)
    is_active = models.BooleanField(default=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tài khoản mạng xã hội"
        verbose_name_plural = "Tài khoản mạng xã hội"
        ordering = ["provider", "label"]

    def __str__(self):
        return f"{self.get_provider_display()}: {self.label}"


class Community(models.Model):
    """Một nhóm/trang đang theo dõi."""

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES,
                                default=PROVIDER_FACEBOOK)
    external_id = models.CharField("Mã trên nền tảng", max_length=200)
    name = models.CharField(max_length=300)
    url = models.URLField(blank=True, default="")

    # Nhóm này thường bàn chuyện gì. Đưa vào prompt khi chấm ý định: cùng một
    # câu "em cần tư vấn" trong nhóm tuyển dụng và trong nhóm vay vốn là hai ý
    # định khác hẳn nhau (Master Plan mục 30 — "group context").
    topic = models.CharField("Chủ đề", max_length=200, blank=True, default="")
    member_count = models.PositiveIntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    account = models.ForeignKey(SocialAccount, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="communities")
    last_scanned_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Nhóm/trang theo dõi"
        verbose_name_plural = "Nhóm/trang theo dõi"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id"],
                                    name="uq_community_provider_external"),
        ]

    def __str__(self):
        return self.name


class SocialPost(models.Model):
    """Một bài đã bắt được, kèm điểm ý định do AI chấm.

    Điểm ý định là **đa nhãn** (Master Plan mục 30): một bài có thể vừa mang ý
    định tìm việc vừa mang ý định vay tiền. Ép về một nhãn duy nhất là bịa ra
    một lựa chọn mà dữ liệu không có.
    """

    STATUS_NEW = "new"
    STATUS_SCORED = "scored"
    STATUS_LINKED = "linked"
    STATUS_IGNORED = "ignored"
    STATUS_CHOICES = [
        (STATUS_NEW, "Mới bắt được"),
        (STATUS_SCORED, "Đã chấm ý định"),
        (STATUS_LINKED, "Đã gắn với hồ sơ người"),
        (STATUS_IGNORED, "Không liên quan"),
    ]

    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES,
                                default=PROVIDER_FACEBOOK)
    external_id = models.CharField("Mã bài trên nền tảng", max_length=200)
    community = models.ForeignKey(Community, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="posts")

    author_name = models.CharField(max_length=200, blank=True, default="")
    author_handle = models.CharField(max_length=200, blank=True, default="")
    author_url = models.URLField(blank=True, default="")

    content = models.TextField()
    url = models.URLField(blank=True, default="")
    posted_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Điểm ý định theo từng nghiệp vụ: {"talent": 0.91, "rb": 0.07}
    intent = models.JSONField(default=dict, blank=True)
    # Vì sao AI chấm như vậy — câu chữ để người đọc, không phải log gỡ lỗi.
    intent_reason = models.CharField(max_length=500, blank=True, default="")
    intent_fallback = models.BooleanField(
        default=False,
        help_text="Điểm do dò từ khoá vì không gọi được LLM")

    # Liên hệ AI đọc được ngay trong bài (nhiều người để lại SĐT/email). Đây là
    # đầu vào để phân giải ra Person.
    contacts = models.JSONField(default=dict, blank=True)
    person = models.ForeignKey("people.Person", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="social_posts")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_NEW, db_index=True)
    captured_by = models.ForeignKey(SocialAccount, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="posts")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bài trên mạng xã hội"
        verbose_name_plural = "Bài trên mạng xã hội"
        ordering = ["-posted_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id"],
                                    name="uq_socialpost_provider_external"),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["community", "-posted_at"]),
        ]

    def __str__(self):
        return f"{self.author_name or 'ẩn danh'}: {self.content[:60]}"

    def score(self, domain):
        try:
            return float((self.intent or {}).get(domain) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def top_domain(self):
        """Nghiệp vụ có điểm cao nhất, hoặc None nếu chưa chấm."""
        rows = [(k, v) for k, v in (self.intent or {}).items()
                if isinstance(v, (int, float))]
        return max(rows, key=lambda item: item[1])[0] if rows else None


class SocialComment(models.Model):
    """Bình luận dưới một bài — bằng chứng thêm cho ý định (mục 30)."""

    post = models.ForeignKey(SocialPost, on_delete=models.CASCADE,
                             related_name="comments")
    external_id = models.CharField(max_length=200, blank=True, default="")
    author_name = models.CharField(max_length=200, blank=True, default="")
    author_handle = models.CharField(max_length=200, blank=True, default="")
    content = models.TextField()
    posted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bình luận"
        verbose_name_plural = "Bình luận"
        ordering = ["posted_at", "id"]

    def __str__(self):
        return f"{self.author_name}: {self.content[:40]}"


class SocialAction(models.Model):
    """Việc MSB làm với một bài (Master Plan mục 34).

    Cùng nguyên tắc với thư tiếp cận ở luồng săn: **AI soạn, người bấm gửi.**
    Không có trạng thái nào ở đây khiến hệ thống tự đăng hay tự bình luận nhân
    danh MSB — `posted` chỉ là người dùng xác nhận đã tự làm.
    """

    KIND_COMMENT = "comment"
    KIND_MESSAGE = "message"
    KIND_SEED_POST = "seed_post"
    KIND_CHOICES = [
        (KIND_COMMENT, "Bình luận vào bài"),
        (KIND_MESSAGE, "Nhắn tin riêng"),
        (KIND_SEED_POST, "Đăng bài tuyển dụng"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_APPROVED = "approved"
    STATUS_POSTED = "posted"
    STATUS_DISCARDED = "discarded"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "AI soạn nháp"),
        (STATUS_APPROVED, "Đã duyệt"),
        (STATUS_POSTED, "Đã đăng/gửi"),
        (STATUS_DISCARDED, "Bỏ"),
    ]

    post = models.ForeignKey(SocialPost, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="actions")
    community = models.ForeignKey(Community, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="actions")
    hiring_need = models.ForeignKey("hiring.HiringNeed", null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="social_actions")

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_COMMENT)
    content = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT, db_index=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_by_name = models.CharField(max_length=150, blank=True, default="")
    posted_at = models.DateTimeField(null=True, blank=True)
    # Kết quả thu được (mục 35): số phản hồi, số tin nhắn, ứng viên tạo ra.
    outcome = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hành động trên mạng xã hội"
        verbose_name_plural = "Hành động trên mạng xã hội"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if self.created_by_id and not self.created_by_name:
            self.created_by_name = str(self.created_by)[:150]
        return super().save(*args, **kwargs)
