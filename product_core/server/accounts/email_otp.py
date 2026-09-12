import base64
import hashlib
import json
import logging
import secrets
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from core.storage import get_storage
from django.conf import settings
from django.contrib.auth import login
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import EmailLoginCode, EmailOtpSettings

log = logging.getLogger(__name__)

#: Cloudflare đứng trước api.resend.com chặn thẳng (HTTP 403, "error code: 1010")
#: mọi request mang User-Agent mặc định của urllib ("Python-urllib/x.y"). Không
#: đặt header này thì mọi lượt gửi OTP đều ném HTTPError -> "Resend từ chối gửi
#: email", dù API key và domain gửi đều hợp lệ.
RESEND_USER_AGENT = "MSB-Radar/1.0 (+https://radar.tunghr.io.vn)"


def make_code_hash(code, record_id):
    return salted_hmac("msb-radar-email-otp", f"{record_id}:{code}").hexdigest()


def recipient_for(user):
    """Email ưu tiên hồ sơ user, fallback username nếu là email hợp lệ."""
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    for candidate in (user.email, user.username):
        try:
            validate_email(candidate)
            return candidate.strip().lower()
        except (ValidationError, AttributeError):
            continue
    return ""


def _get_public_base_url():
    configured = getattr(settings, "PUBLIC_BASE_URL", "")
    if configured:
        return configured.rstrip("/")
    trusted = getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
    for origin in trusted:
        if origin.startswith("https://") and "radar" in origin:
            return origin.rstrip("/")
    for origin in trusted:
        if origin.startswith("https://"):
            return origin.rstrip("/")
    allowed = getattr(settings, "ALLOWED_HOSTS", [])
    for host in allowed:
        if "radar" in host:
            return f"https://{host.strip()}"
    if allowed and allowed[0] not in ("*", "localhost", "127.0.0.1"):
        return f"https://{allowed[0].strip()}"
    return "https://radar.tntalent.vn"


def _normalize_email_icon_url(icon_url):
    """Bảo đảm ảnh trong email luôn là liên kết HTTP(S) tĩnh, KHÔNG bao giờ nhúng base64.

    1. Nhúng base64 data: URI làm email nặng gấp trăm lần, dễ bị Gmail/Outlook cắt bớt ('Message clipped').
    2. Microsoft Outlook (Word engine) chặn hoàn toàn data: URI khiến ảnh bị lỗi gạch chéo đỏ.
    """
    raw = str(icon_url or getattr(settings, "PUBLIC_APP_ICON_URL", "") or "").strip()
    base = _get_public_base_url()
    if not raw:
        return ""

    if raw.startswith("data:image/"):
        try:
            header, b64_data = raw.split(";base64,", 1)
            mime = header.split("data:", 1)[-1].lower()
            ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
                   "image/gif": "gif", "image/svg+xml": "svg"}.get(mime, "png")
            data = base64.b64decode(b64_data)
            digest = hashlib.sha256(data).hexdigest()
            key = f"branding/icon_{digest[:20]}.{ext}"
            get_storage().save(key, data)
            return f"{base}/media/{key}"
        except Exception as exc:
            log.warning("Không thể lưu data: URI của logo thành tệp tĩnh: %s", exc)
            return ""

    if raw.startswith("/"):
        return f"{base}{raw}"

    return raw


