# -*- coding: utf-8 -*-
"""Tải lên và phục vụ ảnh thumbnail (og:image).

Khác biểu tượng/logo — thứ được nhúng thẳng vào CSDL dưới dạng `data:` URI:
**`og:image` KHÔNG dùng được `data:` URI.** Trình thu thập của Zalo, Facebook,
Slack… đòi một URL http(s) thật để tải ảnh về; đưa `data:` URI vào thì chúng bỏ
qua âm thầm — đúng lỗi "ảnh không hiện mà không có gì để lần theo".

Nên ảnh phải nằm ở kho lưu trữ (R2 trên production) và được phục vụ qua một URL
thật. Khoá lưu suy ra từ nội dung ảnh: tải lại đúng ảnh cũ không tạo bản trùng,
và đổi ảnh thì URL đổi theo nên không dính cache của trình duyệt.
"""
from __future__ import annotations

import hashlib
import io
import logging

from core.storage import StorageError, get_storage
from django.http import HttpResponse
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import roles

log = logging.getLogger(__name__)

KEY_PREFIX = "branding"
MAX_BYTES = 5 * 1024 * 1024
#: Chỉ nhận ảnh raster để chèn og:image — SVG thì nhiều nền tảng không dựng
#: thumbnail được, và cũng là một véc-tơ chèn mã.
_MIME_EXT = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
#: Nhỏ hơn mức này thì ảnh xem trước hiện rất tệ; Facebook/Zalo bỏ qua ảnh dưới
#: 200×200.
MIN_SIDE = 200


@api_view(["POST"])
@permission_classes([AllowAny])
def upload_og_image(request):
    """Nhận một tệp ảnh, lưu vào kho, trả URL + kích thước thật.

    `AllowAny` ở decorator nhưng tự kiểm quyền admin bên dưới — giữ đúng khuôn
    của `public_settings` trong cùng app (DRF auth cho phiên cookie chưa chắc
    chạy trước decorator ở mọi cấu hình).
    """
    if not request.user or not request.user.is_authenticated:
        return Response({"detail": "Cần đăng nhập quản trị viên."},
                        status=status.HTTP_401_UNAUTHORIZED)
    if not roles.can_access(request.user, roles.MODULE_ADMIN):
        return Response({"detail": "Chỉ quản trị viên được tải ảnh thumbnail."},
                        status=status.HTTP_403_FORBIDDEN)

    upload = request.FILES.get("file")
    if upload is None:
        return Response({"detail": "Chưa chọn tệp."}, status=400)
    if upload.size > MAX_BYTES:
        return Response({"detail": "Ảnh vượt quá 5MB."}, status=400)

    data = upload.read()

    # Xác thực bằng cách MỞ ảnh, không tin `content_type` do trình duyệt gửi.
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            pil_format = (image.format or "").lower()
    except Exception:                              # noqa: BLE001
        return Response({"detail": "Tệp không phải ảnh hợp lệ."}, status=400)

    mime = {"jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp",
            "gif": "image/gif"}.get(pil_format)
    if mime is None:
        return Response(
            {"detail": "Chỉ nhận PNG, JPG, WebP hoặc GIF cho ảnh xem trước."},
            status=400)
    if width < MIN_SIDE or height < MIN_SIDE:
        return Response(
            {"detail": f"Ảnh quá nhỏ ({width}×{height}). Tối thiểu "
                       f"{MIN_SIDE}×{MIN_SIDE}px; khuyến nghị 1200×630px."},
            status=400)

    digest = hashlib.sha256(data).hexdigest()
    key = f"{KEY_PREFIX}/{digest[:24]}.{_MIME_EXT[mime]}"
    try:
        get_storage().save(key, data)
    except StorageError as exc:
        log.error("branding: lưu ảnh thumbnail hỏng: %s", exc)
        return Response({"detail": "Không lưu được ảnh, thử lại sau."}, status=502)

    return Response({
        "url": f"/media/{key}",
        "width": width,
        "height": height,
        "bytes": len(data),
    })


#: Bộ nhớ đệm trong tiến trình — ảnh thumbnail đổi vài tháng một lần, còn crawler
#: có thể gọi liên tục. Khoá theo nội dung nên không bao giờ trả nhầm ảnh.
_CACHE: dict[str, tuple[bytes, str]] = {}


def serve_media(request, key):
    """Phục vụ ảnh đã tải lên. Công khai — crawler mạng xã hội không đăng nhập."""
    key = str(key or "")
    if ".." in key or not key.startswith(KEY_PREFIX + "/"):
        return HttpResponse(status=404)

    cached = _CACHE.get(key)
    if cached is None:
        try:
            data = get_storage().read(key)
        except StorageError:
            return HttpResponse(status=404)
        ext = key.rsplit(".", 1)[-1].lower()
        content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                        "webp": "image/webp", "gif": "image/gif"}.get(ext,
                                                                      "application/octet-stream")
        _CACHE[key] = cached = (data, content_type)

    data, content_type = cached
    response = HttpResponse(data, content_type=content_type)
    # Khoá suy ra từ nội dung, nên URL này bất biến — cache thoải mái một năm.
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    return response
