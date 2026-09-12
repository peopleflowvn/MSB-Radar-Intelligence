# -*- coding: utf-8 -*-
"""Nhận diện thương hiệu — nguồn sự thật DUY NHẤT cho thẻ meta, manifest và API.

Trước đây thẻ `og:*` / `twitter:*` nằm cứng trong `web/index.html`, cố định lúc
build. Hai hệ quả:

* muốn đổi ảnh xem trước phải sửa mã và triển khai lại;
* không thể đổi từ `/settings`, nên cấu hình "đồng nhất cho mọi người" là không
  thể — mỗi người xem bản HTML của lần build gần nhất họ tải về.

**Vì sao phải render ở máy chủ, không phải bằng JavaScript như favicon.**
Trình thu thập của Zalo, Facebook, Slack, Telegram… đọc HTML **thô** và không
chạy JavaScript. Favicon đổi bằng JS thì được (trình duyệt có chạy JS), nhưng
ảnh xem trước liên kết thì không: crawler chỉ thấy thẻ có sẵn trong HTML trả về.
Nên `index.html` phải đi qua Django để chèn thẻ từ CSDL.
"""
from __future__ import annotations

import html
import json

DEFAULT_NAME = "MSB Radar"
DEFAULT_TAGLINE = "Hệ Thống Tìm Kiếm Nhân Tài & Tăng Trưởng Khách Hàng"
DEFAULT_OG_IMAGE = "/og-image.png"


def _clean(value, fallback=""):
    return " ".join(str(value or "").split()) or fallback


def link_preview(config):
    """Mọi giá trị dùng để dựng thẻ meta, đã điền sẵn phần suy ra.

    Trường rỗng nghĩa là "suy ra từ tên và tagline", không phải "để trống": người
    vận hành đổi tên ứng dụng thì tiêu đề xem trước phải theo, mà không phải đi
    sửa thêm ba ô nữa.
    """
    name = _clean(config.from_name, DEFAULT_NAME)
    tagline = _clean(config.app_tagline, DEFAULT_TAGLINE)
    title = _clean(config.og_title) or f"{name} Hub | {tagline}"
    description = _clean(config.og_description) or tagline
    return {
        "app_name": name,
        "app_tagline": tagline,
        "title": title,
        "description": description,
        "site_name": _clean(config.og_site_name) or f"{name} Hub",
        "image": _clean(config.og_image_url, DEFAULT_OG_IMAGE),
        "image_alt": _clean(config.og_image_alt) or title,
        "image_width": int(config.og_image_width or 1200),
        "image_height": int(config.og_image_height or 630),
        "keywords": _clean(config.meta_keywords),
        "robots": _clean(config.meta_robots, "index, follow"),
        "theme_color": _clean(config.custom_color, "#FF8A33"),
        "background_color": _clean(config.pwa_background_color, "#0F172A"),
        "short_name": _clean(config.pwa_short_name) or name,
        "logo_url": _clean(config.app_logo_url),
        "icon": _clean(config.app_icon, "⚡"),
    }


def _tag(*parts):
    return "    " + "".join(parts)


def meta_tags(preview, *, base_url=""):
    """Khối thẻ meta hoàn chỉnh, đã escape, sẵn sàng chèn vào `<head>`.

    `base_url` biến đường dẫn tương đối thành tuyệt đối: crawler mạng xã hội đòi
    `og:image` là URL đầy đủ, đường dẫn tương đối bị bỏ qua âm thầm — ảnh xem
    trước "không hiện" mà không có lỗi nào để lần theo.
    """
    def esc(value):
        return html.escape(str(value or ""), quote=True)

    image = preview["image"]
    if base_url and image.startswith("/"):
        image = base_url.rstrip("/") + image

    lines = [
        f'<title>{esc(preview["title"])}</title>',
        _tag(f'<meta name="title" content="{esc(preview["title"])}" />'),
        _tag(f'<meta name="description" content="{esc(preview["description"])}" />'),
    ]
    if preview["keywords"]:
        lines.append(_tag(f'<meta name="keywords" content="{esc(preview["keywords"])}" />'))
    lines += [
        _tag(f'<meta name="robots" content="{esc(preview["robots"])}" />'),
        _tag(f'<meta name="theme-color" content="{esc(preview["theme_color"])}" />'),

        _tag('<meta property="og:type" content="website" />'),
        _tag(f'<meta property="og:site_name" content="{esc(preview["site_name"])}" />'),
        _tag(f'<meta property="og:title" content="{esc(preview["title"])}" />'),
        _tag(f'<meta property="og:description" content="{esc(preview["description"])}" />'),
        _tag(f'<meta property="og:image" content="{esc(image)}" />'),
        _tag(f'<meta property="og:image:secure_url" content="{esc(image)}" />'),
        _tag(f'<meta property="og:image:width" content="{preview["image_width"]}" />'),
        _tag(f'<meta property="og:image:height" content="{preview["image_height"]}" />'),
        _tag(f'<meta property="og:image:alt" content="{esc(preview["image_alt"])}" />'),
        _tag('<meta property="og:locale" content="vi_VN" />'),

        _tag('<meta name="twitter:card" content="summary_large_image" />'),
        _tag(f'<meta name="twitter:title" content="{esc(preview["title"])}" />'),
        _tag(f'<meta name="twitter:description" content="{esc(preview["description"])}" />'),
        _tag(f'<meta name="twitter:image" content="{esc(image)}" />'),
        _tag(f'<meta name="twitter:image:alt" content="{esc(preview["image_alt"])}" />'),
    ]
    return "\n".join(lines)


def manifest(preview):
    """`site.webmanifest` dựng từ CSDL — biểu tượng khi cài lên màn hình chính."""
    icons = []
    if preview["logo_url"]:
        icons.append({"src": preview["logo_url"], "sizes": "any",
                      "purpose": "any maskable"})
    icons += [
        {"src": "/favicon-32x32.png", "sizes": "32x32", "type": "image/png"},
        {"src": "/favicon-16x16.png", "sizes": "16x16", "type": "image/png"},
        {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
        {"src": "/favicon.svg", "sizes": "any", "type": "image/svg+xml",
         "purpose": "any maskable"},
    ]
    return json.dumps({
        "name": preview["site_name"],
        "short_name": preview["short_name"],
        "description": preview["description"],
        "start_url": "/",
        "display": "standalone",
        "background_color": preview["background_color"],
        "theme_color": preview["theme_color"],
        "icons": icons,
    }, ensure_ascii=False, indent=2)
