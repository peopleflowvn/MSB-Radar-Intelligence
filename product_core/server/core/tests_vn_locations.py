# -*- coding: utf-8 -*-
"""canonical_province/location_query_variants — xem core/vn_locations.py."""
from django.test import SimpleTestCase

from core.vn_locations import canonical_province, location_query_variants


class CanonicalProvinceTest(SimpleTestCase):
    def test_cac_cach_viet_khac_nhau_cua_ho_chi_minh(self):
        for text in ("Sài Gòn", "sai gon", "TP.HCM", "tphcm", "TP HCM", "HCM", "hcmc"):
            self.assertEqual(canonical_province(text), "Hồ Chí Minh")

    def test_khong_phan_biet_hoa_thuong_hay_dau_cach(self):
        self.assertEqual(canonical_province("  hà nội  "), "Hà Nội")
        self.assertEqual(canonical_province("HÀ NỘI"), "Hà Nội")

    def test_tinh_ngoai_danh_sach_giu_nguyen_van_khong_bien_mat(self):
        self.assertEqual(canonical_province("Sơn La"), "Sơn La")

    def test_dia_chi_chi_co_quan_van_suy_ra_thanh_pho(self):
        self.assertEqual(canonical_province("Quận 1"), "Hồ Chí Minh")
        self.assertEqual(canonical_province("District 7"), "Hồ Chí Minh")
        self.assertEqual(canonical_province("Quận Cầu Giấy"), "Hà Nội")

    def test_rong_van_rong(self):
        self.assertEqual(canonical_province(""), "")
        self.assertEqual(canonical_province(None), "")


class LocationQueryVariantsTest(SimpleTestCase):
    def test_tra_ve_ca_dang_chuan_lan_cac_bien_the(self):
        variants = location_query_variants("Sài Gòn")
        self.assertIn("Hồ Chí Minh", variants)
        self.assertIn("sai gon", variants)
        self.assertIn("tphcm", variants)

    def test_rong_thi_tra_danh_sach_rong(self):
        self.assertEqual(location_query_variants(""), [])
