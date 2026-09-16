# -*- coding: utf-8 -*-
"""Khung Answer Engine dùng chung (`core/answer/`) — kiểm trên MỘT DOMAIN GIẢ.

Vì sao có file này: các phép kiểm resilience trong `talent/tests_answer.py` chạy
qua Talent, nên chúng chứng minh "khung chạy đúng với Talent" chứ không chứng
minh "khung không dính vào Talent". Growth dựa vào vế thứ hai. Ở đây domain là
một cái tên bịa với một generator bịa — không có `talent`, không có `rb`, không
có mô hình nào — nên nếu ai đó lén đưa giả định nghiệp vụ vào `core/answer/`,
file này đỏ trước khi Growth kịp phát hiện bằng cách hỏng ngoài production.
"""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from core.answer import runner as core_runner
from core.answer.cache import TurnCache, plan_marker
from core.answer.fusion import reciprocal_rank_fusion
from core.answer.runner import TurnRunner
from core.answer.steps import drain, step


class FusionTest(SimpleTestCase):
    def test_dong_thuan_nhieu_nhanh_thang_thu_hang_cao_cua_mot_nhanh(self):
        """Đây là lý do dùng RRF thay vì cộng điểm thô của từng nhánh."""
        order, hits = reciprocal_rank_fusion([
            ["a", "b", "c"],
            ["b", "a", "d"],
            ["b", "e", "a"],
        ])
        self.assertEqual(order[0][0], "b")
        self.assertEqual(hits["b"], 3)

    def test_tie_break_on_dinh_khong_theo_thu_tu_chen(self):
        """Điểm bằng nhau phải cho cùng một thứ tự ở mọi lần chạy.

        Không có khoá phụ ổn định thì thứ tự chèn của CSDL quyết định ai vào pool
        đọc sâu — cùng câu hỏi, hai kết quả khác nhau.
        """
        xuoi, _ = reciprocal_rank_fusion([["x"], ["y"]])
        nguoc, _ = reciprocal_rank_fusion([["y"], ["x"]])
        self.assertEqual([k for k, _ in xuoi], [k for k, _ in nguoc])

    def test_trong_so_cho_nhanh_dang_tin_hon(self):
        """Growth cần nó: tín hiệu quan sát được đáng tin hơn khớp chữ nghề nghiệp."""
        khong_trong_so, _ = reciprocal_rank_fusion([["cham-chu"], ["tin-hieu"]])
        self.assertEqual(khong_trong_so[0][0], "cham-chu")   # hoà điểm → theo khoá
        co_trong_so, _ = reciprocal_rank_fusion(
            [["cham-chu"], ["tin-hieu"]], weights=[1.0, 5.0])
        self.assertEqual(co_trong_so[0][0], "tin-hieu")


class StepsTest(SimpleTestCase):
    def test_khuon_su_kien_buoc(self):
        self.assertEqual(step("Tìm trong kho"),
                         {"type": "step", "label": "Tìm trong kho", "state": "active"})
        self.assertEqual(step("Tìm trong kho", "done")["state"], "done")

    def test_drain_tra_ve_gia_tri_return_chu_khong_phai_cac_yield(self):
        def gen():
            yield 1
            yield 2
            return "ket-qua"
        self.assertEqual(drain(gen()), "ket-qua")


class PlanMarkerTest(SimpleTestCase):
    def test_doc_bang_getattr_nen_khong_ep_mot_lop_ke_hoach_cu_the(self):
        """Kế hoạch của Growth không cùng tập trường với Talent."""
        ke_hoach_la = SimpleNamespace(shape="whitespace", limit=7)
        marker = plan_marker(ke_hoach_la)
        self.assertEqual(marker["shape"], "whitespace")
        self.assertEqual(marker["limit"], 7)
        self.assertEqual(marker["must"], [])

    def test_khac_biet_trinh_bay_khong_pha_cache(self):
        a = SimpleNamespace(must_have=["Biết  SQL"], shape="find_people")
        b = SimpleNamespace(must_have=["biết sql"], shape="FIND_PEOPLE")
        self.assertEqual(plan_marker(a), plan_marker(b))


