# -*- coding: utf-8 -*-
"""RB Radar — góc nhìn bán lẻ về cùng những con người đó (Master Plan mục 25).

Đây là chỗ **Nguyên tắc 2 thành code**: *một People Database, nhiều nghiệp vụ.*

```text
Person                          con người — dùng chung, không sao chép
├── TalentProfile               góc nhìn tuyển dụng      (Phase 6)
└── RBProfile                   góc nhìn bán lẻ          (Phase 12)
```

`RBProfile` **không** giữ tên, email hay số điện thoại. Chép sang đây là tự tay
tạo ra bài toán "hai bản ghi cùng một người lệch nhau" mà cả dự án này sinh ra
để giải. Liên hệ luôn đọc từ `Person`.

Vì sao tách khỏi `TalentProfile` thay vì thêm cột: hai nghiệp vụ có vòng đời
khác hẳn nhau. `lead_status` của bán lẻ và `state` quan hệ tuyển dụng không phải
cùng một trục — Master Plan mục 16 nói rõ không ép hai nghiệp vụ dùng chung một
pipeline.

**Ranh giới quyền:** RB Sales đọc được dữ liệu tuyển dụng theo quyết định
19/08/2026, nhưng đó là truy cập LIÊN NGHIỆP VỤ và bị `AccessLog` đánh dấu riêng
(xem `docs/ACCESS_CONTROL.md` mục 4.3). Chiều ngược lại — recruiter đọc hồ sơ
bán lẻ — chưa được mở.
"""
from django.conf import settings
from django.db import models
from pgvector.django import VectorField
from django.utils import timezone

# Nhóm sản phẩm bán lẻ. Cố ý là hằng số trong code chứ không phải một bảng: đây
# là danh mục sản phẩm của ngân hàng, đổi vài năm một lần, và để trong code thì
# mọi chỗ tham chiếu đều kiểm được lúc chạy test.
PRODUCT_CREDIT_CARD = "credit_card"
PRODUCT_MORTGAGE = "mortgage"
PRODUCT_AUTO_LOAN = "auto_loan"
PRODUCT_CONSUMER_LOAN = "consumer_loan"
PRODUCT_SAVINGS = "savings"
PRODUCT_INVESTMENT = "investment"
PRODUCT_INSURANCE = "insurance"
PRODUCT_FX = "fx"
PRODUCT_PAYROLL = "payroll"

PRODUCT_CHOICES = [
    (PRODUCT_CREDIT_CARD, "Thẻ tín dụng"),
    (PRODUCT_MORTGAGE, "Vay mua nhà"),
    (PRODUCT_AUTO_LOAN, "Vay mua xe"),
    (PRODUCT_CONSUMER_LOAN, "Vay tiêu dùng"),
    (PRODUCT_SAVINGS, "Tiết kiệm"),
    (PRODUCT_INVESTMENT, "Đầu tư"),
    (PRODUCT_INSURANCE, "Bảo hiểm"),
    (PRODUCT_FX, "Ngoại tệ / chuyển tiền quốc tế"),
    (PRODUCT_PAYROLL, "Tài khoản lương"),
]
PRODUCT_LABELS = dict(PRODUCT_CHOICES)


