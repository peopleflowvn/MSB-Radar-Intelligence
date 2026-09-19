# -*- coding: utf-8 -*-
"""Chất lượng truy hồi Talent — các lỗi đo được trên production 19/09.

Câu "Tìm Senior Data Analyst ở Hà Nội biết SQL và Python, trên 3 năm kinh
nghiệm" chạy 135 giây, đọc 93 hồ sơ, 0 người phù hợp, và giới thiệu 5 chuyên
viên ngân hàng làm "ứng viên gần phù hợp nhất" — trong khi kho có người làm
phân tích dữ liệu biết SQL/Python. Mỗi test dưới đây giữ một mắt xích của lỗi đó.
"""
from django.test import SimpleTestCase, TestCase

from people.models import Person

from .answer import aggregate, engine, retrieve
from .answer.judge import Judgement
from .answer.plan import QueryPlan, split_seniority, useful_queries
from .answer.retrieve import Candidate, Passage, fuse_candidates
from .answer.structured_match import value_matches
from .models import PersonSearchDocument


class SplitSeniorityTest(SimpleTestCase):
    def test_cap_bac_roi_khoi_dieu_kien_bat_buoc(self):
        must, should = split_seniority(["Senior Data Analyst", "phân tích dữ liệu"], ["Hà Nội"])
        self.assertEqual(must, ["Data Analyst", "phân tích dữ liệu"])
        self.assertIn("cấp Senior", should)

    def test_hau_to_tieng_viet(self):
        must, should = split_seniority(["Kế toán cấp cao"], [])
        self.assertEqual(must, ["Kế toán"])
        self.assertEqual(should, ["cấp cao"])

    def test_khong_dung_chuc_danh_khong_co_cap_bac(self):
        self.assertEqual(split_seniority(["Trưởng phòng Kinh doanh"], []),
                         (["Trưởng phòng Kinh doanh"], []))


class UsefulQueriesTest(SimpleTestCase):
    def test_bo_truy_van_chi_la_dia_danh(self):
        self.assertEqual(useful_queries(["Senior Data Analyst", "Hà Nội", "hanoi", "HN", "SQL"], "x"),
                         ["Senior Data Analyst", "SQL"])

    def test_khong_con_gi_thi_dung_nhu_cau(self):
        self.assertEqual(useful_queries(["Hà Nội"], "Tìm kế toán"), ["Tìm kế toán"])


class ValueMatchesTest(SimpleTestCase):
    def test_cap_bac_khong_khop_ca_chuc_danh(self):
        # Gốc lỗi 40 người ghim: "senior" khớp lỏng "Senior Data Analyst".
        self.assertFalse(value_matches("Senior", "Senior Data Analyst"))

    def test_chuc_danh_that_van_khop(self):
        self.assertTrue(value_matches("Senior Data Analyst", "Data Analyst"))
        self.assertTrue(value_matches("Data Analyst", "Senior Data Analyst"))

    def test_ky_nang_mot_chu_khong_khop_moi_cau(self):
        self.assertFalse(value_matches("R", "biết Python và SQL"))

    def test_bo_tu_dem(self):
        self.assertTrue(value_matches("Python", "biết Python"))
        self.assertTrue(value_matches("SQL", "có kinh nghiệm SQL"))


class NearMissFloorTest(SimpleTestCase):
    def _plan(self):
        return QueryPlan(information_need="x", shape="find_people", limit=10)

    def test_nguoi_bi_loai_khong_lien_quan_khong_phai_gan_dung(self):
        rows = [
            Judgement(person_id=1, name="Không liên quan", relevant=False, confidence=0.1,
                      why="Không có bằng chứng về SQL, Python"),
            Judgement(person_id=2, name="Gần đúng", relevant=False, confidence=0.5,
                      why="Data Analyst 1 năm", gap="thiếu số năm"),
            Judgement(person_id=3, name="Thoả thiếu trích dẫn", relevant=True, confidence=0.3),
        ]
        _chosen, near, _stats = aggregate.aggregate(self._plan(), rows)
        self.assertEqual({j.person_id for j in near}, {2, 3})


class FuseCandidatesTest(SimpleTestCase):
    @staticmethod
    def _c(pid, text="cv"):
        return Candidate(person_id=pid, name=f"#{pid}", passages=[Passage(pid, 1, 0, text)])

    def test_nguon_chung_duoc_cong_diem_va_pool_co_tran(self):
        v2 = [self._c(1), self._c(2), self._c(3)]
        local = [self._c(4), self._c(2)]
        out = fuse_candidates([(v2, 1.0), (local, 1.0)], pool=3)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0].person_id, 2)          # có mặt ở cả hai nguồn

    def test_nguoi_ghim_dung_dau_va_khong_bi_cat(self):
        out = fuse_candidates([([self._c(1), self._c(2)], 1.0), ([self._c(9)], 0.6)],
                              pool=1, pinned_ids=[9])
        self.assertEqual([c.person_id for c in out], [9])

    def test_gop_bang_chung_bo_trung_noi_dung(self):
        a = Candidate(person_id=1, name="A", passages=[Passage(1, 1, 0, "Data Analyst SQL")])
        b = Candidate(person_id=1, name="A", passages=[Passage(1, 2, 0, "Data Analyst SQL"),
                                                       Passage(1, 2, 1, "Python")])
        out = fuse_candidates([([a], 1.0), ([b], 1.0)], pool=5)
        self.assertEqual([p.text for p in out[0].passages], ["Data Analyst SQL", "Python"])


class RankedFtsTest(TestCase):
    def _doc(self, name, content):
        person = Person.objects.create(display_name=name, is_applicant=True)
        from .vector_index import fold_text
        PersonSearchDocument.objects.create(person=person, fingerprint=name,
                                            content=content, content_norm=fold_text(content))
        return person

    def test_xep_theo_do_khop_khong_theo_thu_tu_chen(self):
        noise = self._doc("Nhiễu", "Chuyên viên ngân hàng Hà Nội 5 năm kinh nghiệm")
        best = self._doc("Đúng", "Data Analyst SQL Python Hà Nội 4 năm kinh nghiệm")
        order = retrieve._fts_person_ids("Senior Data Analyst Hà Nội SQL Python trên 3 năm kinh nghiệm", 10)
        self.assertEqual(order[0], best.pk)
        self.assertIn(noise.pk, order)

    def test_tu_chung_khong_keo_nguoi_khac_nghe(self):
        # "kinh nghiệm", "năm", "ứng viên" có trong gần như mọi CV — không được
        # là lý do để một chuyên viên ngân hàng khớp câu tìm Data Analyst.
        self._doc("Nhiễu", "Chuyên viên ngân hàng 5 năm kinh nghiệm")
        self.assertEqual(retrieve._fts_person_ids("ứng viên Data Analyst có kinh nghiệm trên 3 năm", 10), [])


class PreambleTest(SimpleTestCase):
    def test_khong_hai_dau_cham(self):
        plan = QueryPlan(information_need="Tìm Data Analyst trên 3 năm.", shape="find_people",
                         search_queries=["a", "b"])
        self.assertNotIn("..", engine._preamble(plan, "q"))
