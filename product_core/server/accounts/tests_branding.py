# -*- coding: utf-8 -*-
"""Thumbnail / xem trước liên kết — cấu hình ở CSDL, máy chủ chèn vào HTML.

Điểm mấu chốt được canh ở đây: thẻ meta phải nằm SẴN trong HTML trả về. Trình
thu thập của Zalo/Facebook/Slack không chạy JavaScript, nên nếu ai đó sau này
"tối ưu" bằng cách đổi thẻ ở phía trình duyệt như favicon, ảnh xem trước sẽ đứng
im mà không có lỗi nào để lần ra.
"""
import re

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase, override_settings

from . import branding, roles
from .models import EmailOtpSettings

INDEX_HTML = """<!doctype html>
<html lang="vi">
  <head>
    <meta charset="UTF-8" />
    <!-- radar:meta:start -->
    <title>Ban tinh cu</title>
    <meta property="og:image" content="/cu.png" />
    <!-- radar:meta:end -->
    <link rel="manifest" href="/site.webmanifest" />
  </head>
  <body><div id="root"></div><script src="/assets/app.js"></script></body>
</html>
"""


def _dist(tmp):
    (tmp / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    return str(tmp)


class LinkPreviewDerivationTest(TestCase):
    def test_bo_trong_thi_suy_ra_tu_ten_va_tagline(self):
        """Trống nghĩa là "suy ra", không phải "để trắng": đổi tên hệ thống thì
        tiêu đề xem trước phải theo, không phải đi sửa thêm ba ô nữa."""
        config = EmailOtpSettings.current()
        config.from_name = "Radar Thử"
        config.app_tagline = "Câu mô tả thử"
        config.save()
        preview = branding.link_preview(config)
        self.assertEqual(preview["title"], "Radar Thử Hub | Câu mô tả thử")
        self.assertEqual(preview["description"], "Câu mô tả thử")
        self.assertEqual(preview["site_name"], "Radar Thử Hub")
        self.assertEqual(preview["image"], branding.DEFAULT_OG_IMAGE)

    def test_gia_tri_tu_dat_thang_gia_tri_suy_ra(self):
        config = EmailOtpSettings.current()
        config.og_title = "Tiêu đề riêng"
        config.og_image_url = "/rieng.png"
        config.save()
        preview = branding.link_preview(config)
        self.assertEqual(preview["title"], "Tiêu đề riêng")
        self.assertEqual(preview["image"], "/rieng.png")

    def test_duong_dan_tuong_doi_thanh_URL_tuyet_doi(self):
        """Crawler bỏ qua đường dẫn tương đối mà không báo lỗi gì."""
        preview = branding.link_preview(EmailOtpSettings.current())
        tags = branding.meta_tags(preview, base_url="https://radar.example.vn/")
        self.assertIn('content="https://radar.example.vn/og-image.png"', tags)
        self.assertNotIn('content="/og-image.png"', tags)

    def test_chu_co_ky_tu_dac_biet_duoc_escape(self):
        config = EmailOtpSettings.current()
        config.og_title = 'Radar "xịn" & <script>alert(1)</script>'
        config.save()
        tags = branding.meta_tags(branding.link_preview(config))
        self.assertNotIn("<script>", tags)
        self.assertIn("&lt;script&gt;", tags)


class SpaShellTest(TestCase):
    def setUp(self):
        cache.clear()

    def _get(self, path="/talent", **kwargs):
        with override_settings(WEB_DIST_DIR=_dist(self._tmp()), **kwargs):
            return self.client.get(path)

    def _tmp(self):
        import tempfile
        from pathlib import Path
        return Path(tempfile.mkdtemp())

    def test_the_meta_nam_san_trong_html_tra_ve(self):
        """Không phải chèn bằng JavaScript — crawler không chạy JS."""
        config = EmailOtpSettings.current()
        config.og_title = "Tiêu đề từ CSDL"
        config.og_image_url = "/tu-csdl.png"
        config.save()
        body = self._get().content.decode()
        self.assertIn("Tiêu đề từ CSDL", body)
        self.assertIn("tu-csdl.png", body)
        self.assertNotIn("Ban tinh cu", body)      # đã thay khối tĩnh
        self.assertNotIn("/cu.png", body)

    def test_giu_nguyen_phan_con_lai_cua_trang(self):
        """Chỉ thay khối giữa hai mốc; bundle và thẻ khác phải còn nguyên."""
        body = self._get().content.decode()
        self.assertIn('<script src="/assets/app.js">', body)
        self.assertIn('<div id="root">', body)
        self.assertIn('rel="manifest"', body)

    def test_thieu_moc_thi_tra_nguyen_ban_khong_doan_cho_chen(self):
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        (tmp / "index.html").write_text("<html><head></head></html>", encoding="utf-8")
        with override_settings(WEB_DIST_DIR=str(tmp)):
            body = self.client.get("/talent").content.decode()
        self.assertEqual(body, "<html><head></head></html>")

    def test_thieu_han_index_thi_bao_503_chu_khong_no(self):
        with override_settings(WEB_DIST_DIR="/khong/ton/tai"):
            response = self.client.get("/talent")
        self.assertEqual(response.status_code, 503)

    def test_vo_html_khong_duoc_cache_o_trinh_duyet(self):
        """Nó chứa đường dẫn bundle có hash — cache là cách chắc chắn nhất để
        người dùng chạy bản cũ sau khi triển khai."""
        response = self._get()
        self.assertIn("no-store", response["Cache-Control"])

    def test_doi_cau_hinh_thi_html_doi_theo_ngay(self):
        """Cache theo `updated_at`, nên sửa trong /settings là hết hiệu lực ngay."""
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        (tmp / "index.html").write_text(INDEX_HTML, encoding="utf-8")
        with override_settings(WEB_DIST_DIR=str(tmp)):
            first = self.client.get("/talent").content.decode()
            config = EmailOtpSettings.current()
            config.og_title = "Tiêu đề đã đổi"
            config.save()
            second = self.client.get("/talent").content.decode()
        self.assertNotIn("Tiêu đề đã đổi", first)
        self.assertIn("Tiêu đề đã đổi", second)

    def test_khong_cau_hinh_thi_lay_host_cua_request(self):
        """Host của request luôn tới được — người dùng vừa truy cập bằng nó.

        Mặc định cứng thì không: `PUBLIC_BASE_URL` từng được đặt sẵn thành
        `https://radar.tunghr.io.vn`, một tên miền KHÔNG có trong DNS công cộng,
        nên og:image trỏ vào chỗ crawler không tới được.
        """
        with override_settings(PUBLIC_BASE_URL=""):
            body = self._get().content.decode()
        self.assertIn('content="http://testserver/og-image.png"', body)

    def test_hai_lan_sua_lien_tiep_deu_co_hieu_luc(self):
        """Khoá cache băm NỘI DUNG, không dùng `updated_at`.

        `auto_now` chỉ mịn tới độ phân giải đồng hồ hệ điều hành (~15ms trên
        Windows). Hai lần lưu trong cùng một tick cho cùng dấu thời gian, nên
        lần sửa thứ hai không làm hết hiệu lực cache và người vận hành thấy giá
        trị cũ — bộ test bắt được đúng chuyện này.
        """
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        (tmp / "index.html").write_text(INDEX_HTML, encoding="utf-8")
        config = EmailOtpSettings.current()
        seen = []
        with override_settings(WEB_DIST_DIR=str(tmp)):
            for title in ("Lần một", "Lần hai", "Lần ba"):
                config.og_title = title
                config.save()
                seen.append(title in self.client.get("/talent").content.decode())
        self.assertEqual(seen, [True, True, True])

    def test_deploy_moi_bundle_moi_thi_vo_html_doi_theo(self):
        """Khoá cache PHẢI gồm vân tay của bản build.

        Deploy thường chỉ thay `web/dist` (bundle mới có hash mới), cấu hình
        branding không đổi → khoá cache CŨ khớp → Django phục vụ index.html cũ
        trỏ tới bundle của lần deploy trước, TỚI MỘT GIỜ. Đúng lỗi 05/09:
        preamble + nối lại kết nối mobile đã live mà người dùng không thấy.
        """
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp())
        v1 = INDEX_HTML.replace("/assets/app.js", "/assets/index-AAAA1111.js")
        v2 = INDEX_HTML.replace("/assets/app.js", "/assets/index-BBBB2222.js")
        with override_settings(WEB_DIST_DIR=str(tmp)):
            (tmp / "index.html").write_text(v1, encoding="utf-8")
            first = self.client.get("/talent").content.decode()
            # Cấu hình KHÔNG đổi — chỉ bundle đổi (mô phỏng một lần deploy).
            (tmp / "index.html").write_text(v2, encoding="utf-8")
            second = self.client.get("/talent").content.decode()
        self.assertIn("index-AAAA1111.js", first)
        self.assertIn("index-BBBB2222.js", second)
        self.assertNotIn("index-AAAA1111.js", second)

    def test_api_khong_bi_nuot_vao_vo_html(self):
        """Route bắt-tất-cả đứng cuối; nó không được nuốt /api/."""
        response = self.client.get("/api/v1/auth/public-settings/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/json", response["Content-Type"])


