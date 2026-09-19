# -*- coding: utf-8 -*-
"""Đăng nhập, danh tính người dùng, tra cứu nhật ký truy cập, và quản lý tài khoản."""
import io
import json
import logging
import secrets
import zipfile

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError as CoreValidationError
from django.core.validators import validate_email
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db import IntegrityError
from django.db.models import Count, Q
from django.http import HttpResponse
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.sessions.models import Session
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from . import branding, roles
from .email_otp import issue_code, send_test_email, verify_code
from .models import (AccessLog, AuthenticationEvent, EmailOtpSettings, ExternalIdentity,
                     ResendInboxEmail, ResendWebhookEvent, RoleModuleAccess,
                     UserAssistantPreference, UserLoginPolicy)
from .resend_webhooks import fetch_and_store_inbound, verify_svix
from .throttles import EmailOtpRequestThrottle, EmailOtpVerifyThrottle, LoginRateThrottle

#: Trần số dòng một lượt tải lên — chặn TRƯỚC khi đọc, cùng nguyên tắc với
#: EDGE_SYNC_MAX_BATCH (core/views.py): một file lỗi cỡ khổng lồ không được
#: phép làm nghẽn request trước khi kịp báo lỗi.
BULK_USER_MAX_ROWS = 500

#: .xlsx là một file zip — giới hạn dung lượng SAU GIẢI NÉN, cùng nguyên tắc
#: chống zip-bomb với talent/attachment_text.py (nơi đã có ca thật cần chặn).
BULK_USER_MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
log = logging.getLogger(__name__)


def _mask_username(value):
    value = str(value or "")[:254]
    if "@" in value:
        local, domain = value.rsplit("@", 1)
        return f"{local[:2]}***@{domain}"

    return f"{value[:2]}***" if value else ""


def _record_auth_event(request, result, user=None, actor=None, realm="local", detail=""):
    """Ghi audit best-effort; không làm thay đổi kết quả authentication."""
    try:
        AuthenticationEvent.objects.create(
            provider="internal" if realm == "local" else "email_otp",
            realm=realm, result=result, user=user, actor=actor,
            username_masked=_mask_username(getattr(user, "username", "")
                                           or request.data.get("username", "")),
            ip=str(request.META.get("REMOTE_ADDR") or "")[:64],
            user_agent=str(request.META.get("HTTP_USER_AGENT") or "")[:300],
            detail=str(detail or "")[:300])
    except Exception:
        log.exception("Không ghi được AuthenticationEvent (%s)", result)


def _revoke_user_sessions(user):
    """Thu hồi mọi Django session của user; thao tác admin hiếm nên scan chấp nhận được."""
    doomed = []
    for session in Session.objects.filter(expire_date__gte=timezone.now()).iterator():
        try:
            if str(session.get_decoded().get("_auth_user_id")) == str(user.pk):
                doomed.append(session.session_key)
        except Exception:
            continue
    if doomed:
        Session.objects.filter(session_key__in=doomed).delete()


def _identity(user):
    user_roles = sorted(roles.roles_of(user))
    preference = getattr(user, "assistant_preference", None)
    return {
        "id": user.pk,
        "username": user.get_username(),
        "full_name": user.get_full_name() or user.get_username(),
        "is_superuser": user.is_superuser,
        "roles": user_roles,
        "role_labels": [roles.ROLE_LABELS.get(r, r) for r in user_roles],
        "assistant_preference": _preference_payload(preference),
        # Giao diện dùng cái này để ẩn tab người dùng không vào được. Đây chỉ là
        # tiện ích hiển thị — chặn thật nằm ở phía máy chủ.
        "modules": sorted(roles.modules_of(user)),
        # Luật đọc CV không suy ra được từ `modules` (RB Sales vẫn có module
        # `talent`). Trả thẳng từ máy chủ để giao diện khỏi chép lại luật và lệch
        # nhau — lệch là người dùng bấm vào một nút chắc chắn ăn 403.
        "can_read_cv": _can_read_cv(user),
    }


def _can_read_cv(user):
    from talent.corpus_qa import can_read_cv
    return bool(can_read_cv(user))


def _preference_payload(preference):
    if preference is None:
        return {"gender": "", "preferred_name": "", "preferred_salutation": "",
                "personalization_enabled": True, "display_address": "anh/chị"}
    return {"gender": preference.gender, "preferred_name": preference.preferred_name,
            "preferred_salutation": preference.preferred_salutation,
            "personalization_enabled": preference.personalization_enabled,
            "display_address": preference.display_address()}


def _save_preference(user, data):
    keys = {"gender", "preferred_name", "preferred_salutation", "personalization_enabled"}
    if not any(key in data for key in keys):
        return getattr(user, "assistant_preference", None), ""
    row, _ = UserAssistantPreference.objects.get_or_create(user=user)
    gender = str(data.get("gender", row.gender) or "")
    salutation = str(data.get("preferred_salutation", row.preferred_salutation) or "")
    if gender not in {value for value, _label in UserAssistantPreference.GENDER_CHOICES} | {""}:
        return row, "Giới tính không hợp lệ."
    if salutation not in {value for value, _label in UserAssistantPreference.SALUTATION_CHOICES}:
        return row, "Cách xưng hô không hợp lệ."
    row.gender = gender
    row.preferred_salutation = salutation
    row.preferred_name = str(data.get("preferred_name", row.preferred_name) or "").strip()[:80]
    if "personalization_enabled" in data:
        row.personalization_enabled = bool(data.get("personalization_enabled"))
    row.save()
    return row, ""


@api_view(["GET", "PUT", "POST", "PATCH"])
@permission_classes([IsAuthenticated])
def assistant_preference(request):
    if request.method in ("PUT", "POST", "PATCH"):
        row, err = _save_preference(request.user, request.data)
        if err:
            return Response({"detail": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_preference_payload(row))
    row = getattr(request.user, "assistant_preference", None)
    return Response(_preference_payload(row))


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login_view(request):
    username = str(request.data.get("username") or "").strip()
    password = str(request.data.get("password") or "")
    if not username or not password:
        return Response({"detail": "Cần nhập tên đăng nhập và mật khẩu."},
                        status=status.HTTP_400_BAD_REQUEST)

    # Cùng thông báo với sai mật khẩu để không lộ username nào có thật. Tài
    # khoản Microsoft không được âm thầm giữ thêm cửa đăng nhập local.
    candidate = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).select_related("login_policy").first()
    if candidate and UserLoginPolicy.type_of(candidate) != UserLoginPolicy.LOCAL:
        _record_auth_event(request, "local_login_rejected", user=candidate,
                           detail="login_type_not_local")
        return Response({"detail": "Tên đăng nhập hoặc mật khẩu không đúng."},
                        status=status.HTTP_401_UNAUTHORIZED)

    user = authenticate(request, username=candidate.username if candidate else username, password=password)
    if user is None:
        # Cùng một thông báo cho sai tên và sai mật khẩu: đừng cho biết tài
        # khoản nào có thật.
        _record_auth_event(request, "local_login_failed")
        return Response({"detail": "Tên đăng nhập hoặc mật khẩu không đúng."},
                        status=status.HTTP_401_UNAUTHORIZED)
    if not user.is_active:
        _record_auth_event(request, "local_login_inactive", user=user)
        return Response({"detail": "Tài khoản đã bị vô hiệu hoá."},
                        status=status.HTTP_403_FORBIDDEN)

    login(request, user)
    _record_auth_event(request, "local_login_success", user=user)
    return Response(_identity(user))