class RBProfile(models.Model):
    """Góc nhìn bán lẻ về một Person.

    Cố ý mỏng. Mọi thứ suy ra được từ `Person` thì đọc từ đó, không chép lại.
    """

    LEAD_COLD = "cold"
    LEAD_WARM = "warm"
    LEAD_INTERESTED = "interested"
    LEAD_QUALIFIED = "qualified"
    LEAD_CONVERTED = "converted"
    LEAD_DORMANT = "dormant"
    LEAD_CHOICES = [
        (LEAD_COLD, "Chưa tiếp cận"),
        (LEAD_WARM, "Đã tiếp cận"),
        (LEAD_INTERESTED, "Có quan tâm"),
        (LEAD_QUALIFIED, "Đủ điều kiện"),
        (LEAD_CONVERTED, "Đã dùng sản phẩm"),
        (LEAD_DORMANT, "Nguội"),
    ]

    SEGMENT_MASS = "mass"
    SEGMENT_AFFLUENT = "affluent"
    SEGMENT_PRIORITY = "priority"
    SEGMENT_CHOICES = [
        (SEGMENT_MASS, "Phổ thông"),
        (SEGMENT_AFFLUENT, "Khá giả"),
        (SEGMENT_PRIORITY, "Ưu tiên"),
    ]

    person = models.OneToOneField("people.Person", on_delete=models.CASCADE,
                                  related_name="rb_profile")

    sales_owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="rb_customers")
    sales_owner_name = models.CharField(max_length=150, blank=True, default="")

    lead_status = models.CharField(max_length=20, choices=LEAD_CHOICES,
                                   default=LEAD_COLD, db_index=True)
    segment = models.CharField(max_length=20, choices=SEGMENT_CHOICES,
                               blank=True, default="")

    # Nghề nghiệp/công ty ở đây là góc nhìn BÁN LẺ (dùng để đánh giá thu nhập),
    # có thể khác chức danh trong CV — CV nói người ta muốn làm gì, còn hồ sơ
    # bán lẻ nói người ta đang làm gì.
    occupation = models.CharField("Nghề nghiệp", max_length=200, blank=True, default="")
    employer = models.CharField("Nơi làm việc", max_length=200, blank=True, default="")

    interaction_summary = models.TextField(blank=True, default="")
    last_contact_at = models.DateTimeField(null=True, blank=True)
    next_action = models.CharField(max_length=300, blank=True, default="")
    next_action_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ khách hàng cá nhân"
        verbose_name_plural = "Hồ sơ khách hàng cá nhân"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["lead_status", "-updated_at"])]

    def __str__(self):
        return f"{self.person} — {self.get_lead_status_display()}"

    def save(self, *args, **kwargs):
        if self.sales_owner_id and not self.sales_owner_name:
            self.sales_owner_name = str(self.sales_owner)[:150]
        return super().save(*args, **kwargs)


class ProductInterest(models.Model):
    """Một nhóm sản phẩm mà người này có dấu hiệu quan tâm.

    Tách khỏi `RBOpportunity` vì hai thứ khác nhau: quan tâm là **thứ ta quan
    sát được**, còn cơ hội là **việc RM quyết định theo đuổi**. Một người có thể
    quan tâm ba nhóm sản phẩm mà không sinh cơ hội nào — và trộn lại thì danh
    sách việc cần làm của RM đầy những thứ chưa ai định làm.
    """

    profile = models.ForeignKey(RBProfile, on_delete=models.CASCADE,
                                related_name="interests")
    product = models.CharField(max_length=30, choices=PRODUCT_CHOICES, db_index=True)
    confidence = models.FloatField(default=0.0, help_text="0..1")

    # Vì sao tin là họ quan tâm. Bắt buộc theo Nguyên tắc 4 — cùng lý do với
    # `people.Signal.evidence`.
    evidence = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=40, blank=True, default="",
                              help_text="social, cv, rm_nhap_tay…")

    observed_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quan tâm sản phẩm"
        verbose_name_plural = "Quan tâm sản phẩm"
        ordering = ["-confidence", "-observed_at"]
        constraints = [
            models.UniqueConstraint(fields=["profile", "product"],
                                    name="uq_productinterest_profile_product"),
        ]

    def __str__(self):
        return f"{self.get_product_display()} ({self.confidence:.2f})"


