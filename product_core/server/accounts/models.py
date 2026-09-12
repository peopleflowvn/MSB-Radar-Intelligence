# -*- coding: utf-8 -*-
"""Nhật ký truy cập dữ liệu cá nhân (Master Plan PHASE 5B) và Xác thực tài khoản / Email OTP."""
import base64
import hashlib
import re
from cryptography.fernet import Fernet, InvalidToken

from django.conf import settings
from django.db import models
from django.utils import timezone


class AccessLog(models.Model):
    """Một lượt đọc dữ liệu cá nhân."""

    # Đọc thường
    ACTION_VIEW = "view"
    ACTION_SEARCH = "search"
    ACTION_LIST = "list"
    # Dữ liệu RỜI KHỎI hệ thống — nhóm đáng chú ý nhất với Compliance
    ACTION_DOWNLOAD = "download"
    ACTION_EXPORT = "export"
    # Xoá cứng dữ liệu người dùng sở hữu (hội thoại, derived memory) — §21.5.
    ACTION_DELETE = "delete"

    EXFILTRATION_ACTIONS = (ACTION_DOWNLOAD, ACTION_EXPORT)

    ACTION_CHOICES = [
        (ACTION_VIEW, "Xem hồ sơ"),
        (ACTION_SEARCH, "Tìm kiếm"),
        (ACTION_LIST, "Xem danh sách"),
        (ACTION_DOWNLOAD, "Tải tài liệu"),
        (ACTION_EXPORT, "Xuất dữ liệu"),
        (ACTION_DELETE, "Xoá dữ liệu"),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="access_logs")
    user_name = models.CharField(max_length=150, blank=True, default="", db_index=True)
    roles = models.CharField(max_length=200, blank=True, default="",
                             help_text="Vai trò tại thời điểm truy cập")

    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    module = models.CharField(max_length=30, blank=True, default="", db_index=True)

    person = models.ForeignKey("people.Person", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="access_logs")
    person_name = models.CharField(max_length=200, blank=True, default="")
    object_type = models.CharField(max_length=40, blank=True, default="")
    object_id = models.CharField(max_length=64, blank=True, default="")

    cross_domain = models.BooleanField(default=False, db_index=True)
    allowed = models.BooleanField(default=True, db_index=True)

    path = models.CharField(max_length=300, blank=True, default="")
    method = models.CharField(max_length=10, blank=True, default="")
    ip = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    extra = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Nhật ký truy cập"
        verbose_name_plural = "Nhật ký truy cập"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["person", "-created_at"]),
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["cross_domain", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.user_name} {self.action} {self.person_name or self.path}"

    @property
    def is_exfiltration(self):
        """Lượt truy cập này có đưa dữ liệu ra khỏi hệ thống không."""
        return self.action in self.EXFILTRATION_ACTIONS


class UserWorkProfile(models.Model):
    """Người dùng tự khai địa bàn và trọng tâm công việc của mình."""

    DOMAIN_TALENT = "talent"
    DOMAIN_RB = "rb"
    DOMAIN_CHOICES = [(DOMAIN_TALENT, "Tuyển dụng"), (DOMAIN_RB, "Bán lẻ")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="work_profiles")
    domain = models.CharField(max_length=20, choices=DOMAIN_CHOICES, db_index=True)

    regions = models.JSONField(default=list, blank=True,
                               help_text="Danh sách tỉnh/thành phụ trách")
    focus_products = models.JSONField(default=list, blank=True,
                                      help_text="Mã nhóm sản phẩm ưu tiên (RB)")
    focus_job_families = models.JSONField(default=list, blank=True,
                                          help_text="Nhóm vị trí phụ trách (Talent)")
    target_segments = models.JSONField(default=list, blank=True)
    daily_capacity = models.PositiveSmallIntegerField(default=20)
    preferred_channels = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True, default="",
                             help_text="Ngữ cảnh cho AI diễn giải; không đổi điểm số")

    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hồ sơ công việc"
        verbose_name_plural = "Hồ sơ công việc"
        constraints = [
            models.UniqueConstraint(fields=["user", "domain"],
                                    name="uq_workprofile_user_domain"),
        ]

    def __str__(self):
        return f"{self.user} — {self.get_domain_display()}"


