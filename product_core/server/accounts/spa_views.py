# -*- coding: utf-8 -*-
"""Phục vụ vỏ HTML của giao diện, có thẻ meta lấy từ CSDL.

Vì sao Django phải đụng vào việc này thay vì để Caddy trả tệp tĩnh: xem docstring
của `accounts/branding.py`. Tóm lại — crawler mạng xã hội không chạy JavaScript,
nên ảnh xem trước liên kết phải nằm sẵn trong HTML trả về.

Chỉ VỎ HTML đi qua đây. Toàn bộ `assets/*`, ảnh, font… Caddy vẫn trả thẳng, nên
phần nặng của trang không đổi đường.

Kết quả render được cache theo `updated_at` của cấu hình: sửa trong `/settings`
là mục cũ hết hiệu lực ngay, không phải chờ hết hạn.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from django.conf import settings as django_settings
from django.core.cache import cache
from django.http import HttpResponse
from django.views.decorators.cache import never_cache

from . import branding
from .models import EmailOtpSettings

log = logging.getLogger(__name__)

_MARKERS = re.compile(
    r"<!--\s*radar:meta:start\s*-->.*?<!--\s*radar:meta:end\s*-->",
    re.DOTALL)
CACHE_TTL = 3600


def _dist_dir():
    return Path(getattr(django_settings, "WEB_DIST_DIR", "")
                or Path(django_settings.BASE_DIR).parent / "web" / "dist")


def _base_url(request):
    """URL gốc tuyệt đối cho `og:image` — crawler bỏ qua đường dẫn tương đối."""
    configured = getattr(django_settings, "PUBLIC_BASE_URL", "")
    if configured:
        return configured.rstrip("/")
    return f"{request.scheme}://{request.get_host()}"


def _config_stamp(config):
    """Vân tay của CHÍNH nội dung thẻ meta, không phải `updated_at`.

    `updated_at` (auto_now) chỉ mịn tới độ phân giải đồng hồ hệ điều hành —
    trên Windows là ~15ms. Hai lần lưu trong cùng một tick cho ra cùng dấu thời
    gian, nên lần sửa thứ hai không làm hết hiệu lực cache và người vận hành
    thấy giá trị cũ. Test bắt được đúng chuyện này khi chạy cả lớp.

    Băm nội dung thì không phụ thuộc đồng hồ: nội dung đổi là khoá đổi.
    """
    preview = branding.link_preview(config)
    blob = json.dumps(preview, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def _build_stamp():
    """Vân tay của bản build giao diện đang nằm trên đĩa.

    `_config_stamp` chỉ băm cấu hình branding — KHÔNG đổi khi deploy chỉ thay
    `web/dist`. Thiếu phần này thì sau mỗi lần deploy, Django phục vụ `index.html`
    CŨ trong cache (TTL 1 giờ) trỏ tới bundle của lần deploy trước, và người
    dùng chạy mã cũ mất tới một tiếng dù đã deploy xong (đúng lỗi 05/09:
    preamble + nối lại kết nối mobile không hiện dù đã live).

    Băm nội dung `index.html` (chứa tên bundle có hash) — build mới là khoá đổi.
    """
    path = _dist_dir() / "index.html"
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return "no-build"


def _render(request, config):
    path = _dist_dir() / "index.html"
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        log.error("spa: không đọc được %s: %s", path, exc)
        return None
    preview = branding.link_preview(config)
    block = ("    <!-- radar:meta:start -->\n"
             + branding.meta_tags(preview, base_url=_base_url(request))
             + "\n    <!-- radar:meta:end -->")
    if not _MARKERS.search(raw):
        # Không có mốc thì trả nguyên bản: thà dùng thẻ tĩnh của bản build còn
        # hơn đoán chỗ chèn rồi làm hỏng HTML.
        log.warning("spa: index.html thiếu mốc radar:meta, trả nguyên bản")
        return raw
    return _MARKERS.sub(lambda _m: block, raw, count=1)


@never_cache
def spa_index(request, *args, **kwargs):
    """Vỏ HTML cho mọi route của giao diện."""
    config = EmailOtpSettings.current()
    key = (f"spa:index:v2:{_build_stamp()}:{_config_stamp(config)}"
           f":{request.get_host()}")
    body = None
    try:
        body = cache.get(key)
    except Exception:                              # noqa: BLE001
        body = None
    if body is None:
        body = _render(request, config)
        if body is None:
            return HttpResponse(
                "Giao diện chưa được dựng (thiếu web/dist/index.html).",
                status=503, content_type="text/plain; charset=utf-8")
        try:
            cache.set(key, body, CACHE_TTL)
        except Exception:                          # noqa: BLE001
            pass
    response = HttpResponse(body, content_type="text/html; charset=utf-8")
    # Vỏ HTML phải luôn tươi: nó chứa đường dẫn tới bundle có hash, nên cache nó
    # ở trình duyệt là cách chắc chắn nhất để người dùng chạy bản cũ sau deploy.
    response["Cache-Control"] = "no-store, must-revalidate"
    return response


def webmanifest(request):
    """`site.webmanifest` dựng từ CSDL thay vì tệp tĩnh trong `web/public`."""
    preview = branding.link_preview(EmailOtpSettings.current())
    response = HttpResponse(branding.manifest(preview),
                            content_type="application/manifest+json")
    response["Cache-Control"] = "public, max-age=300"
    return response
