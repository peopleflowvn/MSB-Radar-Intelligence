# -*- coding: utf-8 -*-
"""Mô tả cách xác thực cho tài liệu API tự sinh (drf-spectacular).

Không có file này, Swagger vẫn hoạt động nhưng không biết diễn giải
`EdgeApiKeyAuthentication` là gì — kết quả là trang tài liệu thiếu đúng phần
quan trọng nhất với người đọc từ bên ngoài: **gọi endpoint của Edge thì xác
thực bằng cách nào**.
"""
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class EdgeApiKeyScheme(OpenApiAuthenticationExtension):
    target_class = "core.auth.EdgeApiKeyAuthentication"
    name = "EdgeApiKeyAuth"

    def get_security_definition(self, auto_schema):
        return {
            "type": "http",
            "scheme": "bearer",
            "description": (
                "Dành cho các endpoint bắt đầu bằng `/api/v1/edge/...` — nơi "
                "ứng dụng Edge (chạy trên máy nhân viên) đồng bộ dữ liệu lên. "
                "Khoá được quản trị viên Hub cấp cho từng bản cài Edge (trang "
                "Quản trị → Edge → «Cấp khoá API mới», hoặc "
                "`POST /api/v1/edge-admin/edges/<id>/keys/`), hiện **đúng một "
                "lần** lúc cấp — Hub chỉ lưu bản băm, không có cách nào đọc lại "
                "khoá thô sau đó.\n\n"
                "Header bắt buộc kèm theo:\n"
                "```\n"
                "Authorization: Bearer <api_key>\n"
                "X-Edge-Id: <mã Edge do chính ứng dụng Edge tự sinh>\n"
                "```\n"
                "`X-Edge-Id` không phải một bí mật thứ hai — Hub xác định Edge "
                "nào qua khoá (so bản băm), không tin giá trị header này để "
                "phân quyền. Nó chỉ dùng để đối chiếu Edge tự xưng có khớp với "
                "Edge đã đăng ký cho khoá đó không."
            ),
        }