class UserAssistantPreference(models.Model):
    """Cách Radar gọi người dùng; không suy đoán giới tính từ tên."""

    GENDER_MALE = "male"
    GENDER_FEMALE = "female"
    GENDER_OTHER = "other"
    GENDER_UNDISCLOSED = "undisclosed"
    GENDER_CHOICES = [
        (GENDER_MALE, "Nam"),
        (GENDER_FEMALE, "Nữ"),
        (GENDER_OTHER, "Khác"),
        (GENDER_UNDISCLOSED, "Không muốn cung cấp"),
    ]
    SALUTATION_CHOICES = [
        ("anh", "Anh"), ("chị", "Chị"), ("bạn", "Bạn"), ("", "Không chỉ định"),
    ]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="assistant_preference")
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True, default="")
    preferred_name = models.CharField(max_length=80, blank=True, default="")
    preferred_salutation = models.CharField(
        max_length=20, choices=SALUTATION_CHOICES, blank=True, default="")
    personalization_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def display_address(self):
        if not self.personalization_enabled:
            return "anh/chị"
        salutation = self.preferred_salutation or {
            self.GENDER_MALE: "anh", self.GENDER_FEMALE: "chị",
        }.get(self.gender, "anh/chị")
        name = self.preferred_name.strip()
        return f"{salutation} {name}".strip() if name else salutation


class ContactUnlockPolicy(models.Model):
    """Hạn mức mở khoá riêng cho một người, khi mức theo vai trò không đủ."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="unlock_policy")
    is_unlimited = models.BooleanField(
        default=False, help_text="Không giới hạn lượt mở khoá liên hệ mỗi ngày")
    custom_daily_quota = models.PositiveIntegerField(
        null=True, blank=True, help_text="Hạn mức riêng; bỏ trống thì dùng mức theo vai trò")
    reason = models.CharField(max_length=300, blank=True, default="")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Hạn mức mở khoá riêng"
        verbose_name_plural = "Hạn mức mở khoá riêng"

    def __str__(self):
        if self.is_unlimited:
            return f"{self.user} — không giới hạn"
        return f"{self.user} — {self.custom_daily_quota}/ngày"


class ContactUnlockLog(models.Model):
    """Một lượt xem thông tin liên hệ đầy đủ (Master Plan mục 27.3)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="contact_unlocks")
    user_name = models.CharField(max_length=150, blank=True, default="", db_index=True)
    person = models.ForeignKey("people.Person", null=True, blank=True,
                               on_delete=models.SET_NULL, related_name="contact_unlocks")
    person_name = models.CharField(max_length=200, blank=True, default="")
    domain = models.CharField(max_length=20, blank=True, default="",
                              help_text="talent hoặc rb")
    ip = models.CharField(max_length=64, blank=True, default="")
    unlocked_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = "Nhật ký mở khoá liên hệ"
        verbose_name_plural = "Nhật ký mở khoá liên hệ"
        ordering = ["-unlocked_at"]
        indexes = [
            models.Index(fields=["user", "-unlocked_at"]),
            models.Index(fields=["person", "-unlocked_at"]),
        ]

    def __str__(self):
        return f"{self.user_name} mở khoá {self.person_name}"