def _domain_otp_realm(user, config=None):
    """Domain OTP đã cấu hình là nguồn quyết định cho tài khoản email.

    Nếu tài khoản đã có UserLoginPolicy là LOCAL thì tôn trọng hình thức mật khẩu.
    Các tài khoản cũ/tạo từ Django Admin chưa có UserLoginPolicy thì căn cứ theo
    domain email để phân loại.
    """
    config = config or EmailOtpSettings.current()
    if hasattr(user, "login_policy"):
        if user.login_policy.login_type == UserLoginPolicy.LOCAL:
            return ""
        if user.login_policy.login_type in (UserLoginPolicy.TNTALENT, UserLoginPolicy.MSB):
            return user.login_policy.login_type
    return config.realm_for_email(user.email or user.username)


def _sync_domain_otp_policy(user, realm):
    if realm:
        UserLoginPolicy.objects.update_or_create(user=user, defaults={"login_type": realm})


def _otp_candidate(identifier, realm):
    value = str(identifier or "").strip()
    if not value:
        return None
    config = EmailOtpSettings.current()
    if config.realm_for_email(value) != realm:
        return None
    candidate = User.objects.filter(Q(username__iexact=value) | Q(email__iexact=value)).select_related(
        "login_policy").first()
    if not candidate or not candidate.is_active or _domain_otp_realm(candidate, config) != realm:
        return None
    _sync_domain_otp_policy(candidate, realm)
    return candidate


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailOtpRequestThrottle])
def email_otp_request(request, realm):
    if realm not in (UserLoginPolicy.TNTALENT, UserLoginPolicy.MSB):
        return Response({"detail": "Loại đăng nhập không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
    user = _otp_candidate(request.data.get("identifier"), realm)
    # Không làm lộ tài khoản nào tồn tại qua phản hồi request mã.
    generic = {"detail": "Nếu tài khoản hợp lệ, mã đăng nhập đã được gửi tới email đã đăng ký."}
    if not user:
        _record_auth_event(request, "email_otp_request_rejected", realm=realm)
        return Response(generic)
    try:
        sent = issue_code(user, realm, request)
    except ValueError:
        _record_auth_event(request, "email_otp_request_rejected", user=user, realm=realm,
                           detail="missing_email")
        return Response(generic)
    except RuntimeError as exc:
        _record_auth_event(request, "email_otp_send_failed", user=user, realm=realm, detail=str(exc))
        return Response({"detail": "Chưa thể gửi mã. Vui lòng thử lại sau."},
                        status=status.HTTP_503_SERVICE_UNAVAILABLE)
    _record_auth_event(request, "email_otp_sent" if sent else "email_otp_cooldown", user=user, realm=realm)
    return Response(generic)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailOtpVerifyThrottle])
def email_otp_verify(request, realm):
    if realm not in (UserLoginPolicy.TNTALENT, UserLoginPolicy.MSB):
        return Response({"detail": "Loại đăng nhập không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
    code = str(request.data.get("code") or "").strip()
    user = _otp_candidate(request.data.get("identifier"), realm)
    if not user or not (len(code) == 6 and code.isdigit()):
        _record_auth_event(request, "email_otp_verify_failed", realm=realm)
        return Response({"detail": "Mã không đúng hoặc đã hết hạn."}, status=status.HTTP_401_UNAUTHORIZED)
    verified, detail = verify_code(user, realm, code, request)
    if not verified:
        _record_auth_event(request, "email_otp_verify_failed", user=user, realm=realm, detail=detail)
        return Response({"detail": detail}, status=status.HTTP_401_UNAUTHORIZED)
    _record_auth_event(request, "email_otp_login_success", user=user, realm=realm)
    return Response(_identity(user))


def _duplicate_account_conflict(identifier):
    """Đã có tài khoản trùng ``identifier`` ở username HOẶC email chưa.

    Đăng nhập tra cứu bằng ``Q(username__iexact) | Q(email__iexact)`` (xem
    ``login_view``/``login_discovery``). Hai tài khoản trùng nhau ở một trong
    hai trường sẽ khiến ``.first()`` chọn nhầm tài khoản — chặn ngay từ lúc tạo,
    không phân biệt hoa thường. Với tài khoản OTP thì email = username nên chỉ
    cần soi một giá trị này là đủ cho cả hai đường tạo (tay và hàng loạt).
    """
    value = str(identifier or "").strip()
    if not value:
        return False
    return User.objects.filter(
        Q(username__iexact=value) | Q(email__iexact=value)).exists()


def _local_candidate(identifier):
    value = str(identifier or "").strip()
    if not value:
        return None
    candidate = User.objects.filter(Q(username__iexact=value) | Q(email__iexact=value)).select_related(
        "login_policy").first()
    if not candidate or not candidate.is_active or UserLoginPolicy.type_of(candidate) != UserLoginPolicy.LOCAL:
        return None
    return candidate


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailOtpRequestThrottle])
def local_password_reset_request(request):
    user = _local_candidate(request.data.get("identifier"))
    generic = {"detail": "Nếu tài khoản local có email hợp lệ, mã đặt lại mật khẩu đã được gửi."}
    if not user:
        return Response(generic)
    try:
        issue_code(user, UserLoginPolicy.LOCAL, request)
    except (ValueError, RuntimeError):
        _record_auth_event(request, "local_reset_send_failed", user=user, detail="email_delivery_failed")
        return Response(generic)
    _record_auth_event(request, "local_reset_code_sent", user=user)
    return Response(generic)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([EmailOtpVerifyThrottle])
def local_password_reset_confirm(request):
    user = _local_candidate(request.data.get("identifier"))
    code = str(request.data.get("code") or "").strip()
    password = str(request.data.get("password") or "")
    if not user or not (len(code) == 6 and code.isdigit()):
        return Response({"detail": "Mã không đúng hoặc đã hết hạn."}, status=status.HTTP_401_UNAUTHORIZED)
    verified, detail = verify_code(user, UserLoginPolicy.LOCAL, code, request, login_user=False)
    if not verified:
        return Response({"detail": detail}, status=status.HTTP_401_UNAUTHORIZED)
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(password)
    user.save(update_fields=["password"])
    _revoke_user_sessions(user)
    _record_auth_event(request, "local_password_reset_success", user=user)
    return Response({"detail": "Đặt lại mật khẩu thành công. Hãy đăng nhập bằng mật khẩu mới."})


def _public_settings_payload(config):
    return {
        "app_name": config.from_name or "MSB Radar",
        "app_tagline": config.app_tagline or "Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng",
        "app_icon": config.app_icon or "⚡",
        "app_logo_url": config.app_logo_url or "",
        "color_preset": config.color_preset or "amber_gold",
        "custom_color": config.custom_color or "#FF8A33",
        "gradient_from": config.gradient_from or "#FF8A33",
        "gradient_to": config.gradient_to or "#EA580C",
        "gradient_via": config.gradient_via or "#F59E0B",
        "gradient_angle": config.gradient_angle or "135deg",
        "radar_avatar_url": config.radar_avatar_url or "",
        "radar_avatar_emoji": config.radar_avatar_emoji or "⚡",
        "theme_mode": config.theme_mode or "dark",
        "table_density": config.table_density or "normal",
        "mask_sensitive_data": bool(config.mask_sensitive_data),
        "min_match_score": int(config.min_match_score or 50),
        "items_per_page": int(config.items_per_page or 25),
        "sound_alerts": bool(config.sound_alerts),
        # Thumbnail / xem trước liên kết. Trả cả giá trị THÔ (để `/settings` hiện
        # đúng ô nào đang trống) lẫn bản ĐÃ SUY RA (để xem trước khớp với thứ
        # crawler thật sự nhận được).
        "og_image_url": config.og_image_url or "",
        "og_image_alt": config.og_image_alt or "",
        "og_image_width": int(config.og_image_width or 1200),
        "og_image_height": int(config.og_image_height or 630),
        "og_title": config.og_title or "",
        "og_description": config.og_description or "",
        "og_site_name": config.og_site_name or "",
        "meta_keywords": config.meta_keywords or "",
        "meta_robots": config.meta_robots or "index, follow",
        "pwa_short_name": config.pwa_short_name or "",
        "pwa_background_color": config.pwa_background_color or "#0F172A",
        "link_preview": branding.link_preview(config),
    }