class WebmanifestTest(TestCase):
    def test_manifest_lay_tu_csdl(self):
        config = EmailOtpSettings.current()
        config.pwa_short_name = "RadarNB"
        config.pwa_background_color = "#123456"
        config.save()
        response = self.client.get("/site.webmanifest")
        self.assertEqual(response.status_code, 200)
        self.assertIn("manifest+json", response["Content-Type"])
        payload = response.json()
        self.assertEqual(payload["short_name"], "RadarNB")
        self.assertEqual(payload["background_color"], "#123456")

    def test_logo_cau_hinh_thanh_bieu_tuong_dau_tien(self):
        config = EmailOtpSettings.current()
        config.app_logo_url = "https://cdn.example/logo.png"
        config.save()
        icons = self.client.get("/site.webmanifest").json()["icons"]
        self.assertEqual(icons[0]["src"], "https://cdn.example/logo.png")


class ThumbnailApiTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.admin = User.objects.create_user("quantri", password="mat-khau-dai-1")
        self.admin.groups.add(Group.objects.get(name=roles.ADMIN))
        self.plain = User.objects.create_user("thuong", password="mat-khau-dai-1")

    def test_admin_luu_duoc_va_gia_tri_xuong_csdl(self):
        self.client.force_login(self.admin)
        response = self.client.patch(
            "/api/v1/auth/public-settings/",
            data={"og_image_url": "/moi.png", "og_title": "Mới",
                  "og_image_width": 800, "meta_robots": "noindex, nofollow"},
            content_type="application/json")
        self.assertEqual(response.status_code, 200)
        config = EmailOtpSettings.current()
        self.assertEqual(config.og_image_url, "/moi.png")
        self.assertEqual(config.og_image_width, 800)
        self.assertEqual(config.meta_robots, "noindex, nofollow")

    def test_kich_thuoc_vo_ly_bi_bo_qua_chu_khong_lam_hong_ca_lan_luu(self):
        self.client.force_login(self.admin)
        self.client.patch("/api/v1/auth/public-settings/",
                          data={"og_image_width": 99999, "og_title": "Vẫn lưu"},
                          content_type="application/json")
        config = EmailOtpSettings.current()
        self.assertEqual(config.og_image_width, 1200)     # giữ mặc định
        self.assertEqual(config.og_title, "Vẫn lưu")      # phần hợp lệ vẫn vào

    def test_nguoi_thuong_khong_sua_duoc(self):
        self.client.force_login(self.plain)
        response = self.client.patch("/api/v1/auth/public-settings/",
                                     data={"og_title": "Không được"},
                                     content_type="application/json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(EmailOtpSettings.current().og_title, "")

    def test_ai_cung_doc_duoc_va_co_ban_da_suy_ra(self):
        """Trang đăng nhập cần nhận diện trước khi có phiên."""
        payload = self.client.get("/api/v1/auth/public-settings/").json()
        self.assertIn("link_preview", payload)
        self.assertTrue(payload["link_preview"]["title"])
        self.assertIn("og_image_url", payload)

    def test_admin_upload_og_image_thanh_cong_va_phuc_vu_duoc(self):
        """Admin tải ảnh png hợp lệ lên -> trả /media/branding/... và serve được."""
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile

        img_byte_arr = io.BytesIO()
        image = Image.new("RGB", (400, 300), color=(255, 138, 51))
        image.save(img_byte_arr, format="PNG")
        uploaded = SimpleUploadedFile("test_thumb.png", img_byte_arr.getvalue(), content_type="image/png")

        self.client.force_login(self.admin)
        res = self.client.post("/api/v1/auth/branding/upload-og-image/", {"file": uploaded})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["url"].startswith("/media/branding/"))
        self.assertEqual(data["width"], 400)
        self.assertEqual(data["height"], 300)

        # Kiểm tra tải lại qua endpoint /media/
        media_res = self.client.get(data["url"])
        self.assertEqual(media_res.status_code, 200)
        self.assertEqual(media_res["Content-Type"], "image/png")
        self.assertIn("public", media_res["Cache-Control"])


