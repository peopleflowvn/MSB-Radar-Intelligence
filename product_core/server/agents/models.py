# -*- coding: utf-8 -*-
"""Radar Agent Runtime — quan sát được, không tự quyết định (Master Plan mục 41, 14).

**Điều KHÔNG làm ở đây, cố ý:** không có một vòng lặp "LLM chọn tool nào, gọi mấy
lần, theo thứ tự nào". Toàn bộ dự án — từ `talent/scoring.py` tới
`hiring/calibration.py` tới `social/intent.py` — giữ đúng một ranh giới: **LLM
diễn giải, code quyết định.** Một agent runtime để mô hình tự lập kế hoạch rồi
gọi tool sẽ phá đúng ranh giới đó ở đúng chỗ hại nhất — hành động có hậu quả
thật (tạo cơ hội, soạn thư, đổi trạng thái).

Nên "agent" ở đây nghĩa là: **một chuỗi bước đã biết trước, viết bằng code**,
mỗi bước có thể gọi LLM hoặc không, và runtime ghi lại toàn bộ chuỗi đó để trả
lời đúng những câu Master Plan mục 42 (Agent UI) đòi hỏi:

    Goal · Activity · Sources searched · Results · Why · Actions

`AgentRun` ghi một lượt chạy trọn vẹn (một câu hỏi, một cơ hội, một bài đăng).
`AgentStep` ghi từng bước trong đó — tên tool, nhãn tiếng Việt cho người dùng,
có gọi LLM không (và nếu có thì provider/model nào), mất bao lâu, có lỗi không.

Khác với `ai.models.LLMCall` (log MỖI lượt gọi LLM riêng lẻ), `AgentRun` ghi ở
tầng cao hơn: một lượt tìm kiếm có thể gồm 2 lượt gọi LLM (dịch câu hỏi, giải
thích kết quả) cộng nhiều bước không gọi LLM (truy vấn CSDL, chấm điểm). Không
có tầng này thì không ai trả lời được câu "tuần trước hệ thống đã chạy bao
nhiêu lượt tìm, mất trung bình bao lâu, tỉ lệ lỗi bao nhiêu" — đúng thứ mục 41
gọi là "observability".
"""
from django.conf import settings
from django.db import models

AGENT_TALENT = "talent"
AGENT_RB = "rb"
AGENT_SOCIAL = "social"
AGENT_CHOICES = [
    (AGENT_TALENT, "Talent Radar Agent"),
    (AGENT_RB, "RB Radar Agent"),
    (AGENT_SOCIAL, "Social Intent Agent"),
]


class AgentRun(models.Model):
    """Một lượt chạy trọn vẹn của một domain agent."""

    STATUS_RUNNING = "running"
    STATUS_OK = "ok"
    STATUS_ERROR = "error"
    STATUS_CHOICES = [
        (STATUS_RUNNING, "Đang chạy"),
        (STATUS_OK, "Xong"),
        (STATUS_ERROR, "Lỗi"),
    ]

    agent = models.CharField(max_length=20, choices=AGENT_CHOICES, db_index=True)
    # "Goal" theo mục 42 — câu hỏi, tên vị trí, hoặc bài đăng đang xét. Cắt bớt
    # vì đây là log vận hành, không phải nơi lưu trữ nội dung đầy đủ.
    goal = models.CharField(max_length=500, blank=True, default="")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_RUNNING, db_index=True)
    error = models.CharField(max_length=500, blank=True, default="")

    # Kết quả tóm tắt để hiện trong danh sách mà không phải mở từng bước —
    # ví dụ {"count": 8, "top_score": 0.93}. Tự do theo từng agent.
    result_summary = models.JSONField(default=dict, blank=True)

    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Lượt chạy Agent"
        verbose_name_plural = "Lượt chạy Agent"
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["agent", "-started_at"]),
            models.Index(fields=["status", "-started_at"]),
        ]

    def __str__(self):
        return f"{self.get_agent_display()}: {self.goal[:60]}"

    @property
    def duration_ms(self):
        if not self.finished_at:
            return None
        return int((self.finished_at - self.started_at).total_seconds() * 1000)


class AgentStep(models.Model):
    """Một bước bên trong một lượt chạy — "Activity" theo mục 42.

    `tool` là tên kỹ thuật (khớp với `agents.tools.TOOLS`), `label` là câu tiếng
    Việt cho người dùng đọc — cùng cách `talent/ai_search.py` đã làm với
    `trace` từ trước, giờ chuyển sang lưu lại thay vì chỉ tồn tại trong bộ nhớ
    của một lượt gọi API.
    """

    run = models.ForeignKey(AgentRun, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveIntegerField()
    tool = models.CharField(max_length=60, blank=True, default="")
    label = models.CharField(max_length=200)
    detail = models.CharField(max_length=500, blank=True, default="")

    ok = models.BooleanField(default=True)
    # Rỗng nếu bước này không gọi LLM — phần lớn bước là truy vấn CSDL hoặc
    # tính toán tất định, và để trống mới đúng, không phải "chưa biết".
    provider = models.CharField(max_length=40, blank=True, default="")
    model_name = models.CharField(max_length=100, blank=True, default="")
    duration_ms = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bước Agent"
        verbose_name_plural = "Bước Agent"
        ordering = ["run", "order"]
        constraints = [
            models.UniqueConstraint(fields=["run", "order"], name="uq_agentstep_run_order"),
        ]

    def __str__(self):
        return f"{self.order}. {self.label}"