class ExternalIdentity(models.Model):
    """Liên kết tài khoản nội bộ Radar với danh tính SSO bên ngoài (Microsoft Entra)."""
    PROVIDER_MICROSOFT = "microsoft"
    PROVIDER_CHOICES = [(PROVIDER_MICROSOFT, "Microsoft Entra ID")]

    TNTALENT = "tntalent"
    MSB = "msb"
    REALM_CHOICES = [(TNTALENT, "TNTalent"), (MSB, "MSB")]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="external_identities")
    provider = models.CharField(max_length=30, choices=PROVIDER_CHOICES,
                              default=PROVIDER_MICROSOFT, db_index=True)
    realm = models.CharField(max_length=20, choices=REALM_CHOICES, db_index=True)
    tenant_id = models.CharField(max_length=36)
    object_id = models.CharField(max_length=36)
    username_snapshot = models.CharField(max_length=254, blank=True, default="")
    display_name_snapshot = models.CharField(max_length=200, blank=True, default="")
    linked_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True, db_index=True)
    revoke_reason = models.CharField(max_length=300, blank=True, default="")
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True,
                                   on_delete=models.SET_NULL, related_name="revoked_identities")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["provider", "realm", "object_id"],
                                    name="uq_external_identity_realm_object"),
        ]

    def __str__(self):
        return f"{self.user} ({self.realm}:{self.username_snapshot})"


class UserLoginPolicy(models.Model):
    """Quy định hình thức đăng nhập bắt buộc cho từng tài khoản."""
    LOCAL = "local"
    TNTALENT = "tntalent"
    MSB = "msb"
    LOGIN_TYPE_CHOICES = [
        (LOCAL, "Tài khoản thường"),
        (TNTALENT, "Email OTP — TNTalent"),
        (MSB, "Email OTP — MSB"),
    ]
    LOGIN_TYPES = {value for value, _label in LOGIN_TYPE_CHOICES}

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="login_policy")
    login_type = models.CharField(max_length=20, choices=LOGIN_TYPE_CHOICES,
                                  default=LOCAL, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user} — {self.get_login_type_display()}"

    @classmethod
    def type_of(cls, user):
        try:
            return user.login_policy.login_type
        except cls.DoesNotExist:
            return cls.LOCAL


class AuthenticationEvent(models.Model):
    """Nhật ký đăng nhập; tuyệt đối không chứa token/code/client secret."""

    provider = models.CharField(max_length=30, default="microsoft", db_index=True)
    realm = models.CharField(max_length=20, blank=True, default="", db_index=True)
    result = models.CharField(max_length=40, db_index=True)
    tenant_id = models.CharField(max_length=36, blank=True, default="")
    object_id_hash = models.CharField(max_length=64, blank=True, default="")
    username_masked = models.CharField(max_length=254, blank=True, default="")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                             on_delete=models.SET_NULL, related_name="authentication_events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="auth_events_performed")
    ip = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    correlation_id = models.CharField(max_length=64, blank=True, default="", db_index=True)
    detail = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["result", "-created_at"])]

    def __str__(self):
        return f"{self.created_at} {self.realm} {self.result}"