class ForeignDomainCacheTest(TestCase):
    """`TurnCache` phải buộc được vào một domain không phải Talent."""

    def _cache(self, prompts, corpus="v1"):
        return TurnCache(
            prefix="test:domain-gia",
            prompts=prompts,
            tasks=("assistant_conversation",),
            corpus_fingerprint=lambda: corpus,
            row_to_judgement=lambda row: row,
        )

    def test_khoa_doi_khi_van_tay_kho_doi(self):
        truoc = self._cache({"plan": "P"}, corpus="v1").key_for("câu hỏi")
        sau = self._cache({"plan": "P"}, corpus="v2").key_for("câu hỏi")
        self.assertTrue(truoc and sau)
        self.assertNotEqual(truoc, sau)

    def test_khoa_doi_khi_prompt_doi(self):
        truoc = self._cache({"plan": "P"}).key_for("câu hỏi")
        sau = self._cache({"plan": "P đã sửa"}).key_for("câu hỏi")
        self.assertNotEqual(truoc, sau)

    def test_prompt_dang_callable_doc_lai_moi_lan(self):
        """Chốt prompt lúc khởi tạo làm phép kiểm "đổi prompt ⇒ hết cache" xanh giả."""
        hien_tai = {"plan": "P"}
        cache = self._cache(lambda: dict(hien_tai))
        truoc = cache.key_for("câu hỏi")
        hien_tai["plan"] = "P đã sửa"
        self.assertNotEqual(truoc, cache.key_for("câu hỏi"))

    def test_khong_co_van_tay_kho_thi_KHONG_cache(self):
        """Thà không cache còn hơn cache dưới một vân tay rỗng nghĩa."""
        self.assertIsNone(self._cache({"plan": "P"}, corpus="").key_for("câu hỏi"))

    def test_hai_domain_khong_dung_chung_muc_cache(self):
        chung = dict(prompts={"plan": "P"}, tasks=("assistant_conversation",),
                     corpus_fingerprint=lambda: "v1", row_to_judgement=lambda r: r)
        a = TurnCache(prefix="test:domain-a", **chung).key_for("câu hỏi")
        b = TurnCache(prefix="test:domain-b", **chung).key_for("câu hỏi")
        self.assertNotEqual(a, b)


class ForeignDomainRunnerTest(TestCase):
    """`TurnRunner` phải chạy được một domain hoàn toàn bịa ra.

    Không import `talent` lẫn `rb`: nếu khung lén phụ thuộc vào một trong hai,
    những phép kiểm này là chỗ phát hiện.
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user("domain-gia")
        for name, value in (("claim", 1), ("finish", None), ("status", None)):
            patcher = mock.patch(f"core.answer.run_state.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _runner(self, gen):
        return TurnRunner(domain="domain-gia", stream_fn=gen,
                          result_factory=lambda: {"text": ""})

    def test_luot_thanh_cong_chay_het_va_persist_dung_mot_lan(self):
        def gen(question, *, envelope, user, history):
            yield step("Đang làm")
            yield {"type": "answer", "text": "xong"}
            yield {"type": "done", "result": {"text": "xong"}}

        da_luu = []
        with mock.patch("core.answer.runner._threaded_ok", return_value=False):
            chunks = list(self._runner(gen).stream(
                "q", envelope=None, user=self.user, history=[],
                client_turn_id="gia-ok",
                persist=lambda result, aborted=False: da_luu.append((result, aborted))))
        self.assertEqual(chunks[-1], {"type": "done", "result": {"text": "xong"}})
        self.assertEqual(da_luu, [({"text": "xong"}, False)])

    def test_luong_dut_giua_chung_bi_danh_dau_aborted_va_KHONG_bao_done(self):
        """Nửa câu trả lời không được đi ra ngoài dưới dạng một lượt đã xong."""
        def gen(question, *, envelope, user, history):
            yield {"type": "answer", "text": "mới được một nửa"}

        da_luu = []
        with mock.patch("core.answer.runner._threaded_ok", return_value=False):
            chunks = list(self._runner(gen).stream(
                "q", envelope=None, user=self.user, history=[],
                client_turn_id="gia-dut",
                persist=lambda result, aborted=False: da_luu.append(aborted)))
        self.assertEqual(da_luu, [True])
        self.assertEqual(chunks[-1]["type"], "error")
        self.assertNotIn("done", [c["type"] for c in chunks])

    def test_hai_domain_cung_ma_luot_khong_giam_len_nhau(self):
        """Khoá sổ gồm domain — nếu không, lượt Growth sẽ bị nhận nhầm là Talent."""
        a = TurnRunner(domain="domain-a", stream_fn=lambda *a, **k: iter(()),
                       result_factory=dict)
        b = TurnRunner(domain="domain-b", stream_fn=lambda *a, **k: iter(()),
                       result_factory=dict)
        self.assertNotEqual(a._key(self.user, "cung-mot-ma"),
                            b._key(self.user, "cung-mot-ma"))
        core_runner._publish_status("domain-a", self.user, "cung-mot-ma", "running",
                                    deadline=None)
        with mock.patch.object(core_runner, "_INFLIGHT", {}):
            self.assertEqual(a.status_of(self.user, "cung-mot-ma"), "running")
            self.assertIsNone(b.status_of(self.user, "cung-mot-ma"))

    def test_ngan_sach_worker_dung_chung_giua_cac_domain(self):
        """8 worker là sức chịu của MÁY CHỦ, không tự nhân đôi vì có thêm sản phẩm."""
        day = {("domain-khac", 999, "x")}
        with mock.patch.object(core_runner, "_ACTIVE", day), \
                mock.patch.object(core_runner, "_threaded_ok", return_value=True), \
                mock.patch("django.conf.settings.ANSWER_RUNNER_MAX_WORKERS", 1, create=True):
            chunks = list(self._runner(lambda *a, **k: iter(())).stream(
                "q", envelope=None, user=self.user, history=[],
                client_turn_id="gia-qua-tai", persist=lambda r, aborted=False: None))
        self.assertEqual(chunks[-1]["type"], "error")
        self.assertIn("nhiều lượt", chunks[-1]["text"])