class RBOpportunity(models.Model):
    """Một cơ hội bán hàng RM đang theo đuổi (Master Plan mục 32).

    Cùng khuôn với `HuntRequest` bên tuyển dụng: có người nhận, có trạng thái,
    và **bỏ thì phải ghi lý do**. Một cơ hội bị đóng im lặng sẽ được hệ thống đề
    xuất lại vào tháng sau, và khách hàng nhận đúng lời chào đã từ chối.
    """

    STATUS_NEW = "new"
    STATUS_ACCEPTED = "accepted"
    STATUS_CONTACTING = "contacting"
    STATUS_WON = "won"
    STATUS_LOST = "lost"
    STATUS_CHOICES = [
        (STATUS_NEW, "Mới"),
        (STATUS_ACCEPTED, "Đã nhận"),
        (STATUS_CONTACTING, "Đang liên hệ"),
        (STATUS_WON, "Thành công"),
        (STATUS_LOST, "Không thành"),
    ]
    OPEN_STATUSES = (STATUS_NEW, STATUS_ACCEPTED, STATUS_CONTACTING)

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="rb_opportunities")
    product = models.CharField(max_length=30, choices=PRODUCT_CHOICES, db_index=True)

    need = models.CharField("Nhu cầu", max_length=300, blank=True, default="",
                            help_text="Nói bằng lời của khách, không phải tên sản phẩm")
    confidence = models.FloatField(default=0.0)
    evidence = models.JSONField(default=dict, blank=True)
    suggested_action = models.CharField(max_length=300, blank=True, default="")

    # Tín hiệu sinh ra cơ hội này. Giữ liên kết để mở lại được bằng chứng gốc.
    signal = models.ForeignKey("people.Signal", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="rb_opportunities")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_NEW, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL,
                                    related_name="rb_opportunities")
    assigned_to_name = models.CharField(max_length=150, blank=True, default="")
    close_reason = models.CharField(max_length=300, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")
    next_action_at = models.DateTimeField(null=True, blank=True, db_index=True)
    priority = models.CharField(max_length=10, choices=[
        ("low", "Thấp"), ("normal", "Bình thường"),
        ("high", "Cao"), ("urgent", "Khẩn cấp")],
        default="normal", db_index=True)

    # Theo dõi phản hồi (Master Plan mục 35). Lưu lại chứ không chỉ hiện một
    # lần: RM sửa nội dung AI soạn rồi mới gửi, và lần sau mở lại phải thấy
    # đúng thứ mình đã gửi — cùng lý do với `HuntCandidate.outreach_draft`.
    outreach_draft = models.TextField(blank=True, default="")
    outreach_sent_at = models.DateTimeField(null=True, blank=True)

    # SLA phải bám thời điểm đi vào trạng thái, không bị gia hạn bởi thao tác
    # không liên quan như lưu ghi chú, đổi ưu tiên hay sửa bản nháp.
    stage_entered_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cơ hội bán lẻ"
        verbose_name_plural = "Cơ hội bán lẻ"
        ordering = ["-confidence", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-created_at"]),
            models.Index(fields=["assigned_to", "status"]),
            models.Index(fields=["assigned_to", "status", "next_action_at"],
                         name="rb_opp_owner_status_due_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["person", "product"],
                condition=models.Q(status__in=("new", "accepted", "contacting")),
                name="uq_rb_open_opportunity_person_product"),
        ]

    def __str__(self):
        return f"{self.get_product_display()} cho {self.person}"

    def save(self, *args, **kwargs):
        if self.assigned_to_id and not self.assigned_to_name:
            self.assigned_to_name = str(self.assigned_to)[:150]
        return super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status in self.OPEN_STATUSES


class ProductValueConfig(models.Model):
    """Giá trị kinh doanh kỳ vọng của mỗi nhóm sản phẩm — **cấu hình, không hardcode**.

    Vì sao là một bảng chứ không phải hằng số trong code như `PRODUCT_CHOICES`:
    danh mục sản phẩm đổi vài năm một lần, nhưng *giá trị kinh tế* của từng nhóm
    đổi theo từng quý và theo định hướng kinh doanh từng thời kỳ. Nhét con số
    tiền vào source nghĩa là mỗi lần khối bán lẻ đổi khẩu vị lại phải sửa code
    và deploy lại.

    Quan trọng hơn: đây là dữ liệu **chưa được kiểm chứng**. Đội thi không có số
    biên lợi nhuận thật của MSB, và bịa ra một con số VNĐ cụ thể rồi đem đi thi
    là tự tạo ra một câu hỏi không trả lời được trước hội đồng. Nên mặc định
    dùng thang định tính (Thấp/Trung bình/Cao/Rất cao) — ai có số thật thì nhập
    `value_weight`, còn không thì thang này vẫn xếp hạng đúng thứ tự ưu tiên.
    """

    BAND_LOW = "low"
    BAND_MEDIUM = "medium"
    BAND_HIGH = "high"
    BAND_VERY_HIGH = "very_high"
    BAND_CHOICES = [
        (BAND_LOW, "Thấp"),
        (BAND_MEDIUM, "Trung bình"),
        (BAND_HIGH, "Cao"),
        (BAND_VERY_HIGH, "Rất cao"),
    ]
    #: Điểm quy đổi 0..100 cho mỗi bậc. Dùng khi chưa có `value_weight` thật.
    BAND_SCORES = {BAND_LOW: 25, BAND_MEDIUM: 50, BAND_HIGH: 75, BAND_VERY_HIGH: 100}

    product = models.CharField(max_length=30, choices=PRODUCT_CHOICES, unique=True)
    value_band = models.CharField(max_length=20, choices=BAND_CHOICES,
                                  default=BAND_MEDIUM)
    #: Trọng số giá trị thật (nếu tổ chức có số đã kiểm chứng). 0 = chưa có,
    #: khi đó hệ thống dùng `BAND_SCORES[value_band]`.
    value_weight = models.FloatField(default=0.0,
                                     help_text="0 = chưa có số thật, dùng thang định tính")
    #: Ưu tiên chiến lược của ngân hàng trong kỳ. Nhân vào cuối, không cộng —
    #: một sản phẩm đang được đẩy mạnh phải nổi lên trong CẢ danh sách, chứ
    #: không chỉ nhích vài điểm.
    strategic_weight = models.FloatField(default=1.0, help_text="Hệ số nhân, 1.0 = trung tính")
    business_priority = models.IntegerField(default=0, help_text="Thứ tự hiển thị khi bằng điểm")
    active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cấu hình giá trị sản phẩm"
        verbose_name_plural = "Cấu hình giá trị sản phẩm"
        ordering = ["-business_priority", "product"]

    def __str__(self):
        return f"{self.get_product_display()} — {self.get_value_band_display()}"

    @property
    def effective_value_score(self):
        """Điểm giá trị 0..100. Số thật thắng thang định tính nếu có."""
        if self.value_weight > 0:
            return max(0.0, min(100.0, self.value_weight))
        return float(self.BAND_SCORES.get(self.value_band, 50))


class OpportunitySuggestion(models.Model):
    """Radar **đề xuất** một cơ hội — chưa phải cơ hội thật (Master Plan mục 33).

    Đây là mắt xích còn thiếu giữa tín hiệu và việc RM làm:

    ```text
    Signal → ProductInterest → OpportunitySuggestion → RM ACCEPT → RBOpportunity
    ```

    Trước khi có bảng này, `routing.route_signal()` biến **mọi** tín hiệu đủ
    ngưỡng thành `RBOpportunity` ngay. Hệ quả: hộp thư của RM đầy những việc
    chưa ai quyết định làm, và chỉ số "cơ hội đang mở" mất hết ý nghĩa vì nó đếm
    lẫn cả thứ máy đoán lẫn thứ người đã nhận.

    Ranh giới ở đây là ranh giới **trách nhiệm**, không phải kỹ thuật:

        Suggestion   máy nói "người này có vẻ đáng gọi, đây là bằng chứng"
        Opportunity  người nói "tôi nhận việc này"

    Nên `accept()` là thao tác duy nhất sinh ra `RBOpportunity`, và nó luôn cần
    một `actor` — không có đường nào để hệ thống tự nhận việc thay RM.
    """

    STATUS_NEW = "new"
    STATUS_REVIEWED = "reviewed"
    STATUS_ACCEPTED = "accepted"
    STATUS_SNOOZED = "snoozed"
    STATUS_DISMISSED = "dismissed"
    STATUS_EXPIRED = "expired"
    STATUS_CONVERTED = "converted_to_opportunity"
    STATUS_CHOICES = [
        (STATUS_NEW, "Mới"),
        (STATUS_REVIEWED, "Đã xem"),
        (STATUS_ACCEPTED, "Đã nhận"),
        (STATUS_SNOOZED, "Để sau"),
        (STATUS_DISMISSED, "Bỏ qua"),
        (STATUS_EXPIRED, "Hết hạn"),
        (STATUS_CONVERTED, "Đã thành cơ hội"),
    ]
    #: Trạng thái còn "sống" — còn chiếm chỗ trong danh sách Cơ hội hôm nay và
    #: còn chặn việc tạo đề xuất trùng cho cùng người + cùng sản phẩm.
    ACTIVE_STATUSES = (STATUS_NEW, STATUS_REVIEWED, STATUS_SNOOZED)

    # Next Best Action (Master Plan mục 34). Mã hành động do business logic
    # quyết định, KHÔNG để LLM tự chọn — LLM chỉ được diễn giải và soạn nội
    # dung cho hành động đã chọn.
    ACTION_CALL_NOW = "CALL_NOW"
    ACTION_SEND_MESSAGE = "SEND_MESSAGE"
    ACTION_ASK_FOR_INFORMATION = "ASK_FOR_INFORMATION"
    ACTION_FOLLOW_UP = "FOLLOW_UP"
    ACTION_WAIT = "WAIT"
    ACTION_REACTIVATE = "REACTIVATE"
    ACTION_INVITE_MEETING = "INVITE_MEETING"
    ACTION_CLOSE = "CLOSE"
    ACTION_CHOICES = [
        (ACTION_CALL_NOW, "Gọi ngay"),
        (ACTION_SEND_MESSAGE, "Nhắn tin"),
        (ACTION_ASK_FOR_INFORMATION, "Hỏi thêm thông tin"),
        (ACTION_FOLLOW_UP, "Theo dõi tiếp"),
        (ACTION_WAIT, "Chờ"),
        (ACTION_REACTIVATE, "Kích hoạt lại"),
        (ACTION_INVITE_MEETING, "Mời gặp"),
        (ACTION_CLOSE, "Đóng"),
    ]

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="rb_suggestions")
    product = models.CharField(max_length=30, choices=PRODUCT_CHOICES, db_index=True)

    need_summary = models.CharField("Nhu cầu", max_length=300, blank=True, default="",
                                    help_text="Nói bằng lời của khách, không phải tên sản phẩm")
    #: Bằng chứng thô. Bắt buộc theo Nguyên tắc 4 — cùng lý do với
    #: `people.Signal.evidence`: không có bằng chứng thì không giải thích được,
    #: mà không giải thích được thì RM không có cơ sở để nhận hay bỏ.
    evidence = models.JSONField(default=dict, blank=True)
    source_signals = models.ManyToManyField("people.Signal", blank=True,
                                            related_name="rb_suggestions")

    # Năm chiều điểm, mỗi chiều 0..100 (Master Plan mục 14.2). Lưu riêng từng
    # chiều chứ không chỉ lưu điểm tổng: RM cần biết vì sao điểm cao — "khớp hồ
    # sơ nhưng khó liên hệ" và "dễ liên hệ nhưng chưa rõ nhu cầu" cùng ra 60
    # điểm nhưng là hai việc hoàn toàn khác nhau.
    fit_score = models.FloatField(default=0.0)
    need_score = models.FloatField(default=0.0)
    timing_score = models.FloatField(default=0.0)
    reachability_score = models.FloatField(default=0.0)
    value_score = models.FloatField(default=0.0)

    #: Điểm tổng tất định, tính từ 5 chiều trên bằng `scoring.priority_score()`.
    #: LLM không được tạo ra con số này (Master Plan mục 15).
    priority_score = models.FloatField(default=0.0, db_index=True)
    confidence = models.FloatField(default=0.0, help_text="0..1")

    recommended_action = models.CharField(max_length=30, choices=ACTION_CHOICES,
                                          default=ACTION_FOLLOW_UP)
    #: Diễn giải bằng lời cho RM đọc. Đây là chỗ DUY NHẤT trong bảng này mà LLM
    #: được phép sinh nội dung — và kể cả khi LLM hỏng, các `why` tất định trong
    #: `evidence` vẫn đủ để hiển thị "vì sao bây giờ".
    reasoning_summary = models.TextField(blank=True, default="")

    status = models.CharField(max_length=30, choices=STATUS_CHOICES,
                              default=STATUS_NEW, db_index=True)
    owner_suggestion = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                         on_delete=models.SET_NULL,
                                         related_name="rb_suggestions",
                                         help_text="RM được gợi ý phụ trách; chưa phải người nhận")
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                    on_delete=models.SET_NULL, related_name="+")
    #: Vì sao bỏ qua. Bắt buộc về mặt nghiệp vụ giống `RBOpportunity.close_reason`:
    #: một đề xuất bị bỏ im lặng sẽ được sinh lại y hệt vào tháng sau.
    dismiss_reason = models.CharField(max_length=300, blank=True, default="")
    snoozed_until = models.DateTimeField(null=True, blank=True, db_index=True)

    #: Cơ hội được tạo ra khi RM nhận. Giữ liên kết để đo được tỷ lệ chấp nhận
    #: và để mở lại bằng chứng gốc từ trong cơ hội.
    converted_opportunity = models.ForeignKey(RBOpportunity, null=True, blank=True,
                                              on_delete=models.SET_NULL,
                                              related_name="from_suggestions")

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    #: Tín hiệu có tuổi thọ. "Đang hỏi mua nhà" của sáu tháng trước không còn là
    #: lý do để gọi hôm nay, và để nó nằm mãi trong danh sách sẽ làm RM mất tin
    #: vào toàn bộ danh sách.
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        verbose_name = "Đề xuất cơ hội"
        verbose_name_plural = "Đề xuất cơ hội"
        ordering = ["-priority_score", "-created_at"]
        indexes = [
            models.Index(fields=["status", "-priority_score"]),
            models.Index(fields=["owner_suggestion", "status", "-priority_score"],
                         name="rb_sugg_owner_status_idx"),
            models.Index(fields=["person", "-created_at"]),
        ]
        constraints = [
            # Cùng khuôn với `uq_rb_open_opportunity_person_product`: không đẻ
            # thêm đề xuất khi đã có một cái đang chờ RM xử lý cho đúng sản phẩm
            # đó. Tín hiệu mới thì cập nhật điểm cái đang có, không xếp chồng.
            models.UniqueConstraint(
                fields=["person", "product"],
                condition=models.Q(status__in=("new", "reviewed", "snoozed")),
                name="uq_rb_active_suggestion_person_product"),
        ]

    def __str__(self):
        return f"Đề xuất {self.get_product_display()} cho {self.person}"

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES


