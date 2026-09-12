# -*- coding: utf-8 -*-
"""Xác thực Edge bằng khoá API.

Edge không phải người dùng Django: nó không có tài khoản, không có phiên, và
không được vào trang quản trị. Vì vậy request.user vẫn là None còn Edge đã xác
thực nằm ở request.auth — đúng ngữ nghĩa DRF cho khoá máy-với-máy.
"""
from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import EdgeApiKey, hash_api_key

HEADER_PREFIX = "Bearer "
EDGE_ID_HEADER = "HTTP_X_EDGE_ID"

# Chỉ cập nhật last_used_at khi đã đủ cũ. Một lượt đồng bộ là hàng chục yêu cầu;
# ghi vào cùng một hàng mỗi lần là tự tạo điểm nghẽn mà chẳng để làm gì.
LAST_USED_RESOLUTION_SECONDS = 60


class EdgeAuth:
    """Kết quả xác thực đặt vào request.auth."""

    def __init__(self, edge, api_key):
        self.edge = edge
        self.api_key = api_key

    def __str__(self):
        return f"Edge<{self.edge.label}>"


class EdgeApiKeyAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if not header.startswith(HEADER_PREFIX):
            # Không phải khoá Edge. Trả None để DRF thử tiếp lớp xác thực khác
            # (phiên đăng nhập cho trang quản trị).
            return None

        raw_key = header[len(HEADER_PREFIX):].strip()
        if not raw_key:
            raise exceptions.AuthenticationFailed("Thiếu khoá API.")

        try:
            api_key = (EdgeApiKey.objects
                       .select_related("edge")
                       .get(key_hash=hash_api_key(raw_key)))
        except EdgeApiKey.DoesNotExist:
            # Cùng một thông báo cho khoá sai và khoá đã thu hồi: đừng cho bên
            # gọi biết khoá của họ từng tồn tại.
            raise exceptions.AuthenticationFailed("Khoá API không hợp lệ.")

        if not api_key.is_active:
            raise exceptions.AuthenticationFailed("Khoá API không hợp lệ.")
        if not api_key.edge.is_active:
            raise exceptions.AuthenticationFailed("Edge này đã bị vô hiệu hoá.")

        self._touch(api_key)
        return (None, EdgeAuth(api_key.edge, api_key))

    def authenticate_header(self, request):
        """Có hàm này thì lỗi mới là 401 thay vì 403."""
        return self.keyword

    @staticmethod
    def _touch(api_key):
        now = timezone.now()
        if (api_key.last_used_at is None
                or (now - api_key.last_used_at).total_seconds() >= LAST_USED_RESOLUTION_SECONDS):
            api_key.last_used_at = now
            api_key.save(update_fields=["last_used_at"])


def require_edge(request):
    """Lấy Edge đã xác thực, hoặc báo lỗi rõ ràng.

    Dùng ở view thay vì tin rằng permission class đã lọc: một permission class
    bị khai sót sẽ để lọt request.auth là None, và AttributeError lúc chạy là
    cách tệ nhất để phát hiện điều đó.
    """
    auth = getattr(request, "auth", None)
    if not isinstance(auth, EdgeAuth):
        raise exceptions.NotAuthenticated("Cần xác thực bằng khoá API của Edge.")
    return auth.edge
