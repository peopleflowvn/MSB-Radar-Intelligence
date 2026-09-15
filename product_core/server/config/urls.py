# -*- coding: utf-8 -*-
from accounts import branding_assets, spa_views
from django.contrib import admin
from django.urls import include, path, re_path
from drf_spectacular.views import (SpectacularAPIView, SpectacularRedocView,
                                   SpectacularSwaggerView)
from rest_framework.permissions import AllowAny

urlpatterns = [
    path("admin/", admin.site.urls),

    # Công khai HÌNH DẠNG api (endpoint, tham số, khuôn dữ liệu) mà không cần
    # đăng nhập — một doanh nghiệp đang cân nhắc tích hợp cần đọc được tài liệu
    # trước khi có tài khoản. "Thử gọi thật" trong Swagger vẫn phải qua đúng xác
    # thực của từng endpoint (Bearer key cho Edge, phiên đăng nhập cho phần
    # còn lại) — trang tài liệu chỉ MIỄN đăng nhập để XEM, không miễn xác thực
    # để GỌI.
    path("api/v1/schema/",
         SpectacularAPIView.as_view(permission_classes=[AllowAny]),
         name="api-schema"),
    path("api/v1/docs/",
         SpectacularSwaggerView.as_view(url_name="api-schema",
                                        permission_classes=[AllowAny]),
         name="api-docs"),
    path("api/v1/docs/redoc/",
         SpectacularRedocView.as_view(url_name="api-schema",
                                      permission_classes=[AllowAny]),
         name="api-docs-redoc"),

    path("api/v1/auth/", include("accounts.urls")),
    path("api/v1/", include("core.urls")),
    path("api/v1/ai/", include("ai.urls")),
    path("api/v1/intel/", include("intel.urls")),
    path("api/v1/knowledge/", include("knowledge.urls")),
    path("api/v1/talent/", include("talent.urls")),
    path("api/v1/intake/", include("intake.urls")),
    path("api/v1/hiring/", include("hiring.urls")),
    path("api/v1/social/", include("social.urls")),
    path("api/v1/rb/", include("rb.urls")),
    path("api/v1/reports/", include("reports.urls")),

    # Phục vụ tệp media tải lên (thumbnail og:image, tài liệu).
    path("media/<path:key>", branding_assets.serve_media, name="media-serve"),

    # Manifest dựng từ CSDL, không phải tệp tĩnh trong `web/public`.
    path("site.webmanifest", spa_views.webmanifest, name="webmanifest"),
]

# Vỏ HTML của giao diện — ĐẶT CUỐI CÙNG vì nó bắt mọi đường dẫn còn lại.
#
# Caddy đã trả thẳng mọi tệp có thật (`assets/*`, ảnh, font); chỉ những đường dẫn
# KHÔNG khớp tệp nào mới tới đây, tức các route của React Router. Django chèn thẻ
# meta từ CSDL vào đó — crawler mạng xã hội không chạy JavaScript nên ảnh xem
# trước phải nằm sẵn trong HTML (xem `accounts/branding.py`).
urlpatterns += [re_path(r"^(?!api/|admin/|static/|media/).*$", spa_views.spa_index,
                        name="spa-index")]
