# -*- coding: utf-8 -*-
"""Talent Radar — hồ sơ tuyển dụng gắn trên Person (Master Plan mục 19.2, Phase 6).

Person là con người; TalentProfile là **góc nhìn tuyển dụng** về con người đó. RB Radar
sẽ có RBProfile riêng gắn lên cùng một Person. Đó là Nguyên tắc 2: một People Database,
nhiều nghiệp vụ — không sao chép con người sang cơ sở dữ liệu thứ hai.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from pgvector.django import VectorField
from people.models import Person


class Tag(models.Model):
    """Nhãn dùng chung, gắn được lên nhiều Person.

    Bảng riêng chứ không phải trường text tự do trên Person: recruiter phải gõ được
    "python" một lần rồi dùng lại, thay vì mỗi người gõ một biến thể ("Python", "python3",
    "py") rồi không lọc được theo nhãn nữa.
    """

    name = models.CharField("Tên nhãn", max_length=60, unique=True)
    slug = models.CharField(max_length=60, unique=True, db_index=True,
                            help_text="Bỏ dấu, chữ thường — để so khớp")
    color = models.CharField(max_length=20, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Nhãn"
        verbose_name_plural = "Nhãn"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            from people.normalize import normalize_name
            self.slug = normalize_name(self.name).replace(" ", "-")[:60]
        return super().save(*args, **kwargs)


class Pool(models.Model):
    """Một nhóm ứng viên do recruiter tự gom (Master Plan mục 19.2).

    Khác Tag ở chỗ Pool có chủ sở hữu và mục đích: "Data Analyst Q4/2026", "Đã phỏng
    vấn nhưng chưa tuyển". Tag mô tả *con người*; Pool mô tả *việc đang làm với họ*.
    """

    DOMAIN_TALENT = "talent"
    DOMAIN_RB = "rb"
    DOMAIN_CHOICES = [(DOMAIN_TALENT, "Ứng viên"), (DOMAIN_RB, "Khách hàng")]

    name = models.CharField("Tên pool", max_length=150)
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES,
                              default=DOMAIN_TALENT, db_index=True)
    description = models.TextField(blank=True, default="")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="pools")
    owner_name = models.CharField(max_length=150, blank=True, default="")
    members = models.ManyToManyField(Person, through="PoolMembership",
                                     related_name="pools")
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Pool ứng viên"
        verbose_name_plural = "Pool ứng viên"
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.owner_id and not self.owner_name:
            self.owner_name = str(self.owner)[:150]
        return super().save(*args, **kwargs)


class PoolMembership(models.Model):
    """Bảng nối, có thêm thông tin ai đưa vào và vì sao.

    Dùng `through` thay vì ManyToMany trần: câu "ai đưa người này vào pool, lúc nào"
    là câu recruiter sẽ hỏi, và không có bảng nối thì không trả lời được.
    """

    pool = models.ForeignKey(Pool, on_delete=models.CASCADE, related_name="memberships")
    person = models.ForeignKey(Person, on_delete=models.CASCADE,
                               related_name="pool_memberships")
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL, related_name="+")
    added_by_name = models.CharField(max_length=150, blank=True, default="")
    note = models.CharField(max_length=300, blank=True, default="")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Thành viên pool"
        verbose_name_plural = "Thành viên pool"
        ordering = ["-added_at"]
        constraints = [
            models.UniqueConstraint(fields=["pool", "person"], name="uq_pool_person"),
        ]

    def save(self, *args, **kwargs):
        if self.added_by_id and not self.added_by_name:
            self.added_by_name = str(self.added_by)[:150]
        return super().save(*args, **kwargs)


class TalentProfile(models.Model):
    """Góc nhìn tuyển dụng về một Person.

    Phần lớn trường được **suy ra** từ các SourceRecord đã đồng bộ. Nhưng recruiter đã
    nói chuyện với ứng viên thì biết rõ hơn CV. Vì vậy mọi trường đều sửa tay được, và
    trường nào đã sửa tay sẽ được ghi vào `curated_fields` — lần suy ra sau **không
    ghi đè** lên nó.

    Cùng một nguyên tắc với `_refresh_snapshot()` ở People Core: dữ liệu mới không
    nhất thiết đúng hơn dữ liệu đã có, và kiến thức của con người thì luôn thắng.
    """

    person = models.OneToOneField(Person, on_delete=models.CASCADE,
                                  related_name="talent_profile")

    current_title = models.CharField("Chức danh hiện tại", max_length=200,
                                     blank=True, default="")
    current_company = models.CharField("Công ty hiện tại", max_length=200,
                                       blank=True, default="")
    years_experience = models.FloatField("Số năm kinh nghiệm", null=True, blank=True)
    seniority = models.CharField("Cấp bậc", max_length=40, blank=True, default="")
    education = models.CharField("Học vấn", max_length=200, blank=True, default="")
    expected_salary = models.CharField("Mức lương mong muốn", max_length=100,
                                       blank=True, default="")
    current_salary = models.CharField("Mức lương hiện tại", max_length=100,
                                      blank=True, default="")
    location = models.CharField("Nơi ở", max_length=200, blank=True, default="")

    # Các trường "mong muốn" chỉ có trên trang chi tiết ứng viên của nguồn (không
    # nằm trong file CV). Đồng bộ từ Edge như mọi trường khác — xem
    # edge/KINH_NGHIEM_TRIEN_KHAI_CAC_KENH_TUYEN_DUNG.md mục 41.
    desired_location = models.CharField("Nơi làm việc mong muốn", max_length=200,
                                        blank=True, default="")
    desired_level = models.CharField("Cấp bậc mong muốn", max_length=100,
                                     blank=True, default="")
    desired_position = models.CharField("Ngành nghề/Vị trí mong muốn", max_length=200,
                                        blank=True, default="")
    job_type = models.CharField("Hình thức làm việc mong muốn", max_length=120,
                                blank=True, default="")
    foreign_language = models.CharField("Ngoại ngữ", max_length=200,
                                        blank=True, default="")
    marital_status = models.CharField("Tình trạng hôn nhân", max_length=40,
                                      blank=True, default="")

    skills = models.JSONField("Kỹ năng", default=list, blank=True)
    industries = models.JSONField("Ngành từng làm", default=list, blank=True)

    summary = models.TextField("Tóm tắt", blank=True, default="")

    # Recruiter phụ trách. SET_NULL để nghỉ việc không làm mất hồ sơ ứng viên.
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="owned_talents")
    owner_name = models.CharField(max_length=150, blank=True, default="")

    tags = models.ManyToManyField(Tag, blank=True, related_name="talents")

    # Tên trường mà con người đã sửa; những trường này miễn nhiễm với việc suy lại.
    curated_fields = models.JSONField(default=list, blank=True, editable=False)

    # Mốc thời gian dùng để xếp hạng độ "tươi" của hồ sơ (Master Plan mục 23).
    last_source_at = models.DateTimeField(null=True, blank=True, db_index=True,
                                          help_text="Lần cuối có dữ liệu mới từ nguồn")
    derived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ Talent"
        verbose_name_plural = "Hồ sơ Talent"
        ordering = ["-last_source_at"]
        indexes = [
            models.Index(fields=["-last_source_at"]),
            models.Index(fields=["owner", "-updated_at"]),
        ]

    def __str__(self):
        return f"Talent: {self.person}"

    def save(self, *args, **kwargs):
        if self.owner_id and not self.owner_name:
            self.owner_name = str(self.owner)[:150]
        return super().save(*args, **kwargs)

    def mark_curated(self, *field_names):
        """Đánh dấu các trường do người dùng sửa, để việc suy lại không ghi đè."""
        curated = set(self.curated_fields or [])
        curated.update(field_names)
        self.curated_fields = sorted(curated)

    def is_curated(self, field_name):
        return field_name in (self.curated_fields or [])


class TalentAIAnalysis(models.Model):
    """Kết quả AI dùng lại giữa Recruiter và RM cho cùng một câu hỏi.

    Chỉ lưu ID Person, điểm và insight; tên/liên hệ luôn được serialize lại từ
    People Core để không sinh thêm một bản sao dữ liệu cá nhân.
    """

    STATUS_PROCESSING = "processing"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PROCESSING, "Đang phân tích"),
        (STATUS_READY, "Sẵn sàng"),
        (STATUS_FAILED, "Thất bại"),
    ]

    cache_key = models.CharField(max_length=64, unique=True)
    question = models.TextField()
    normalized_question = models.TextField(db_index=True)
    limit = models.PositiveSmallIntegerField(default=20)
    version = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES,
                              default=STATUS_PROCESSING, db_index=True)
    criteria = models.JSONField(default=dict, blank=True)
    trace = models.JSONField(default=list, blank=True)
    results = models.JSONField(default=list, blank=True)
    provider = models.CharField(max_length=40, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")
    error = models.CharField(max_length=500, blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    analyzed_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_used_at = models.DateTimeField(default=timezone.now)
    hit_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-analyzed_at"]
        indexes = [models.Index(fields=["status", "-analyzed_at"],
                                name="talent_ai_status_time_idx")]


class TalentSemanticIndex(models.Model):
    """Precomputed, provider-independent semantic representation of one person."""
    person = models.OneToOneField(Person, on_delete=models.CASCADE,
                                  related_name="talent_semantic_index")
    fingerprint = models.CharField(max_length=64, db_index=True)
    normalized_text = models.TextField(blank=True, default="")
    terms = models.JSONField(default=list, blank=True)
    vector = models.JSONField(default=dict, blank=True)
    source_characters = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Chỉ mục semantic Talent"
        verbose_name_plural = "Chỉ mục semantic Talent"
        indexes = [models.Index(fields=["-updated_at"])]


class PersonSearchDocument(models.Model):
    """Projection đầy đủ một Person cho hybrid/dense retrieval.

    Không copy CV binary; text đã parse và dữ liệu Edge/DB được materialize có
    fingerprint, để rebuild idempotent và biết chính xác coverage index.
    """
    person = models.OneToOneField(Person, on_delete=models.CASCADE,
                                  related_name="search_document")
    fingerprint = models.CharField(max_length=64, db_index=True)
    content = models.TextField(blank=True, default="")
    #: `content` đã bỏ dấu + hạ chữ thường. Là cột mà PostgreSQL full-text search
    #: đánh chỉ mục (GIN trên `to_tsvector('simple', content_norm)`), nhờ vậy khớp
    #: không phụ thuộc dấu tiếng Việt mà không cần extension `unaccent`.
    content_norm = models.TextField(blank=True, default="")
    # Số chiều KHÔNG chốt ở model: người vận hành chọn nguồn embedding từ
    # `/settings` (Gemini API hay tự host) và `pin_vector_dimensions` chốt số
    # chiều thật + tạo HNSW. Đổi nguồn ⇒ đánh dấu backfill lại.
    embedding = VectorField(null=True, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True, default="")
    embedding_version = models.PositiveIntegerField(default=1)
    #: Fingerprint của nội dung ĐÃ được embed. Khác `fingerprint` ⇒ vector cũ,
    #: worker nền sẽ embed lại. Đây chính là hàng đợi embedding: không cần bảng job
    #: riêng, và một kho triệu CV vẫn backfill tăng dần được.
    embedding_fingerprint = models.CharField(max_length=64, blank=True, default="",
                                             db_index=True)
    indexed_at = models.DateTimeField(auto_now=True, db_index=True)


class CVChunk(models.Model):
    """Đoạn CV có provenance để AI giải thích bằng evidence, không chỉ score."""
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="cv_chunks")
    document = models.ForeignKey("people.Document", on_delete=models.CASCADE,
                                 related_name="search_chunks")
    ordinal = models.PositiveIntegerField()
    fingerprint = models.CharField(max_length=64, db_index=True)
    text = models.TextField()
    #: `text` đã bỏ dấu + hạ chữ thường — cột được GIN full-text index (xem
    #: `PersonSearchDocument.content_norm`).
    text_norm = models.TextField(blank=True, default="")
    # Số chiều do `/settings` + `pin_vector_dimensions` quyết (xem
    # `PersonSearchDocument.embedding`).
    embedding = VectorField(null=True, blank=True)
    embedding_model = models.CharField(max_length=120, blank=True, default="")
    embedding_version = models.PositiveIntegerField(default=1)
    embedding_fingerprint = models.CharField(max_length=64, blank=True, default="",
                                             db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "ordinal"],
                                                name="uq_talent_cv_chunk_document_ordinal")]
        indexes = [models.Index(fields=["person", "document", "ordinal"],
                                name="talent_cvch_person__a19abe_idx")]


class EmbeddingConfig(models.Model):
    """Singleton (pk=1): chọn nguồn embedding cho dense retrieval kho CV.

    `vector_index._embedding_config()` đọc bảng này TRƯỚC biến môi trường và route
    DB — người vận hành bật/tắt và chuyển giữa **Gemini API** và **endpoint tự
    host** (Ollama…) ngay trên `/settings`, không sửa `.env` / redeploy.

    Đổi `mode` hoặc model ⇒ toàn bộ vector cũ thành "cần tính lại" (worker nền
    `embed_talent_index` tự làm). Số chiều giữ 768 cho cả hai nguồn để hoán đổi
    không phải đổi kiểu cột — Gemini `gemini-embedding-001` nhận
    `output_dimensionality=768`.
    """

    MODE_GREENNODE = "greennode"
    MODE_SELFHOST = "selfhost"
    MODE_GEMINI = "gemini"
    MODE_OFF = "off"
    MODE_CHOICES = [
        (MODE_GREENNODE, "GreenNode MaaS (ưu tiên)"),
        (MODE_SELFHOST, "Tự host (Ollama / TEI)"),
        (MODE_GEMINI, "Google Gemini API"),
        (MODE_OFF, "Tắt — chỉ tìm full-text"),
    ]

    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_SELFHOST)
    selfhost_base_url = models.CharField(max_length=300, blank=True,
                                        default="http://ollama:11434/v1")
    selfhost_model = models.CharField(max_length=120, blank=True, default="nomic-embed-text")
    gemini_model = models.CharField(max_length=120, blank=True, default="gemini-embedding-001")
    greennode_model = models.CharField(max_length=120, blank=True, default="BAAI/bge-m3")
    dimensions = models.PositiveIntegerField(default=768)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        verbose_name = "Cấu hình embedding"
        verbose_name_plural = "Cấu hình embedding"

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def resolve(self):
        """(provider, base_url, key, model) cho `embed()`, hoặc None nếu tắt/thiếu."""
        if self.mode == self.MODE_OFF:
            return None
        if self.mode == self.MODE_SELFHOST:
            if self.selfhost_base_url and self.selfhost_model:
                return ("local", self.selfhost_base_url.rstrip("/"), "local",
                        self.selfhost_model)
            return None
        if self.mode == self.MODE_GREENNODE and self.greennode_model:
            from ai.models import ProviderConfig
            from ai.providers import PROVIDER_DEFAULTS
            config = ProviderConfig.objects.filter(provider="greennode", enabled=True).first()
            key = config.get_api_key() if config else ""
            if key:
                base = (config.base_url or PROVIDER_DEFAULTS["greennode"]["base_url"]).rstrip("/")
                return ("greennode", base, key, self.greennode_model)
            return None
        if self.mode == self.MODE_GEMINI and self.gemini_model:
            from ai.models import ProviderConfig
            config = ProviderConfig.objects.filter(provider="gemini").first()
            key = config.get_api_key() if config else ""
            if key:
                return ("gemini", "https://generativelanguage.googleapis.com/v1beta",
                        key, self.gemini_model)
        return None


class TitleSimilarity(models.Model):
    """Độ gần về NGHĨA giữa hai chức danh, do LLM chấm một lần rồi nhớ lại.

    Bộ chấm điểm vốn so khớp chuỗi, và chỗ đó hỏng theo một kiểu rất tốn kém:
    "BI Developer" khớp **0%** với "Data Analyst" dù hai người làm gần như cùng
    một việc. Recruiter nhìn danh sách thấy sai ngay, rồi thôi không tin cả bảng
    điểm nữa.

    Vì sao lưu thành bảng thay vì gọi LLM mỗi lần chấm:

      • **Tái lập được.** Cùng một tìm kiếm phải cho cùng một thứ tự. Điểm nhảy
        múa giữa hai lần bấm là thứ giết niềm tin nhanh nhất, và nó cũng làm
        việc hiệu chỉnh trọng số (mục 21) mất ý nghĩa.
      • **Rẻ.** Khoá theo CẶP CHỨC DANH chứ không theo con người: kho 20 nghìn
        hồ sơ chỉ có vài trăm chức danh khác nhau, nên bộ nhớ này bão hoà rất
        nhanh và gần như không còn lượt gọi nào.
      • **Kiểm được.** Mỗi dòng có lý do bằng lời, đọc được, sửa được tay.

    Đây vẫn KHÔNG phải LLM chấm điểm. Nó cung cấp **một chiều đầu vào**; điểm
    tổng vẫn là tổng có trọng số tất định của bảy chiều.
    """

    SOURCE_LLM = "llm"
    SOURCE_STRING = "string"
    SOURCE_MANUAL = "manual"
    SOURCE_CHOICES = [
        (SOURCE_LLM, "AI chấm"),
        (SOURCE_STRING, "So khớp chuỗi"),
        (SOURCE_MANUAL, "Người sửa tay"),
    ]

    needed = models.CharField("Chức danh cần tuyển", max_length=200, db_index=True)
    candidate = models.CharField("Chức danh của ứng viên", max_length=200)
    score = models.FloatField(help_text="0..1")
    reason = models.CharField(max_length=300, blank=True, default="")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES,
                              default=SOURCE_LLM)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Độ gần chức danh"
        verbose_name_plural = "Độ gần chức danh"
        ordering = ["needed", "-score"]
        constraints = [
            models.UniqueConstraint(fields=["needed", "candidate"],
                                    name="uq_titlesimilarity_pair"),
        ]

    def __str__(self):
        return f"{self.candidate} → {self.needed}: {self.score:.2f}"


class IntelligenceDocumentTombstone(models.Model):
    """Append-only deletion/visibility event consumed by Intelligence V2."""

    document_id = models.BigIntegerField(db_index=True)
    person_id = models.BigIntegerField()
    version = models.CharField(max_length=64)
    content_hash = models.CharField(max_length=64)
    source = models.CharField(max_length=40, default="radar")
    document_type = models.CharField(max_length=40, default="cv")
    deleted_at = models.DateTimeField(db_index=True)

    class Meta:
        ordering = ["deleted_at", "pk"]
        indexes = [models.Index(fields=["deleted_at", "id"])]