class OpportunityOutcome(models.Model):
    """Kết quả thật sau khi RM liên hệ (Master Plan mục 35).

    `RBOpportunity.outreach_sent_at` chỉ trả lời "đã gửi chưa". Bảng này trả lời
    câu đắt hơn nhiều: **gửi rồi thì sao**. Không có nó thì vòng lặp không khép
    được — hệ thống mãi mãi không học được rằng sản phẩm nào chào ai thì trúng.

    Đây cũng là nguồn dữ liệu cho Reactivation Radar: một cơ hội đóng vì
    `MAYBE_LATER` khác hẳn đóng vì `NOT_INTERESTED`, và chỉ cái đầu mới đáng
    được gợi ý lại khi có tín hiệu mới.
    """

    OUTCOME_NO_RESPONSE = "NO_RESPONSE"
    OUTCOME_READ = "READ"
    OUTCOME_REPLIED = "REPLIED"
    OUTCOME_INTERESTED = "INTERESTED"
    OUTCOME_MAYBE_LATER = "MAYBE_LATER"
    OUTCOME_NOT_INTERESTED = "NOT_INTERESTED"
    OUTCOME_WRONG_PRODUCT = "WRONG_PRODUCT"
    OUTCOME_ALREADY_USING = "ALREADY_USING"
    OUTCOME_NEED_CONSULTATION = "NEED_CONSULTATION"
    OUTCOME_MEETING_BOOKED = "MEETING_BOOKED"
    OUTCOME_CONVERTED = "CONVERTED"
    OUTCOME_CHOICES = [
        (OUTCOME_NO_RESPONSE, "Không phản hồi"),
        (OUTCOME_READ, "Đã đọc"),
        (OUTCOME_REPLIED, "Có trả lời"),
        (OUTCOME_INTERESTED, "Quan tâm"),
        (OUTCOME_MAYBE_LATER, "Để sau"),
        (OUTCOME_NOT_INTERESTED, "Không quan tâm"),
        (OUTCOME_WRONG_PRODUCT, "Sai sản phẩm"),
        (OUTCOME_ALREADY_USING, "Đang dùng rồi"),
        (OUTCOME_NEED_CONSULTATION, "Cần tư vấn thêm"),
        (OUTCOME_MEETING_BOOKED, "Đã hẹn gặp"),
        (OUTCOME_CONVERTED, "Đã chốt"),
    ]
    #: Kết quả cho phép gợi ý lại sau khi nguội. `NOT_INTERESTED` và
    #: `ALREADY_USING` cố ý KHÔNG nằm đây — chào lại người đã nói không là cách
    #: nhanh nhất để mất khách.
    REACTIVATABLE = (OUTCOME_NO_RESPONSE, OUTCOME_MAYBE_LATER,
                     OUTCOME_NEED_CONSULTATION, OUTCOME_WRONG_PRODUCT)

    CHANNEL_CHOICES = [
        ("call", "Gọi điện"), ("sms", "Tin nhắn"), ("email", "Email"),
        ("zalo", "Zalo"), ("meeting", "Gặp trực tiếp"), ("other", "Khác"),
    ]

    opportunity = models.ForeignKey(RBOpportunity, on_delete=models.CASCADE,
                                    related_name="outcomes")
    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="rb_outcomes")

    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="call")
    action = models.CharField(max_length=30, choices=OpportunitySuggestion.ACTION_CHOICES,
                              blank=True, default="")
    outcome = models.CharField(max_length=30, choices=OUTCOME_CHOICES, db_index=True)
    note = models.CharField(max_length=500, blank=True, default="")

    response_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_by_name = models.CharField(max_length=150, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Kết quả tiếp cận"
        verbose_name_plural = "Kết quả tiếp cận"
        ordering = ["-response_at"]
        indexes = [
            models.Index(fields=["opportunity", "-response_at"]),
            models.Index(fields=["outcome", "-response_at"]),
        ]

    def __str__(self):
        return f"{self.get_outcome_display()} — {self.person}"

    def save(self, *args, **kwargs):
        if self.created_by_id and not self.created_by_name:
            self.created_by_name = str(self.created_by)[:150]
        return super().save(*args, **kwargs)


class RBOpportunityStatusEvent(models.Model):
    opportunity = models.ForeignKey(RBOpportunity, on_delete=models.CASCADE,
                                    related_name="status_events")
    from_status = models.CharField(max_length=20, blank=True, default="")
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="+")
    actor_name = models.CharField(max_length=150, blank=True, default="")
    note = models.CharField(max_length=500, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["opportunity", "-created_at"])]

    def save(self, *args, **kwargs):
        if self.actor_id and not self.actor_name:
            self.actor_name = str(self.actor)[:150]
        return super().save(*args, **kwargs)