def _email_otp_cipher():
    """Mã hóa API key trong CSDL; khóa gốc vẫn là SECRET_KEY của Hub, không gửi ra UI."""
    raw = hashlib.sha256(settings.SECRET_KEY.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


DEFAULT_OTP_HTML_TEMPLATE = (
    "<!DOCTYPE html PUBLIC \"-//W3C//DTD XHTML 1.0 Transitional//EN\" \"http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd\">"
    "<html xmlns=\"http://www.w3.org/1999/xhtml\" lang=\"vi\">"
    "<head>"
    "<meta http-equiv=\"Content-Type\" content=\"text/html; charset=UTF-8\" />"
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />"
    "<meta name=\"color-scheme\" content=\"light dark\" />"
    "<meta name=\"supported-color-schemes\" content=\"light dark\" />"
    "<title>Mã xác thực đăng nhập - {{app_name}}</title>"
    "<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->"
    "</head>"
    "<body bgcolor=\"#F1F5F9\" style=\"margin:0;padding:0;background-color:#F1F5F9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;\">"
    "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" bgcolor=\"#F1F5F9\" style=\"margin:0;padding:40px 16px;background-color:#F1F5F9;width:100%;\">"
    "<tr><td align=\"center\" valign=\"top\">"
    "<!--[if (gte mso 9)|(IE)]><table width=\"580\" align=\"center\" cellpadding=\"0\" cellspacing=\"0\" border=\"0\" bgcolor=\"#FFFFFF\"><tr><td><![endif]-->"
    "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" bgcolor=\"#FFFFFF\" style=\"max-width:580px;width:100%;margin:0 auto;background-color:#FFFFFF;border-radius:16px;overflow:hidden;border:1px solid #E2E8F0;box-shadow:0 4px 20px rgba(0,0,0,0.06);\">"
    "<tr>"
    "<td bgcolor=\"#EA580C\" style=\"background-color:#EA580C;background-image:linear-gradient(135deg, #EA580C 0%, #F97316 50%, #C2410C 100%);background-repeat:no-repeat;padding:28px 36px;\">"
    "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\">"
    "<tr>"
    "<td valign=\"middle\" width=\"56\" style=\"width:56px;padding-right:16px;\">"
    "{{app_logo_badge}}"
    "</td>"
    "<td valign=\"middle\" align=\"left\">"
    "<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" style=\"margin-bottom:6px;\">"
    "<tr><td bgcolor=\"#C2410C\" style=\"background-color:#C2410C;padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;color:#FFFFFF;letter-spacing:0.5px;text-transform:uppercase;\">XÁC THỰC BẢO MẬT HỆ THỐNG</td></tr>"
    "</table>"
    "<h1 style=\"margin:0;padding:0;color:#FFFFFF;font-size:22px;font-weight:800;letter-spacing:-0.4px;line-height:1.2;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;\">{{app_name}}</h1>"
    "<p style=\"margin:4px 0 0;padding:0;color:#FFF7ED;font-size:12.5px;line-height:1.4;\">Hệ Thống Tìm Kiếm Nhân Tài &amp; Tăng Trưởng Khách Hàng</p>"
    "</td>"
    "</tr>"
    "</table>"
    "</td>"
    "</tr>"
    "<tr>"
    "<td bgcolor=\"#FFFFFF\" style=\"padding:32px 36px 24px;background-color:#FFFFFF;\">"
    "<h2 style=\"margin:0 0 12px;padding:0;font-size:19px;font-weight:700;color:#0F172A;line-height:1.3;\">Mã xác thực đăng nhập (OTP)</h2>"
    "<p style=\"margin:0 0 24px;padding:0;font-size:14.5px;color:#475569;line-height:1.6;\">Bạn vừa thực hiện yêu cầu đăng nhập an toàn vào hệ thống <strong>{{app_name}}</strong>. Vui lòng sử dụng mã xác thực gồm 6 chữ số dưới đây để tiếp tục:</p>"
    "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" style=\"margin:0 0 24px;\">"
    "<tr>"
    "<td bgcolor=\"#FFF7ED\" align=\"center\" style=\"background-color:#FFF7ED;border:2px dashed #EA580C;border-radius:12px;padding:24px 16px;text-align:center;\">"
    "<div style=\"font-size:11.5px;font-weight:700;color:#9A3412;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px;\">MÃ XÁC THỰC CỦA BẠN</div>"
    "<div style=\"font-family:'SF Mono',Consolas,'Liberation Mono',Menlo,Courier,monospace;font-size:40px;font-weight:800;color:#EA580C;letter-spacing:12px;line-height:48px;padding:4px 0;text-align:center;\">{{code}}</div>"
    "<div style=\"font-size:13px;color:#C2410C;font-weight:600;margin-top:8px;\">⏱️ Mã có hiệu lực trong vòng {{expires_minutes}} phút</div>"
    "</td>"
    "</tr>"
    "</table>"
    "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\" bgcolor=\"#F8FAFC\" style=\"background-color:#F8FAFC;border:1px solid #E2E8F0;border-radius:10px;margin-bottom:8px;\">"
    "<tr>"
    "<td style=\"padding:16px 18px;\">"
    "<div style=\"font-size:13px;font-weight:700;color:#334155;margin-bottom:8px;\">🛡️ Lưu ý an ninh quan trọng:</div>"
    "<table role=\"presentation\" width=\"100%\" cellspacing=\"0\" cellpadding=\"0\" border=\"0\">"
    "<tr><td valign=\"top\" width=\"16\" style=\"font-size:13px;color:#EA580C;line-height:1.5;font-weight:bold;\">•</td><td style=\"font-size:13px;color:#64748B;line-height:1.5;padding-bottom:6px;\">Mã OTP này chỉ có hiệu lực <strong>một lần duy nhất</strong>.</td></tr>"
    "<tr><td valign=\"top\" width=\"16\" style=\"font-size:13px;color:#EA580C;line-height:1.5;font-weight:bold;\">•</td><td style=\"font-size:13px;color:#64748B;line-height:1.5;padding-bottom:6px;\"><strong>Tuyệt đối không chia sẻ</strong> mã này với bất kỳ ai, bao gồm cả quản trị viên hay nhân viên hỗ trợ.</td></tr>"
    "<tr><td valign=\"top\" width=\"16\" style=\"font-size:13px;color:#EA580C;line-height:1.5;font-weight:bold;\">•</td><td style=\"font-size:13px;color:#64748B;line-height:1.5;\">Nếu bạn không thực hiện yêu cầu này, vui lòng bỏ qua email hoặc liên hệ ngay với Quản trị viên An ninh.</td></tr>"
    "</table>"
    "</td>"
    "</tr>"
    "</table>"
    "</td>"
    "</tr>"
    "<tr>"
    "<td bgcolor=\"#F8FAFC\" style=\"background-color:#F8FAFC;border-top:1px solid #E2E8F0;padding:20px 36px;text-align:center;\">"
    "<p style=\"margin:0 0 4px;padding:0;font-size:12.5px;font-weight:600;color:#64748B;\">Email bảo mật tự động từ {{app_name}}</p>"
    "<p style=\"margin:0;padding:0;font-size:11.5px;color:#94A3B8;line-height:1.5;\">Ngân hàng TMCP Hàng Hải Việt Nam (MSB) • Đây là email tự động, vui lòng không phản hồi thư này.</p>"
    "</td>"
    "</tr>"
    "</table>"
    "<!--[if (gte mso 9)|(IE)]></td></tr></table><![endif]-->"
    "</td></tr></table>"
    "</body>"
    "</html>"
)


class EmailOtpSettings(models.Model):
    """Cấu hình Resend singleton, chỉ admin Hub được đọc/trị; API key không bao giờ serialize."""

    enabled = models.BooleanField(default=False)
    resend_api_key_encrypted = models.TextField(blank=True, default="")
    from_email = models.EmailField(blank=True, default="")
    from_name = models.CharField(max_length=100, blank=True, default="MSB Radar")
    reply_to = models.TextField(blank=True, default="")
    subject = models.CharField(max_length=160, blank=True, default="Mã đăng nhập MSB Radar")
    otp_html_template = models.TextField(default=DEFAULT_OTP_HTML_TEMPLATE)
    app_logo_url = models.TextField(blank=True, default="")
    app_icon = models.CharField(max_length=20, blank=True, default="⚡")
    app_tagline = models.CharField(max_length=255, blank=True, default="Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng")

    # --- Thumbnail / xem trước liên kết (Open Graph + Twitter card + SEO) ---
    #
    # Trước đây nằm cứng trong `web/index.html` lúc build: muốn đổi ảnh xem trước
    # phải sửa mã và triển khai lại. Đưa xuống CSDL để một người đổi là mọi người
    # thấy như nhau ngay, không phụ thuộc trình duyệt ai đã tải bản nào.
    #
    # Rỗng nghĩa là "suy ra từ tên/tagline" chứ không phải "để trống" — xem
    # `accounts.branding.link_preview()`.
    og_image_url = models.TextField(blank=True, default="")
    og_image_alt = models.CharField(max_length=255, blank=True, default="")
    og_image_width = models.PositiveSmallIntegerField(default=1200)
    og_image_height = models.PositiveSmallIntegerField(default=630)
    og_title = models.CharField(max_length=255, blank=True, default="")
    og_description = models.TextField(blank=True, default="")
    og_site_name = models.CharField(max_length=120, blank=True, default="")
    meta_keywords = models.TextField(blank=True, default="")
    #: Cho crawler biết có được lập chỉ mục không. Hệ thống nội bộ thường muốn
    #: "noindex", nhưng đó là quyết định của người vận hành, không phải mặc định
    #: cứng trong mã.
    meta_robots = models.CharField(max_length=60, blank=True, default="index, follow")
    #: PWA (`site.webmanifest`) — biểu tượng khi cài lên màn hình chính.
    pwa_short_name = models.CharField(max_length=60, blank=True, default="")
    pwa_background_color = models.CharField(max_length=20, blank=True, default="#0F172A")
    color_preset = models.CharField(max_length=40, blank=True, default="amber_gold")
    custom_color = models.CharField(max_length=20, blank=True, default="#FF8A33")
    gradient_from = models.CharField(max_length=20, blank=True, default="#FF8A33")
    gradient_to = models.CharField(max_length=20, blank=True, default="#EA580C")
    gradient_via = models.CharField(max_length=20, blank=True, default="#F59E0B")
    gradient_angle = models.CharField(max_length=15, blank=True, default="135deg")
    radar_avatar_url = models.TextField(blank=True, default="")
    radar_avatar_emoji = models.CharField(max_length=20, blank=True, default="⚡")
    theme_mode = models.CharField(max_length=20, blank=True, default="dark")
    table_density = models.CharField(max_length=20, blank=True, default="normal")
    mask_sensitive_data = models.BooleanField(default=False)
    min_match_score = models.PositiveSmallIntegerField(default=50)
    items_per_page = models.PositiveSmallIntegerField(default=25)
    sound_alerts = models.BooleanField(default=True)
    tntalent_domains = models.TextField(blank=True, default="tntalent.vn")
    msb_domains = models.TextField(blank=True, default="msb.com.vn")
    code_ttl_seconds = models.PositiveIntegerField(default=600)
    resend_cooldown_seconds = models.PositiveIntegerField(default=60)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    webhook_secret_encrypted = models.TextField(blank=True, default="")
    webhook_inbound_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="email_otp_settings_updates")

    @classmethod
    def current(cls):
        settings_row, _created = cls.objects.get_or_create(pk=1)
        return settings_row

    @property
    def api_key_configured(self):
        return bool(self.resend_api_key_encrypted)

    def set_api_key(self, value):
        self.resend_api_key_encrypted = _email_otp_cipher().encrypt(value.encode("utf-8")).decode("ascii")

    def get_api_key(self):
        if not self.resend_api_key_encrypted:
            return ""
        try:
            return _email_otp_cipher().decrypt(self.resend_api_key_encrypted.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            return ""

    @property
    def webhook_secret_configured(self):
        return bool(self.webhook_secret_encrypted)

    def set_webhook_secret(self, value):
        self.webhook_secret_encrypted = _email_otp_cipher().encrypt(value.encode("utf-8")).decode("ascii")

    def get_webhook_secret(self):
        if not self.webhook_secret_encrypted:
            return ""
        try:
            return _email_otp_cipher().decrypt(self.webhook_secret_encrypted.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeDecodeError):
            return ""

    @property
    def is_ready(self):
        return bool(self.enabled and self.api_key_configured and self.from_email)

    @staticmethod
    def normalize_domains(value):
        """Chuẩn hóa cả chuỗi nhập tay, JSON array và dữ liệu array bị stringify.

        DRF trả ``allowed_domains`` dưới dạng list. Bản cũ gọi ``str(list)`` nên
        mỗi lần admin lưu lại bọc thêm ``['...']`` vào CSDL. Nhánh regex chỉ
        dùng để cứu dữ liệu legacy có dấu ngoặc/quote/backslash; dữ liệu nhập
        bình thường vẫn được tách nghiêm ngặt theo dấu phẩy/chấm phẩy.
        """
        if isinstance(value, (list, tuple, set)):
            domains = set()
            for item in value:
                domains.update(EmailOtpSettings.normalize_domains(item))
            return sorted(domains)

        text = str(value or "").strip().lower()
        if not text:
            return []
        if any(marker in text for marker in ("[", "]", "'", '"', "\\")):
            return sorted(set(re.findall(
                r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", text)))
        return sorted({item.strip().lstrip("@")
                       for item in text.replace(";", ",").replace("\n", ",").split(",")
                       if item.strip().lstrip("@")})

    def domains_for(self, realm):
        raw = self.tntalent_domains if realm == UserLoginPolicy.TNTALENT else self.msb_domains
        return self.normalize_domains(raw)

    @property
    def all_allowed_domains(self):
        return sorted(set(self.domains_for(UserLoginPolicy.TNTALENT)) | set(self.domains_for(UserLoginPolicy.MSB)))

    def realm_for_email(self, email):
        domain = str(email or "").strip().lower().rsplit("@", 1)[-1]
        for realm in (UserLoginPolicy.TNTALENT, UserLoginPolicy.MSB):
            if domain in self.domains_for(realm):
                return realm
        return ""


class EmailLoginCode(models.Model):
    """OTP chỉ lưu HMAC, không lưu mã 6 số nguyên văn."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="email_login_codes")
    realm = models.CharField(max_length=20, choices=[("local", "Tài khoản thường"), *ExternalIdentity.REALM_CHOICES],
                             db_index=True)
    sent_to = models.EmailField()
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    used_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    request_ip = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["user", "realm", "-created_at"])]


class ResendWebhookEvent(models.Model):
    """Webhook đã được xác minh; svix_id chống delivery at-least-once bị lặp."""
    svix_id = models.CharField(max_length=120, unique=True)
    event_type = models.CharField(max_length=60, db_index=True)
    email_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    occurred_at = models.DateTimeField(null=True, blank=True, db_index=True)
    payload = models.JSONField(default=dict)
    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-received_at"]


class ResendInboxEmail(models.Model):
    """Nội dung inbound lấy sau webhook email.received; admin-only vì có thể chứa PII."""
    email_id = models.CharField(max_length=80, unique=True)
    sender = models.EmailField(blank=True, default="")
    recipients = models.JSONField(default=list)
    subject = models.CharField(max_length=500, blank=True, default="")
    text_body = models.TextField(blank=True, default="")
    html_body = models.TextField(blank=True, default="")
    headers = models.JSONField(default=dict)
    attachments = models.JSONField(default=list)
    received_at = models.DateTimeField(null=True, blank=True, db_index=True)
    stored_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at", "-stored_at"]


class RoleModuleAccess(models.Model):
    """Sửa quyền vào module theo vai trò — do Admin đặt, phủ lên ma trận mặc định.

    Ma trận mặc định (`accounts.roles.ROLE_MODULES`) là **sàn an toàn** viết trong
    code. Bảng này chỉ chứa các Ô đã bị Admin đổi so với mặc định: `allowed=True`
    cấp thêm một module cho một vai trò, `allowed=False` thu hồi. Ô trùng mặc định
    thì không lưu hàng nào (giữ bảng gọn và dễ đọc "đã đổi gì").

    `accounts.roles.modules_of()` hợp nhất: mặc định + các hàng ở đây.
    """

    role = models.CharField(max_length=32, db_index=True,
                            help_text="Khoá vai trò trong accounts.roles.ALL_ROLES")
    module = models.CharField(max_length=32,
                              help_text="Khoá module trong accounts.roles.MODULE_LABELS")
    allowed = models.BooleanField()
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    updated_by_name = models.CharField(max_length=150, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Phân quyền module theo vai trò"
        verbose_name_plural = "Phân quyền module theo vai trò"
        ordering = ["role", "module"]
        constraints = [
            models.UniqueConstraint(fields=["role", "module"],
                                    name="uq_role_module_access"),
        ]

    def __str__(self):
        verb = "cấp" if self.allowed else "thu hồi"
        return f"{verb} {self.module} cho {self.role}"

    def save(self, *args, **kwargs):
        if self.updated_by_id and not self.updated_by_name:
            self.updated_by_name = str(self.updated_by)[:150]
        return super().save(*args, **kwargs)