class EmailOtpBulletproofTest(TestCase):
    def test_email_template_chua_bgcolor_cam_va_mso_cho_outlook(self):
        from .models import DEFAULT_OTP_HTML_TEMPLATE
        self.assertIn('bgcolor="#EA580C"', DEFAULT_OTP_HTML_TEMPLATE)
        self.assertIn('background-color:#EA580C', DEFAULT_OTP_HTML_TEMPLATE)
        self.assertIn('<!--[if mso]>', DEFAULT_OTP_HTML_TEMPLATE)
        self.assertIn('<!--[if (gte mso 9)|(IE)]>', DEFAULT_OTP_HTML_TEMPLATE)

    def test_normalize_email_icon_chuyen_data_uri_thanh_link_tinh(self):
        """Ảnh dạng data: URI được tự động lưu thành tệp tĩnh và trả về link https://, không nhúng base64."""
        import io
        from PIL import Image
        import base64
        from .email_otp import _normalize_email_icon_url

        img_byte_arr = io.BytesIO()
        image = Image.new("RGB", (64, 64), color=(255, 255, 255))
        image.save(img_byte_arr, format="PNG")
        b64 = base64.b64encode(img_byte_arr.getvalue()).decode("ascii")
        data_uri = f"data:image/png;base64,{b64}"

        normalized = _normalize_email_icon_url(data_uri)
        self.assertFalse(normalized.startswith("data:"))
        self.assertIn("/media/branding/icon_", normalized)
        self.assertTrue(normalized.startswith("http"))


class MetaTagShapeTest(TestCase):
    def test_du_bo_the_cho_zalo_facebook_va_twitter(self):
        tags = branding.meta_tags(branding.link_preview(EmailOtpSettings.current()))
        for required in ('property="og:title"', 'property="og:description"',
                         'property="og:image"', 'property="og:image:width"',
                         'property="og:site_name"', 'name="twitter:card"',
                         'name="twitter:image"', 'name="description"'):
            self.assertIn(required, tags, f"thiếu {required}")
        self.assertEqual(len(re.findall(r"<title>", tags)), 1)