class ProspectEvidenceChunk(models.Model):
    """Một mẩu bằng chứng về khách hàng, đã lập chỉ mục để tìm theo NGHĨA.

    Bản tương ứng của `talent.CVChunk` cho Growth. Không có bảng này thì ② của
    Growth chỉ khớp chữ: "mua chung cư" không tìm ra "mua căn hộ", và khách viết
    "cần xoay vốn" không khớp truy vấn "vay tiêu dùng".

    Nội dung đến từ đúng hàm `rb.answer.evidence.gather` mà ③ đọc — nên thứ được
    tìm thấy và thứ được đọc là một, đã che liên hệ theo cùng một cách. Không có
    số điện thoại hay email nào đi vào `text`, `text_norm` hay vector.

    Bảng này là HÀNG ĐỢI embedding của chính nó (`embedding_fingerprint` khác
    `fingerprint` ⇒ vector cũ), cùng cơ chế với `talent.PersonSearchDocument`.
    Chỉ mục là thứ dựng lại được bất cứ lúc nào (`rebuild_prospect_evidence_index`);
    nguồn sự thật vẫn là các bảng gốc.
    """

    person = models.ForeignKey("people.Person", on_delete=models.CASCADE,
                               related_name="prospect_evidence_chunks")
    #: "socialpost:12", "signal:7"… — khoá ổn định để cập nhật tại chỗ.
    ref = models.CharField(max_length=80, unique=True)
    source = models.CharField(max_length=20, db_index=True)
    text = models.TextField()
    #: `text` bỏ dấu + hạ chữ thường; GIN `to_tsvector('simple', text_norm)`.
    text_norm = models.TextField(blank=True, default="")
    observed_at = models.DateTimeField(null=True, blank=True)
    fingerprint = models.CharField(max_length=64, db_index=True)
    embedding = VectorField(null=True, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True, default="")
    embedding_fingerprint = models.CharField(max_length=64, blank=True, default="",
                                             db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Bằng chứng khách hàng (chỉ mục)"
        verbose_name_plural = "Bằng chứng khách hàng (chỉ mục)"
        indexes = [models.Index(fields=["person", "-observed_at"],
                                name="rb_pec_person_observed_idx")]
