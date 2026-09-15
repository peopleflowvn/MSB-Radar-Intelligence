import unittest

from app.geo import canonical_province, find_provinces, normalize_location


class GeoTests(unittest.TestCase):
    def test_canonical_province_handles_abbreviations_and_accents(self):
        for raw in ("TP.HCM", "tp hcm", "TPHCM", "Sài Gòn", "HCM", "Ho Chi Minh City",
                    "Thành phố Hồ Chí Minh"):
            self.assertEqual(canonical_province(raw), "Hồ Chí Minh", raw)
        for raw in ("Hà Nội", "ha noi", "HANOI", "HN"):
            self.assertEqual(canonical_province(raw), "Hà Nội", raw)
        self.assertEqual(canonical_province("Nha Trang"), "Khánh Hòa")
        self.assertEqual(canonical_province("Vũng Tàu"), "Bà Rịa - Vũng Tàu")

    def test_canonical_province_strips_trailing_detail(self):
        self.assertEqual(canonical_province("Khánh Hòa (Tất cả quận/huyện)"), "Khánh Hòa")
        self.assertEqual(canonical_province("Đà Nẵng: Ngũ Hành Sơn"), "Đà Nẵng")

    def test_canonical_province_returns_empty_for_non_province(self):
        self.assertEqual(canonical_province("Quận 7"), "")
        self.assertEqual(canonical_province(""), "")

    def test_find_provinces_scans_text_in_order_no_duplicates(self):
        self.assertEqual(
            find_provinces("Muốn làm ở Hồ Chí Minh hoặc Bình Dương; quê Nghệ An, "
                           "từng làm tại HCM"),
            ["Hồ Chí Minh", "Bình Dương", "Nghệ An"])

    def test_find_provinces_longest_match_wins(self):
        # "Vũng Tàu" nằm trong "Bà Rịa - Vũng Tàu" — không được đếm 2 lần
        self.assertEqual(find_provinces("Bà Rịa - Vũng Tàu"), ["Bà Rịa - Vũng Tàu"])

    def test_normalize_location(self):
        self.assertEqual(normalize_location("Bình Dương, Hồ Chí Minh"),
                         "Bình Dương, Hồ Chí Minh")
        self.assertEqual(normalize_location("tp. hcm"), "Hồ Chí Minh")
        self.assertEqual(normalize_location("Quận Cầu Giấy"), "Quận Cầu Giấy")
        self.assertEqual(normalize_location(""), "")


if __name__ == "__main__":
    unittest.main()