def _send_resend(config, recipient, code, custom_template=None):
    sender = f"{config.from_name} <{config.from_email}>" if config.from_name else config.from_email
    icon_url = _normalize_email_icon_url(config.app_logo_url)
    icon_emoji = config.app_icon or "⚡"
    app_name = config.from_name or "MSB Radar"
    template = custom_template if custom_template is not None else config.otp_html_template

    # Tạo huy hiệu logo / icon bulletproof không bao giờ bị lỗi ảnh gạch chéo
    if icon_url:
        logo_badge = (
            f'<img src="{icon_url}" width="48" height="48" alt="{app_name}" border="0" '
            'style="display:block;width:48px;height:48px;max-width:48px;border-radius:12px;'
            'border:none;outline:none;text-decoration:none;-ms-interpolation-mode:bicubic;" />'
        )
    else:
        logo_badge = (
            '<table role="presentation" cellspacing="0" cellpadding="0" border="0" width="48" height="48" '
            'bgcolor="#FFFFFF" style="width:48px;height:48px;background-color:#FFFFFF;border-radius:12px;text-align:center;">'
            f'<tr><td align="center" valign="middle" style="font-size:26px;line-height:1;text-align:center;">{icon_emoji}</td></tr>'
            '</table>'
        )

    # Chuẩn hóa để Microsoft Outlook (sử dụng engine Word) không bị mất màu cam ở top banner:
    if "linear-gradient" in template and "bgcolor=" not in template:
        template = template.replace(
            '<td style="background:linear-gradient',
            '<td bgcolor="#EA580C" style="background-color:#EA580C;background-image:linear-gradient',
        ).replace(
            '<td style=\\"background:linear-gradient',
            '<td bgcolor=\\"#EA580C\\" style=\\"background-color:#EA580C;background-image:linear-gradient',
        )

    html = (
        template.replace("{{code}}", code)
        .replace("{{expires_minutes}}", str(max(1, config.code_ttl_seconds // 60)))
        .replace("{{app_name}}", app_name)
        .replace("{{app_logo_badge}}", logo_badge)
        .replace("{{app_icon_url}}", icon_url or f"{_get_public_base_url()}/apple-touch-icon.png")
        .replace("{{app_icon}}", icon_emoji)
    )
    body = {
        "from": sender,
        "to": [recipient],
        "subject": config.subject,
        "html": html,
    }
    reply_to = [item.strip() for item in config.reply_to.replace(";", ",").split(",") if item.strip()]
    if reply_to:
        body["reply_to"] = reply_to
    request = Request(
        "https://api.resend.com/emails", data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {config.get_api_key()}",
                 "Content-Type": "application/json",
                 "User-Agent": RESEND_USER_AGENT,
                 "Idempotency-Key": f"radar-otp-{secrets.token_hex(16)}"}, method="POST")
    try:
        with urlopen(request, timeout=15) as response:
            res_data = response.read() if hasattr(response, "read") else b"{}"
            if response.status not in (200, 201):
                raise RuntimeError(f"Resend HTTP {response.status}")
            try:
                return json.loads(res_data.decode("utf-8")) if res_data else {"id": ""}
            except Exception:
                return {"id": ""}
    except HTTPError as exc:
        err_msg = ""
        try:
            err_body = exc.read().decode("utf-8")
            err_json = json.loads(err_body)
            err_msg = err_json.get("message") or err_body
        except Exception:
            err_msg = str(exc)
        log.warning("Resend từ chối gửi OTP: HTTP %s - %s", exc.code, err_msg)
        raise RuntimeError(f"Resend từ chối gửi email (HTTP {exc.code}): {err_msg}") from exc
    except (URLError, TimeoutError) as exc:
        log.warning("Không kết nối được Resend: %s", exc)
        raise RuntimeError("Không kết nối được máy chủ Resend") from exc


def send_test_email(recipient_email, custom_code=None, custom_template=None):
    """Gửi email OTP thử nghiệm để quản trị viên kiểm tra luồng gửi và mẫu thư."""
    from django.core.validators import validate_email
    from django.core.exceptions import ValidationError
    config = EmailOtpSettings.current()
    if not config.get_api_key():
        raise RuntimeError("Chưa cấu hình API key của Resend.")
    if not config.from_email:
        raise RuntimeError("Chưa cấu hình email người gửi (From Email).")
    try:
        validate_email(recipient_email)
    except (ValidationError, AttributeError):
        raise ValueError("Địa chỉ email nhận test không hợp lệ.")

    test_code = custom_code or f"{secrets.randbelow(1_000_000):06d}"
    t0 = timezone.now()
    res = _send_resend(config, recipient_email.strip().lower(), test_code, custom_template=custom_template)
    duration_ms = int((timezone.now() - t0).total_seconds() * 1000)

    return {
        "success": True,
        "recipient": recipient_email.strip().lower(),
        "test_code": test_code,
        "resend_id": (res or {}).get("id", ""),
        "sender": f"{config.from_name} <{config.from_email}>" if config.from_name else config.from_email,
        "subject": config.subject,
        "duration_ms": duration_ms,
        "message": f"Đã gửi mã test OTP ({test_code}) tới {recipient_email} thành công qua Resend.",
    }


def issue_code(user, realm, request):
    config = EmailOtpSettings.current()
    if not config.is_ready:
        raise RuntimeError("Đăng nhập email chưa được quản trị viên cấu hình")
    recipient = recipient_for(user)
    if not recipient:
        raise ValueError("Tài khoản chưa có email hợp lệ")
    now = timezone.now()
    recent = EmailLoginCode.objects.filter(
        user=user, realm=realm, used_at__isnull=True,
        created_at__gte=now - timedelta(seconds=config.resend_cooldown_seconds)).exists()
    if recent:
        return False
    EmailLoginCode.objects.filter(user=user, realm=realm, used_at__isnull=True).update(used_at=now)
    code = f"{secrets.randbelow(1_000_000):06d}"
    record = EmailLoginCode.objects.create(
        user=user, realm=realm, sent_to=recipient, code_hash="",
        expires_at=now + timedelta(seconds=config.code_ttl_seconds),
        request_ip=str(request.META.get("REMOTE_ADDR") or "")[:64])
    record.code_hash = make_code_hash(code, record.pk)
    record.save(update_fields=["code_hash"])
    try:
        _send_resend(config, recipient, code)
    except Exception:
        record.used_at = timezone.now()
        record.save(update_fields=["used_at"])
        raise
    return True


def verify_code(user, realm, code, request, login_user=True):
    now = timezone.now()
    record = EmailLoginCode.objects.filter(
        user=user, realm=realm, used_at__isnull=True, expires_at__gte=now).order_by("-created_at").first()
    if not record:
        return False, "Mã không đúng hoặc đã hết hạn."
    config = EmailOtpSettings.current()
    if record.attempts >= config.max_attempts:
        record.used_at = now
        record.save(update_fields=["used_at"])
        return False, "Đã vượt quá số lần thử cho phép. Vui lòng lấy mã mới."
    record.attempts += 1
    expected_hash = make_code_hash(code, record.pk)
    if not constant_time_compare(record.code_hash, expected_hash):
        if record.attempts >= config.max_attempts:
            record.used_at = now
            record.save(update_fields=["attempts", "used_at"])
        else:
            record.save(update_fields=["attempts"])
        return False, "Mã không chính xác."
    record.used_at = now
    record.save(update_fields=["attempts", "used_at"])
    if login_user:
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    return True, "Xác thực thành công."
