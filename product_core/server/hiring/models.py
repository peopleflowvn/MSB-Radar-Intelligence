# -*- coding: utf-8 -*-
"""Nhu cầu tuyển dụng và luồng làm việc của Hiring Manager (Master Plan mục 20, 21).

Ba mô hình, ba vai trò rõ ràng:

    HiringNeed    một vị trí đang cần tuyển — do HM tạo, có JD và tiêu chí
    Candidacy     một Person được xét cho một HiringNeed, kèm đánh giá của HM
    HuntRequest   shortlist/worklist ứng viên do Recruiter hoặc RM quản lý

`Candidacy` cố ý tách khỏi `Pool` của Talent Radar: Pool là nhóm do recruiter tự gom
để làm việc, còn Candidacy gắn với một vị trí cụ thể và mang **đánh giá phù hợp/không
phù hợp** — thứ dùng để hiệu chỉnh xếp hạng (mục 21). Gộp lại thì "đã xem người này
cho vị trí A" lẫn với "đã bỏ vào nhóm B".
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class HiringNeed(models.Model):
    """Một vị trí đang cần tuyển."""

    STATUS_DRAFT = "draft"
    STATUS_OPEN = "open"
    STATUS_HUNTING = "hunting"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Nháp"),
        (STATUS_OPEN, "Đang mở"),
        (STATUS_HUNTING, "Đã nhờ recruiter săn"),
        (STATUS_CLOSED, "Đã đóng"),
    ]

    title = models.CharField("Vị trí cần tuyển", max_length=200)
    department = models.CharField("Bộ phận", max_length=150, blank=True, default="")
    jd_text = models.TextField("Mô tả công việc", blank=True, default="",
                               help_text="Dán JD vào đây; hệ thống tự rút ra tiêu chí")

    # Tiêu chí tìm kiếm — cùng định dạng mà `talent.search()` nhận. Có thể do AI
    # rút từ JD hoặc do HM sửa tay. Một định dạng duy nhất cho cả tìm thủ công,
    # tìm bằng AI và nhu cầu tuyển dụng: không có đường thứ hai.
    criteria = models.JSONField(default=dict, blank=True)

    # True = tiêu chí do dò chữ vì LLM bận/hết hạn mức, không phải do AI đọc JD.
    # Lưu vào CSDL chứ không chỉ trả một lần trong phản hồi: HM mở lại vị trí này
    # ngày mai vẫn phải thấy cảnh báo, nếu không họ sẽ tin nhầm vào tiêu chí thô.
    criteria_fallback = models.BooleanField(default=False)

    # Trọng số học được từ đánh giá của HM (mục 21). Rỗng = dùng trọng số mặc định.
    learned_weights = models.JSONField(default=dict, blank=True, editable=False)
    calibrated_at = models.DateTimeField(null=True, blank=True)

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="hiring_needs")
    owner_name = models.CharField(max_length=150, blank=True, default="")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_DRAFT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Nhu cầu tuyển dụng"
        verbose_name_plural = "Nhu cầu tuyển dụng"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["owner", "-updated_at"])]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.owner_id and not self.owner_name:
            self.owner_name = str(self.owner)[:150]
        return super().save(*args, **kwargs)

    @property
    def is_calibrated(self):
        return bool(self.learned_weights)


class Candidacy(models.Model):
    """Một Person được xét cho một HiringNeed, kèm đánh giá của Hiring Manager."""

    STATE_SUGGESTED = "suggested"
    STATE_GOOD_FIT = "good_fit"
    STATE_NOT_FIT = "not_fit"
    STATE_SHORTLISTED = "shortlisted"
    STATE_CHOICES = [
        (STATE_SUGGESTED, "Hệ thống đề xuất"),
        (STATE_GOOD_FIT, "Phù hợp"),
        (STATE_NOT_FIT, "Không phù hợp"),
        (STATE_SHORTLISTED, "Đưa vào shortlist"),
    ]

    # Các trạng thái mang tín hiệu hiệu chỉnh (mục 21). Shortlist nằm ở đây vì
    # nó là lời khen mạnh hơn "phù hợp" — xem hiring/calibration.py.
    FEEDBACK_STATES = (STATE_GOOD_FIT, STATE_NOT_FIT, STATE_SHORTLISTED)

    hiring_need = models.ForeignKey(HiringNeed, on_delete=models.CASCADE,
                                    related_name="candidacies")
    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="candidacies")
    state = models.CharField(max_length=20, choices=STATE_CHOICES,
                             default=STATE_SUGGESTED, db_index=True)

    # Ảnh chụp điểm và từng chiều tại thời điểm đề xuất. Giữ lại vì hiệu chỉnh
    # cần biết CHIỀU NÀO cao/thấp ở những người được đánh giá phù hợp — chấm lại
    # sau sẽ ra điểm khác (dữ liệu đã đổi, trọng số đã đổi) và tín hiệu bị lệch.
    score_snapshot = models.FloatField(default=0.0)
    dimensions_snapshot = models.JSONField(default=list, blank=True)

    note = models.CharField(max_length=500, blank=True, default="")
    marked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                  on_delete=models.SET_NULL, related_name="+")
    marked_by_name = models.CharField(max_length=150, blank=True, default="")
    marked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ứng viên cho vị trí"
        verbose_name_plural = "Ứng viên cho vị trí"
        ordering = ["-score_snapshot"]
        constraints = [
            models.UniqueConstraint(fields=["hiring_need", "person"],
                                    name="uq_candidacy_need_person"),
        ]
        indexes = [models.Index(fields=["hiring_need", "state"])]

    def __str__(self):
        return f"{self.person} — {self.hiring_need} ({self.get_state_display()})"

    def mark(self, state, user=None, note=""):
        self.state = state
        self.marked_by = user
        self.marked_by_name = str(user)[:150] if user else ""
        self.marked_at = timezone.now()
        if note:
            self.note = note[:500]
        self.save()


class HuntRequest(models.Model):
    """Danh sách xử lý ứng viên do Recruiter trực tiếp tạo và quản lý.

    Bản ghi độc lập với HiringNeed để dùng được như một worklist CRM. Khóa ngoại
    HiringNeed chỉ còn phục vụ dữ liệu lịch sử từ luồng cũ.
    """

    STATUS_NEW = "new"
    STATUS_ACCEPTED = "accepted"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_DONE = "done"
    STATUS_DECLINED = "declined"
    STATUS_CHOICES = [
        (STATUS_NEW, "Mới, chưa ai nhận"),
        (STATUS_ACCEPTED, "Recruiter đã nhận"),
        (STATUS_IN_PROGRESS, "Đang liên hệ ứng viên"),
        (STATUS_DONE, "Đã xong"),
        (STATUS_DECLINED, "Từ chối"),
    ]

    OPEN_STATUSES = (STATUS_NEW, STATUS_ACCEPTED, STATUS_IN_PROGRESS)

    title = models.CharField("Tên shortlist", max_length=200, blank=True, default="")
    hiring_need = models.ForeignKey(HiringNeed, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name="hunt_requests")
    people = models.ManyToManyField("people.Person", blank=True,
                                    through="HuntCandidate",
                                    related_name="hunt_requests",
                                    help_text="Ứng viên trong shortlist")

    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="hunt_requests")
    requested_by_name = models.CharField(max_length=150, blank=True, default="")

    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="assigned_hunts")
    assigned_to_name = models.CharField(max_length=150, blank=True, default="")

    message = models.TextField("Lời nhắn cho recruiter", blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_NEW, db_index=True)
    decline_reason = models.CharField(max_length=300, blank=True, default="")
    priority = models.CharField(max_length=10, choices=[
        ("low", "Thấp"), ("normal", "Bình thường"),
        ("high", "Cao"), ("urgent", "Khẩn cấp")],
        default="normal", db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Shortlist xử lý ứng viên"
        verbose_name_plural = "Shortlist xử lý ứng viên"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["assigned_to", "status"]),
        ]

    def __str__(self):
        return f"{self.title or self.hiring_need or 'Shortlist'} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if self.requested_by_id and not self.requested_by_name:
            self.requested_by_name = str(self.requested_by)[:150]
        if self.assigned_to_id and not self.assigned_to_name:
            self.assigned_to_name = str(self.assigned_to)[:150]
        return super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class HuntCandidate(models.Model):
    """Một ứng viên bên trong một danh sách xử lý, kèm trạng thái công việc riêng.

    Trạng thái của `HuntRequest` nói recruiter đã nhận việc chưa; trạng thái ở
    đây nói **từng người** đã liên hệ tới đâu. Hai thứ khác nhau: một yêu cầu 5
    người thường có người đã nhận lời, người chưa bắt máy, người từ chối — gộp
    lại thành một trạng thái duy nhất là mất chính thông tin recruiter cần.

    Đây cũng là bảng trung gian của `HuntRequest.people`, nên mỗi người chỉ nằm
    trong một yêu cầu đúng một lần.
    """

    STATE_PENDING = "pending"
    STATE_CONTACTING = "contacting"
    STATE_RESPONDED = "responded"
    STATE_INTERESTED = "interested"
    STATE_NOT_INTERESTED = "not_interested"
    STATE_UNREACHABLE = "unreachable"
    STATE_SUBMITTED = "submitted"
    STATE_RETURNED = "returned"
    STATE_CHOICES = [
        (STATE_PENDING, "Mới trong danh sách"),
        (STATE_CONTACTING, "Đang liên hệ"),
        (STATE_RESPONDED, "Đã phản hồi"),
        (STATE_INTERESTED, "Có quan tâm"),
        (STATE_NOT_INTERESTED, "Chưa quan tâm"),
        (STATE_UNREACHABLE, "Không liên hệ được"),
        (STATE_SUBMITTED, "Hoàn tất mục tiêu"),
        (STATE_RETURNED, "Đưa về chăm sóc dài hạn"),
    ]

    # Đã xong việc với người này — không còn nằm trong danh sách cần làm.
    CLOSED_STATES = (STATE_SUBMITTED, STATE_RETURNED)

    # Trạng thái quan hệ (people.Relationship) tương ứng. Cập nhật cả hai nơi vì
    # `Relationship` là thứ NGƯỜI KHÁC nhìn thấy khi mở hồ sơ ngoài luồng săn này.
    RELATIONSHIP_MAP = {
        STATE_CONTACTING: "attempted",
        STATE_RESPONDED: "connected",
        STATE_INTERESTED: "interested",
        STATE_NOT_INTERESTED: "unavailable",
        STATE_UNREACHABLE: "attempted",
        STATE_SUBMITTED: "ready",
        STATE_RETURNED: "nurturing",
    }

    hunt_request = models.ForeignKey(HuntRequest, on_delete=models.CASCADE,
                                     related_name="candidates")
    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="hunt_candidates")
    state = models.CharField(max_length=20, choices=STATE_CHOICES,
                             default=STATE_PENDING, db_index=True)

    # Thư tiếp cận do AI soạn. Lưu lại chứ không chỉ hiện một lần: recruiter sửa
    # rồi mới gửi, và lần sau mở lại phải thấy đúng thứ mình đã gửi.
    outreach_draft = models.TextField(blank=True, default="")
    outreach_sent_at = models.DateTimeField(null=True, blank=True)

    note = models.CharField(max_length=500, blank=True, default="")
    next_action_at = models.DateTimeField(null=True, blank=True, db_index=True)
    priority = models.CharField(max_length=10, choices=[
        ("low", "Thấp"), ("normal", "Bình thường"),
        ("high", "Cao"), ("urgent", "Khẩn cấp")],
        default="normal", db_index=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_hunt_candidates")
    assigned_to_name = models.CharField(max_length=150, blank=True, default="")
    # Vì sao trả người này về kho. Bắt buộc khi trả về — một hồ sơ quay lại kho
    # mà không ai biết vì sao thì lần sau lại có người gọi lại từ đầu.
    return_reason = models.CharField(max_length=300, blank=True, default="")

    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    # Mốc bắt đầu của trạng thái hiện tại. SLA phải dựa vào mốc này, không dựa vào
    # ``updated_at`` vì sửa ghi chú/phân công/nháp thư không được phép kéo dài SLA.
    stage_entered_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ứng viên trong yêu cầu săn"
        verbose_name_plural = "Ứng viên trong yêu cầu săn"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["hunt_request", "person"],
                                    name="uq_huntcandidate_hunt_person"),
        ]
        indexes = [
            models.Index(fields=["hunt_request", "state"]),
            models.Index(fields=["assigned_to", "state", "next_action_at"],
                         name="hiring_hc_owner_state_due"),
            models.Index(fields=["person", "state"], name="hiring_hc_person_state"),
        ]

    def __str__(self):
        return f"{self.person} — {self.get_state_display()}"

    @property
    def is_closed(self):
        return self.state in self.CLOSED_STATES

    def save(self, *args, **kwargs):
        if self.assigned_to_id and not self.assigned_to_name:
            self.assigned_to_name = str(self.assigned_to)[:150]
        return super().save(*args, **kwargs)


class HuntCandidateStatusEvent(models.Model):
    """Lịch sử trạng thái theo từng worklist; không bị ghi đè bởi lần cập nhật sau."""

    candidate = models.ForeignKey(HuntCandidate, on_delete=models.CASCADE,
                                  related_name="status_events")
    from_state = models.CharField(max_length=20, blank=True, default="")
    to_state = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    actor_name = models.CharField(max_length=150, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["candidate", "-created_at"])]

    def save(self, *args, **kwargs):
        if self.actor_id and not self.actor_name:
            self.actor_name = str(self.actor)[:150]
        return super().save(*args, **kwargs)
