# -*- coding: utf-8 -*-
"""Shared People Intelligence Core (Master Plan mục 10–18).

Nguyên tắc 1: **Một Person là một con người.** Không phải một CV, không phải một
lượt ứng tuyển. Một người có thể có nhiều CV ở nhiều nguồn, qua nhiều năm.

Nguyên tắc 2: **Một People Database, nhiều nghiệp vụ.** Talent Radar và RB Radar
dùng chung Person; mỗi bên gắn thêm hồ sơ riêng của mình chứ không tạo lại một
cơ sở dữ liệu con người thứ hai.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Person(models.Model):
    """Một con người. Hạt nhân của toàn bộ hệ thống."""

    # Không phải Person nào cũng là ứng viên. Người tham chiếu bóc từ CV của
    # người khác cũng là con người thật, cũng cần hồ sơ và quan hệ — nhưng họ
    # CHƯA TỪNG ỨNG TUYỂN. Trộn họ vào pool ứng viên sẽ thổi phồng "tổng hồ sơ"
    # ở báo cáo và làm sai mọi tỷ lệ phủ của Answer Engine.
    ORIGIN_APPLICATION = "application"
    ORIGIN_CV_REFERENCE = "cv_reference"
    ORIGIN_MANUAL = "manual"
    ORIGIN_CHOICES = [
        (ORIGIN_APPLICATION, "Từ lượt ứng tuyển"),
        (ORIGIN_CV_REFERENCE, "Người tham chiếu trong CV"),
        (ORIGIN_MANUAL, "Nhập tay"),
    ]

    display_name = models.CharField("Tên hiển thị", max_length=200, blank=True, default="")
    normalized_name = models.CharField(max_length=200, blank=True, default="", db_index=True,
                                       help_text="Bỏ dấu, chữ thường — chỉ để gợi ý trùng lặp")

    # Ảnh chụp nhanh của những trường hay dùng nhất, để danh sách và tìm kiếm
    # không phải join sang Identity. Identity vẫn là nguồn sự thật.
    primary_email = models.CharField(max_length=200, blank=True, default="", db_index=True)
    primary_phone = models.CharField(max_length=20, blank=True, default="", db_index=True)
    headline = models.CharField("Vị trí gần nhất", max_length=200, blank=True, default="")
    location = models.CharField("Nơi ở", max_length=200, blank=True, default="")

    origin = models.CharField("Biết đến qua", max_length=20, choices=ORIGIN_CHOICES,
                              default=ORIGIN_APPLICATION, db_index=True,
                              help_text="Lần đầu gặp người này ở đâu — không đổi về sau")
    # Denormalize thay vì EXISTS(source_records) ở mọi truy vấn tìm kiếm: đây là
    # bộ lọc nằm trên đường nóng của cả tìm kiếm lẫn thống kê corpus.
    #
    # MẶC ĐỊNH True, và đó là lựa chọn có chủ đích. Hai kiểu sai không cân nhau:
    # quên bật cờ cho một ứng viên thật thì hồ sơ BIẾN MẤT im lặng khỏi tìm kiếm
    # (nặng, khó phát hiện); quên tắt cho một người tham chiếu thì họ hiện thêm
    # trong pool ứng viên (nhẹ, và họ vốn cũng là mục tiêu tuyển dụng tốt).
    # Bản đầu để default=False và 16 bài kiểm thử tắt ngay vì mọi Person tạo
    # thẳng bằng ORM đều rơi khỏi kết quả — đúng cái kiểu hỏng cần tránh.
    is_applicant = models.BooleanField("Đã từng ứng tuyển", default=True, db_index=True,
                                       help_text="Hiện trong các bề mặt tuyển dụng")

    needs_review = models.BooleanField("Cần người xem lại", default=False, db_index=True,
                                       help_text="Có xung đột định danh chưa xử lý")
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="merged_from",
                                    help_text="Đã gộp vào Person này; giữ lại để không vỡ liên kết cũ")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Person"
        verbose_name_plural = "Person"
        ordering = ["-updated_at"]
        indexes = [models.Index(fields=["needs_review", "-updated_at"]),
                   models.Index(fields=["is_applicant", "-updated_at"])]

    def __str__(self):
        return self.display_name or f"Person #{self.pk}"

    @property
    def is_merged(self):
        return self.merged_into_id is not None

    def canonical(self):
        """Đi theo chuỗi gộp tới Person còn hiệu lực.

        Có chặn trên vòng lặp: dữ liệu hỏng không được phép treo tiến trình.
        """
        seen, current = set(), self
        while current.merged_into_id and current.merged_into_id not in seen:
            seen.add(current.pk)
            current = current.merged_into
        return current

    @classmethod
    def applicants(cls):
        """Vũ trụ mặc định của MỌI bề mặt tuyển dụng: người đã từng ứng tuyển.

        Dùng ở tìm kiếm ứng viên, thống kê corpus và bộ so khớp của Answer
        Engine. Bán hàng (`rb/`) CỐ Ý không dùng hàm này — bên đó muốn cả người
        tham chiếu, đấy chính là nguồn khách hàng tiềm năng của họ.
        """
        return cls.objects.filter(merged_into__isnull=True, is_applicant=True)


class Identity(models.Model):
    """Một định danh mạnh trỏ tới một Person (Master Plan mục 12).

    'Mạnh' nghĩa là gần như chắc chắn thuộc về đúng một người: email, số điện
    thoại di động, hồ sơ LinkedIn/Facebook, mã ứng viên do nguồn tuyển dụng cấp.

    Tên KHÔNG phải định danh mạnh và cố ý không có mặt ở đây.
    """

    KIND_EMAIL = "email"
    KIND_PHONE = "phone"
    KIND_LINKEDIN = "linkedin"
    KIND_FACEBOOK = "facebook"
    KIND_PROVIDER = "provider_person_id"
    KIND_CHOICES = [
        (KIND_EMAIL, "Email"),
        (KIND_PHONE, "Điện thoại"),
        (KIND_LINKEDIN, "LinkedIn"),
        (KIND_FACEBOOK, "Facebook"),
        (KIND_PROVIDER, "Mã ứng viên của nguồn"),
    ]

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="identities")
    kind = models.CharField("Loại", max_length=32, choices=KIND_CHOICES)
    value = models.CharField("Giá trị đã chuẩn hoá", max_length=300)
    raw_value = models.CharField("Giá trị gốc", max_length=300, blank=True, default="")

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Định danh"
        verbose_name_plural = "Định danh"
        constraints = [
            # Một giá trị định danh chỉ thuộc về ĐÚNG MỘT Person. Ràng buộc này
            # nằm ở CSDL chứ không chỉ trong code: nó là thứ biến "hai bản ghi
            # cùng email" thành một phép khớp thay vì hai người trùng nhau.
            models.UniqueConstraint(fields=["kind", "value"], name="uq_identity_kind_value"),
        ]
        indexes = [models.Index(fields=["person", "kind"])]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.value}"


class IdentityConflict(models.Model):
    """Ghi nhận trường hợp một bản ghi trỏ tới hai Person khác nhau.

    Master Plan mục 12: email → Person A còn phone → Person B thì KHÔNG tự động
    gộp. Hai người thật có thể dùng chung một điện thoại (vợ chồng, người nhà
    điền hộ), và gộp nhầm hai hồ sơ là việc gần như không gỡ lại được.

    **AI không quyết định việc gộp định danh.** Bảng này là hàng đợi cho người xử lý.
    """

    STATUS_OPEN = "open"
    STATUS_MERGED = "merged"
    STATUS_DISMISSED = "dismissed"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Chờ xử lý"),
        (STATUS_MERGED, "Đã gộp"),
        (STATUS_DISMISSED, "Đã bỏ qua — hai người khác nhau"),
    ]

    people = models.ManyToManyField(Person, related_name="conflicts")
    evidence = models.JSONField(default=dict,
                                help_text="Các định danh dẫn tới xung đột và Person tương ứng")
    source_record_id = models.CharField(max_length=64, blank=True, default="",
                                        help_text="Bản ghi nguồn làm lộ ra xung đột")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN,
                              db_index=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Xung đột định danh"
        verbose_name_plural = "Xung đột định danh"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Xung đột #{self.pk} ({self.get_status_display()})"

    def resolve(self, status, note=""):
        self.status = status
        self.note = note or self.note
        self.resolved_at = timezone.now()
        self.save(update_fields=["status", "note", "resolved_at"])


class ParsedTextVersion(models.Model):
    """Một nội dung parsing duy nhất của một Person, dùng chung cho nhiều CV.

    Hash theo text đã chuẩn hóa giúp hai file nhị phân khác nhau nhưng bóc ra cùng nội dung
    không lưu lặp hàng chục nghìn ký tự. Phạm vi dedupe là từng Person để không tạo liên kết
    ngầm giữa dữ liệu của hai người khác nhau.
    """
    person = models.ForeignKey(Person, on_delete=models.CASCADE,
                               related_name="parsed_text_versions")
    text_hash = models.CharField(max_length=64)
    text = models.TextField()
    text_length = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["person", "text_hash"],
                                    name="uq_parsed_text_person_hash"),
        ]
        indexes = [models.Index(fields=["person", "-created_at"])]


class Document(models.Model):
    """Một tài liệu của Person — chủ yếu là CV (Master Plan mục 14).

    **Một người có nhiều CV theo thời gian, và phải giữ tất cả.** Người ứng tuyển
    năm 2023 rồi ứng tuyển lại năm 2026 sẽ nộp hai file khác nhau: CV cũ cho biết
    họ từng ở đâu, CV mới cho biết họ đang ở đâu. Cả hai đều cần cho Talent Radar.

    **Phiên bản tự sinh ra từ mã băm nội dung.** Không có trường "version" nào phải
    tự tăng: cùng một file gửi từ TopCV và VietnamWorks cho cùng sha256 nên chỉ có
    một hàng; file đã sửa cho sha256 khác nên thành một hàng mới. Thứ tự phiên bản
    suy từ `observed_at`.
    """

    PARSE_PENDING = "pending"
    PARSE_DONE = "done"
    PARSE_FAILED = "failed"
    #: Đã thử hết cách (trích cục bộ + OCR) mà file thật sự không có chữ — trang
    #: trắng, ảnh không có nội dung. Là trạng thái CUỐI để worker không gọi OCR
    #: mãi, nhưng vẫn hiện trong `audit_data_pipeline` để người xem lại được.
    PARSE_UNREADABLE = "unreadable"

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="documents")
    document_type = models.CharField(max_length=40, default="cv")
    source = models.CharField(max_length=40, blank=True, default="",
                              help_text="Nguồn của lần đầu nhìn thấy file này")
    filename = models.CharField(max_length=300, blank=True, default="")
    mime_type = models.CharField(max_length=100, blank=True, default="")
    file_size = models.PositiveIntegerField(default=0)

    sha256 = models.CharField(max_length=64, db_index=True,
                              help_text="Khử trùng lặp: cùng một file tải từ hai nguồn")
    storage_key = models.CharField(max_length=500, blank=True, default="",
                                   help_text="Khoá trong kho file; trống = Edge chưa tải lên")

    # Cùng một file CV có thể được đính vào nhiều lượt ứng tuyển. Quan hệ nhiều-nhiều
    # để trả lời được "phiên bản CV này dùng cho những lần ứng tuyển nào".
    source_records = models.ManyToManyField("core.SourceRecord", blank=True,
                                            related_name="documents")

    parsed_text = models.TextField(blank=True, default="")
    primary_text_version = models.ForeignKey(
        ParsedTextVersion, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="primary_for_documents")
    text_length = models.PositiveIntegerField(default=0)
    parse_status = models.CharField(max_length=20, default=PARSE_PENDING)
    quality_score = models.FloatField(default=0.0)
    parse_provider = models.CharField(max_length=40, blank=True, default="")
    parse_model = models.CharField(max_length=100, blank=True, default="")
    parse_error = models.CharField(max_length=500, blank=True, default="")
    parsed_at = models.DateTimeField(null=True, blank=True)
    #: Số lần Hub đã kiểm/parse bù file này (`core/cv_parsing.py`). > 0 cũng có
    #: nghĩa "Hub đã xác nhận text dùng được", để worker không kiểm lại mãi.
    parse_attempts = models.PositiveSmallIntegerField(default=0)
    #: Lịch thử lại khi lần trước lỗi (lùi dần), đồng thời là lease giữa các
    #: tiến trình gunicorn: tiến trình nào đặt được mốc này thì tiến trình đó xử lý.
    next_parse_at = models.DateTimeField(null=True, blank=True, db_index=True)
    preview_key = models.CharField(max_length=500, blank=True, default="",
                                   help_text="Bản PDF xem trước do Hub tạo, tách khỏi file gốc")
    preview_status = models.CharField(max_length=20, default=PARSE_PENDING)
    preview_error = models.CharField(max_length=500, blank=True, default="")
    previewed_at = models.DateTimeField(null=True, blank=True)

    # Thời điểm file này thực sự xuất hiện (ngày ứng tuyển), KHÔNG phải lúc Hub
    # nhận được. Đây là thứ quyết định thứ tự phiên bản — một CV cũ đồng bộ muộn
    # vẫn phải nằm đúng chỗ của nó trong dòng thời gian.
    observed_at = models.DateTimeField(null=True, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tài liệu"
        verbose_name_plural = "Tài liệu"
        ordering = ["-observed_at", "-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["person", "sha256"], name="uq_document_person_hash"),
        ]
        indexes = [
            models.Index(fields=["person", "-observed_at"]),
            models.Index(fields=["parse_status", "updated_at", "id"]),
        ]

    def __str__(self):
        return self.filename or f"Tài liệu #{self.pk}"

    @property
    def has_file(self):
        return bool(self.storage_key)

    def version_number(self):
        """Thứ tự phiên bản trong số CV của người này, tính từ 1 (cũ nhất).

        Tính lúc đọc chứ không lưu: một CV cũ được đồng bộ muộn sẽ chen vào giữa,
        và mọi số thứ tự đã lưu sẽ sai từ đó trở đi.
        """
        earlier = Document.objects.filter(
            person_id=self.person_id, document_type=self.document_type)
        if self.observed_at:
            earlier = earlier.filter(observed_at__lt=self.observed_at)
        else:
            earlier = earlier.filter(created_at__lt=self.created_at)
        return earlier.count() + 1

    @property
    def best_text(self):
        if self.primary_text_version_id:
            return self.primary_text_version.text
        return self.parsed_text


class DocumentTextLink(models.Model):
    ORIGIN_EDGE = "edge"
    ORIGIN_AI = "hub_ai"
    ORIGIN_EXTRACTOR = "hub_extractor"

    document = models.ForeignKey(Document, on_delete=models.CASCADE,
                                 related_name="text_links")
    text_version = models.ForeignKey(ParsedTextVersion, on_delete=models.CASCADE,
                                     related_name="document_links")
    origins = models.JSONField(default=list, blank=True)
    provider = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    quality_score = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["document", "text_version"],
                                    name="uq_document_text_version"),
        ]


class Signal(models.Model):
    """Một thay đổi hoặc sự kiện đáng chú ý về một Person (Master Plan mục 15)."""

    STATUS_NEW = "new"
    STATUS_ACTED = "acted"
    STATUS_IGNORED = "ignored"
    STATUS_CHOICES = [
        (STATUS_NEW, "Mới"),
        (STATUS_ACTED, "Đã xử lý"),
        (STATUS_IGNORED, "Bỏ qua"),
    ]

    DOMAIN_TALENT = "talent"
    DOMAIN_RB = "rb"
    DOMAIN_CHOICES = [(DOMAIN_TALENT, "Tuyển dụng"), (DOMAIN_RB, "Bán lẻ")]

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="signals")
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES, default=DOMAIN_TALENT)
    signal_type = models.CharField(max_length=60, db_index=True)
    source = models.CharField(max_length=40, blank=True, default="")

    confidence = models.FloatField(default=0.0, help_text="0..1")
    # Bằng chứng là bắt buộc về mặt thiết kế: Nguyên tắc 4 nói AI phải giải
    # thích trước khi đề xuất hành động, và không có bằng chứng thì không giải
    # thích được.
    evidence = models.JSONField(default=dict)

    observed_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW,
                              db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Tín hiệu"
        verbose_name_plural = "Tín hiệu"
        ordering = ["-observed_at"]
        indexes = [
            models.Index(fields=["domain", "status", "-observed_at"]),
            models.Index(fields=["person", "-observed_at"]),
        ]

    def __str__(self):
        return f"{self.signal_type} ({self.confidence:.2f})"


class Relationship(models.Model):
    """Trạng thái quan hệ giữa MSB và một Person, theo từng nghiệp vụ.

    Master Plan mục 16 nói rõ **không** ép hai nghiệp vụ dùng chung một pipeline:
    'Hot' của tuyển dụng và 'Qualified' của bán lẻ là hai chuyện khác nhau. Vì
    vậy trạng thái được lưu dưới dạng chuỗi kèm domain, không phải một enum chung.
    """

    TALENT_STATES = [
        "new", "attempted", "connected", "interested", "nurturing", "ready",
        "placed", "unavailable", "do_not_contact",
        # Mã cũ được giữ để dữ liệu và bộ lọc đã lưu không bị hỏng.
        "cool", "re_engagement", "warm", "hot", "contacted",
    ]
    RB_STATES = ["cold", "warm", "interested", "qualified", "converted", "dormant"]

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="relationships")
    domain = models.CharField(max_length=20, choices=Signal.DOMAIN_CHOICES)
    state = models.CharField(max_length=40)
    owner = models.CharField(max_length=150, blank=True, default="",
                             help_text="Recruiter hoặc RM phụ trách")
    owner_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="owned_relationships")
    interest_level = models.PositiveSmallIntegerField(default=0,
                                                       help_text="0 chưa rõ; 1..5 tăng dần")
    last_contact_at = models.DateTimeField(null=True, blank=True, db_index=True)
    next_action = models.CharField(max_length=300, blank=True, default="")
    next_action_at = models.DateTimeField(null=True, blank=True, db_index=True)
    preferred_channel = models.CharField(max_length=30, blank=True, default="")
    do_not_contact = models.BooleanField(default=False, db_index=True)
    reason = models.CharField(max_length=300, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    preferences = models.JSONField(default=dict, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Quan hệ"
        verbose_name_plural = "Quan hệ"
        constraints = [
            models.UniqueConstraint(fields=["person", "domain"], name="uq_relationship_person_domain"),
        ]
        indexes = [
            models.Index(fields=["domain", "owner_user", "do_not_contact", "next_action_at"],
                         name="people_rel_owner_due"),
        ]

    def __str__(self):
        return f"{self.person} — {self.domain}: {self.state}"

    def save(self, *args, **kwargs):
        if self.owner_user_id:
            self.owner = str(self.owner_user)[:150]
        return super().save(*args, **kwargs)

    @classmethod
    def valid_states(cls, domain):
        return cls.TALENT_STATES if domain == Signal.DOMAIN_TALENT else cls.RB_STATES


class Interaction(models.Model):
    """Một lần con người tác động lên hồ sơ (Master Plan mục 17).

    Dùng chung cho mọi module: xem hồ sơ, đưa vào shortlist, gọi điện, nhắn tin,
    yêu cầu recruiter săn. Đây là hạ tầng chung, không thuộc riêng Talent hay RB.
    """

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="interactions")
    domain = models.CharField(max_length=20, choices=Signal.DOMAIN_CHOICES,
                              default=Signal.DOMAIN_TALENT)
    action = models.CharField(max_length=40, db_index=True)

    # Khoá ngoại tới User, không phải chuỗi tự do (Phase 5B).
    # SET_NULL chứ không CASCADE: nhân viên nghỉ việc, tài khoản bị xoá, nhưng
    # lịch sử tương tác với ứng viên vẫn phải còn — nó là dữ liệu nghiệp vụ.
    # actor_name giữ tên tại thời điểm xảy ra, để dòng lịch sử vẫn đọc được sau
    # khi tài khoản biến mất hoặc đổi tên.
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="interactions")
    actor_name = models.CharField(max_length=150, blank=True, default="")

    detail = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Tương tác"
        verbose_name_plural = "Tương tác"
        ordering = ["-occurred_at"]
        indexes = [models.Index(fields=["person", "-occurred_at"])]

    def __str__(self):
        return f"{self.action} — {self.person}"

    def save(self, *args, **kwargs):
        # Chụp lại tên người thực hiện tại thời điểm ghi. Đọc từ actor lúc hiển
        # thị sẽ mất thông tin khi tài khoản bị xoá — đúng lúc cần nhất.
        if self.actor_id and not self.actor_name:
            self.actor_name = str(self.actor)[:150]
        return super().save(*args, **kwargs)


class Opportunity(models.Model):
    """Cơ hội chung cho cả hai nghiệp vụ (Master Plan mục 18).

    Talent: Person ↔ nhu cầu tuyển dụng. RB: Person ↔ nhu cầu tài chính.
    Phần khác biệt của từng nghiệp vụ nằm trong `detail`; phần chung — điểm số,
    lý do, chủ sở hữu, hành động đề xuất — nằm ở đây để một hộp thư cơ hội duy
    nhất hiển thị được cả hai.
    """

    STATUS_OPEN = "open"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_DONE = "done"
    STATUS_CHOICES = [
        (STATUS_OPEN, "Đang mở"),
        (STATUS_ACCEPTED, "Đã nhận"),
        (STATUS_REJECTED, "Từ chối"),
        (STATUS_DONE, "Hoàn tất"),
    ]

    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="opportunities")
    domain = models.CharField(max_length=20, choices=Signal.DOMAIN_CHOICES)
    title = models.CharField(max_length=200)

    score = models.FloatField(default=0.0, help_text="0..1, do hệ thống chấm")
    confidence = models.FloatField(default=0.0, help_text="0..1")
    # 'why' là bắt buộc, không phải tuỳ chọn: Nguyên tắc 4 — AI giải thích trước
    # khi đề xuất hành động. Một cơ hội không nói được vì sao thì không dùng được.
    why = models.JSONField(default=dict, help_text="FACT / INFERENCE / UNKNOWN")
    recommended_action = models.CharField(max_length=200, blank=True, default="")

    signals = models.ManyToManyField(Signal, blank=True, related_name="opportunities")
    detail = models.JSONField(default=dict, blank=True,
                              help_text="Phần riêng của từng nghiệp vụ")
    owner = models.CharField(max_length=150, blank=True, default="", db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_OPEN,
                              db_index=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Cơ hội"
        verbose_name_plural = "Cơ hội"
        ordering = ["-score", "-created_at"]
        indexes = [models.Index(fields=["domain", "status", "-score"])]

    def __str__(self):
        return self.title


class ContactMention(models.Model):
    """Một người ĐƯỢC NHẮC TỚI trong tài liệu của người khác.

    CV ứng viên thường kèm khối "Người tham chiếu": họ tên, chức danh, công ty,
    email, điện thoại của một người thứ ba — rất hay là quản lý cũ đang làm ở
    ngân hàng khác. Trước khi có bảng này, những liên hệ đó bị Edge gộp chung
    vào ô `email`/`phone` của ứng viên, khiến Hub hoặc vứt cả định danh, hoặc
    (nguy hiểm hơn) coi email người tham chiếu là định danh của ứng viên — hai
    ứng viên cùng một người tham chiếu sẽ bị gộp thành một Person.

    Đây là tầng CÓ BẰNG CHỨNG, cố ý tách khỏi `Person`: bóc xong chưa tạo người
    ngay. Chỉ khi bản ghi được chấp nhận mới `promote` thành Person thật kèm
    `PersonLink` trỏ về ứng viên đã nhắc tới họ.
    """

    KIND_REFERENCE = "reference"          # người tham chiếu
    KIND_REFERRER = "referrer"            # người giới thiệu ứng viên vào
    KIND_EMERGENCY = "emergency"          # liên hệ khẩn cấp
    KIND_SELF = "self"                    # hoá ra vẫn là của chính ứng viên
    KIND_CHOICES = [
        (KIND_REFERENCE, "Người tham chiếu"),
        (KIND_REFERRER, "Người giới thiệu"),
        (KIND_EMERGENCY, "Liên hệ khẩn cấp"),
        (KIND_SELF, "Của chính ứng viên"),
    ]

    STATUS_PROPOSED = "proposed"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PROPOSED, "Chờ duyệt"),
        (STATUS_ACCEPTED, "Đã nhận"),
        (STATUS_REJECTED, "Đã loại"),
    ]

    subject = models.ForeignKey(Person, on_delete=models.CASCADE,
                                related_name="contact_mentions",
                                help_text="Người mà tài liệu này nói về (ứng viên)")
    document = models.ForeignKey(Document, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="contact_mentions")

    full_name = models.CharField(max_length=200, blank=True, default="")
    title = models.CharField(max_length=200, blank=True, default="")
    company = models.CharField(max_length=200, blank=True, default="")
    relationship_note = models.CharField(max_length=200, blank=True, default="",
                                         help_text="CV mô tả quan hệ thế nào")

    email_raw = models.CharField(max_length=300, blank=True, default="")
    phone_raw = models.CharField(max_length=100, blank=True, default="")
    email = models.CharField(max_length=200, blank=True, default="", db_index=True)
    phone = models.CharField(max_length=20, blank=True, default="", db_index=True)

    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_REFERENCE)
    confidence = models.FloatField(default=0.0, help_text="0..1")
    # Trích dẫn nguyên văn từ CV. Bắt buộc về mặt nghiệp vụ: một liên hệ không
    # chỉ ra được nó nằm ở đâu trong CV thì không phân biệt được với AI bịa.
    evidence = models.TextField(blank=True, default="")
    extractor = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")

    linked_person = models.ForeignKey(Person, null=True, blank=True,
                                      on_delete=models.SET_NULL,
                                      related_name="mentioned_as",
                                      help_text="Person đã tạo/khớp từ bản ghi này")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_PROPOSED, db_index=True)
    # Giống ExtractedFact.fingerprint: chạy lại bộ bóc trên cùng một CV không
    # được đẻ thêm bản ghi trùng.
    fingerprint = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Liên hệ nhắc tới trong tài liệu"
        verbose_name_plural = "Liên hệ nhắc tới trong tài liệu"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["subject", "status"]),
                   models.Index(fields=["status", "-created_at"])]

    def __str__(self):
        return f"{self.full_name or self.email or self.phone} ({self.get_kind_display()})"


class PersonLink(models.Model):
    """Quan hệ giữa HAI CON NGƯỜI.

    Khác `Relationship` (Person ↔ một nghiệp vụ, unique theo `person`+`domain`):
    ở đây cả hai đầu đều là người. Đây là thứ trả lời được "ai giới thiệu ai",
    "ai từng làm cùng ai" — nền cho cả sourcing tuyển dụng lẫn bán hàng theo
    mạng lưới quan hệ.

    Có hướng: `subject` là người mà tài liệu nói về, `related` là người được
    nhắc tới. Đảo chiều là một quan hệ khác về nghĩa, nên không tự sinh cặp
    ngược — muốn hỏi hai chiều thì dùng `links_in`/`links_out`.
    """

    KIND_REFERENCE = "reference"        # related là người tham chiếu cho subject
    KIND_REFERRED_BY = "referred_by"    # subject được related giới thiệu vào
    KIND_COLLEAGUE = "colleague"
    KIND_MANAGER = "manager"            # related từng quản lý subject
    KIND_SAME_EMPLOYER = "same_employer"
    KIND_CHOICES = [
        (KIND_REFERENCE, "Người tham chiếu"),
        (KIND_REFERRED_BY, "Được giới thiệu bởi"),
        (KIND_COLLEAGUE, "Đồng nghiệp"),
        (KIND_MANAGER, "Quản lý cũ"),
        (KIND_SAME_EMPLOYER, "Cùng nơi làm việc"),
    ]

    subject = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="links_out")
    related = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="links_in")
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)

    confidence = models.FloatField(default=0.0, help_text="0..1")
    evidence = models.JSONField(default=dict, blank=True)
    source_document = models.ForeignKey(Document, null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name="person_links")
    created_by = models.CharField(max_length=150, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Quan hệ giữa người với người"
        verbose_name_plural = "Quan hệ giữa người với người"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["subject", "related", "kind"],
                                    name="uq_person_link"),
            # Tự trỏ về chính mình là dữ liệu hỏng, không phải quan hệ.
            models.CheckConstraint(check=~models.Q(subject=models.F("related")),
                                   name="ck_person_link_khac_nguoi"),
        ]
        indexes = [models.Index(fields=["related", "kind"])]

    def __str__(self):
        return f"{self.subject_id} —{self.kind}→ {self.related_id}"
