# -*- coding: utf-8 -*-
"""Lỗi production 18–20/09: bịa kết quả tìm kiếm, lộ nhãn nội bộ, câu tinh chỉnh
bị xếp nhầm vào hội thoại."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from ai.answer_hygiene import claims_search, strip_internal_labels
from talent.answer.plan import is_refinement, previous_search_criteria


class ClaimsSearchTest(SimpleTestCase):
    def test_bat_cau_tu_nhan_da_tim(self):
        self.assertTrue(claims_search("Chào anh/chị, Radar đã thực hiện tìm kiếm lại với tiêu chí nới lỏng"))
        self.assertTrue(claims_search("Dưới đây là kết quả lọc từ 1.073 hồ sơ"))

    def test_khong_bat_cau_binh_thuong(self):
        self.assertFalse(claims_search("Quy trình tuyển dụng của MSB gồm 3 bước."))
        self.assertFalse(claims_search("Anh/chị muốn tìm ứng viên nào?"))


class StripLabelsTest(SimpleTestCase):
    def test_bo_nhan_fact_inference(self):
        text = "**FACT (Đã xác minh từ kết quả tra Internet):** Ông A là TGĐ."
        self.assertEqual(strip_internal_labels(text), "Ông A là TGĐ.")
        self.assertEqual(strip_internal_labels("Lý do Nổi Bật (Inference) | x"), "Lý do Nổi Bật | x")
        self.assertEqual(strip_internal_labels("INFERENCE: Cơ hội suy từ vị trí"), "Cơ hội suy từ vị trí")

    def test_giu_nguyen_van_ban_thuong(self):
        self.assertEqual(strip_internal_labels("Kinh nghiệm 5 năm (Hà Nội)."), "Kinh nghiệm 5 năm (Hà Nội).")


class RefinementTest(SimpleTestCase):
    def test_nhan_biet_cau_tinh_chinh(self):
        for q in ("Nới lỏng tiêu chí số năm kinh nghiệm để tìm thêm ứng viên tiềm năng",
                  "Bỏ yêu cầu cấp Senior, giữ nguyên các tiêu chí còn lại",
                  "Tìm ứng viên biết Python hoặc Data (không cần cả hai)",
                  "không bắt buộc Hà Nội"):
            with self.subTest(q=q):
                self.assertTrue(is_refinement(q))
        self.assertFalse(is_refinement("Quy trình tuyển dụng của MSB gồm mấy bước"))

    def test_lay_nhu_cau_luot_truoc_tu_snapshot(self):
        projection = SimpleNamespace(
            recent_turns=[{"question": "Tìm Senior Data Analyst ở Hà Nội", "answer": "..."},
                          {"question": "Nới lỏng tiêu chí số năm", "answer": "..."}],
            active_criteria={}, last_result={"kind": "answer", "items": [{"id": 1}]})
        got = previous_search_criteria(SimpleNamespace(projection=projection))
        self.assertEqual(got["information_need"], "Tìm Senior Data Analyst ở Hà Nội")

    def test_chua_tim_lan_nao_thi_rong(self):
        projection = SimpleNamespace(recent_turns=[{"question": "xin chào"}],
                                     active_criteria={}, last_result={})
        self.assertEqual(previous_search_criteria(SimpleNamespace(projection=projection)), {})


from django.test import TestCase  # noqa: E402


class MergedCorpusStatsTest(TestCase):
    """Thống kê toàn kho đọc cả dữ liệu AI đã bóc, không chỉ hồ sơ có cấu trúc."""
    _seq = 0

    def _person(self, name):
        from people.models import Person
        return Person.objects.create(display_name=name, is_applicant=True)

    def _fact(self, person, field, value, status="accepted"):
        from intel.models import ExtractedFact
        MergedCorpusStatsTest._seq += 1
        return ExtractedFact.objects.create(
            person=person, field=field, raw_value=value, normalized_value=value.lower(),
            source_kind=ExtractedFact.SOURCE_AI, status=status, is_current=True,
            confidence=0.9, fingerprint=f"mc-{MergedCorpusStatsTest._seq}")

    def test_overview_dem_ky_nang_va_noi_o_tu_fact(self):
        from talent.answer import corpus
        from talent.models import TalentProfile
        a, b, c = self._person("A"), self._person("B"), self._person("C")
        TalentProfile.objects.create(person=a, location="Hà Nội", skills=["SQL"])
        self._fact(b, "skills", "Python")
        self._fact(b, "city", "Hà Nội")
        self._fact(c, "city", "Đà Nẵng")
        self._fact(c, "skills", "Excel", status="rejected")      # bị bác: không tính
        data = corpus.overview()
        self.assertEqual(data["ky_nang"]["filled"], 2)
        self.assertEqual(data["noi_o"]["filled"], 3)
        self.assertEqual(dict((i["value"], i["count"]) for i in data["noi_o"]["top"])["Hà Nội"], 2)

    def test_ho_so_co_cau_truc_thang_fact(self):
        from talent.answer import corpus
        from talent.models import TalentProfile
        a = self._person("A")
        TalentProfile.objects.create(person=a, location="Hồ Chí Minh")
        self._fact(a, "city", "Hà Nội")
        self.assertEqual(corpus.merged_profiles(["location"])[a.pk]["location"], "Hồ Chí Minh")

    def test_phan_bo_theo_khu_vuc_khong_can_nhom_loc(self):
        from talent.answer import corpus
        self._fact(self._person("A"), "city", "Hà Nội")
        block = corpus.breakdown_for_question("Thống kê số lượng ứng viên theo từng khu vực")
        self.assertEqual(block["field"], "location")
        self.assertEqual(block["filled"], 1)


class DistributionRoutingTest(SimpleTestCase):
    def test_cau_thong_ke_theo_truong_la_tong_hop(self):
        from talent.answer.plan import _DISTRIBUTION
        from people.normalize import normalize_name
        for q in ("Thống kê số lượng ứng viên theo từng khu vực",
                  "phân bố ứng viên theo ngành", "tỷ lệ hồ sơ theo cấp bậc"):
            with self.subTest(q=q):
                self.assertTrue(_DISTRIBUTION.search(normalize_name(q)))
        self.assertFalse(_DISTRIBUTION.search(normalize_name("Tìm Data Analyst ở Hà Nội")))


class TurnBudgetTest(TestCase):
    """Hết giờ thì trả danh sách đã chốt, KHÔNG để runner cắt thành câu trả lời rỗng."""

    def test_het_gio_thi_khong_goi_model_viet(self):
        from unittest import mock
        from talent.answer import engine, plan as plan_stage
        from talent.answer.judge import Judgement

        called = {"n": 0}

        def fake_stream(messages, task="", **kwargs):
            called["n"] += 1
            yield {"type": "answer", "text": "không được gọi"}

        chosen = [Judgement(person_id=1, name="An", relevant=True, confidence=0.9, why="khớp")]
        plan_obj = plan_stage.QueryPlan(shape="find_people", search_queries=["x"],
                                        information_need="Tìm An")

        def slow_pipeline(*args, **kwargs):
            return (plan_obj, chosen, [], {"judged": 1}, {})
            yield  # generator

        clock = iter([0.0] + [200.0] * 50)
        with mock.patch("talent.answer.engine._pipeline", side_effect=slow_pipeline), \
                mock.patch("talent.answer.engine.time.monotonic", side_effect=lambda: next(clock)):
            chunks = list(engine.stream_answer("x", stream_fn=fake_stream, query_plan=plan_obj))
        result = next(c["result"] for c in chunks if c["type"] == "done")
        self.assertEqual(called["n"], 0)
        self.assertIn("An", result.text)
        self.assertTrue(result.trace.get("compose_skipped"))