def _email_otp_settings_payload(config):
    all_domains = config.all_allowed_domains
    payload = _public_settings_payload(config)
    payload.update({
        "enabled": config.enabled,
        "api_key_configured": config.api_key_configured,
        "from_email": config.from_email,
        "from_name": config.from_name,
        "reply_to": config.reply_to,
        "subject": config.subject,
        "otp_html_template": config.otp_html_template,
        "allowed_domains": all_domains,
        "domains": ", ".join(all_domains),
        "tntalent_domains": config.domains_for(UserLoginPolicy.TNTALENT),
        "msb_domains": config.domains_for(UserLoginPolicy.MSB),
        "code_ttl_seconds": config.code_ttl_seconds,
        "resend_cooldown_seconds": config.resend_cooldown_seconds,
        "max_attempts": config.max_attempts,
        "is_ready": config.is_ready,
        "webhook_secret_configured": config.webhook_secret_configured,
        "webhook_inbound_enabled": config.webhook_inbound_enabled,
        "updated_at": config.updated_at,
        "updated_by": config.updated_by.username if config.updated_by else "",
    })
    return payload


def _resend_webhook_url(request):
    """URL public gửi sang Resend luôn phải là HTTPS.

    Một số reverse proxy kết thúc TLS nhưng không chuyển ``X-Forwarded-Proto``
    vào Django. Khi đó ``build_absolute_uri`` sẽ sinh nhầm http dù endpoint
    bên ngoài đã có chứng chỉ hợp lệ. Resend chỉ chấp nhận HTTPS.
    """
    url = request.build_absolute_uri(reverse("resend-webhook"))
    return "https://" + url.split("://", 1)[-1]


@api_view(["GET"])
@permission_classes([AllowAny])
def login_options(request):
    config = EmailOtpSettings.current()
    return Response({
        "local_login_enabled": True,
        "branding": _public_settings_payload(config),
        "email_otp": {
            "tntalent": config.is_ready and bool(config.domains_for(UserLoginPolicy.TNTALENT)),
            "msb": config.is_ready and bool(config.domains_for(UserLoginPolicy.MSB)),
        },
        "email_otp_domains": {
            "tntalent": config.domains_for(UserLoginPolicy.TNTALENT),
            "msb": config.domains_for(UserLoginPolicy.MSB),
        },
    })


@api_view(["GET", "PATCH", "POST"])
@permission_classes([AllowAny])
def public_settings(request):
    """Đọc cấu hình giao diện & nhận diện chung toàn hệ thống (AllowAny); chỉ Admin được lưu (PATCH/POST)."""
    config = EmailOtpSettings.current()
    if request.method == "GET":
        return Response(_public_settings_payload(config))

    if not request.user or not request.user.is_authenticated:
        return Response({"detail": "Yêu cầu đăng nhập quản trị viên để cập nhật cài đặt hệ thống."},
                        status=status.HTTP_401_UNAUTHORIZED)
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được cập nhật cài đặt hệ thống."},
                        status=status.HTTP_403_FORBIDDEN)

    data = request.data
    if "app_name" in data:
        name = str(data.get("app_name") or "").strip()
        if len(name) <= 100:
            config.from_name = name or "MSB Radar"
    if "app_tagline" in data:
        tagline = str(data.get("app_tagline") or "").strip()
        if len(tagline) <= 255:
            config.app_tagline = tagline or "Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng"
    if "app_icon" in data:
        icon = str(data.get("app_icon") or "").strip()
        if len(icon) <= 20:
            config.app_icon = icon or "⚡"
    if "app_logo_url" in data:
        logo_url = str(data.get("app_logo_url") or "").strip()
        if len(logo_url) <= 2000000:
            config.app_logo_url = logo_url
    if "color_preset" in data:
        preset = str(data.get("color_preset") or "").strip()
        if len(preset) <= 40:
            config.color_preset = preset or "amber_gold"
    if "custom_color" in data:
        color = str(data.get("custom_color") or "").strip()
        if len(color) <= 20:
            config.custom_color = color or "#FF8A33"
    if "gradient_from" in data:
        val = str(data.get("gradient_from") or "").strip()
        if len(val) <= 20:
            config.gradient_from = val or "#FF8A33"
    if "gradient_to" in data:
        val = str(data.get("gradient_to") or "").strip()
        if len(val) <= 20:
            config.gradient_to = val or "#EA580C"
    if "gradient_via" in data:
        val = str(data.get("gradient_via") or "").strip()
        if len(val) <= 20:
            config.gradient_via = val or "#F59E0B"
    if "gradient_angle" in data:
        val = str(data.get("gradient_angle") or "").strip()
        if len(val) <= 15:
            config.gradient_angle = val or "135deg"
    if "radar_avatar_url" in data:
        raw_val = str(data.get("radar_avatar_url") or "").strip()
        config.radar_avatar_url = raw_val
    if "radar_avatar_emoji" in data:
        val = str(data.get("radar_avatar_emoji") or "").strip()
        if len(val) <= 20:
            config.radar_avatar_emoji = val or "⚡"
    if "theme_mode" in data:
        mode = str(data.get("theme_mode") or "").strip()
        if mode in ("dark", "light", "auto"):
            config.theme_mode = mode
    if "table_density" in data:
        density = str(data.get("table_density") or "").strip()
        if density in ("compact", "normal", "comfortable"):
            config.table_density = density
    if "mask_sensitive_data" in data:
        config.mask_sensitive_data = bool(data["mask_sensitive_data"])
    if "min_match_score" in data:
        try:
            score = int(data["min_match_score"])
            if 0 <= score <= 100:
                config.min_match_score = score
        except (ValueError, TypeError):
            pass
    if "items_per_page" in data:
        try:
            items = int(data["items_per_page"])
            if 5 <= items <= 100:
                config.items_per_page = items
        except (ValueError, TypeError):
            pass
    if "sound_alerts" in data:
        config.sound_alerts = bool(data["sound_alerts"])

    _apply_link_preview(config, data)

    config.updated_by = request.user
    config.save()
    return Response(_public_settings_payload(config))


#: (tên trường, độ dài tối đa). Cắt thay vì từ chối: người vận hành dán một mô tả
#: dài không nên bị chặn cả lần lưu, và thẻ meta dài quá thì mạng xã hội cũng tự
#: cắt.
_PREVIEW_TEXT_FIELDS = (
    ("og_image_url", 1000), ("og_image_alt", 255), ("og_title", 255),
    ("og_description", 2000), ("og_site_name", 120), ("meta_keywords", 1000),
    ("meta_robots", 60), ("pwa_short_name", 60), ("pwa_background_color", 20),
)


def _apply_link_preview(config, data):
    """Ghi các trường thumbnail. Bỏ trống = "suy ra từ tên/tagline", hợp lệ."""
    for name, limit in _PREVIEW_TEXT_FIELDS:
        if name in data:
            setattr(config, name, str(data.get(name) or "").strip()[:limit])
    for name, low, high in (("og_image_width", 200, 4000),
                            ("og_image_height", 200, 4000)):
        if name in data:
            try:
                value = int(data[name])
            except (ValueError, TypeError):
                continue
            if low <= value <= high:
                setattr(config, name, value)


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([LoginRateThrottle])
def login_discovery(request):
    """Xác định luồng từ account thật, để UI không cho user không tồn tại đi tiếp."""
    identifier = str(request.data.get("identifier") or "").strip()
    if not identifier:
        return Response({"detail": "Cần nhập username hoặc email."}, status=status.HTTP_400_BAD_REQUEST)
    user = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier)).select_related(
        "login_policy").first()
    if not user:
        return Response({"detail": "Tài khoản không tồn tại. Vui lòng kiểm tra lại username hoặc email."},
                        status=status.HTTP_404_NOT_FOUND)
    if not user.is_active:
        return Response({"detail": "Tài khoản đã bị vô hiệu hóa. Vui lòng liên hệ quản trị viên."},
                        status=status.HTTP_403_FORBIDDEN)
    config = EmailOtpSettings.current()
    if hasattr(user, "login_policy"):
        login_type = user.login_policy.login_type
        if login_type == UserLoginPolicy.LOCAL:
            return Response({"mode": "local"})
        return Response({"mode": "otp", "realm": login_type})

    domain_realm = config.realm_for_email(user.email or user.username)
    if domain_realm:
        _sync_domain_otp_policy(user, domain_realm)
        return Response({"mode": "otp", "realm": domain_realm})
    _sync_domain_otp_policy(user, UserLoginPolicy.LOCAL)
    return Response({"mode": "local"})


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated])
def email_otp_settings(request):
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được cấu hình Email OTP."},
                        status=status.HTTP_403_FORBIDDEN)
    config = EmailOtpSettings.current()
    if request.method == "GET":
        payload = _email_otp_settings_payload(config)
        payload["webhook_url"] = _resend_webhook_url(request)
        return Response(payload)
    data = request.data
    if "from_email" in data:
        value = str(data.get("from_email") or "").strip()
        if value:
            try:
                validate_email(value)
            except CoreValidationError:
                return Response({"detail": "from_email không phải email hợp lệ."},
                                status=status.HTTP_400_BAD_REQUEST)
        config.from_email = value
    if "reply_to" in data:
        replies = [item.strip() for item in str(data.get("reply_to") or "").replace(";", ",").split(",") if item.strip()]
        if len(replies) > 20:
            return Response({"detail": "Tối đa 20 email Reply-to."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            for reply in replies:
                validate_email(reply)
        except CoreValidationError:
            return Response({"detail": "Một hoặc nhiều email Reply-to không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        config.reply_to = ",".join(replies)
    for key, limit in (("from_name", 100), ("subject", 160), ("otp_html_template", 30000),
                       ("app_logo_url", 2000000), ("app_icon", 20), ("app_tagline", 255)):
        if key in data:
            value = str(data.get(key) or "").strip()
            if len(value) > limit:
                return Response({"detail": f"{key} quá dài."}, status=status.HTTP_400_BAD_REQUEST)
            setattr(config, key, value)
    if "webhook_secret" in data and str(data.get("webhook_secret") or "").strip():
        secret = str(data["webhook_secret"]).strip()
        if not secret.startswith("whsec_"):
            return Response({"detail": "Webhook signing secret Resend phải bắt đầu bằng whsec_."},
                            status=status.HTTP_400_BAD_REQUEST)
        config.set_webhook_secret(secret)
    if "webhook_inbound_enabled" in data:
        config.webhook_inbound_enabled = bool(data["webhook_inbound_enabled"])
    for key, minimum, maximum in (("code_ttl_seconds", 600, 600),
                                  ("resend_cooldown_seconds", 30, 600),
                                  ("max_attempts", 3, 10)):
        if key in data:
            try:
                value = int(data[key])
            except (ValueError, TypeError):
                return Response({"detail": f"{key} không hợp lệ."}, status=status.HTTP_400_BAD_REQUEST)
            if not minimum <= value <= maximum:
                return Response({"detail": f"{key} phải trong khoảng {minimum}-{maximum}."},
                                status=status.HTTP_400_BAD_REQUEST)
            setattr(config, key, value)
    if "allowed_domains" in data or "domains" in data:
        domain_input = data.get("allowed_domains") if "allowed_domains" in data else data.get("domains")
        domains = EmailOtpSettings.normalize_domains(domain_input)
        if any("." not in domain or "@" in domain or " " in domain for domain in domains):
            return Response({"detail": "Danh sách domain chứa tên miền không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        tnt_list = [d for d in domains if "tntalent" in d]
        msb_list = [d for d in domains if "tntalent" not in d]
        config.tntalent_domains = ",".join(tnt_list) if tnt_list else ",".join(domains)
        config.msb_domains = ",".join(msb_list) if msb_list else ",".join(domains)
    else:
        raw_domains = {}
        for key in ("tntalent_domains", "msb_domains"):
            if key in data:
                domains = EmailOtpSettings.normalize_domains(data.get(key))
                if any("." not in domain or "@" in domain or " " in domain for domain in domains):
                    return Response({"detail": f"{key} chứa domain không hợp lệ."},
                                    status=status.HTTP_400_BAD_REQUEST)
                raw_domains[key] = ",".join(domains)
        overlap = set(EmailOtpSettings.normalize_domains(raw_domains.get("tntalent_domains", config.tntalent_domains))) & set(
            EmailOtpSettings.normalize_domains(raw_domains.get("msb_domains", config.msb_domains)))
        if overlap and ("tntalent_domains" in data or "msb_domains" in data):
            return Response({"detail": f"Một domain chỉ thuộc một loại OTP: {', '.join(sorted(overlap))}."},
                            status=status.HTTP_400_BAD_REQUEST)
        for key, value in raw_domains.items():
            setattr(config, key, value)
    if "api_key" in data and str(data.get("api_key") or "").strip():
        key = str(data["api_key"]).strip()
        if not key.startswith("re_"):
            return Response({"detail": "Resend API key phải bắt đầu bằng re_."},
                            status=status.HTTP_400_BAD_REQUEST)
        config.set_api_key(key)
    if "enabled" in data:
        config.enabled = bool(data["enabled"])
    if config.enabled and (not config.api_key_configured or not config.from_email
                           or not (config.domains_for(UserLoginPolicy.TNTALENT) or config.domains_for(UserLoginPolicy.MSB))):
        return Response({"detail": "Cần API key, email người gửi và ít nhất một domain OTP trước khi bật."},
                        status=status.HTTP_400_BAD_REQUEST)
    if config.webhook_inbound_enabled and (not config.webhook_secret_configured or not config.api_key_configured):
        return Response({"detail": "Bật hộp thư inbound cần Resend API key và Webhook Signing Secret."},
                        status=status.HTTP_400_BAD_REQUEST)
    config.updated_by = request.user
    config.save()
    _record_auth_event(request, "email_otp_settings_changed", actor=request.user, realm="email_otp")
    payload = _email_otp_settings_payload(config)
    payload["webhook_url"] = _resend_webhook_url(request)
    return Response(payload)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def email_otp_test_send(request):
    """Gửi email OTP thử nghiệm để kiểm tra luồng gửi thư và API Resend."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được gửi thử nghiệm Email OTP."},
                        status=status.HTTP_403_FORBIDDEN)
    data = request.data or {}
    recipient = str(data.get("recipient") or request.user.email or request.user.username or "").strip()
    custom_template = str(data.get("template") or "") if "template" in data else None
    if not recipient:
        return Response({"detail": "Cần nhập địa chỉ email nhận mã test OTP."},
                        status=status.HTTP_400_BAD_REQUEST)
    try:
        result = send_test_email(recipient, custom_template=custom_template)
        _record_auth_event(request, "email_otp_test_sent", actor=request.user, realm="email_otp",
                           detail=f"Test sent to {recipient}")
        return Response(result)
    except (ValueError, RuntimeError) as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        log.exception("Lỗi không mong muốn khi gửi test email OTP")
        return Response({"detail": f"Lỗi gửi thư: {str(exc)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def resend_webhook(request):
    """Callback Resend công khai; không bao giờ tin payload trước khi verify Svix."""
    config = EmailOtpSettings.current()
    raw = request.body
    if not config.webhook_secret_configured or not verify_svix(raw, request.headers, config.get_webhook_secret()):
        return Response({"detail": "Invalid webhook signature."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return Response({"detail": "Invalid JSON."}, status=status.HTTP_400_BAD_REQUEST)
    event_type = str(payload.get("type") or "")[:60]
    data = payload.get("data") or {}
    svix_id = str(request.headers.get("svix-id") or "")[:120]
    try:
        event = ResendWebhookEvent.objects.create(
            svix_id=svix_id, event_type=event_type,
            email_id=str(data.get("email_id") or "")[:80],
            occurred_at=data.get("created_at") or payload.get("created_at") or None,
            payload=payload)
    except IntegrityError:
        return Response({"ok": True, "duplicate": True})
    if event_type == "email.received" and config.webhook_inbound_enabled and event.email_id and config.api_key_configured:
        fetch_and_store_inbound(event.email_id, config.get_api_key(), data)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def resend_inbox(request):
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên xem hộp thư Resend."}, status=status.HTTP_403_FORBIDDEN)
    rows = ResendInboxEmail.objects.all()[:100]
    return Response({"results": [{
        "id": row.id, "email_id": row.email_id, "sender": row.sender,
        "recipients": row.recipients, "subject": row.subject, "text_body": row.text_body,
        "attachments": row.attachments, "received_at": row.received_at,
    } for row in rows]})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def resend_webhook_events(request):
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên xem webhook Resend."}, status=status.HTTP_403_FORBIDDEN)
    rows = ResendWebhookEvent.objects.all()[:100]
    return Response({"results": [{
        "id": row.id, "event_type": row.event_type, "email_id": row.email_id,
        "occurred_at": row.occurred_at, "received_at": row.received_at,
    } for row in rows]})


@api_view(["POST"])
@permission_classes([AllowAny])
def logout_view(request):
    logout(request)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
def me_view(request):
    """Ai đang đăng nhập. Trả 200 kể cả khi chưa đăng nhập.

    Giao diện gọi hàm này đầu tiên để biết hiện màn hình đăng nhập hay nội dung.
    Trả 401 ở đây sẽ khiến trạng thái "chưa đăng nhập" trông như một lỗi.
    """
    if not request.user or not request.user.is_authenticated:
        return Response({"authenticated": False})
    return Response({"authenticated": True, **_identity(request.user)})



@api_view(["GET"])
@permission_classes([IsAuthenticated])
def access_log_list(request):
    """Tra cứu nhật ký truy cập.

    Chỉ Admin xem được: đây là dữ liệu về hành vi của đồng nghiệp, không phải
    thứ ai cũng cần thấy.
    """
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên xem được nhật ký truy cập."},
                        status=status.HTTP_403_FORBIDDEN)

    queryset = AccessLog.objects.all()
    params = request.query_params

    if params.get("person"):
        queryset = queryset.filter(person_id=params["person"])
    if params.get("user"):
        queryset = queryset.filter(user_name__icontains=params["user"])
    if params.get("action"):
        queryset = queryset.filter(action=params["action"])
    if params.get("cross_domain") == "1":
        queryset = queryset.filter(cross_domain=True)
    if params.get("exfiltration") == "1":
        queryset = queryset.filter(action__in=AccessLog.EXFILTRATION_ACTIONS)
    if params.get("denied") == "1":
        # Ai đang cố vào chỗ không được phép — câu hỏi an ninh, không phải
        # câu hỏi tuân thủ, nhưng cùng dùng một nhật ký.
        queryset = queryset.filter(allowed=False)

    try:
        limit = min(500, max(1, int(params.get("limit", 100))))
    except (TypeError, ValueError):
        limit = 100

    total = queryset.count()
    rows = [{
        "id": row.id,
        "at": row.created_at,
        "user": row.user_name,
        "roles": row.roles,
        "action": row.action,
        "module": row.module,
        "person": row.person_id,
        "person_name": row.person_name,
        "cross_domain": row.cross_domain,
        "allowed": row.allowed,
        "exfiltration": row.is_exfiltration,
        "path": row.path,
        "ip": row.ip,
        "extra": row.extra,
    } for row in queryset.select_related()[:limit]]

    return Response({"count": total, "results": rows})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def access_log_summary(request):
    """Vài con số Compliance sẽ hỏi trước tiên."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên xem được."},
                        status=status.HTTP_403_FORBIDDEN)

    return Response({
        "total": AccessLog.objects.count(),
        "cross_domain": AccessLog.objects.filter(cross_domain=True).count(),
        "denied": AccessLog.objects.filter(allowed=False).count(),
        "exfiltration": AccessLog.objects.filter(
            action__in=AccessLog.EXFILTRATION_ACTIONS).count(),
        "by_user": list(AccessLog.objects.values("user_name")
                        .annotate(n=Count("id"),
                                  cross=Count("id", filter=Q(cross_domain=True)))
                        .order_by("-n")[:20]),
        "by_action": list(AccessLog.objects.values("action")
                          .annotate(n=Count("id")).order_by("-n")),
    })


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def role_module_matrix(request):
    """Phân quyền vào module theo vai trò — Admin gán, phủ lên ma trận mặc định.

    GET  → ma trận đầy đủ (mọi vai trò × mọi module) kèm `enabled` / `is_default`
           / `editable`.
    POST → `{role, module, enabled}` bật/tắt một Ô. Ô trùng mặc định thì xoá hàng
           override (giữ bảng chỉ chứa cái đã đổi). Không cho sửa Ô bị khoá
           (`roles.LOCKED_GRANTS`, ví dụ Admin ↔ Quản trị hệ thống).
    """
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên phân quyền được."},
                        status=status.HTTP_403_FORBIDDEN)

    if request.method == "POST":
        role = str(request.data.get("role") or "")
        module = str(request.data.get("module") or "")
        enabled = bool(request.data.get("enabled"))
        if role not in roles.ALL_ROLES or module not in roles.MODULE_LABELS:
            return Response({"detail": "Vai trò hoặc module không hợp lệ."},
                            status=status.HTTP_400_BAD_REQUEST)
        if (role, module) in roles.LOCKED_GRANTS:
            return Response({"detail": "Ô này bị khoá để tránh tự khoá mình khỏi trang quản trị."},
                            status=status.HTTP_400_BAD_REQUEST)

        is_default = module in roles.default_modules_for_role(role)
        if enabled == is_default:
            RoleModuleAccess.objects.filter(role=role, module=module).delete()
        else:
            RoleModuleAccess.objects.update_or_create(
                role=role, module=module,
                defaults={"allowed": enabled, "updated_by": request.user,
                          "updated_by_name": str(request.user)[:150]})

    return Response(_role_module_payload())


def _role_module_payload():
    overrides = roles.role_module_overrides()
    cells = []
    for role in roles.ALL_ROLES:
        default_set = roles.default_modules_for_role(role)
        for module in roles.ALL_MODULES:
            is_default = module in default_set
            override = overrides.get((role, module))
            enabled = override if override is not None else is_default
            cells.append({
                "role": role,
                "module": module,
                "enabled": enabled,
                "is_default": is_default,
                "changed": override is not None,
                "editable": (role, module) not in roles.LOCKED_GRANTS,
            })
    return {
        "roles": [{"key": r, "label": roles.ROLE_LABELS[r]} for r in roles.ALL_ROLES],
        "modules": [{"key": m, "label": roles.MODULE_LABELS[m]}
                    for m in roles.ALL_MODULES],
        "cells": cells,
    }


def _user_row(user):
    user_roles = sorted(roles.roles_of(user))
    active_identity = next(
        (identity for identity in user.external_identities.all()
         if identity.revoked_at is None), None)
    preference = getattr(user, "assistant_preference", None)
    return {
        "id": user.id,
        "username": user.get_username(),
        "full_name": user.get_full_name() or user.get_username(),
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "roles": user_roles,
        "role_labels": [roles.ROLE_LABELS.get(r, r) for r in user_roles],
        "date_joined": user.date_joined,
        "last_login": user.last_login,
        "login_type": UserLoginPolicy.type_of(user),
        "microsoft_linked": active_identity is not None,
        "last_sso_login_at": active_identity.last_login_at if active_identity else None,
        "assistant_preference": _preference_payload(preference),
    }


def _require_admin(request):
    """Chỉ Admin quản lý được tài khoản người khác — tự cấp quyền cho chính
    mình không phải việc một vai trò khác nên làm được."""
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên quản lý được người dùng."},
                        status=status.HTTP_403_FORBIDDEN)
    return None


def _clean_roles(raw):
    """Chỉ nhận vai trò có thật; bỏ qua roles=None nghĩa là 'không đổi'."""
    if raw is None:
        return None, None
    if not isinstance(raw, list):
        return None, "roles phải là một danh sách."
    unknown = [r for r in raw if r not in roles.ALL_ROLES]
    if unknown:
        return None, f"Vai trò không tồn tại: {', '.join(unknown)}"
    return raw, None


def _clean_login_type(raw):
    """Lúc tạo/sửa chỉ còn hai lựa chọn: ``local`` (mật khẩu) và ``otp`` (mã email).

    Vẫn nhận ``tntalent``/``msb`` để không phá API cũ và file .xlsx đã phát —
    :func:`_resolve_create_login_type` quy tất cả về realm theo domain đã khai.
    """
    value = str(raw or UserLoginPolicy.LOCAL).strip().lower()
    if value == "otp":
        return "otp", None
    if value not in UserLoginPolicy.LOGIN_TYPES:
        return None, "Loại đăng nhập phải là local hoặc otp."
    return value, None


def _resolve_create_login_type(identifier, requested):
    """Chốt hình thức đăng nhập từ lựa chọn tay + domain đã khai, trả ``(type, error)``.

    Loại OTP không còn tách "nhân sự / nhân viên": tab Email OTP đã khai danh
    sách domain cho từng realm nên chỉ cần biết "thường" hay "OTP".

    - ``local``: giữ local, TRỪ KHI email thuộc một domain OTP đã khai — khi đó
      ép về đúng realm để không vô tình tạo tài khoản mật khẩu cho địa chỉ
      @tntalent.vn/@msb.com.vn.
    - ``otp``/``tntalent``/``msb``: email BẮT BUỘC thuộc một domain OTP đã khai;
      nếu không thì từ chối, vì tài khoản tạo ra sẽ không bao giờ nhận được mã.
    """
    realm = EmailOtpSettings.current().realm_for_email(identifier)
    if requested == UserLoginPolicy.LOCAL:
        return realm or UserLoginPolicy.LOCAL, None
    if not realm:
        domain = identifier.rsplit("@", 1)[-1] if "@" in identifier else (identifier or "—")
        return None, (f'Domain "{domain}" chưa được khai trong tab Email OTP. '
                      "Thêm domain ở đó rồi tạo lại, hoặc chọn Tài khoản thường.")
    return realm, None


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def user_list(request):
    """Danh sách tài khoản (GET) và tạo tài khoản mới (POST). Chỉ Admin."""
    denied = _require_admin(request)
    if denied:
        return denied

    if request.method == "GET":
        users = (User.objects.select_related("login_policy")
                 .prefetch_related("external_identities").all().order_by("username"))
        return Response({"results": [_user_row(u) for u in users]})

    username = str(request.data.get("username") or "").strip()
    password = str(request.data.get("password") or "")
    full_name = str(request.data.get("full_name") or "").strip()
    login_type, login_error = _clean_login_type(request.data.get("login_type"))
    if login_error:
        return Response({"detail": login_error}, status=status.HTTP_400_BAD_REQUEST)
    role_names, error = _clean_roles(request.data.get("roles") or [])
    if error:
        return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)

    if not username:
        return Response({"detail": "Cần tên đăng nhập."}, status=status.HTTP_400_BAD_REQUEST)
    if _duplicate_account_conflict(username):
        return Response({"detail": "Đã có tài khoản dùng tên đăng nhập hoặc email này."},
                        status=status.HTTP_400_BAD_REQUEST)
    login_type, type_error = _resolve_create_login_type(username, login_type)
    if type_error:
        return Response({"detail": type_error}, status=status.HTTP_400_BAD_REQUEST)
    if login_type == UserLoginPolicy.LOCAL:
        try:
            validate_password(password)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
    else:
        try:
            validate_email(username)
        except CoreValidationError:
            return Response({"detail": "Tài khoản Email OTP phải dùng email hợp lệ làm tên đăng nhập."},
                            status=status.HTTP_400_BAD_REQUEST)

    roles.ensure_groups()
    with transaction.atomic():
        user = User.objects.create_user(
            username, password=password if login_type == UserLoginPolicy.LOCAL else None,
            first_name=full_name, email=username if login_type != UserLoginPolicy.LOCAL else "")
        UserLoginPolicy.objects.create(user=user, login_type=login_type)
        if role_names:
            user.groups.set(Group.objects.filter(name__in=role_names))
        _preference, preference_error = _save_preference(user, request.data)
        if preference_error:
            transaction.set_rollback(True)
            return Response({"detail": preference_error}, status=status.HTTP_400_BAD_REQUEST)

    return Response(_user_row(user), status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def user_bulk_template(request):
    """File mẫu (.xlsx) để điền hàng loạt rồi tải lên `user_bulk_create`.

    .xlsx thay vì .csv để cột `vai_tro` có được ô chọn từ danh sách thả xuống
    ngay trong Excel — gõ tay dễ sai chính tả khoá vai trò, chọn từ danh sách
    thì không. Validation để errorStyle="warning" (không "stop"): một người
    có nhiều vai trò vẫn gõ tay được `recruiter|manager`, chỉ là Excel nhắc
    chứ không chặn — chặn cứng sẽ vô tình cấm luôn ca hợp lệ đó.

    Không còn dòng ví dụ giả trong vùng dữ liệu (bản .csv trước đây phải đánh
    dấu bằng # để khỏi lỡ tạo nhầm tài khoản "ví dụ", gây khó hiểu) — chú
    thích và bảng tra vai trò để ở các cột E/F, tách hẳn khỏi vùng A:C mà
    `user_bulk_create` đọc.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Tài khoản"
    sheet.append(["username", "ho_ten", "vai_tro", "loai_dang_nhap"])

    role_list = ",".join(roles.ALL_ROLES)
    validation = DataValidation(
        type="list", formula1=f'"{role_list}"', allow_blank=True, errorStyle="warning",
        errorTitle="Vai trò lạ",
        error="Không có trong danh sách vai trò. Nếu cần gán nhiều vai trò cho"
              " một người, gõ tay cách nhau bởi | (ví dụ: recruiter|manager).",
    )
    sheet.add_data_validation(validation)
    validation.add(f"C2:C{BULK_USER_MAX_ROWS + 1}")

    login_validation = DataValidation(
        type="list", formula1='"local,otp"', allow_blank=False,
        errorStyle="stop", errorTitle="Loại đăng nhập không hợp lệ",
        error="Chọn local (mật khẩu) hoặc otp (mã qua email).",
    )
    sheet.add_data_validation(login_validation)
    login_validation.add(f"D2:D{BULK_USER_MAX_ROWS + 1}")

    sheet["G1"] = "Mã vai trò"
    sheet["H1"] = "Tên hiển thị"
    for offset, key in enumerate(roles.ALL_ROLES):
        sheet[f"G{offset + 2}"] = key
        sheet[f"H{offset + 2}"] = roles.ROLE_LABELS[key]
    note_row = len(roles.ALL_ROLES) + 3
    sheet[f"G{note_row}"] = "Nhiều vai trò: cách nhau bởi | (vd: recruiter|manager)"
    sheet[f"G{note_row + 1}"] = "Bỏ trống vai_tro nếu chưa muốn gán vai trò nào"
    sheet[f"G{note_row + 2}"] = "loai_dang_nhap bắt buộc: local (mật khẩu) hoặc otp (mã email)"
    sheet[f"G{note_row + 3}"] = "otp: username phải là email thuộc domain đã khai ở tab Email OTP"

    widths = {"A": 30, "B": 24, "C": 22, "D": 20, "G": 18, "H": 34}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width

    buf = io.BytesIO()
    workbook.save(buf)
    response = HttpResponse(
        buf.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = 'attachment; filename="mau_tao_tai_khoan.xlsx"'
    return response


def _bulk_rows_from_xlsx(uploaded_file):
    """Đọc các dòng dữ liệu thật từ file .xlsx — bỏ dòng tiêu đề và dòng trống.

    Chỉ đọc 4 cột đầu (A:D) — bảng tra vai trò ở cột G/H trong file mẫu không
    lọt vào đây. Cùng cách chống zip-bomb với talent/attachment_text.py: .xlsx
    là một file zip, phải giới hạn dung lượng SAU GIẢI NÉN trước khi mở bằng
    openpyxl, không thì một file nén cố ý ác ý làm nghẽn tiến trình.
    """
    uploaded_file.seek(0)
    try:
        with zipfile.ZipFile(uploaded_file) as archive:
            if sum(item.file_size for item in archive.infolist()) > BULK_USER_MAX_ARCHIVE_BYTES:
                raise ValueError("Tệp sau giải nén vượt quá giới hạn an toàn.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Không phải file .xlsx hợp lệ.") from exc
    uploaded_file.seek(0)

    from openpyxl import load_workbook
    workbook = load_workbook(uploaded_file, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    data_rows = []
    for row in sheet.iter_rows(min_row=2, max_col=4, values_only=True):
        cells = ["" if value is None else str(value).strip() for value in row]
        if any(cells):
            data_rows.append(cells)
    workbook.close()
    return data_rows


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def user_bulk_create(request):
    """Tạo hàng loạt tài khoản từ file .xlsx tải lên (đúng khuôn `user_bulk_template`).

    Mỗi dòng một kết quả riêng — cùng nguyên tắc với edge_sync (core/views.py):
    một dòng gõ sai (tên trùng, vai trò không tồn tại) không được phép làm hỏng
    cả lô, người quản trị chỉ cần sửa lại đúng dòng đó rồi tải lại.

    Mật khẩu KHÔNG nằm trong file — tự sinh ngẫu nhiên và trả về đúng một lần
    trong kết quả, giống EdgeApiKey.issue(): không ai nên gõ mật khẩu thật vào
    một file Excel có thể bị lưu lại hay gửi lung tung.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    uploaded = request.FILES.get("file")
    if uploaded is None:
        return Response({"detail": "Thiếu file để tải lên."}, status=status.HTTP_400_BAD_REQUEST)

    try:
        rows = _bulk_rows_from_xlsx(uploaded)
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

    if not rows:
        return Response({"detail": "File không có dòng dữ liệu nào."},
                        status=status.HTTP_400_BAD_REQUEST)
    if len(rows) > BULK_USER_MAX_ROWS:
        return Response(
            {"detail": f"File có {len(rows)} dòng, tối đa {BULK_USER_MAX_ROWS} mỗi lần."},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    roles.ensure_groups()
    seen_in_file = set()
    results = []
    for line_no, row in enumerate(rows, start=2):  # dòng 1 là tiêu đề
        username = str(row[0]).strip() if len(row) > 0 else ""
        full_name = str(row[1]).strip() if len(row) > 1 else ""
        raw_roles = str(row[2]).strip() if len(row) > 2 else ""
        raw_login_type = str(row[3]).strip() if len(row) > 3 and row[3] is not None else ""
        login_type, login_error = _clean_login_type(raw_login_type)
        role_names = [r.strip() for r in raw_roles.split("|") if r.strip()]

        if not username:
            results.append({"row": line_no, "username": "", "status": "rejected",
                            "detail": "Thiếu tên đăng nhập."})
            continue
        if username.lower() in seen_in_file:
            results.append({"row": line_no, "username": username, "status": "rejected",
                            "detail": "Trùng tên đăng nhập với một dòng khác trong cùng file."})
            continue
        unknown_roles = [r for r in role_names if r not in roles.ALL_ROLES]
        if unknown_roles:
            results.append({"row": line_no, "username": username, "status": "rejected",
                            "detail": f"Vai trò không tồn tại: {', '.join(unknown_roles)}"})
            continue
        if not raw_login_type:
            results.append({"row": line_no, "username": username, "status": "rejected",
                            "detail": "Thiếu loại đăng nhập (local hoặc otp)."})
            continue
        if login_error:
            results.append({"row": line_no, "username": username, "status": "rejected",
                            "detail": login_error})
            continue
        # Cùng quy tắc với tạo tay: realm suy theo domain đã khai; dòng otp mà
        # domain chưa khai bị từ chối để cả lô không tạo ra tài khoản chết.
        login_type, type_error = _resolve_create_login_type(username, login_type)
        if type_error:
            results.append({"row": line_no, "username": username, "status": "rejected",
                            "detail": type_error})
            continue
        if login_type != UserLoginPolicy.LOCAL:
            try:
                validate_email(username)
            except CoreValidationError:
                results.append({"row": line_no, "username": username, "status": "rejected",
                                "detail": "Tài khoản Email OTP phải dùng email hợp lệ làm tên đăng nhập."})
                continue
        if _duplicate_account_conflict(username):
            results.append({"row": line_no, "username": username, "status": "rejected",
                            "detail": "Đã có tài khoản dùng tên đăng nhập hoặc email này."})
            continue

        seen_in_file.add(username.lower())
        # 16 ký tự ngẫu nhiên (secrets.token_urlsafe) — dài và ngẫu nhiên hơn
        # nhiều so với ngưỡng validate_password, không cần thử lại.
        raw_password = (secrets.token_urlsafe(12)
                        if login_type == UserLoginPolicy.LOCAL else "")
        with transaction.atomic():
            user = User.objects.create_user(username, password=raw_password or None,
                                            first_name=full_name,
                                            email=username if login_type != UserLoginPolicy.LOCAL else "")
            UserLoginPolicy.objects.create(user=user, login_type=login_type)
            if role_names:
                user.groups.set(Group.objects.filter(name__in=role_names))

        results.append({"row": line_no, "username": username, "full_name": full_name,
                        "status": "created", "password": raw_password,
                        "roles": role_names, "login_type": login_type})

    created = sum(1 for r in results if r["status"] == "created")
    return Response({"created": created, "total": len(results), "results": results})


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def user_detail(request, user_id):
    """Sửa tài khoản: tên, khoá/mở, vai trò, đặt lại mật khẩu. Không xoá.

    Không xoá vì giống `Interaction.actor` (xem docs/ACCESS_CONTROL.md) — tài
    khoản có thể đứng tên trong AccessLog/Interaction của nhiều năm trước; xoá
    mất tài khoản là mất luôn khả năng tra lại "ai đã làm việc này". Khoá tài
    khoản (`is_active=False`) đạt cùng mục đích nghiệp vụ mà không xoá vết.
    """
    denied = _require_admin(request)
    if denied:
        return denied

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response({"detail": "Không có tài khoản này."},
                        status=status.HTTP_404_NOT_FOUND)

    data = request.data
    role_names = None
    if "roles" in data:
        role_names, error = _clean_roles(data.get("roles"))
        if error:
            return Response({"detail": error}, status=status.HTTP_400_BAD_REQUEST)
    current_login_type = UserLoginPolicy.type_of(user)
    requested_login_type = current_login_type
    auth_changes = []
    if "login_type" in data:
        requested_login_type, login_error = _clean_login_type(data.get("login_type"))
        if login_error:
            return Response({"detail": login_error}, status=status.HTTP_400_BAD_REQUEST)
        if requested_login_type == "otp":
            # Sửa tài khoản: tôn trọng lựa chọn của admin, chỉ suy realm từ domain
            # email hiện có — KHÔNG ép ngược tài khoản local về OTP như lúc tạo.
            realm = EmailOtpSettings.current().realm_for_email(user.email or user.username)
            if not realm:
                return Response(
                    {"detail": "Email của tài khoản này chưa thuộc domain Email OTP nào. "
                               "Khai domain ở tab Email OTP trước."},
                    status=status.HTTP_400_BAD_REQUEST)
            requested_login_type = realm
        if requested_login_type == UserLoginPolicy.LOCAL and current_login_type != UserLoginPolicy.LOCAL:
            if not data.get("password"):
                return Response(
                    {"detail": "Chuyển sang tài khoản thường phải đặt mật khẩu mới."},
                    status=status.HTTP_400_BAD_REQUEST)
        if requested_login_type != current_login_type:
            auth_changes.append(f"login_type:{current_login_type}->{requested_login_type}")
    if "full_name" in data:
        user.first_name = str(data.get("full_name") or "").strip()
    _preference, preference_error = _save_preference(user, data)
    if preference_error:
        return Response({"detail": preference_error}, status=status.HTTP_400_BAD_REQUEST)
    if "is_active" in data:
        if user.pk == request.user.pk and not data["is_active"]:
            return Response({"detail": "Không thể tự khoá tài khoản của chính mình."},
                            status=status.HTTP_400_BAD_REQUEST)
        new_active = bool(data["is_active"])
        if new_active != user.is_active:
            auth_changes.append(f"is_active:{user.is_active}->{new_active}")
        user.is_active = new_active
    if data.get("password"):
        try:
            validate_password(str(data["password"]), user=user)
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        user.set_password(str(data["password"]))
        auth_changes.append("password:reset")
    if requested_login_type != UserLoginPolicy.LOCAL:
        user.set_unusable_password()
    user.save()
    UserLoginPolicy.objects.update_or_create(
        user=user, defaults={"login_type": requested_login_type})

    if requested_login_type != current_login_type:
        ExternalIdentity.objects.filter(
            user=user, revoked_at__isnull=True).exclude(realm=requested_login_type).update(
                revoked_at=timezone.now(), revoked_by=request.user,
                revoke_reason=f"Đổi loại đăng nhập {current_login_type} -> {requested_login_type}")

    if "roles" in data:
        roles.ensure_groups()
        user.groups.set(Group.objects.filter(name__in=(role_names or [])))

    if auth_changes:
        _record_auth_event(request, "account_auth_policy_changed", user=user,
                           actor=request.user, realm=requested_login_type,
                           detail="; ".join(auth_changes))
        _revoke_user_sessions(user)

    return Response(_user_row(user))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def contact_unlock(request, person_id):
    """Mở khoá thông tin liên hệ đầy đủ của một người (Master Plan mục 27).

    Đây là **cửa duy nhất** trong hệ thống trả về email/SĐT chưa che. Mọi API
    danh sách đều che vô điều kiện (xem `accounts/privacy.py`), nên không có
    đường vòng nào lấy được liên hệ hàng loạt mà không đi qua đúng chỗ này —
    nơi có đếm hạn mức và có ghi vết.

    Yêu cầu vai trò nghiệp vụ, không chỉ "đã đăng nhập": tài khoản chỉ vào được
    trang vận hành không có lý do gì để lấy số điện thoại của ứng viên.
    """
    from people.models import Person

    from . import privacy

    allowed = {roles.RECRUITER, roles.RB_SALES, roles.MANAGER, roles.ADMIN,
               roles.HIRING_MANAGER}
    if not (roles.roles_of(request.user) & allowed):
        return Response({"detail": "Vai trò của bạn không được xem thông tin liên hệ."},
                        status=status.HTTP_403_FORBIDDEN)

    person = Person.objects.filter(pk=person_id, merged_into__isnull=True).first()
    if person is None:
        return Response({"detail": "Không tìm thấy hồ sơ."},
                        status=status.HTTP_404_NOT_FOUND)

    domain = str(request.data.get("domain") or "")
    if domain not in {"", "talent", "rb"}:
        return Response({"detail": "Nghiệp vụ không hợp lệ."},
                        status=status.HTTP_400_BAD_REQUEST)

    try:
        contact, left, charged = privacy.unlock(
            request.user, person, domain=domain,
            ip=request.META.get("REMOTE_ADDR", ""))
    except privacy.QuotaExceeded as exceeded:
        # 429 chứ không 403: người dùng KHÔNG bị cấm, họ chỉ hết lượt hôm nay.
        # Trả 403 sẽ khiến họ tưởng mình mất quyền và đi hỏi quản trị viên.
        return Response(
            {"detail": "Bạn đã dùng hết hạn mức mở khoá liên hệ hôm nay.",
             "used": exceeded.used, "limit": exceeded.limit},
            status=status.HTTP_429_TOO_MANY_REQUESTS)

    return Response({**contact, "remaining": left, "charged": charged})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def contact_unlock_quota(request):
    """Hạn mức mở khoá còn lại hôm nay, để giao diện hiện trước khi người dùng bấm."""
    from . import privacy

    return Response({
        "limit": privacy.quota_for(request.user),
        "used": privacy.used_today(request.user),
        "remaining": privacy.remaining(request.user),
    })
