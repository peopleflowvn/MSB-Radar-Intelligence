# -*- coding: utf-8 -*-
"""Test cho Answer Engine — neo vào đúng ba lỗi đã làm hỏng các lượt trả lời cũ.

1. Kế hoạch mất nguyên văn tiếng Việt ⇒ truy hồi 0 kết quả.
2. Model bịa trích dẫn ⇒ nguồn trỏ vào chỗ không tồn tại.
3. Model tự sắp xếp/đếm ⇒ "5 người ít tuổi nhất" ra sai thứ tự, sai số lượng.
"""
import json
import threading
import time
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase, SimpleTestCase, TransactionTestCase, override_settings
from people.models import Document, Person

from core.asgi_stream import drain_to_bytes

from .answer import act as act_stage
from .answer import aggregate as aggregate_stage
from .answer import cache as cache_stage
from .answer import chat as chat_stage
from .answer import compose as compose_stage
from .answer import corpus as corpus_stage
from .answer import engine
from .answer import judge as judge_stage
from .answer import plan as plan_stage
from .answer import retrieve as retrieve_stage
from .answer import verify as verify_stage
from .answer.judge import Judgement
from .models import CVChunk, PersonSearchDocument, TalentProfile


class FakeCompletion:
    def __init__(self, text, provider="fake", model="fake-1"):
        self.text = text
        self.provider = provider
        self.model = model


def _many_candidates(count):
    """`count` ứng viên tối thiểu để chia thành nhiều lô (`judge.BATCH`)."""
    rows = []
    for index in range(count):
        person = Person.objects.create(display_name=f"Ứng viên {index}")
        rows.append(retrieve_stage.Candidate(
            person_id=person.pk, name=person.display_name,
            passages=[retrieve_stage.Passage(person.pk, 1, 1, "Kinh doanh 5 năm.")]))
    return rows


class CandidateSetRankingBridgeTest(SimpleTestCase):
    def test_candidate_set_is_a_ranked_source_not_a_hard_pin(self):
        """CandidateSet V2 may improve rank but must not erase legacy recall."""
        one = retrieve_stage.Candidate(1, "legacy-only", 1.0, 1, [])
        two_local = retrieve_stage.Candidate(2, "both", 1.0, 1, [])
        two_v2 = retrieve_stage.Candidate(2, "both", 1.0, 1, [])
        three = retrieve_stage.Candidate(3, "v2-only", 1.0, 1, [])

        def fake_retrieve(_plan, *, pinned_ids=(), search_queries=None, **_kwargs):
            if list(pinned_ids) == [3, 2] and search_queries == []:
                return [three, two_v2]
            return [one, two_local]

        with mock.patch("talent.answer.engine.retrieve_stage.retrieve",
                        side_effect=fake_retrieve):
            rows, engine_name = engine._retrieve_all(
                SimpleNamespace(), user=None, envelope=SimpleNamespace(thread=None),
                pool=3, pinned_ids=[], structured_ids=[], candidate_set_ids=[3, 2],
                queries=["java"], pinned_only=False)

        self.assertEqual([row.person_id for row in rows], [2, 1, 3])
        self.assertEqual(engine_name, "product-core")


def _reader(seen):
    """`complete_fn` giả đọc trọn lô: ghi lại cỡ mỗi lô đã thực sự gửi đi."""
    def _call(messages, task="", **kwargs):
        payload = json.loads(messages[-1]["content"])
        seen.append(len(payload["ho_so"]))
        return FakeCompletion(json.dumps({"ket_qua": [
            {"id": i + 1, "thoa": False, "do_tin": 0.1, "vi_sao": "không thoả"}
            for i in range(len(payload["ho_so"]))]}, ensure_ascii=False))
    return _call


def replies(mapping):
    """`complete_fn` giả: trả theo task, ghi lại prompt để soi."""
    seen = []

    def _call(messages, task="", **kwargs):
        seen.append({"task": task, "messages": messages})
        value = mapping.get(task, "{}")
        return FakeCompletion(value(messages) if callable(value) else value)

    _call.seen = seen
    return _call


# ---------------------------------------------------------------- ① plan

class PlanTest(TestCase):
    def test_lay_ho_so_va_phan_tich_khong_bi_day_sang_action(self):
        caller = replies({plan_stage.TASK: json.dumps({
            "shape": "action",
            "information_need": "Lấy hồ sơ Nguyễn Tiến Đạt và phân tích chi tiết",
            "search_queries": [],
        }, ensure_ascii=False)})
        planned = plan_stage.plan(
            "lấy hồ sơ của Nguyễn Tiến Đạt và phân tích chi tiết",
            complete_fn=caller)
        self.assertEqual(planned.shape, "analyze")
        self.assertTrue(planned.needs_people)
        self.assertEqual(planned.search_queries,
                         ["lấy hồ sơ của Nguyễn Tiến Đạt và phân tích chi tiết"])

    def test_giu_nguyen_van_tieng_viet_va_sinh_nhieu_cach_noi(self):
        caller = replies({plan_stage.TASK: json.dumps({
            "shape": "find_people",
            "information_need": "ứng viên làm quan hệ khách hàng",
            "search_queries": ["quan hệ khách hàng cá nhân",
                               "customer relationship manager RM",
                               "chăm sóc khách hàng ngân hàng"],
            "limit": 5,
        }, ensure_ascii=False)})
        result = plan_stage.plan("tìm ứng viên quan hệ khách hàng", complete_fn=caller)
        self.assertEqual(result.limit, 5)
        self.assertEqual(len(result.search_queries), 3)
        # Chính lỗi cũ: dịch một lần sang "Customer Relationship" rồi mất bản gốc.
        self.assertTrue(any("quan hệ khách hàng" in q for q in result.search_queries))

    def test_model_hong_van_tra_ve_ke_hoach_tim_duoc(self):
        def boom(*args, **kwargs):
            raise RuntimeError("provider chết")
        result = plan_stage.plan("ai biết Python", complete_fn=boom)
        self.assertTrue(result.fallback)
        self.assertEqual(result.search_queries, ["ai biết Python"])
        self.assertTrue(result.needs_people)

    def test_limit_nhan_dang_chuoi(self):
        caller = replies({plan_stage.TASK: json.dumps(
            {"shape": "find_people", "limit": "top 5", "search_queries": ["a"]})})
        self.assertEqual(plan_stage.plan("x", complete_fn=caller).limit, 5)

    def test_dieu_nguoi_dung_da_dan_di_vao_ke_hoach(self):
        """Panel "Radar nhớ" phải có tác dụng thật, không chỉ là cuốn sổ."""
        from types import SimpleNamespace
        caller = replies({plan_stage.TASK: json.dumps(
            {"shape": "find_people", "search_queries": ["BA"]})})
        envelope = SimpleNamespace(projection=SimpleNamespace(
            recent_turns=[], memories=["Tôi chỉ tuyển ở Hà Nội"],
            last_result_lines=lambda: ""))
        plan_stage.plan("tìm BA", envelope=envelope, complete_fn=caller)
        sent = caller.seen[0]["messages"][-1]["content"]
        self.assertIn("NGƯỜI DÙNG ĐÃ DẶN", sent)
        self.assertIn("chỉ tuyển ở Hà Nội", sent)

    def test_suy_luan_duoc_hoi_truoc_khi_chot_shape(self):
        """① sinh token trái→phải: khoá nào viết trước thì khoá sau bị đặt điều
        kiện lên nó. Trước đây "shape" là khoá ĐẦU TIÊN, tức nhánh trả lời bị
        chốt ngay ở token đầu, chưa có gì để suy nghĩ. Mọi lỗi định tuyến đều
        sinh ra ở đúng chỗ đó."""
        prompt = plan_stage.SYSTEM
        self.assertIn('"suy_luan"', prompt)
        self.assertLess(prompt.index('"suy_luan"'), prompt.index('- "shape"'),
                        '"suy_luan" phải được yêu cầu TRƯỚC "shape"')

    def test_suy_luan_duoc_giu_lai_de_soi_khi_dinh_tuyen_sai(self):
        caller = replies({plan_stage.TASK: json.dumps({
            "suy_luan": "Người dùng chỉ chào hỏi, không nhắc gì tới kho hồ sơ.",
            "shape": "general",
            "information_need": "chào hỏi",
            "search_queries": [],
        }, ensure_ascii=False)})
        result = plan_stage.plan("xin chào", complete_fn=caller)
        self.assertEqual(result.shape, "general")
        self.assertIn("chỉ chào hỏi", result.reasoning)
        # Có trong trace thì mới soi được ① đã nghĩ gì khi nó chọn sai nhánh.
        self.assertIn("chỉ chào hỏi", result.as_dict()["reasoning"])

    def test_do_tin_cay_thap_kem_cau_hoi_thi_hoi_lai(self):
        caller = replies({plan_stage.TASK: json.dumps({
            "suy_luan": "Câu này hiểu được hai kiểu, không đoán được kiểu nào đúng.",
            "shape": "find_people", "do_tin_cay": 0.2,
            "cau_hoi_lam_ro": "Anh/chị muốn ứng viên ĐANG làm ở MSB hay TỪNG làm ở MSB ạ?",
            "search_queries": ["MSB"],
        }, ensure_ascii=False)})
        result = plan_stage.plan("tìm người MSB", complete_fn=caller)
        self.assertTrue(result.wants_clarification)
        self.assertIn("ĐANG làm ở MSB", result.clarify)

    def test_khong_hoi_lai_khi_da_chac(self):
        """Model hay kèm câu hỏi cho MỌI lượt. Chắc rồi thì phải bỏ đi, nếu
        không Radar hoá ra hỏi lại suốt thay vì trả lời."""
        caller = replies({plan_stage.TASK: json.dumps({
            "suy_luan": "Rõ ràng: tìm ứng viên biết Java.",
            "shape": "find_people", "do_tin_cay": 0.9,
            "cau_hoi_lam_ro": "Anh/chị cần bao nhiêu hồ sơ ạ?",
            "search_queries": ["Java"],
        }, ensure_ascii=False)})
        result = plan_stage.plan("tìm ứng viên Java", complete_fn=caller)
        self.assertFalse(result.wants_clarification)
        self.assertEqual(result.clarify, "")

    def test_hoi_lai_khong_dong_toi_truy_hoi(self):
        """Hỏi lại phải RẺ: không truy hồi, không đọc hồ sơ, không gọi model lần
        hai — nếu không thì nó chẳng tiết kiệm được gì so với đoán bừa."""
        def plan_must_not_run(*args, **kwargs):
            raise AssertionError("② không được chạy khi Radar đang hỏi lại")
        query_plan = plan_stage.QueryPlan(
            shape="find_people", confidence=0.2, search_queries=["MSB"],
            clarify="Anh/chị muốn ứng viên ĐANG làm hay TỪNG làm ở MSB ạ?")
        with mock.patch("talent.answer.retrieve.retrieve", plan_must_not_run):
            chunks = list(engine.stream_answer("tìm người MSB", query_plan=query_plan))
        done = next(c for c in chunks if c.get("type") == "done")
        self.assertEqual(done["result"].trace["mode"], "clarify")
        self.assertIn("ĐANG làm", done["result"].text)

    def test_chot_chan_kho_nhuong_duong_khi_muc_tin_rat_cao(self):
        """Chốt chặn `mentions_store` chỉ dò TỪ KHOÁ, nên một câu "general" đúng
        nghĩa mà lỡ có chữ "dữ liệu" vẫn bị nó bẻ sang nhánh tìm người."""
        payload = {
            "suy_luan": "Họ hỏi về luật bảo vệ dữ liệu cá nhân nói chung, "
                        "không hỏi gì về kho hồ sơ của Radar.",
            "shape": "general", "do_tin_cay": 0.95, "search_queries": [],
        }
        caller = replies({plan_stage.TASK: json.dumps(payload, ensure_ascii=False)})
        result = plan_stage.plan("nghị định bảo vệ dữ liệu cá nhân có gì mới",
                                 complete_fn=caller)
        self.assertEqual(result.shape, "general")

    def test_chot_chan_kho_van_ra_tay_khi_khong_chac(self):
        """Chốt chặn cho lỗi TỆ NHẤT ("tôi không có dữ liệu" trong khi kho có
        hàng trăm hồ sơ) không được nới chỉ vì đã có `do_tin_cay`."""
        for confidence in (0.0, 0.5, 0.85):
            caller = replies({plan_stage.TASK: json.dumps({
                "suy_luan": "Chắc là câu hỏi chung.",
                "shape": "general", "do_tin_cay": confidence, "search_queries": [],
            }, ensure_ascii=False)})
            result = plan_stage.plan("thế bạn có cv những ngành nào", complete_fn=caller)
            self.assertEqual(result.shape, "analyze", confidence)

    def test_khong_co_do_tin_cay_thi_giu_nguyen_hanh_vi_cu(self):
        """Model cũ / model bỏ qua khoá mới ⇒ 0.0 ⇒ mọi chốt chặn giữ hiệu lực."""
        caller = replies({plan_stage.TASK: json.dumps({
            "shape": "general", "search_queries": [],
        }, ensure_ascii=False)})
        result = plan_stage.plan("thế bạn có cv những ngành nào", complete_fn=caller)
        self.assertEqual(result.confidence, 0.0)
        self.assertEqual(result.shape, "analyze")
        self.assertFalse(result.wants_clarification)

    def test_widen_giu_bat_buoc_chi_mo_rong_truy_hoi(self):
        original = plan_stage.QueryPlan(
            information_need="nhân sự NEU", must_have=["tốt nghiệp NEU"],
            search_queries=["NEU"])
        wider = plan_stage.widen(original)
        self.assertEqual(wider.must_have, ["tốt nghiệp NEU"])
        self.assertEqual(wider.should_have, original.should_have)
        self.assertIn("nhân sự NEU", wider.search_queries)


# --------------------------------------------------------------- ③ judge

class JudgeTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(display_name="Trần Thị Bằng Chứng")
        self.candidate = retrieve_stage.Candidate(
            person_id=self.person.pk, name=self.person.display_name,
            passages=[retrieve_stage.Passage(
                self.person.pk, 42, 3,
                "Tốt nghiệp Cao đẳng Kinh tế Đối ngoại năm 2018, sinh năm 1997.")])
        self.query_plan = plan_stage.QueryPlan(
            information_need="ứng viên học cao đẳng",
            extract=["năm sinh", "trình độ"], search_queries=["cao đẳng"])

    def _judge(self, payload):
        caller = replies({judge_stage.TASK: json.dumps(payload, ensure_ascii=False)})
        return judge_stage.judge(self.query_plan, [self.candidate], complete_fn=caller)

    def test_trich_dan_co_that_thi_giu_va_tro_dung_tai_lieu(self):
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.9, "vi_sao": "học cao đẳng",
            "trich_dan": [{"doan": 1, "nguyen_van": "Tốt nghiệp Cao đẳng Kinh tế Đối ngoại"}],
            "boc_duoc": {"năm sinh": "1997", "trình độ": "Cao đẳng"}}]})
        self.assertTrue(result.relevant)
        self.assertEqual(len(result.evidence), 1)
        self.assertEqual(result.evidence[0]["document_id"], 42)
        self.assertEqual(result.evidence[0]["ordinal"], 3)
        self.assertEqual(result.extracted["năm sinh"], "1997")

    def test_trich_dan_bia_thi_lui_ve_dan_chinh_doan_model_chi(self):
        """Câu chữ bịa KHÔNG được lưu, nhưng đoạn model chỉ là nguồn có thật.

        Bỏ luôn cả trích dẫn là mất nguồn của một phán đoán có thể vẫn đúng — đo
        trên kho thật: hai câu trả lời nêu tên người mà không có [n] nào.
        """
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.95, "vi_sao": "có vẻ hợp",
            "trich_dan": [{"doan": 1,
                           "nguyen_van": "Thạc sĩ Đại học Kinh tế Quốc dân, 12 năm kinh nghiệm"}],
            "boc_duoc": {}}]})
        self.assertEqual(len(result.evidence), 1)
        self.assertFalse(result.evidence[0]["exact"])
        # Nội dung lưu là văn bản THẬT của đoạn, không phải chữ model viết.
        self.assertIn(result.evidence[0]["quote"], self.candidate.passages[0].text)
        self.assertNotIn("Thạc sĩ", result.evidence[0]["quote"])

    def test_khong_chi_duoc_doan_nao_thi_khong_co_nguon(self):
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.95, "vi_sao": "cảm giác hợp",
            "trich_dan": [{"doan": 99, "nguyen_van": "Thạc sĩ NEU"}]}]})
        self.assertEqual(result.evidence, [])
        self.assertLessEqual(result.confidence, 0.4)

    def test_khong_doan_thuoc_tinh_khi_cv_khong_noi(self):
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.8, "vi_sao": "ok",
            "trich_dan": [{"doan": 1, "nguyen_van": "sinh năm 1997"}],
            "boc_duoc": {"năm sinh": "1997", "trường tốt nghiệp": None,
                         "số năm kinh nghiệm": "không rõ"}}]})
        self.assertIn("năm sinh", result.extracted)
        self.assertNotIn("trường tốt nghiệp", result.extracted)
        self.assertNotIn("số năm kinh nghiệm", result.extracted)

    def test_thuoc_tinh_uoc_luong_bi_bo_vi_chang_sau_sap_xep_tren_no(self):
        """Model suy năm sinh từ năm tốt nghiệp — không được để nó xếp thứ hạng."""
        for guess in ["ước tính khoảng 1995", "1993-1995", "có thể 1994", "~1995"]:
            with self.subTest(guess=guess):
                [result] = self._judge({"ket_qua": [{
                    "id": 1, "thoa": True, "do_tin": 0.8, "vi_sao": "ok",
                    "trich_dan": [{"doan": 1, "nguyen_van": "Tốt nghiệp Cao đẳng"}],
                    "boc_duoc": {"năm sinh": guess, "trình độ": "Cao đẳng"}}]})
                self.assertNotIn("năm sinh", result.extracted)
                self.assertEqual(result.extracted["trình độ"], "Cao đẳng")

    def test_chuoi_mo_ta_dai_khong_bi_vut_vi_mot_dau_hoi(self):
        """Bản đầu bắt "?" ở bất cứ đâu nên vứt cả lịch sử công việc CÓ THẬT."""
        history = ("MBLand Holdings, Vietcombank (gián tiếp qua thực tập sinh "
                   "đối tác?), South Street")
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.8, "vi_sao": "ok",
            "trich_dan": [{"doan": 1, "nguyen_van": "Tốt nghiệp Cao đẳng"}],
            "boc_duoc": {"lịch sử công việc": history}}]})
        self.assertIn("lịch sử công việc", result.extracted)
        self.assertIn("Vietcombank", result.extracted["lịch sử công việc"])

    def test_gia_tri_NGAN_co_dau_hoi_van_bi_loai(self):
        """Vẫn nghiêm với thứ ④ đem đi sắp xếp — "1995?" là đoán."""
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.8, "vi_sao": "ok",
            "trich_dan": [{"doan": 1, "nguyen_van": "Tốt nghiệp Cao đẳng"}],
            "boc_duoc": {"năm sinh": "1995?"}}]})
        self.assertNotIn("năm sinh", result.extracted)

    def test_nam_sinh_doc_duoc_that_thi_van_giu(self):
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.9, "vi_sao": "ok",
            "trich_dan": [{"doan": 1, "nguyen_van": "sinh năm 1997"}],
            "boc_duoc": {"năm sinh": "1997"}}]})
        self.assertEqual(result.extracted["năm sinh"], "1997")

    def test_id_ngoai_dai_bi_bo_qua(self):
        self.assertEqual(list(self._judge({"ket_qua": [{"id": 99, "thoa": True}]})), [])

    def test_cau_tra_loi_bi_cat_khong_duoc_coi_la_da_doc_xong(self):
        """Lỗi đã gặp trên kho thật: JSON cụt ⇒ parse rỗng ⇒ báo 'kho không có ai'."""
        class Cut:
            text = '{"ket_qua": [{"id": 1, "thoa": true, "trich_'
            truncated = True
            provider = model = "fake"

        report = judge_stage.judge(self.query_plan, [self.candidate],
                                   complete_fn=lambda *a, **k: Cut())
        self.assertEqual(list(report), [])
        self.assertTrue(report.broken)      # gãy chặng đọc, KHÔNG phải kho rỗng

    def test_chi_giu_phan_trich_dan_doi_chieu_duoc(self):
        """Model chép đúng đầu câu rồi tự viết đuôi — đuôi bịa không được lưu."""
        [result] = self._judge({"ket_qua": [{
            "id": 1, "thoa": True, "do_tin": 0.9, "vi_sao": "ok",
            "trich_dan": [{"doan": 1, "nguyen_van":
                           "Tốt nghiệp Cao đẳng Kinh tế Đối ngoại loại giỏi, GPA 3.8"}]}]})
        self.assertEqual(len(result.evidence), 1)
        quote = result.evidence[0]["quote"]
        self.assertIn("Tốt nghiệp Cao đẳng Kinh tế Đối ngoại", quote)
        self.assertNotIn("GPA 3.8", quote)
        self.assertIn(quote, self.candidate.passages[0].text)

    def test_het_ngan_sach_thoi_gian_thi_bo_lo_con_lai_va_bao_chua_day_du(self):
        """Hết giờ phải trả phần đã đọc, không kéo cả lượt quá trần 150s của runner."""
        seen = []
        report = judge_stage.judge(
            self.query_plan, _many_candidates(16), complete_fn=_reader(seen),
            workers=1, deadline=time.monotonic() - 1)
        self.assertEqual(len(seen), 1)          # lô đầu vẫn chạy, lô sau bị bỏ
        self.assertEqual(report.skipped, 1)
        self.assertTrue(report.incomplete)
        self.assertFalse(report.broken)         # đọc được 8 hồ sơ ⇒ không phải gãy

    def test_khong_dat_han_gio_thi_van_doc_het_nhu_cu(self):
        seen = []
        report = judge_stage.judge(self.query_plan, _many_candidates(16),
                                   complete_fn=_reader(seen), workers=1)
        self.assertEqual(len(seen), 2)
        self.assertEqual(report.skipped, 0)
        self.assertFalse(report.incomplete)

    def test_het_gio_khi_chua_lo_nao_ve_thi_bao_gay_chu_khong_bao_kho_rong(self):
        """Đúng cái sai lớp này sinh ra để chặn: chưa đọc được gì ≠ kho không có ai."""
        block = threading.Event()

        def _call(messages, task="", **kwargs):
            block.wait(5)
            return FakeCompletion("{}")

        try:
            report = judge_stage.judge(self.query_plan, _many_candidates(16),
                                       complete_fn=_call, workers=2,
                                       deadline=time.monotonic() + 0.2)
        finally:
            block.set()
        self.assertEqual(list(report), [])
        self.assertTrue(report.skipped > 0)
        self.assertTrue(report.broken)

    def test_lo_hong_thi_chia_doi_thu_lai(self):
        calls = []

        def caller(messages, task="", **kwargs):
            payload = json.loads(messages[-1]["content"])
            size = len(payload["ho_so"])
            calls.append(size)
            if size > 1:                      # lô to thì "tràn token"
                return FakeCompletion("", provider="fake")
            return FakeCompletion(json.dumps({"ket_qua": [
                {"id": 1, "thoa": True, "do_tin": 0.8, "vi_sao": "ok",
                 "trich_dan": [{"doan": 1, "nguyen_van": "sinh năm 1997"}]}]}))

        pair = [self.candidate, self.candidate]
        report = judge_stage.judge(self.query_plan, pair, complete_fn=caller,
                                   batch_size=2)
        self.assertEqual(calls, [2, 1, 1])
        self.assertEqual(len(report), 2)
        self.assertFalse(report.broken)


# ----------------------------------------------------------- ④ aggregate

def _j(name, confidence=0.9, relevant=True, **extracted):
    return Judgement(person_id=abs(hash(name)) % 100000, name=name,
                     relevant=relevant, confidence=confidence,
                     evidence=[{"document_id": 1, "ordinal": 0, "quote": "x"}],
                     extracted=extracted)


class AggregateTest(TestCase):
    def test_it_tuoi_nhat_xep_theo_nam_sinh_giam_dan(self):
        query_plan = plan_stage.QueryPlan(
            limit=3, sort_by={"key": "năm sinh", "dir": "desc"})
        rows = [_j("An", **{"năm sinh": "1990"}), _j("Bình", **{"năm sinh": "2001"}),
                _j("Cường", **{"năm sinh": "1996"}), _j("Dũng", **{"năm sinh": "1985"})]
        chosen, _near, stats = aggregate_stage.aggregate(query_plan, rows)
        self.assertEqual([j.name for j in chosen], ["Bình", "Cường", "An"])
        self.assertEqual(stats["shown"], 3)
        self.assertEqual(stats["truncated"], 1)

    def test_hoi_theo_tuoi_van_xep_dung_chieu(self):
        """"Tuổi tăng dần" == "năm sinh giảm dần" — người trẻ nhất đứng đầu."""
        query_plan = plan_stage.QueryPlan(limit=2, sort_by={"key": "tuổi", "dir": "asc"})
        rows = [_j("Già", **{"tuổi": "45"}), _j("Trẻ", **{"tuổi": "24"})]
        chosen, _near, _stats = aggregate_stage.aggregate(query_plan, rows)
        self.assertEqual([j.name for j in chosen], ["Trẻ", "Già"])

    def test_thieu_thuoc_tinh_thi_xuong_cuoi_va_duoc_dem(self):
        query_plan = plan_stage.QueryPlan(
            limit=5, sort_by={"key": "năm sinh", "dir": "desc"})
        rows = [_j("Không rõ"), _j("Biết", **{"năm sinh": "1999"})]
        chosen, _near, stats = aggregate_stage.aggregate(query_plan, rows)
        self.assertEqual([j.name for j in chosen], ["Biết", "Không rõ"])
        self.assertEqual(stats["missing_sort_value"], 1)

    def test_ten_thuoc_tinh_lech_van_khop(self):
        query_plan = plan_stage.QueryPlan(
            limit=2, sort_by={"key": "Năm sinh", "dir": "desc"})
        rows = [_j("A", **{"nam sinh": "1990"}), _j("B", **{"nam sinh": "2000"})]
        chosen, _near, stats = aggregate_stage.aggregate(query_plan, rows)
        self.assertEqual([j.name for j in chosen], ["B", "A"])
        self.assertEqual(stats["missing_sort_value"], 0)

    def test_khong_thoa_thi_thanh_gan_dung_chu_khong_mat_hut(self):
        # `do_tin` là mức khớp: bị loại mà khớp một phần (≥ NEAR_FLOOR) là gần
        # đúng; khớp gần như không có gì thì không được giới thiệu là gần đúng.
        rows = [_j("Khớp một phần", confidence=0.4, relevant=False),
                _j("Không liên quan", confidence=0.2, relevant=False)]
        chosen, near, _stats = aggregate_stage.aggregate(
            plan_stage.QueryPlan(limit=5), rows)
        self.assertEqual(chosen, [])
        self.assertEqual([j.name for j in near], ["Khớp một phần"])


# ------------------------------------------------------------- ⑤ compose

class ComposeTest(TestCase):
    def setUp(self):
        self.chosen = [_j("Lê Văn A", **{"năm sinh": "1999"})]
        self.sources = compose_stage.build_sources(self.chosen)

    def test_history_keeps_twelve_complete_question_answer_turns(self):
        history = [{"question": f"question {i}", "answer": f"answer {i}"}
                   for i in range(14)]
        block = compose_stage._history_block(history)
        self.assertNotIn("question 0", block)
        self.assertIn("question 2", block)
        self.assertIn("answer 13", block)

    def test_danh_so_nguon_theo_tung_trich_dan(self):
        self.assertEqual(self.sources[0]["n"], 1)
        self.assertEqual(self.sources[0]["name"], "Lê Văn A")

    def test_tim_nguoi_co_dieu_kien_phai_qua_model_viet(self):
        calls = []

        def caller(*args, **kwargs):
            calls.append(kwargs.get("task"))
            return FakeCompletion("Lê Văn A phù hợp nhờ kinh nghiệm đã nêu [1].")

        _text, _used, _sources, meta = compose_stage.compose(
            plan_stage.QueryPlan(shape="find_people", information_need="Senior Data Analyst"),
            self.chosen, [], {"count": {"reviewed": 60, "scope_total": 1000,
                                        "matched": 1, "scope": "all",
                                        "read_failed": False, "read_incomplete": False,
                                        "criteria_unknown": 0}}, complete_fn=caller)
        self.assertEqual(calls, [compose_stage.TASK])
        self.assertEqual(meta["model"], "fake-1")
        self.assertFalse(meta["fallback"])

    def test_nguoi_da_xac_dinh_duoc_gui_bang_chung_vao_model(self):
        row = Judgement(person_id=9, name="Nguyễn Tiến Đạt", relevant=False,
                        why="không thấy chứng chỉ", gap="chứng chỉ",
                        evidence=[{"document_id": 3, "ordinal": 0,
                                   "quote": "Android Engineer, Kotlin"}],
                        extracted={"chức danh": "Android Engineer"},
                        attribute_status={"chức danh": {"status": "FACT"}})
        captured = {}

        def caller(messages, **kwargs):
            captured["prompt"] = messages[-1]["content"]
            return FakeCompletion("Nguyễn Tiến Đạt là Android Engineer [1]; hồ sơ chưa ghi chứng chỉ.")

        text, used, sources, meta = compose_stage.compose(
            plan_stage.QueryPlan(shape="followup", information_need="chứng chỉ"), [], [],
            {"identified_people": [row.name], "identified_judgements": [row.as_dict()],
             "pinned": True, "read_failed": False}, complete_fn=caller)
        self.assertIn("nguoi_da_xac_dinh", captured["prompt"])
        self.assertIn("Android Engineer", captured["prompt"])
        self.assertEqual([source["document_id"] for source in sources], [3])
        self.assertEqual([source["n"] for source in used], [1])
        self.assertEqual(meta["model"], "fake-1")
        self.assertIn("chưa ghi chứng chỉ", text)

    def test_dem_chinh_xac_cung_phai_qua_model_viet(self):
        calls = []
        def writer(messages, **kwargs):
            calls.append(kwargs["task"])
            self.assertIn('"scope_total": 1075', messages[-1]["content"])
            return FakeCompletion("Trong toàn kho có 2 ứng viên tên Tùng.")

        text, _used, _sources, meta = compose_stage.compose(
            plan_stage.QueryPlan(shape="count", information_need="bao nhiêu người tên Tùng"),
            [], [], {"exact_name_count": {"query": "Tùng", "scope_total": 1075,
                                           "matched": 2, "people": []}},
            complete_fn=writer)
        self.assertEqual(calls, [compose_stage.TASK])
        self.assertEqual(meta["model"], "fake-1")
        self.assertIn("2 ứng viên", text)

    def test_trich_dan_ngoai_dai_bi_go_khoi_van_ban(self):
        text, used = compose_stage.used_sources("Anh A phù hợp [1], còn [7] thì không.",
                                                self.sources)
        self.assertNotIn("[7]", text)
        self.assertIn("[1]", text)
        self.assertEqual([s["n"] for s in used], [1])

    def test_trich_dan_gop_kieu_1_2_van_dem_duoc(self):
        """Model viết `[1,2]` rất thường xuyên — regex chỉ bắt `[n]` là đếm sót.

        Đo trên kho thật: hai câu trả lời tốt bị chấm "không trích dẫn nguồn
        nào" chỉ vì viết gộp, và trên giao diện `[1,2]` thành chữ thường bấm
        không được.
        """
        chosen = [_j("A", **{"x": "1"}), _j("B", **{"x": "2"})]
        sources = compose_stage.build_sources(chosen)
        text, used = compose_stage.used_sources("Hai người này hợp [1, 2].", sources)
        self.assertEqual([s["n"] for s in used], [1, 2])
        self.assertIn("[1,2]", text)

    def test_trich_dan_gop_co_so_sai_thi_chi_giu_so_dung(self):
        text, used = compose_stage.used_sources("Xem [1,9] nhé.", self.sources)
        self.assertEqual([s["n"] for s in used], [1])
        self.assertIn("[1]", text)
        self.assertNotIn("9", text)

    def test_cau_tra_loi_bi_cat_thi_thu_lai_roi_moi_bo_cuoc(self):
        """Đo trên kho thật: ⑤ trả về "Kho có 6 ứng viên đ" — cắt GIỮA CHỮ.

        ⑤ chạy model có bước suy nghĩ bị tước `reasoning_effort`, nên phần suy
        nghĩ ăn hết ngân sách token. Một mẩu câu dở tệ hơn bản tóm tắt khô khan.
        """
        budgets = []

        class Cut:
            truncated = True
            text = "Kho có 6 ứng viên đ"
            provider = model = "fake"

        def caller(messages, task="", **kwargs):
            budgets.append(kwargs.get("max_tokens"))
            return Cut()

        text, _used, _sources, meta = compose_stage.compose(
            plan_stage.QueryPlan(information_need="x"), self.chosen, [],
            {"judged": 6}, complete_fn=caller)
        self.assertEqual(budgets, [compose_stage.MAX_TOKENS,
                                   compose_stage.RETRY_MAX_TOKENS])
        self.assertTrue(meta["fallback"])
        self.assertNotIn("ứng viên đ", text)     # không đưa mẩu cụt cho người dùng

    def test_cat_du_dai_van_khong_duoc_coi_la_hoan_chinh(self):
        class Cut:
            truncated = True
            text = "Có 1 hồ sơ phù hợp: Lê Văn A [1]. " + "Chi tiết thêm. " * 20
            provider = model = "fake"

        text, _used, _sources, meta = compose_stage.compose(
            plan_stage.QueryPlan(information_need="x"), self.chosen, [], {},
            complete_fn=lambda *a, **k: Cut())
        self.assertTrue(meta["fallback"])
        self.assertIn("AI", text)
        self.assertNotIn("Lê Văn A", text)

    def test_model_hong_van_co_cau_tra_loi(self):
        def boom(*args, **kwargs):
            raise RuntimeError("hết quota")
        text, _used, _sources, meta = compose_stage.compose(
            plan_stage.QueryPlan(information_need="ai sinh năm 1999"),
            self.chosen, [], {"judged": 3}, complete_fn=boom)
        self.assertTrue(meta["fallback"])
        self.assertIn("AI", text)
        self.assertNotIn("Lê Văn A", text)

    def test_persona_va_loi_dan_di_vao_prompt_viet(self):
        messages = compose_stage.build_messages(
            plan_stage.QueryPlan(information_need="x"), self.chosen, [], {},
            self.sources, memories=["Tôi chỉ tuyển ở Hà Nội"])
        system, user_msg = messages[0]["content"], messages[1]["content"]
        self.assertIn("Radar", system)          # persona ổn định, không tự khai giọng
        self.assertIn("anh/chị", system)        # cách xưng hô theo tuỳ chọn
        self.assertIn("chỉ tuyển ở Hà Nội", user_msg)

    def test_khong_ai_thoa_thi_noi_thang(self):
        text = compose_stage.fallback_text(
            plan_stage.QueryPlan(information_need="phi hành gia"), [], {"judged": 40})
        self.assertIn("40", text)

    def test_doc_ho_so_gay_thi_khong_duoc_noi_kho_khong_co_ai(self):
        stats = {"judged": 0, "retrieved": 40, "read_failed": True}
        text = compose_stage.fallback_text(
            plan_stage.QueryPlan(information_need="quan hệ khách hàng"), [], stats)
        self.assertIn("40", text)
        self.assertIn("lỗi", text.lower())
        self.assertNotIn("Chưa tìm được hồ sơ nào", text)
        # Và ⑤ phải NHÌN THẤY cờ đó trong payload gửi model.
        payload = compose_stage.build_payload(
            plan_stage.QueryPlan(information_need="x"), [], [], stats, [])
        self.assertTrue(payload["loi_doc_ho_so"])
        self.assertEqual(payload["da_tim_thay"], 40)


    def test_unknown_va_chua_doc_khong_bi_noi_thanh_khong_phu_hop(self):
        stats = {"candidate_total": 12, "judged": 4, "unknown": 2,
                 "not_read": 8, "retrieved": 12}
        plan_obj = plan_stage.QueryPlan(information_need="SQL va Python")
        text = compose_stage.fallback_text(plan_obj, [], stats)
        self.assertIn("2", text)
        self.assertIn("8", text)
        self.assertIn("không có nghĩa là không phù hợp", text)
        payload = compose_stage.build_payload(plan_obj, [], [], stats, [])
        self.assertEqual(payload["candidate_total"], 12)
        self.assertEqual(payload["judged"], 4)
        self.assertEqual(payload["unknown"], 2)
        self.assertEqual(payload["not_read"], 8)


# ------------------------------------------------------- ② + toàn tuyến

class EngineEndToEndTest(TestCase):
    """Chạy trọn ①→⑤ trên dữ liệu thật trong DB, chỉ giả lập LLM."""

    def setUp(self):
        self.people = {}
        for name, year, level in [("Nguyễn Trẻ", 2001, "Cao đẳng"),
                                  ("Trần Vừa", 1996, "Cao đẳng"),
                                  ("Lê Già", 1988, "Cao đẳng")]:
            person = Person.objects.create(display_name=name)
            TalentProfile.objects.create(person=person, current_title="Chuyên viên")
            document = Document.objects.create(
                person=person, sha256=f"{abs(hash(name)):064x}"[:64],
                parsed_text=f"{name} sinh năm {year}, tốt nghiệp {level} Kinh tế.")
            text = (f"{name} sinh năm {year}. Tốt nghiệp {level} Kinh tế, "
                    "chuyên viên quan hệ khách hàng cá nhân tại ngân hàng.")
            CVChunk.objects.create(person=person, document=document, ordinal=0,
                                   fingerprint="f", text=text,
                                   text_norm=retrieve_stage._fold(text))
            PersonSearchDocument.objects.create(
                person=person, fingerprint="f", content=text,
                content_norm=retrieve_stage._fold(text))
            self.people[name] = person

    def _caller(self):
        def judge_reply(messages):
            payload = json.loads(messages[-1]["content"])
            rows = []
            for dossier in payload["ho_so"]:
                first = dossier["doan"][0]["text"]
                year = first.split("sinh năm ")[1][:4]
                rows.append({
                    "id": dossier["id"], "thoa": True, "do_tin": 0.9,
                    "vi_sao": "tốt nghiệp cao đẳng, làm quan hệ khách hàng",
                    "trich_dan": [{"doan": 1, "nguyen_van": f"sinh năm {year}"}],
                    "boc_duoc": {"năm sinh": year}})
            return json.dumps({"ket_qua": rows}, ensure_ascii=False)

        return replies({
            plan_stage.TASK: json.dumps({
                "shape": "find_people",
                "information_need": "2 ứng viên học cao đẳng ít tuổi nhất",
                "must_have": ["tốt nghiệp cao đẳng"],
                "extract": ["năm sinh"],
                "sort_by": {"key": "năm sinh", "dir": "desc"},
                "limit": 2,
                "search_queries": ["cao đẳng", "quan hệ khách hàng cá nhân"],
            }, ensure_ascii=False),
            judge_stage.TASK: judge_reply,
            compose_stage.TASK: "Có 2 ứng viên phù hợp: Nguyễn Trẻ (2001) [1] và "
                                "Trần Vừa (1996) [2].",
        })

    def test_dung_thu_tu_dung_so_luong_va_co_nguon(self):
        result = engine.answer("2 ứng viên học cao đẳng ít tuổi nhất",
                               complete_fn=self._caller())
        self.assertEqual([p["name"] for p in result.people],
                         ["Nguyễn Trẻ", "Trần Vừa"])
        self.assertEqual(result.trace["pass1"]["shown"], 2)
        self.assertTrue(result.sources)
        self.assertTrue(all(s["document_id"] for s in result.all_sources))

    def test_truy_hoi_khong_phu_thuoc_truong_co_cau_truc(self):
        """Chính lỗi cũ: `current_title` trống ⇒ scoring 0.0 ⇒ "0 hồ sơ"."""
        TalentProfile.objects.all().update(current_title="", skills=[])
        result = engine.answer("ứng viên quan hệ khách hàng",
                               complete_fn=self._caller())
        self.assertTrue(result.people)

    def test_pool_co_gian_theo_so_ho_so_nguoi_dung_muon(self):
        """③ tốn phần lớn token — hỏi 3 người thì đừng đọc sâu cả pool.
        Trần nâng 40→60 (kho sẽ lớn hơn nhiều); hệ số ×6 để câu "liệt kê hết"
        không bỏ sót."""
        self.assertEqual(retrieve_stage.pool_for(plan_stage.QueryPlan(limit=2)), 16)
        self.assertEqual(retrieve_stage.pool_for(plan_stage.QueryPlan(limit=10)), 60)
        self.assertEqual(retrieve_stage.pool_for(plan_stage.QueryPlan(limit=50)),
                         retrieve_stage.POOL)
        self.assertEqual(retrieve_stage.POOL, 60)

    def test_duong_stream_phai_co_ngan_sach_bang_muc_retry(self):
        """Stream không chữa được: chữ đã phát ra rồi, gọi lại là viết đè.

        Đường `complete` bị cắt thì retry với ngân sách lớn hơn. Đường stream —
        đường người dùng THẬT đi — phải phòng ngay từ đầu. Đo trên production:
        "tổng quan về kho ứng viên" bị cắt giữa chừng ở mức MAX_TOKENS.
        """
        sent = {}

        def fake_stream(messages, task="", **kwargs):
            sent.update(kwargs)
            yield {"type": "answer", "text": "xong"}
            yield {"type": "done", "completion": FakeCompletion("xong")}

        caller = replies({plan_stage.TASK: json.dumps(
            {"shape": "general", "search_queries": []})})
        list(engine.stream_answer("tìm ứng viên quan hệ khách hàng",
                                  complete_fn=caller, stream_fn=fake_stream,
                                  query_plan=plan_stage.QueryPlan(
                                      shape="find_people", search_queries=["x"])))
        self.assertEqual(sent["max_tokens"], compose_stage.RETRY_MAX_TOKENS)

    def test_cau_tong_hop_chi_lay_pool_toi_thieu(self):
        """Đo trên production: "tổng quan về kho" mất 90s với pool 40 — sát trần
        timeout của gunicorn, mà câu trả lời thật nằm ở số liệu toàn kho."""
        self.assertEqual(
            retrieve_stage.pool_for(plan_stage.QueryPlan(shape="analyze", limit=10)),
            retrieve_stage.MIN_POOL)

    def test_duoi_danh_sach_doc_nong_hon_dau_danh_sach(self):
        """Nhưng KHÔNG ai bị loại oan: mọi người vẫn có bằng chứng để ③ đọc."""
        query_plan = plan_stage.QueryPlan(
            information_need="cao đẳng", limit=10,
            search_queries=["cao đẳng", "quan hệ khách hàng"])
        candidates = retrieve_stage.retrieve(query_plan)
        self.assertTrue(candidates)
        for candidate in candidates:
            self.assertTrue(candidate.passages)

    def test_stream_phat_tien_do_roi_moi_phat_chu(self):
        def fake_stream(messages, task="", **kwargs):
            yield {"type": "answer", "text": "Có 2 ứng viên [1]."}
            yield {"type": "done", "completion": FakeCompletion("Có 2 ứng viên [1].")}

        chunks = list(engine.stream_answer(
            "ai học cao đẳng", complete_fn=self._caller(), stream_fn=fake_stream))
        kinds = [c["type"] for c in chunks]
        self.assertEqual(kinds[0], "step")
        self.assertEqual(kinds[-1], "done")
        # Tiến độ phải ra TRƯỚC chữ — màn hình không được đứng im lúc ①→④ chạy.
        self.assertLess(kinds.index("step"), kinds.index("answer"))
        # Các bước có nhãn đọc được, không phải token suy nghĩ.
        labels = [c["label"] for c in chunks if c["type"] == "step"]
        self.assertIn("Hiểu yêu cầu", labels)
        self.assertTrue(any("đọc" in lbl.lower() for lbl in labels))
        self.assertNotIn("reasoning", [c["type"] for c in chunks])
        self.assertEqual(chunks[-1]["result"].provider, "fake")

        # "Đã nhận yêu cầu — cách mình định làm": ra SAU khi hiểu câu hỏi,
        # TRƯỚC khi ②③ (chỗ tốn thời gian) chạy, và trước chữ trả lời.
        pre = next(c for c in chunks if c["type"] == "preamble")
        self.assertIn("cách làm", pre["text"].lower())
        self.assertLess(kinds.index("preamble"), kinds.index("answer"))
        # Không đợi ②③: preamble ra trước bước "Đọc hồ sơ".
        read_i = next(i for i, c in enumerate(chunks)
                      if c["type"] == "step" and "Đọc hồ sơ" in c["label"])
        self.assertLess(kinds.index("preamble"), read_i)

    def test_cau_hoi_pho_thong_re_sang_nhanh_hoi_thoai_khong_di_truy_hoi(self):
        """Không được đưa câu hỏi phổ thông qua ⑤ — nó viết bằng prompt tuyển dụng."""
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "general", "search_queries": []})})

        class FakeAdapter:
            def stream(self, request):
                from ai.adapter import ModelResponse
                yield {"type": "answer", "text": "Radar là trợ lý của MSB."}
                yield {"type": "done", "response": ModelResponse(
                    text="Radar là trợ lý của MSB.", provider="fake", model="glm")}

        result = engine.answer("Radar là gì?", complete_fn=caller,
                               adapter=FakeAdapter())
        self.assertEqual(result.people, [])
        self.assertNotIn("pass1", result.trace)
        self.assertEqual(result.trace["mode"], "chat")
        self.assertIn("trợ lý của MSB", result.text)
        self.assertEqual(result.model, "glm")

    def test_cau_hoi_can_du_lieu_ngoai_thi_tra_web_va_dan_nguon(self):
        """DuckDuckGo từng chạy qua `assistant_stream`; dồn về /ask/ là mất đường."""
        from ai.websearch import WebResult
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "general", "search_queries": []})})
        hit = WebResult(text="Lãi suất huy động hiện quanh 5%/năm.",
                        citations=[{"title": "SBV", "url": "https://sbv.gov.vn"}],
                        provider="duckduckgo", model="glm")

        class Intent:
            is_web = True

        with mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer",
                           return_value=hit) as web, \
                mock.patch("ai.intent.classify", return_value=Intent()):
            result = engine.answer("lãi suất huy động hiện nay?", complete_fn=caller)

        web.assert_called_once()
        self.assertIn("5%/năm", result.text)
        self.assertEqual(result.web_sources[0]["url"], "https://sbv.gov.vn")
        self.assertEqual(result.trace["mode"], "web")

    def test_cau_factual_khong_ro_rang_web_van_tra_khong_cho_intent_flag(self):
        """"Tổng giám đốc MSB là ai" — intent KHÔNG cờ is_web, nhưng trợ lý
        tuyển dụng không trả đúng từ trí nhớ được. Web bật thì phải tra."""
        from ai.websearch import WebResult
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "general", "search_queries": []})})
        hit = WebResult(text="Tổng giám đốc MSB là ông Nguyễn Hoàng Linh.",
                        citations=[{"title": "MSB", "url": "https://msb.com.vn"}],
                        provider="gemini_grounding", model="gemini")

        class Intent:
            is_web = False                          # intent KHÔNG cờ web

        with mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer",
                           return_value=hit) as web, \
                mock.patch("ai.intent.classify", return_value=Intent()):
            result = engine.answer("Tổng giám đốc MSB là ai?", complete_fn=caller)

        web.assert_called_once()
        self.assertIn("Nguyễn Hoàng Linh", result.text)
        self.assertEqual(result.trace["mode"], "web")

    def test_model_hoi_thoai_tra_rong_thi_thu_web_lan_cuoi(self):
        """Model hội thoại im lặng (câu factual nó không biết) → thử web trước
        khi buông "không có nội dung"."""
        from ai.websearch import WebResult
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "general", "search_queries": []})})

        class MuteAdapter:
            def stream(self, request):
                yield {"type": "done", "response": None}   # RỖNG

        hit = WebResult(text="Hà Nội hôm nay 28°C, nắng.",
                        citations=[{"title": "wt", "url": "https://w.com"}],
                        provider="ddg", model="x")

        class Intent:
            is_web = False

        calls = {"n": 0}

        def web_answer(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("lần đầu backend nghẽn")
            return hit

        with mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer", web_answer), \
                mock.patch("ai.intent.classify", return_value=Intent()):
            result = engine.answer("thời tiết Hà Nội hiện tại", complete_fn=caller,
                                   adapter=MuteAdapter())
        self.assertIn("28°C", result.text)
        self.assertEqual(calls["n"], 2)            # thử lại lần cuối sau khi model rỗng

    def test_web_TAT_thi_khong_tra_web_du_cau_factual(self):
        """`ASSISTANT_WEB_SEARCH=0` → không có backend nào bị gọi."""
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "general", "search_queries": []})})

        class FakeAdapter:
            def stream(self, request):
                yield {"type": "answer", "text": "Tôi không rõ."}
                yield {"type": "done", "response": None}

        with mock.patch("talent.answer.chat.websearch.enabled", return_value=False), \
                mock.patch("talent.answer.chat.websearch.web_answer") as web, \
                mock.patch("ai.intent.classify", return_value=_NoWeb()):
            engine.answer("Tổng giám đốc MSB là ai?", complete_fn=caller,
                          adapter=FakeAdapter())
        web.assert_not_called()

    def test_cau_hoi_chinh_sach_bi_xep_analyze_van_uu_tien_tai_lieu_noi_bo(self):
        """"Có quy định giới thiệu ứng viên cho MSB không" nhắc "ứng viên" nên ①
        (plan.py::mentions_store) không cho phép xếp "general", ra "analyze" —
        điều đúng cho câu hỏi tổng quan về KHO, nhưng đây là câu hỏi CHÍNH SÁCH
        công ty. Có tài liệu tri thức nội bộ khớp thì nó phải thắng và trả lời
        thẳng, không được chạy tiếp ②→⑤ tìm người rồi báo "kho không có dữ
        liệu quy định" (đúng lỗi báo cáo thật)."""
        caller = replies({
            plan_stage.TASK: json.dumps({
                "shape": "analyze",
                "search_queries": ["quy định giới thiệu ứng viên cho MSB"]})})

        class FakeAdapter:
            def stream(self, request):
                blob = "\n".join(str(m["content"]) for m in request.messages)
                assert "Quy định giới thiệu ứng viên" in blob
                yield {"type": "answer", "text": "Theo tài liệu nội bộ, nhân viên "
                                                  "giới thiệu ứng viên qua form X."}
                yield {"type": "done", "response": None}

        with mock.patch("ai.conversation.knowledge_sources",
                        return_value=[("Quy định giới thiệu ứng viên",
                                      "Nhân viên giới thiệu ứng viên qua form X.")]):
            result = engine.answer("có quy định giới thiệu ứng viên cho msb khôgn",
                                   complete_fn=caller, adapter=FakeAdapter())

        self.assertNotIn("pass1", result.trace)
        self.assertEqual(result.trace["mode"], "chat")
        self.assertIn("form X", result.text)

    def test_cau_hoi_analyze_that_ve_kho_khong_bi_lac_sang_hoi_thoai(self):
        """Không có tài liệu nội bộ khớp thì "analyze" vẫn chạy ②→⑤ như cũ —
        chỉ khi kho tri thức THỰC SỰ có câu trả lời mới đổi nhánh."""
        caller = replies({
            plan_stage.TASK: json.dumps({
                "shape": "analyze",
                "search_queries": ["tổng quan kho ứng viên"]})})

        with mock.patch("ai.conversation.knowledge_sources", return_value=[]):
            result = engine.answer("bạn đánh giá tổng quan về kho ứng viên thế nào",
                                   complete_fn=caller)

        self.assertIn("pass1", result.trace)
        self.assertNotEqual(result.trace.get("mode"), "chat")

    def test_cau_hoi_msb_that_bi_xep_nham_analyze_van_duoc_cuu_sang_web(self):
        """"Tổng giám đốc msb là ai" không nhắc cv/hồ sơ/ứng viên/kho — nếu ①
        vẫn lỡ xếp "analyze" (nhầm MSB ngân hàng với kho CV), không có tài liệu
        nội bộ nào khớp (đây là dữ kiện thời sự, không phải chính sách công ty),
        thì `mentions_store` phải bắt được và đẩy sang nhánh hội thoại có tra
        web — thay vì chạy ②→⑤ trên kho CV rồi báo "không tìm thấy"."""
        from ai.websearch import WebResult
        caller = replies({
            plan_stage.TASK: json.dumps({
                "shape": "analyze",
                "search_queries": ["tổng giám đốc msb"]})})
        hit = WebResult(text="Tổng giám đốc MSB là ông Nguyễn Hoàng Linh.",
                        citations=[{"title": "MSB", "url": "https://msb.com.vn"}],
                        provider="gemini_grounding", model="gemini")

        with mock.patch("ai.conversation.knowledge_sources", return_value=[]), \
                mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer",
                           return_value=hit) as web, \
                mock.patch("ai.intent.classify", return_value=_NoWeb()):
            result = engine.answer("tổng giám đốc msb là ai", complete_fn=caller)

        web.assert_called_once()
        self.assertNotIn("pass1", result.trace)
        self.assertIn("Nguyễn Hoàng Linh", result.text)

    def test_ke_hoach_loi_van_khong_bo_qua_kho_tri_thuc(self):
        """① lỗi (timeout/JSON hỏng/provider chết) luôn rơi về `_fallback()`,
        vốn LUÔN đặt shape="find_people" — một câu chính sách gặp đúng lúc ①
        trục trặc không được phép bỏ qua tài liệu nội bộ chỉ vì rơi vào nhánh
        mặc định (khác hẳn trường hợp "analyze" bị nhầm, đây là lỗi kỹ thuật
        của chính ①, không liên quan tới nội dung câu hỏi)."""
        def boom(*args, **kwargs):
            raise RuntimeError("provider chết")

        class _FakeAdapter:
            def stream(self, request):
                yield {"type": "answer",
                      "text": "Theo tài liệu nội bộ: đăng ký qua cổng Đại sứ tuyển dụng."}
                yield {"type": "done", "response": None}

        with mock.patch("ai.conversation.knowledge_sources",
                        return_value=[("Thể lệ giới thiệu ứng viên",
                                      "Đăng ký qua cổng Đại sứ tuyển dụng.")]), \
                mock.patch("talent.answer.chat.websearch.enabled", return_value=False):
            result = engine.answer(
                "cho tôi thể lệ và cách thức giới thiệu nội bộ ứng viên cho MSB",
                complete_fn=boom, adapter=_FakeAdapter())

        self.assertNotIn("pass1", result.trace)
        self.assertIn("Đại sứ tuyển dụng", result.text)

    def test_tra_web_hong_thi_lui_ve_hoi_thoai_chu_khong_tra_man_hinh_trang(self):
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "general", "search_queries": []})})

        class FakeAdapter:
            def stream(self, request):
                yield {"type": "answer", "text": "Tôi chưa tra được, nhưng…"}
                yield {"type": "done", "response": None}

        class Intent:
            is_web = True

        with mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer",
                           side_effect=RuntimeError("backend chết")), \
                mock.patch("ai.intent.classify", return_value=Intent()):
            result = engine.answer("tin tức hôm nay?", complete_fn=caller,
                                   adapter=FakeAdapter())
        self.assertIn("chưa tra được", result.text)
        self.assertEqual(result.trace["mode"], "chat")


class SuperlativeWholeStoreTest(TestCase):
    """"Ứng viên lớn tuổi nhất" — phải quét TOÀN kho, không phải top-N ngữ nghĩa.

    Dựng 5 người; người "già nhất" (sinh 1979) KHÔNG khớp câu hỏi về ngữ nghĩa
    (CV không nói gì đặc biệt) nên truy hồi ngữ nghĩa sẽ bỏ sót — đường cực trị
    tất định thì không.
    """

    def setUp(self):
        for name, year in [("An 1998", 1998), ("Bình 1992", 1992),
                           ("Cường 2001", 2001), ("Dũng 1979", 1979),
                           ("Em 1995", 1995)]:
            p = Person.objects.create(display_name=name)
            Document.objects.create(
                person=p, sha256=f"{abs(hash(name)):064x}"[:64],
                document_type="cv",
                parsed_text=f"Họ tên: {name}. Sinh năm {year}. "
                            "Nhân viên văn phòng, ngân hàng bán lẻ.")

    def _plan(self, need, key="năm sinh", direction="asc"):
        return plan_stage.QueryPlan(
            shape="find_people", information_need=need, search_queries=[need],
            sort_by={"key": key, "dir": direction}, limit=3)

    def test_lon_tuoi_nhat_lay_dung_nguoi_gia_nhat_toan_kho(self):
        from talent.answer import superlative
        attr = superlative.wants_whole_store(
            self._plan("ứng viên lớn tuổi nhất trong kho"))
        self.assertEqual(attr, "birth_year")
        chosen, stats = superlative.run(
            self._plan("ứng viên lớn tuổi nhất trong kho"), attr=attr)
        self.assertEqual([j.name for j in chosen][:1], ["Dũng 1979"])
        self.assertEqual(stats["coverage_have"], 5)
        self.assertEqual(stats["coverage_total"], 5)
        self.assertTrue(chosen[0].evidence)        # có nguồn [n] mở CV

    def test_tre_nhat_dao_chieu(self):
        from talent.answer import superlative
        chosen, _ = superlative.run(
            self._plan("3 ứng viên trẻ nhất trong kho", direction="desc"),
            attr="birth_year")
        self.assertEqual([j.name for j in chosen][:1], ["Cường 2001"])

    def test_co_bo_loc_khac_thi_KHONG_di_duong_cuc_tri(self):
        """"java dev nhiều KN nhất" — có tiêu chí kỹ năng → để đường ngữ nghĩa."""
        from talent.answer import superlative
        qp = plan_stage.QueryPlan(
            shape="find_people", information_need="java dev nhiều kinh nghiệm nhất",
            search_queries=["java"], should_have=["java", "spring"],
            sort_by={"key": "số năm kinh nghiệm", "dir": "desc"})
        self.assertIsNone(superlative.wants_whole_store(qp))

    def test_text_nam_o_ParsedTextVersion_van_doc_duoc(self):
        """Bug bắt được trên production 05/09: `parsed_text` (cột thô) rỗng cho
        TOÀN BỘ 433 Document thật — text nằm ở `ParsedTextVersion.text` qua
        `primary_text_version`. Đọc thẳng `.values_list("parsed_text")` bỏ qua
        `Document.best_text` (property nối hai nguồn) → 0/798 phủ, không lỗi,
        không cảnh báo, chỉ lặng lẽ vô dụng. Dựng ĐÚNG hình dạng đó: Document
        rỗng ở `parsed_text`, text thật nằm ở `primary_text_version`.
        """
        from people.models import ParsedTextVersion
        from talent.answer import superlative

        p = Person.objects.create(display_name="Phạm Thị Mai")
        version = ParsedTextVersion.objects.create(
            person=p, text_hash="h1", text_length=40,
            text="Phạm Thị Mai. Sinh năm 1983. Kế toán trưởng.")
        Document.objects.create(
            person=p, sha256="c" * 64, document_type="cv",
            parsed_text="",                          # RỖNG như production thật
            primary_text_version=version)

        # `setUp` đã dựng 5 người khác (parsed_text trực tiếp, không qua
        # primary_text_version) — người mới phải CỘNG THÊM vào độ phủ, không
        # thay thế, để bài test chứng minh CẢ HAI đường đọc cùng hoạt động.
        # Chỉ Dũng (1979) già hơn Mai (1983) nên limit=3 mặc định vẫn lọt Mai.
        chosen, stats = superlative.run(
            self._plan("ứng viên lớn tuổi nhất trong kho"), attr="birth_year")
        self.assertEqual(stats["coverage_have"], 6)
        self.assertIn("Phạm Thị Mai", [j.name for j in chosen])
        mai = next(j for j in chosen if j.name == "Phạm Thị Mai")
        self.assertIn("1983", mai.why)

    def test_engine_di_duong_cuc_tri_khong_goi_LLM_judge(self):
        from talent.answer import engine as engine_mod

        def boom_judge(messages, task="", **k):
            if task == "talent_answer_judge":
                raise AssertionError("KHÔNG được gọi ③ cho câu cực trị toàn kho")
            raise RuntimeError("no llm in test")

        def fake_stream(messages, task="", **kwargs):
            yield {"type": "answer", "text": "Người lớn tuổi nhất là Dũng 1979 [1]."}
            yield {"type": "done", "completion": FakeCompletion("x")}

        plan_obj = self._plan("ứng viên lớn tuổi nhất trong kho")
        chunks = list(engine_mod.stream_answer(
            "ứng viên lớn tuổi nhất trong kho", query_plan=plan_obj,
            complete_fn=boom_judge, stream_fn=fake_stream))
        done = next(c for c in chunks if c["type"] == "done")
        self.assertIn("cực trị", done["result"].trace.get("fast_path", ""))
        self.assertEqual(done["result"].trace["superlative"]["attr"], "birth_year")


class StructuredMustHaveTest(TestCase):
    """`must_have` khớp trường có cấu trúc → ghim trên TOÀN kho, không chỉ pool
    ngữ nghĩa. "must_have" nghĩa là BẮT BUỘC (plan.py); truy hồi ngữ nghĩa chỉ
    là xấp xỉ và có thể xếp người thoả THẬT xuống dưới hạng pool."""

    def _fact(self, person, field, value, fp, **extra):
        from intel.models import ExtractedFact
        return ExtractedFact.objects.create(
            person=person, field=field, raw_value=value, normalized_value=value,
            source_kind=ExtractedFact.SOURCE_AI, fingerprint=fp,
            status=extra.pop("status", ExtractedFact.STATUS_ACCEPTED),
            is_current=True, **extra)

    def test_khop_ky_nang_tren_toan_kho_khong_chi_pool(self):
        from talent.answer import structured_match

        co_python = Person.objects.create(display_name="Có Python")
        self._fact(co_python, "skills", "Python", "fp1")
        khong_co = Person.objects.create(display_name="Không liên quan")

        qp = plan_stage.QueryPlan(must_have=["biết kỹ năng Python"])
        pins = structured_match.must_have_pins(qp)
        self.assertEqual(pins, [co_python.pk])
        self.assertNotIn(khong_co.pk, pins)

    def test_so_nam_kinh_nghiem_doc_tu_TalentProfile(self):
        from talent.answer import structured_match

        p5 = Person.objects.create(display_name="5 năm KN")
        TalentProfile.objects.create(person=p5, years_experience=5)
        p1 = Person.objects.create(display_name="1 năm KN")
        TalentProfile.objects.create(person=p1, years_experience=1)

        qp = plan_stage.QueryPlan(must_have=["trên 3 năm kinh nghiệm"])
        pins = structured_match.must_have_pins(qp)
        self.assertIn(p5.pk, pins)
        self.assertNotIn(p1.pk, pins)

    def test_so_nam_kinh_nghiem_cung_doc_tu_ExtractedFact(self):
        """Bug bắt được trên production 05/09: chỉ đọc cột `TalentProfile` thì
        "trên 3 năm KN" ra 0 người dù `ExtractedFact` (AI mới bóc) đã có dữ
        liệu — coverage thấp của TalentProfile bị hiểu nhầm thành "không ai"."""
        from talent.answer import structured_match

        p = Person.objects.create(display_name="Chỉ có ở ExtractedFact")
        self._fact(p, "years_experience", "5 năm", "fp-years-1")
        # TalentProfile CỐ Ý không có years_experience cho người này.

        qp = plan_stage.QueryPlan(must_have=["trên 3 năm kinh nghiệm"])
        pins = structured_match.must_have_pins(qp)
        self.assertIn(p.pk, pins)

    def test_khop_noi_lam_viec_mong_muon_tren_TalentProfile(self):
        """"muốn làm ở Đà Nẵng" → đối chiếu `TalentProfile.desired_location`
        (Edge đã chuẩn hoá tên tỉnh khi đồng bộ). Alias "Sài Gòn"/"HCM" quy về
        tên chuẩn."""
        from talent.answer import structured_match

        dn = Person.objects.create(display_name="Muốn Đà Nẵng")
        TalentProfile.objects.create(person=dn, desired_location="Đà Nẵng")
        hcm = Person.objects.create(display_name="Muốn HCM")
        TalentProfile.objects.create(person=hcm, desired_location="Hồ Chí Minh, Bình Dương")
        hn = Person.objects.create(display_name="Muốn Hà Nội")
        TalentProfile.objects.create(person=hn, desired_location="Hà Nội")

        pins = structured_match.must_have_pins(
            plan_stage.QueryPlan(must_have=["ứng viên muốn làm việc ở Đà Nẵng"]))
        self.assertEqual(pins, [dn.pk])

        pins = structured_match.must_have_pins(
            plan_stage.QueryPlan(must_have=["muốn làm tại Sài Gòn"]))
        self.assertEqual(pins, [hcm.pk])

        pins = structured_match.must_have_pins(
            plan_stage.QueryPlan(must_have=["khu vực làm việc Bình Dương"]))
        self.assertEqual(pins, [hcm.pk])

    def test_cau_khong_co_tin_hieu_dia_diem_khong_kich_hoat_khop_location(self):
        """"python developer" KHÔNG được hiểu thành một địa danh."""
        from talent.answer import structured_match

        p = Person.objects.create(display_name="X")
        TalentProfile.objects.create(person=p, desired_location="Hà Nội")
        # không có tín hiệu địa điểm -> nhường ngữ nghĩa, không ghim theo location
        self.assertIsNone(structured_match.must_have_pins(
            plan_stage.QueryPlan(must_have=["python developer"])))

    def test_cau_chu_khong_quy_ve_duoc_truong_nao_thi_tra_None(self):
        """Không đoán bừa — nhường lại cho truy hồi ngữ nghĩa."""
        from talent.answer import structured_match
        qp = plan_stage.QueryPlan(must_have=["có tinh thần trách nhiệm cao"])
        self.assertIsNone(structured_match.must_have_pins(qp))

    def test_khong_co_must_have_thi_tra_None(self):
        from talent.answer import structured_match
        self.assertIsNone(structured_match.must_have_pins(plan_stage.QueryPlan()))

    def test_nguong_nam_kn_o_should_have_van_duoc_ghim(self):
        """Bug bắt được trên production 05/09: cùng câu hỏi ("trên 3 năm kinh
        nghiệm ngành ngân hàng"), plan.py (LLM, được dặn must_have "Rất ít")
        có lượt xếp vào should_have thay vì must_have — đảm bảo "rà soát toàn
        kho" không được phép phụ thuộc vào lựa chọn không ổn định đó cho đúng
        MỘT loại tiêu chí tất định (ngưỡng số năm KN)."""
        from talent.answer import structured_match

        p5 = Person.objects.create(display_name="5 năm KN")
        TalentProfile.objects.create(person=p5, years_experience=5)
        p1 = Person.objects.create(display_name="1 năm KN")
        TalentProfile.objects.create(person=p1, years_experience=1)

        qp = plan_stage.QueryPlan(must_have=[], should_have=["trên 3 năm kinh nghiệm"])
        pins = structured_match.must_have_pins(qp)
        self.assertIn(p5.pk, pins)
        self.assertNotIn(p1.pk, pins)

    def test_should_have_ky_nang_khong_bi_ghim_an(self):
        """Ngoại lệ CHỈ áp cho ngưỡng số năm KN — should_have về kỹ năng vẫn
        là "ưu tiên", không được ép thành ghim cứng (đúng thiết kế gốc)."""
        from talent.answer import structured_match

        co_python = Person.objects.create(display_name="Có Python")
        self._fact(co_python, "skills", "Python", "fp-should-1")

        qp = plan_stage.QueryPlan(must_have=[], should_have=["biết kỹ năng Python"])
        self.assertIsNone(structured_match.must_have_pins(qp))

    def test_khop_qua_nhieu_nguoi_thi_cat_co_tran(self):
        """Khớp nhiều là tin tốt (đủ ứng viên) — không đọc HẾT bằng LLM."""
        from talent.answer import structured_match
        for i in range(structured_match.MAX_STRUCTURED_PINS + 15):
            p = Person.objects.create(display_name=f"KN {i}")
            self._fact(p, "skills", "Excel", f"fp-many-{i}")
        qp = plan_stage.QueryPlan(must_have=["kỹ năng Excel"])
        pins = structured_match.must_have_pins(qp)
        self.assertEqual(len(pins), structured_match.MAX_STRUCTURED_PINS)

    def test_nhom_cau_truc_xep_theo_so_dieu_kien_khop_khong_theo_id(self):
        """Người vào hệ sau nhưng khớp nhiều điều kiện hơn phải đứng trước."""
        from talent.answer import structured_match

        one = Person.objects.create(display_name="Chỉ Excel")
        self._fact(one, "skills", "Excel", "fp-rank-1")
        two = Person.objects.create(display_name="Excel và ngân hàng")
        self._fact(two, "skills", "Excel", "fp-rank-2")
        self._fact(two, "industries", "Ngân hàng", "fp-rank-3")

        pins = structured_match.must_have_pins(plan_stage.QueryPlan(
            must_have=["biết kỹ năng Excel", "ngành Ngân hàng"]))
        self.assertEqual(pins[:2], [two.pk, one.pk])

    def test_engine_ghim_nguoi_khop_cau_truc_vao_pinned_ids(self):
        """Tích hợp: `_pipeline` phải gọi `structured_match` và cộng vào
        `pinned_ids` — kiểm ĐÚNG lớp này (ghim), không kiểm lại cách ③ đọc JSON
        (đã có bộ test riêng của `judge.py`)."""
        from talent.answer import engine as engine_mod

        p = Person.objects.create(display_name="Ứng Viên Python")
        self._fact(p, "skills", "Python", "fp-engine-1")

        captured = {}
        qp = plan_stage.QueryPlan(shape="find_people", information_need="tìm Python",
                                  search_queries=["python developer"],
                                  must_have=["biết kỹ năng Python"])

        real_retrieve = retrieve_stage.retrieve

        def spy_retrieve(active_plan, **kwargs):
            captured["pinned_ids"] = list(kwargs.get("pinned_ids") or [])
            return real_retrieve(active_plan, **kwargs)

        with mock.patch("talent.answer.engine.retrieve_stage.retrieve", spy_retrieve), \
                mock.patch("talent.answer.engine.judge_stage.judge",
                          return_value=judge_stage.JudgeReport([])):
            gen = engine_mod._pipeline("tìm Python", query_plan=qp, complete_fn=None)
            try:
                while True:
                    next(gen)
            except StopIteration as stop:
                _qp, _chosen, _near, _stats, trace = stop.value

        self.assertIn("structured_pins", trace)
        self.assertGreaterEqual(trace["structured_pins"], 1)
        self.assertIn(p.pk, captured["pinned_ids"])
        self.assertEqual(_stats["identified_people"], [])
        self.assertEqual(_stats["identified_judgements"], [])


# ------------------------- Radar phải BIẾT nó có dữ liệu gì (ảnh production)

class _NoWeb:
    """Ý định giả: không tra web. Tránh gọi bộ phân loại thật trong test."""
    is_web = False


class KnowsItsOwnStoreTest(TestCase):
    """Ảnh người dùng gửi: hỏi "thế bạn có cv những ngành nào", Radar đáp
    "không có dữ liệu thực tế về danh sách ngành nghề" — trong khi kho có 786
    hồ sơ. Đây là kiểu sai tệ nhất: chối bỏ dữ liệu mình đang có.
    """

    def setUp(self):
        for name, title, industries in [
            ("Nguyễn Ngân Hàng", "Chuyên viên QHKH", ["Ngân hàng"]),
            ("Trần Công Nghệ", "Lập trình viên", ["Công nghệ"]),
            ("Lê Ngân Hàng Hai", "Giao dịch viên", ["Ngân hàng"]),
        ]:
            person = Person.objects.create(display_name=name)
            TalentProfile.objects.create(person=person, current_title=title,
                                         industries=industries, location="Hà Nội")

    def test_cau_hoi_ve_kho_khong_duoc_xep_thanh_general(self):
        """Chốt chặn CODE: model xếp nhầm thì vẫn phải bị ép về nhánh có dữ liệu."""
        for question in ["thế bạn có cv những ngành nào",
                         "bạn đánh giá và đưa ra tổng quan về kho ứng viên",
                         "kho mình có dữ liệu gì",
                         "bạn xem có CV nào ngành tuyển dụng k"]:
            with self.subTest(question=question):
                caller = replies({plan_stage.TASK: json.dumps(
                    {"shape": "general", "search_queries": []})})
                result = plan_stage.plan(question, complete_fn=caller)
                self.assertNotEqual(result.shape, "general")
                self.assertTrue(result.needs_people)

    def test_cau_hoi_that_su_chung_van_la_general(self):
        """Chốt chặn không được rộng tay tới mức nuốt cả câu hỏi thường."""
        for question in ["Radar là gì?", "xin chào", "lãi suất hôm nay bao nhiêu?"]:
            with self.subTest(question=question):
                caller = replies({plan_stage.TASK: json.dumps(
                    {"shape": "general", "search_queries": []})})
                self.assertEqual(plan_stage.plan(question, complete_fn=caller).shape,
                                 "general")

    def test_so_lieu_kho_co_kem_do_phu(self):
        """Bảng xếp hạng không kèm độ phủ là con số gây hiểu nhầm."""
        data = corpus_stage.overview()
        self.assertEqual(data["quy_mo"]["tong_ho_so"], 3)
        nganh = data["nganh"]
        self.assertEqual(nganh["filled"], 3)
        self.assertEqual(nganh["top"][0], {"value": "Ngân hàng", "count": 2})
        self.assertEqual(nganh["coverage"], 1.0)

    def test_truong_trong_thi_noi_thang_chua_du_de_thong_ke(self):
        TalentProfile.objects.all().update(industries=[])
        block = corpus_stage.overview()["nganh"]
        self.assertFalse(block["meaningful"])
        self.assertIn("chưa đủ để thống kê", corpus_stage.facts_for_prompt())

    def test_nhanh_hoi_thoai_duoc_bom_so_lieu_that(self):
        """Không có bước này thì Radar nói "tôi không có dữ liệu"."""
        sent = {}

        class FakeAdapter:
            def stream(self, request):
                sent["messages"] = request.messages
                yield {"type": "answer", "text": "ok"}
                yield {"type": "done", "response": None}

        # `intent` cấp sẵn để `stream_chat` không đi phân loại lại — phân loại
        # là một lượt gọi model thật, bộ test không được phụ thuộc nhà cung cấp.
        list(chat_stage.stream_chat("bạn có cv những ngành nào",
                                    adapter=FakeAdapter(), intent=_NoWeb()))
        blob = json.dumps(sent["messages"], ensure_ascii=False)
        self.assertIn("SỐ LIỆU THẬT VỀ KHO", blob)
        self.assertIn("Ngân hàng", blob)

    def test_cau_hoi_thuong_khong_bom_so_lieu_kho(self):
        sent = {}

        class FakeAdapter:
            def stream(self, request):
                sent["messages"] = request.messages
                yield {"type": "answer", "text": "ok"}
                yield {"type": "done", "response": None}

        list(chat_stage.stream_chat("thời tiết hôm nay thế nào",
                                    adapter=FakeAdapter(), intent=_NoWeb()))
        self.assertNotIn("SỐ LIỆU THẬT VỀ KHO",
                         json.dumps(sent["messages"], ensure_ascii=False))

    def test_cau_hoi_tong_hop_duoc_cap_so_lieu_toan_kho_cho_chang_viet(self):
        """40 hồ sơ truy hồi được không nói lên gì về toàn kho."""
        messages = compose_stage.build_messages(
            plan_stage.QueryPlan(shape="analyze", information_need="tổng quan kho"),
            [], [], {}, [], corpus_facts=corpus_stage.facts_for_prompt())
        self.assertIn("SỐ LIỆU THẬT VỀ KHO", messages[-1]["content"])

    def test_tron_chuoi_cau_dem_khong_cham_vao_truy_hoi(self):
        """Câu đếm lấy số thật rẻ rồi giao AI diễn đạt.

        Trước đây nó chạy ②③ trên 40 hồ sơ (~35s, ~38.000 token) rồi vẫn không
        đếm được gì cho 786 hồ sơ.
        """
        caller = replies({
            plan_stage.TASK: json.dumps(
                {"shape": "count", "information_need": "kho có bao nhiêu hồ sơ",
                 "search_queries": ["hồ sơ"]}, ensure_ascii=False),
            compose_stage.TASK: lambda messages: (
                "Kho có 3 hồ sơ." if '"total_count": 3' in messages[-1]["content"]
                else "KHÔNG ĐƯỢC CẤP SỐ LIỆU"),
        })
        with mock.patch("talent.answer.retrieve.retrieve") as retrieved, \
                mock.patch("talent.answer.judge.judge") as judged:
            result = engine.answer("kho có bao nhiêu hồ sơ?", complete_fn=caller)
        retrieved.assert_not_called()
        judged.assert_not_called()
        self.assertIn("fast_path", result.trace)
        self.assertEqual(result.text, "Kho có 3 hồ sơ.")
        self.assertEqual(
            [call["task"] for call in caller.seen],
            [plan_stage.TASK, compose_stage.TASK],
        )

    def test_tron_chuoi_cau_hoi_ve_nganh_khong_bi_day_sang_hoi_thoai(self):
        """Đúng câu trong ảnh: phải đi nhánh có dữ liệu, không phải nhánh chat."""
        caller = replies({
            plan_stage.TASK: json.dumps(
                {"shape": "general", "search_queries": []}),   # ① xếp NHẦM
            compose_stage.TASK: lambda messages: (
                "Kho có 3 hồ sơ, ngành phổ biến nhất là Ngân hàng (2)."
                if "SỐ LIỆU THẬT VỀ KHO" in messages[-1]["content"] else "SAI"),
        })

        class Boom:
            def stream(self, request):
                raise AssertionError("không được rẽ sang nhánh hội thoại")

        result = engine.answer("thế bạn có cv những ngành nào",
                               complete_fn=caller, adapter=Boom())
        self.assertIn("Ngân hàng", result.text)

    def test_cau_tim_nguoi_khong_ton_tien_tinh_so_lieu_kho(self):
        from talent.answer import engine as engine_mod
        self.assertEqual(
            engine_mod._corpus_facts(plan_stage.QueryPlan(shape="find_people")), "")
        self.assertTrue(
            engine_mod._corpus_facts(plan_stage.QueryPlan(shape="analyze")))


# -------------------------------------------------- cache ②③④ (GĐ D)

class _WantsWeb:
    """Ý định giả: bộ phân loại nói câu này cần tra web."""
    is_web = True


class InternalKnowledgeBeatsWebTest(TestCase):
    """Một câu hỏi chính sách công ty có thể hợp lý bị bộ phân loại ý định gắn
    nhãn "web" (nó không biết gì về kho tri thức nội bộ). Tài liệu nội bộ
    KHÔNG được thắng tuyệt đối một mình — nó có thể đã lỗi thời (ví dụ tên
    lãnh đạo trong một văn bản cũ) — nên vẫn phải tra Internet song song và
    ghép làm hai nguồn cho model tự đối chiếu."""

    class _FakeAdapter:
        def __init__(self):
            self.sent = None

        def stream(self, request):
            self.sent = request.messages
            yield {"type": "answer", "text": "ok"}
            yield {"type": "done", "response": None}

    def test_internal_knowledge_khong_chan_tra_web_song_song(self):
        adapter = self._FakeAdapter()
        web_result = SimpleNamespace(
            text="Không có thay đổi nào được công bố.",
            citations=[{"title": "MSB", "url": "https://msb.com.vn/x"}],
            provider="tavily", model="", queries=["quy trình nghỉ phép MSB"])
        with mock.patch(
                "talent.answer.chat.knowledge_sources",
                return_value=[("Quy trình nghỉ phép", "Nhân viên được nghỉ 12 ngày phép năm.")]), \
                mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer",
                          return_value=web_result) as web_answer:
            chunks = list(chat_stage.stream_chat(
                "quy trình nghỉ phép của công ty là gì",
                adapter=adapter, intent=_WantsWeb()))
        web_answer.assert_called_once()
        done = next(c for c in chunks if c.get("type") == "done")
        self.assertEqual(done["payload"]["mode"], "chat")
        self.assertEqual(done["payload"]["web_sources"], web_result.citations)
        blob = json.dumps(adapter.sent, ensure_ascii=False)
        self.assertIn("Nhân viên được nghỉ 12 ngày phép năm", blob)
        self.assertIn("Quy trình nghỉ phép", blob)
        self.assertIn("Không có thay đổi nào được công bố", blob)

    def test_web_hong_van_lui_ve_tai_lieu_noi_bo(self):
        """Web lỗi (backend chết/hết hạn mức) thì vẫn còn tài liệu nội bộ để
        trả lời — không được để cả lượt hỏng theo."""
        adapter = self._FakeAdapter()
        with mock.patch(
                "talent.answer.chat.knowledge_sources",
                return_value=[("Quy trình nghỉ phép", "Nhân viên được nghỉ 12 ngày phép năm.")]), \
                mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer",
                          side_effect=RuntimeError("backend chết")) as web_answer:
            chunks = list(chat_stage.stream_chat(
                "quy trình nghỉ phép của công ty là gì",
                adapter=adapter, intent=_WantsWeb()))
        web_answer.assert_called_once()
        done = next(c for c in chunks if c.get("type") == "done")
        self.assertEqual(done["payload"]["mode"], "chat")
        blob = json.dumps(adapter.sent, ensure_ascii=False)
        self.assertIn("Nhân viên được nghỉ 12 ngày phép năm", blob)

    def test_no_internal_knowledge_still_goes_to_web(self):
        """Chốt lại hành vi cũ: câu hỏi không khớp tài liệu nào vẫn tra web như trước."""
        adapter = self._FakeAdapter()
        fake_result = SimpleNamespace(
            text="Trời nắng.", citations=[{"title": "Báo thời tiết", "url": "https://x"}],
            provider="tavily", model="", queries=["thời tiết hà nội"])
        with mock.patch("talent.answer.chat.knowledge_sources", return_value=[]), \
                mock.patch("talent.answer.chat.websearch.enabled", return_value=True), \
                mock.patch("talent.answer.chat.websearch.web_answer", return_value=fake_result) as web_answer:
            chunks = list(chat_stage.stream_chat(
                "thời tiết hà nội hôm nay", adapter=adapter, intent=_WantsWeb()))
        web_answer.assert_called_once()
        self.assertTrue(any(c.get("type") == "done" and c.get("payload", {}).get("mode") == "web"
                            for c in chunks))
        self.assertIsNone(adapter.sent)  # không rơi xuống nhánh hội thoại thường


class SmalltalkTest(TestCase):
    """Người dùng gõ "xin chào" và nhận lại nguyên quy trình "GIỚI THIỆU ỨNG
    VIÊN" (ảnh báo lỗi 16/09). Nguyên nhân: bộ truy hồi luôn trả top-k tài liệu
    bất kể liên quan hay không, nên một câu chào vẫn kéo về một tài liệu nội bộ
    ngẫu nhiên, rồi model ngoan ngoãn tóm tắt đúng tài liệu đó."""

    class _FakeAdapter:
        def __init__(self):
            self.sent = None

        def stream(self, request):
            self.sent = request.messages
            yield {"type": "answer", "text": "Chào anh/chị, Radar có thể giúp gì?"}
            yield {"type": "done", "response": None}

    def test_cau_chao_khong_tra_kho_khong_tra_web(self):
        adapter = self._FakeAdapter()
        with mock.patch("talent.answer.chat.knowledge_sources",
                        return_value=[("Thong tin chung",
                                       "Truy cập mục GIỚI THIỆU ỨNG VIÊN bằng tài khoản Outlook.")]) as kb,                 mock.patch("talent.answer.chat.websearch.enabled", return_value=True),                 mock.patch("talent.answer.chat.websearch.web_answer") as web_answer:
            chunks = list(chat_stage.stream_chat("xin chào", adapter=adapter))
        kb.assert_not_called()
        web_answer.assert_not_called()
        blob = json.dumps(adapter.sent, ensure_ascii=False)
        self.assertNotIn("GIỚI THIỆU ỨNG VIÊN", blob)
        done = next(c for c in chunks if c.get("type") == "done")
        self.assertEqual(done["payload"]["mode"], "chat")
        # Không còn bước "tra internet" nào để hiện trên thẻ tiến trình.
        self.assertEqual([c.get("stage") for c in chunks if c.get("type") == "stage"],
                         ["chat"])

    def test_cau_hoi_that_van_tra_kho_nhu_cu(self):
        """Giữ HẸP: câu dài hơn, dù mở đầu bằng lời chào, vẫn đi đường thường."""
        adapter = self._FakeAdapter()
        with mock.patch("talent.answer.chat.knowledge_sources",
                        return_value=[("Quy trình nghỉ phép", "Nghỉ 12 ngày phép năm.")]) as kb,                 mock.patch("talent.answer.chat.websearch.enabled", return_value=False):
            list(chat_stage.stream_chat("chào bạn, quy trình nghỉ phép thế nào",
                                        adapter=adapter))
        kb.assert_called_once()
        self.assertIn("Nghỉ 12 ngày phép năm", json.dumps(adapter.sent, ensure_ascii=False))

    def test_tra_noi_bo_co_buoc_rieng_tren_giao_dien(self):
        """Trước đây bước tra `knowledge_sources()` chạy hoàn toàn im lặng —
        người dùng chỉ thấy "Tra trên internet" và tưởng nội bộ chưa hề được
        tra (dù nó có chạy, chỉ trả rỗng). Giờ phải có một bước riêng hiện ra."""
        adapter = self._FakeAdapter()
        with mock.patch("talent.answer.chat.knowledge_sources", return_value=[]) as kb,                 mock.patch("talent.answer.chat.websearch.enabled", return_value=False):
            chunks = list(chat_stage.stream_chat(
                "cho tôi thể lệ giới thiệu nội bộ ứng viên cho MSB", adapter=adapter))
        kb.assert_called_once()
        stages = [c.get("stage") for c in chunks if c.get("type") == "stage"]
        self.assertEqual(stages, ["knowledge", "chat"])

    def test_nhan_dien_cac_bien_the_chao_hoi(self):
        for text in ("xin chào", "Chào bạn", "hello", "Hi", "cảm ơn nhé",
                     "ok", "tạm biệt", "xin chào Radar"):
            self.assertTrue(chat_stage._is_smalltalk(text), text)
        for text in ("chào bạn, tìm giúp tôi ứng viên Java",
                     "cảm ơn, giờ cho tôi xem hồ sơ Nguyễn An",
                     "lãi suất huy động hiện nay thế nào"):
            self.assertFalse(chat_stage._is_smalltalk(text), text)


class PipelineCacheTest(TestCase):
    """Hỏi lại một câu = ~38.700 token nếu không nhớ gì. ③ chiếm 75% trong đó."""

    def setUp(self):
        cache.clear()
        person = Person.objects.create(display_name="Nguyễn Cache")
        TalentProfile.objects.create(person=person)
        document = Document.objects.create(person=person, sha256="d" * 64,
                                           parsed_text="Chuyên viên quan hệ khách hàng.")
        text = "Nguyễn Cache: chuyên viên quan hệ khách hàng cá nhân, sinh năm 1994."
        CVChunk.objects.create(person=person, document=document, ordinal=0,
                               fingerprint="f", text=text,
                               text_norm=retrieve_stage._fold(text))
        PersonSearchDocument.objects.create(person=person, fingerprint="f",
                                            content=text,
                                            content_norm=retrieve_stage._fold(text))
        self.person = person
        self.plan = plan_stage.QueryPlan(
            information_need="quan hệ khách hàng", limit=5,
            search_queries=["quan hệ khách hàng"])

    def _judgement(self):
        return Judgement(person_id=self.person.pk, name="Nguyễn Cache", relevant=True,
                         confidence=0.9, why="khớp",
                         evidence=[{"document_id": 1, "ordinal": 0, "quote": "x"}])

    def test_luot_thu_hai_khong_goi_lai_chang_doc(self):
        key = cache_stage.key_for("ai làm quan hệ khách hàng?")
        self.assertIsNotNone(key)
        cache_stage.save(key, [self._judgement()], 12)

        with mock.patch("talent.answer.judge.judge") as judged:
            loaded = cache_stage.load(key)
        judged.assert_not_called()
        judgements, retrieved = loaded
        self.assertEqual(judgements[0].name, "Nguyễn Cache")
        self.assertEqual(judgements[0].evidence[0]["quote"], "x")
        self.assertEqual(retrieved, 12)

    def test_pipeline_luot_hai_hits_cache_with_same_executed_plan(self):
        candidate = retrieve_stage.Candidate(
            self.person.pk, "Nguyễn Cache", passages=[retrieve_stage.Passage(
                self.person.pk, self.person.documents.first().pk, 0,
                "Chuyên viên quan hệ khách hàng.")])
        report = judge_stage.JudgeReport([self._judgement()])
        with mock.patch("talent.answer.retrieve.retrieve", return_value=[candidate]), \
             mock.patch("talent.answer.judge.judge", return_value=report) as judged:
            first = engine._drain(engine._pipeline(
                "ai làm quan hệ khách hàng?", query_plan=self.plan))
            second = engine._drain(engine._pipeline(
                "ai làm quan hệ khách hàng?", query_plan=self.plan))
        self.assertEqual(judged.call_count, 1)
        self.assertEqual(first[-1]["cache"], "miss")
        self.assertEqual(second[-1]["cache"], "hit")

    def test_khoa_chuan_hoa_cau_hoi_va_ke_hoach_tuong_duong(self):
        first = plan_stage.QueryPlan(shape="find_people", must_have=["SQL", "Hà Nội"],
                                     search_queries=["Data SQL", "phân tích dữ liệu"])
        second = plan_stage.QueryPlan(shape="FIND_PEOPLE", must_have=[" hà nội ", "sql"],
                                      search_queries=["PHÂN TÍCH DỮ LIỆU", "data  sql"])
        a = cache_stage.key_for("Tìm  ứng viên  QUAN HỆ khách hàng ", query_plan=first)
        b = cache_stage.key_for("tìm ứng viên quan hệ khách hàng", query_plan=second)
        self.assertEqual(a, b)

    def test_ke_hoach_khac_dieu_kien_hoac_truy_hoi_khong_dung_chung_cache(self):
        base = plan_stage.QueryPlan(shape="find_people", must_have=["SQL"],
                                    search_queries=["Data SQL"])
        changed_constraint = plan_stage.QueryPlan(
            shape="find_people", must_have=["SQL", "Python"], search_queries=["Data SQL"])
        changed_retrieval = plan_stage.QueryPlan(
            shape="find_people", must_have=["SQL"], search_queries=["Data warehouse SQL"])
        changed_pool = plan_stage.QueryPlan(
            shape="find_people", must_have=["SQL"], search_queries=["Data SQL"], limit=50)
        keys = {cache_stage.key_for("tìm người", query_plan=p)
                for p in (base, changed_constraint, changed_retrieval, changed_pool)}
        self.assertEqual(len(keys), 4)

    def test_ngu_canh_luot_truoc_nam_trong_khoa(self):
        """"so sánh hai người đầu" nghĩa khác nhau tuỳ danh sách đang nói tới."""
        from types import SimpleNamespace
        empty = SimpleNamespace(projection=SimpleNamespace(last_result={}))
        with_people = SimpleNamespace(projection=SimpleNamespace(
            last_result={"items": [{"id": self.person.pk, "name": "x"}]}))
        self.assertNotEqual(cache_stage.key_for("so sánh hai người đầu",
                                                envelope=empty),
                            cache_stage.key_for("so sánh hai người đầu",
                                                envelope=with_people))

    def test_kho_doi_thi_khoa_doi_theo(self):
        """Nhập hồ sơ mới xong không ai phải nhớ đi xoá cache."""
        before = cache_stage.key_for("quan hệ khách hàng")
        other = Person.objects.create(display_name="Người Mới")
        PersonSearchDocument.objects.create(person=other, fingerprint="g",
                                            content="x", content_norm="x")
        self.assertNotEqual(before, cache_stage.key_for("quan hệ khách hàng"))

    def test_hai_tai_khoan_khac_quyen_khong_dung_chung_muc(self):
        """Hai tài khoản không bao giờ dùng chung một mục cache.

        Không phải vì ② đang lọc theo quyền — hôm nay nó KHÔNG lọc, và đó là
        đúng thiết kế (phân quyền Talent ở cấp module, xem
        `core/answer/cache.py::key_for`). Đây là lưới đỡ phòng xa: ngày ai đó
        thêm lọc cấp dòng, cache đã không thể là đường rò sẵn.
        """
        from accounts import roles
        roles.ensure_groups()
        a = User.objects.create_user("cache-a", password="mat-khau-dai-1")
        b = User.objects.create_user("cache-b", password="mat-khau-dai-1")
        self.assertNotEqual(cache_stage.key_for("quan hệ khách hàng", user=a),
                            cache_stage.key_for("quan hệ khách hàng", user=b))

    def test_prompt_or_effective_route_change_invalidates_key(self):
        from ai.models import TaskModelRoute
        from ai.router import reset_router
        baseline = cache_stage.key_for("quan hệ khách hàng")
        with mock.patch("talent.answer.judge.SYSTEM", judge_stage.SYSTEM + " changed"):
            self.assertNotEqual(baseline, cache_stage.key_for("quan hệ khách hàng"))
        route = TaskModelRoute.objects.get(task=judge_stage.TASK)
        route.model += "-changed"
        route.save(update_fields=["model", "updated_at"])
        reset_router()  # settings write does this in the serving worker
        self.assertNotEqual(baseline, cache_stage.key_for("quan hệ khách hàng"))

    def test_execution_fingerprint_is_reused_without_database_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        cache_stage.execution_fingerprint()
        with CaptureQueriesContext(connection) as captured:
            self.assertTrue(cache_stage.execution_fingerprint())
        self.assertEqual(len(captured), 0)

    def test_role_and_module_permission_changes_invalidate_same_users_key(self):
        from accounts import roles
        from accounts.models import RoleModuleAccess
        roles.ensure_groups()
        user = User.objects.create_user("cache-role", password="mat-khau-dai-1")
        before = cache_stage.key_for("quan hệ khách hàng", user=user)
        user.groups.add(Group.objects.get(name=roles.RECRUITER))
        after_role = cache_stage.key_for("quan hệ khách hàng", user=user)
        self.assertNotEqual(before, after_role)
        RoleModuleAccess.objects.create(role=roles.RECRUITER,
                                        module=roles.MODULE_TALENT, allowed=False)
        self.assertNotEqual(after_role,
                            cache_stage.key_for("quan hệ khách hàng", user=user))

    def test_person_eligibility_and_unindexed_document_change_invalidate_corpus(self):
        from datetime import timedelta
        from django.utils import timezone
        old = timezone.now() - timedelta(days=1)
        Person.objects.filter(pk=self.person.pk).update(updated_at=old)
        Document.objects.filter(person=self.person).update(updated_at=old)
        self.person.refresh_from_db()
        before = cache_stage.key_for("quan hệ khách hàng")
        self.person.display_name = "Nguyễn Cache Mới"
        self.person.save(update_fields=["display_name", "updated_at"])
        after_person = cache_stage.key_for("quan hệ khách hàng")
        self.assertNotEqual(before, after_person)
        document = self.person.documents.first()
        document.parsed_text += " Có thêm bằng chứng mới."
        document.save(update_fields=["parsed_text", "updated_at"])
        self.assertNotEqual(after_person, cache_stage.key_for("quan hệ khách hàng"))

    def test_khong_luu_luot_bi_gay(self):
        """Lưu một lượt ③ gãy là đóng đinh câu trả lời sai suốt sáu tiếng."""
        caller = replies({
            plan_stage.TASK: json.dumps(
                {"shape": "find_people", "search_queries": ["quan hệ khách hàng"]}),
            judge_stage.TASK: "",          # mọi lô hỏng ⇒ JudgeReport.broken
            compose_stage.TASK: "Chưa đọc được hồ sơ."})
        engine.answer("ai làm quan hệ khách hàng?", complete_fn=caller)
        self.assertIsNone(
            cache_stage.load(cache_stage.key_for("ai làm quan hệ khách hàng?")))


# ------------------------------------------------ vòng TỰ SỬA của ⑤

def _pipeline_returning(value):
    """`_pipeline` nay là generator (`yield` bước, `return` tuple). Mock phải là
    generator có `return` đúng tuple, không phải hàm trả tuple."""
    def gen(*_a, **_k):
        return value
        yield                                        # pragma: no cover
    return gen


class VerifyTest(TestCase):
    """② có `widen()` khi truy hồi mỏng; ⑤ trước đây không có gì bắt lỗi."""

    def _chosen(self, *names):
        return [Judgement(person_id=i, name=name, relevant=True, confidence=0.9,
                          evidence=[{"document_id": 1, "ordinal": 0, "quote": "x"}])
                for i, name in enumerate(names, start=1)]

    def test_ke_sai_thu_tu_thi_bi_bat(self):
        """④ đã sắp tất định; ⑤ kể ngược lại là đưa người đọc một bảng xếp hạng sai."""
        chosen = self._chosen("An", "Bình", "Cường")
        plan_obj = plan_stage.QueryPlan(sort_by={"key": "năm sinh", "dir": "desc"})
        problems = verify_stage.check(
            plan_obj, chosen, "Đầu tiên là Cường [1], rồi An [2], rồi Bình [3].", [])
        self.assertTrue(any("Thứ tự" in p for p in problems))

    def test_ke_dung_thu_tu_thi_khong_bao_gi(self):
        chosen = self._chosen("An", "Bình", "Cường")
        plan_obj = plan_stage.QueryPlan(sort_by={"key": "năm sinh", "dir": "desc"})
        self.assertEqual(verify_stage.check(
            plan_obj, chosen, "An [1] trước, Bình [2], cuối là Cường [3].",
            compose_stage.build_sources(chosen)), [])

    def test_ke_nhieu_hon_so_duoc_xin(self):
        chosen = self._chosen("An", "Bình", "Cường")
        problems = verify_stage.check(
            plan_stage.QueryPlan(limit=2), chosen, "An [1], Bình [2], Cường [3].", [])
        self.assertTrue(any("chỉ xin" in p for p in problems))

    def test_neu_ten_ma_khong_co_nguon(self):
        problems = verify_stage.check(
            plan_stage.QueryPlan(limit=5), self._chosen("An"), "An rất phù hợp.", [])
        self.assertTrue(any("trích dẫn" in p for p in problems))

    def test_trich_dan_phai_nam_trong_khoi_cua_dung_nguoi(self):
        chosen = self._chosen("An", "Bình")
        sources = compose_stage.build_sources(chosen)
        problems = verify_stage.check(
            plan_stage.QueryPlan(limit=2), chosen,
            "An phù hợp nhờ SQL [2]. Bình phù hợp nhờ Java [1].", sources)
        self.assertTrue(any("đúng phần" in p and "An" in p for p in problems))
        self.assertTrue(any("đúng phần" in p and "Bình" in p for p in problems))
        audit = verify_stage.citation_audit(chosen,
            "An phù hợp nhờ SQL [2]. Bình phù hợp nhờ Java [1].", sources)
        self.assertEqual(audit["status"], "FAIL")
        self.assertEqual(audit["semantic_entailment"], "NOT_MEASURED")

    def test_ten_ngan_khong_khop_ben_trong_tu_khac(self):
        problems = verify_stage.check(
            plan_stage.QueryPlan(limit=5), self._chosen("An"),
            "Ngân hàng bán lẻ đang cần tuyển dụng.", [])
        self.assertEqual(problems, [])

    def test_ten_lap_lai_co_mot_khoi_dung_nguon_thi_dat(self):
        chosen = self._chosen("An", "Bình")
        sources = compose_stage.build_sources(chosen)
        text = ("Hai người nổi bật là An và Bình. "
                "An phù hợp vì có SQL [1]. Bình phù hợp vì có Java [2].")
        self.assertEqual(
            verify_stage.check(plan_stage.QueryPlan(limit=2), chosen, text, sources), [])

    def test_bai_khong_nhac_ten_ai_thi_khong_kiem_thu_tu(self):
        """Bài có quyền không kể hết — không được coi đó là lỗi."""
        chosen = self._chosen("An", "Bình")
        plan_obj = plan_stage.QueryPlan(sort_by={"key": "năm sinh", "dir": "desc"})
        self.assertEqual(
            verify_stage.check(plan_obj, chosen, "Kho có 2 hồ sơ phù hợp [1].", []), [])

    def test_loi_thi_engine_viet_lai_va_phat_su_kien_revision(self):
        person = Person.objects.create(display_name="An")
        TalentProfile.objects.create(person=person)
        calls = []

        def fake_stream(messages, task="", **kwargs):
            calls.append(messages)
            text = ("An [1] rồi Bình [2]." if len(calls) > 1
                    else "Bình [2] rồi An [1].")     # lượt đầu SAI thứ tự
            yield {"type": "answer", "text": text}
            yield {"type": "done", "completion": FakeCompletion(text)}

        chosen = self._chosen("An", "Bình")
        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["x"],
            sort_by={"key": "năm sinh", "dir": "desc"})
        with mock.patch("talent.answer.engine._pipeline",
                        side_effect=_pipeline_returning(
                            (plan_obj, chosen, [], {"judged": 2}, {}))):
            chunks = list(engine.stream_answer("x", stream_fn=fake_stream,
                                               query_plan=plan_obj))
        kinds = [c["type"] for c in chunks]
        self.assertIn("revision", kinds)
        self.assertEqual(len(calls), 2)             # đúng MỘT lượt viết lại
        revised = next(c for c in chunks if c["type"] == "revision")
        self.assertTrue(revised["text"].startswith("An"))
        result = next(c["result"] for c in chunks if c["type"] == "done")
        self.assertEqual(result.trace["citation_audit"]["status"], "PASS")
        self.assertEqual(result.trace["citation_audit"]["locally_cited_people"], 2)

    def test_viet_lai_hong_thi_khong_phat_hanh_ban_chua_dat_kiem_chung(self):
        def fake_stream(messages, task="", **kwargs):
            if len(messages) > 2:                   # lượt viết lại
                raise RuntimeError("provider chết")
            yield {"type": "answer", "text": "Bình [2] rồi An [1]."}
            yield {"type": "done", "completion": FakeCompletion("Bình [2] rồi An [1].")}

        chosen = self._chosen("An", "Bình")
        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["x"],
            sort_by={"key": "năm sinh", "dir": "desc"})
        with mock.patch("talent.answer.engine._pipeline",
                        side_effect=_pipeline_returning(
                            (plan_obj, chosen, [], {"judged": 2}, {}))):
            chunks = list(engine.stream_answer("x", stream_fn=fake_stream,
                                               query_plan=plan_obj))
        result = next(c["result"] for c in chunks if c["type"] == "done")
        # Không phát hành bản sai thứ tự của model; thay bằng danh sách ĐÃ CHỐT
        # (đúng thứ tự ④) và nói rõ lý do — không bỏ trắng.
        self.assertNotIn("Bình [2] rồi An [1]", result.text)
        self.assertIn("không vượt qua bước kiểm chứng", result.text)
        self.assertLess(result.text.index("An"), result.text.index("Bình"))


# --------------------------------------- một câu, NHIỀU việc (phân rã)

class MultiStepTest(TestCase):
    """"Tìm ứng viên Java rồi soạn thư cho người đầu" là MỘT câu, HAI việc.

    Một `shape` không diễn tả được: chọn `find_people` thì thư không bao giờ
    được soạn; chọn `action` thì không có ai để soạn cho.
    """

    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("rec-steps", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.an = Person.objects.create(display_name="Đỗ Quốc Huy")

    def test_doc_duoc_next_steps_va_bo_buoc_sai_khuon(self):
        caller = replies({plan_stage.TASK: json.dumps({
            "shape": "find_people", "search_queries": ["Java"],
            "next_steps": [
                {"shape": "action", "yeu_cau": "soạn thư cho người đầu"},
                {"shape": "khong-ton-tai", "yeu_cau": "việc lạ"},   # sai shape
                {"shape": "action"},                                # thiếu yêu cầu
                {"shape": "action", "yeu_cau": "việc thứ ba"},      # quá trần
            ]}, ensure_ascii=False)})
        result = plan_stage.plan("tìm Java rồi soạn thư", complete_fn=caller)
        self.assertEqual(len(result.next_steps), 1)
        self.assertEqual(result.next_steps[0]["yeu_cau"], "soạn thư cho người đầu")

    def test_buoc_sau_nhan_dung_nguoi_cua_buoc_truoc(self):
        """Truyền qua `last_result` — đúng cơ chế câu hỏi tiếp vẫn dùng."""
        from talent.answer import engine as engine_mod
        envelope = engine_mod._steps_envelope(
            [{"person_id": self.an.pk, "name": "Đỗ Quốc Huy"}])
        self.assertEqual(act_stage.people_in_context(envelope),
                         [{"person_id": self.an.pk, "name": "Đỗ Quốc Huy"}])

    def test_envelope_phai_dung_lop_Projection_that(self):
        """`ai/agent.py` gọi `projection.context_system()`.

        Một `SimpleNamespace` cùng hình dạng sẽ nổ AttributeError GIỮA LƯỢT — đã
        xảy ra thật trên production: bước "soạn thư" chết trong khi bước tìm
        người vẫn chạy, nên nhìn qua tưởng ổn.
        """
        from ai.projection import Projection
        from talent.answer import engine as engine_mod
        projection = engine_mod._steps_envelope(
            [{"person_id": self.an.pk, "name": "X"}]).projection
        self.assertIsInstance(projection, Projection)
        context = projection.context_system()      # không được ném AttributeError
        self.assertEqual(context["role"], "system")
        # Và người của bước trước phải thật sự nằm trong ngữ cảnh bước sau.
        self.assertIn("X", context["content"])

    def test_chay_tiep_viec_thu_hai_va_ghep_vao_cau_tra_loi(self):
        from talent.answer import engine as engine_mod

        def fake_turn(question, **kwargs):
            yield {"type": "answer", "text": f"Đã soạn nháp thư ({question})."}
            yield {"type": "done", "result": None}

        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["Java"],
            next_steps=[{"shape": "action", "yeu_cau": "soạn thư cho người đầu"}])
        with mock.patch("ai.agent.iter_turn", fake_turn), \
                mock.patch("talent.answer.act.available", return_value=True):
            out = list(engine_mod._run_next_steps(
                plan_obj, [{"person_id": self.an.pk, "name": "Đỗ Quốc Huy"}],
                self.user, [], time.monotonic()))
        texts = [c["text"] for c in out if c["type"] == "step_result"]
        self.assertEqual(len(texts), 1)
        self.assertIn("Đã soạn nháp thư", texts[0])

    def test_tool_chay_o_buoc_sau_phai_thay_duoc_trong_trace(self):
        """Chạy được mà không thấy dấu vết thì người soi kết luận sai.

        `docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §4 ghi một "case đang mở": trace
        cho thấy `draft_outreach` không được gọi như một tool (`trace.tools`
        rỗng) dù kết quả đúng, và kết luận là "registry tool chưa được khai
        thác thật". Kết luận ấy SAI. Tool có chạy — `act_stage` đi qua
        `ai/agent.py`, vòng lặp tool có lọc RBAC. Cái hỏng là `_run_next_steps`
        chỉ lấy `payload["text"]` rồi vứt `payload["tool_trace"]`.

        Mất dấu vết tệ hơn mất tính năng: nó làm người ta đi sửa nhầm chỗ.
        """
        from talent.answer import engine as engine_mod

        def fake_turn(question, **kwargs):
            yield {"type": "tool", "tool": {"name": "draft_outreach",
                                            "arguments": {"person_id": self.an.pk}}}
            yield {"type": "answer", "text": "Đã soạn nháp thư."}
            yield {"type": "done", "result": None}

        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["Java"],
            next_steps=[{"shape": "action", "yeu_cau": "soạn thư cho người đầu"}])
        with mock.patch("ai.agent.iter_turn", fake_turn), \
                mock.patch("talent.answer.act.available", return_value=True):
            out = list(engine_mod._run_next_steps(
                plan_obj, [{"person_id": self.an.pk, "name": "Đỗ Quốc Huy"}],
                self.user, [], time.monotonic()))

        vet = [c for c in out if c.get("type") == "tool_trace"]
        self.assertEqual(len(vet), 1, "bước sau chạy tool mà không phát dấu vết")
        ten = [t.get("name") for t in vet[0]["tools"]]
        self.assertIn("draft_outreach", ten)

    def test_khong_tim_duoc_ai_thi_noi_thang_chu_khong_im_lang_bo_qua(self):
        """Im lặng bỏ qua khiến người dùng tưởng thư đã được soạn."""
        from talent.answer import engine as engine_mod
        plan_obj = plan_stage.QueryPlan(
            next_steps=[{"shape": "action", "yeu_cau": "soạn thư"}])
        out = list(engine_mod._run_next_steps(plan_obj, [], self.user, [],
                                              time.monotonic()))
        self.assertIn("không ra hồ sơ nào",
                      " ".join(c.get("text", "") for c in out))

    def test_qua_ngan_sach_thi_dung_va_bao_con_viec_chua_lam(self):
        from talent.answer import engine as engine_mod
        plan_obj = plan_stage.QueryPlan(
            next_steps=[{"shape": "action", "yeu_cau": "soạn thư"}])
        out = list(engine_mod._run_next_steps(
            plan_obj, [{"person_id": self.an.pk, "name": "X"}], self.user, [],
            time.monotonic() - engine_mod.NEXT_STEP_BUDGET - 1))
        self.assertIn("quá thời gian chờ",
                      " ".join(c.get("text", "") for c in out))

    def test_cham_5_duoc_dan_KHONG_lam_viec_cua_buoc_sau(self):
        """⑤ nhìn thấy cả câu hỏi gốc nên nếu không dặn, nó tự soạn thư luôn.

        Đo trên production: ⑤ soạn xong thư, rồi bước sau chạy lại và thất bại,
        nên ngay dưới lá thư là "Tôi chưa thực hiện được yêu cầu này" — câu trả
        lời tự mâu thuẫn với chính nó.
        """
        plan_obj = plan_stage.QueryPlan(
            shape="find_people", information_need="tìm Java rồi soạn thư",
            next_steps=[{"shape": "action", "yeu_cau": "soạn thư cho người đầu"}])
        payload = compose_stage.build_payload(plan_obj, [], [], {}, [])
        self.assertEqual(payload["viec_cua_buoc_sau"], ["soạn thư cho người đầu"])
        self.assertIn("viec_cua_buoc_sau", compose_stage.SYSTEM)

    def test_buoc_that_bai_noi_ro_viec_nao_chu_khong_noi_chung_chung(self):
        from talent.answer import engine as engine_mod

        def empty_turn(question, **kwargs):
            yield {"type": "done", "result": None}

        plan_obj = plan_stage.QueryPlan(
            next_steps=[{"shape": "action", "yeu_cau": "soạn thư cho người đầu"}])
        with mock.patch("ai.agent.iter_turn", empty_turn), \
                mock.patch("talent.answer.act.available", return_value=True):
            out = list(engine_mod._run_next_steps(
                plan_obj, [{"person_id": self.an.pk, "name": "X"}], self.user, [],
                time.monotonic()))
        said = " ".join(f"{c.get('text', '')} {c.get('label', '')}" for c in out)
        self.assertIn("soạn thư cho người đầu", said)   # nêu ĐÍCH DANH việc nào

    def test_cau_mot_viec_khong_phat_sinh_buoc_nao(self):
        from talent.answer import engine as engine_mod
        out = list(engine_mod._run_next_steps(
            plan_stage.QueryPlan(shape="find_people"), [{"person_id": 1, "name": "X"}],
            self.user, [], time.monotonic()))
        self.assertEqual(out, [])


# ------------------------------------------------ nhánh HÀNH ĐỘNG (⑥)

class ActionBranchTest(TestCase):
    """"Soạn thư cho 3 người đầu" là MỆNH LỆNH, không phải câu hỏi tra cứu.

    Đưa nó qua ①→⑤ là sai từ gốc: ② tìm lại từ đầu và có thể ra danh sách khác
    với danh sách người dùng đang trỏ tới.
    """

    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("rec-act", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.an = Person.objects.create(display_name="Nguyễn An")

    def _envelope(self):
        from types import SimpleNamespace
        projection = SimpleNamespace(
            recent_turns=[], last_result={"items": [
                {"id": self.an.pk, "name": "Nguyễn An", "score": 0.9, "why": ""}]})
        return SimpleNamespace(projection=projection)

    def test_nguoi_cua_luot_truoc_duoc_bom_vao_ngu_canh(self):
        people = act_stage.people_in_context(self._envelope())
        self.assertEqual(people, [{"person_id": self.an.pk, "name": "Nguyễn An"}])

    def test_shape_action_re_sang_nhanh_tool_khong_di_truy_hoi(self):
        caller = replies({plan_stage.TASK: json.dumps(
            {"shape": "action", "information_need": "soạn thư cho người đầu",
             "search_queries": []}, ensure_ascii=False)})

        def fake_turn(question, **kwargs):
            yield {"type": "tool", "tool": {"name": "draft_outreach", "ok": True}}
            yield {"type": "answer", "text": "Đã soạn nháp thư cho Nguyễn An."}
            yield {"type": "done", "result": FakeCompletion("")}

        with mock.patch("ai.agent.iter_turn", fake_turn), \
                mock.patch("talent.answer.act.available", return_value=True), \
                mock.patch("talent.answer.retrieve.retrieve") as retrieved:
            result = engine.answer("soạn thư cho người đầu", envelope=self._envelope(),
                                   user=self.user, complete_fn=caller)
        retrieved.assert_not_called()          # KHÔNG được đi tìm lại
        self.assertIn("Đã soạn nháp thư", result.text)
        self.assertEqual(result.trace["mode"], "action")
        self.assertEqual(result.trace["tools"][0]["name"], "draft_outreach")

    def test_khong_co_tool_kha_dung_thi_van_tra_loi_binh_thuong(self):
        """Tài khoản không có quyền dùng tool ⇒ không được rơi vào ngõ cụt."""
        caller = replies({
            plan_stage.TASK: json.dumps({"shape": "action", "search_queries": []})})

        class FakeAdapter:
            def stream(self, request):
                yield {"type": "answer", "text": "Tôi chưa làm được việc này."}
                yield {"type": "done", "response": None}

        with mock.patch("talent.answer.act.available", return_value=False):
            result = engine.answer("soạn thư", user=self.user, complete_fn=caller,
                                   adapter=FakeAdapter())
        self.assertIn("chưa làm được", result.text)

    def test_stage_tool_phat_nhan_tieng_viet(self):
        def fake_turn(question, **kwargs):
            yield {"type": "tool", "tool": {"name": "compare_candidates", "ok": True}}
            yield {"type": "answer", "text": "xong"}
            yield {"type": "done", "result": None}

        with mock.patch("ai.agent.iter_turn", fake_turn):
            chunks = list(act_stage.stream_action("so sánh giúp tôi",
                                                  envelope=self._envelope(),
                                                  user=self.user))
        labels = [c["text"] for c in chunks if c.get("stage") == "tool"]
        self.assertEqual(labels, ["So sánh ứng viên"])


# ------------------------------------------------- che liên hệ (GĐ A)

EMAIL = "nguyen.van.an@gmail.com"
PHONE = "0975219309"


class ContactRedactionTest(TestCase):
    """Liên hệ không được rò qua đường trả lời.

    Đo trên kho thật: 33% đoạn CV có email, 25% có số điện thoại. Hệ thống có
    hạn mức mở khoá liên hệ; trả nguyên văn ở đây là mở một đường vòng qua nó.
    """

    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("rec-privacy", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.client.force_login(self.user)

        self.person = Person.objects.create(display_name="Nguyễn Văn An")
        TalentProfile.objects.create(person=self.person)
        body = (f"Nguyễn Văn An — chuyên viên quan hệ khách hàng. "
                f"Email: {EMAIL}. Điện thoại: {PHONE}.")
        self.document = Document.objects.create(
            person=self.person, sha256="c" * 64, parsed_text=body)
        CVChunk.objects.create(person=self.person, document=self.document, ordinal=0,
                               fingerprint="f", text=body,
                               text_norm=retrieve_stage._fold(body))
        PersonSearchDocument.objects.create(
            person=self.person, fingerprint="f", content=body,
            content_norm=retrieve_stage._fold(body))

    def test_doan_bang_chung_da_che_truoc_khi_toi_llm(self):
        """Che tại NGUỒN: model không được nhìn thấy liên hệ ngay từ đầu."""
        query_plan = plan_stage.QueryPlan(
            information_need="quan hệ khách hàng", search_queries=["quan hệ khách hàng"])
        candidates = retrieve_stage.retrieve(query_plan)
        self.assertTrue(candidates)
        for candidate in candidates:
            for passage in candidate.passages:
                self.assertNotIn(EMAIL, passage.text)
                self.assertNotIn(PHONE, passage.text)
        # Phần còn lại của đoạn vẫn nguyên — che chứ không xoá trắng.
        self.assertIn("quan hệ khách hàng", candidates[0].passages[0].text)

    def test_clean_passage_che_ca_email_lan_sdt(self):
        cleaned = retrieve_stage.clean_passage(f"LH {PHONE} hoặc {EMAIL} nhé")
        self.assertNotIn(PHONE, cleaned)
        self.assertNotIn(EMAIL, cleaned)
        self.assertIn("nhé", cleaned)

    def test_xem_nguyen_van_cv_bi_che_khi_chua_mo_khoa(self):
        response = self.client.get(f"/api/v1/talent/documents/{self.document.pk}/text/")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["contacts_masked"])
        self.assertNotIn(EMAIL, payload["text"])
        self.assertNotIn(PHONE, payload["text"])
        self.assertNotIn(PHONE, json.dumps(payload, ensure_ascii=False))

    def test_da_mo_khoa_thi_tra_nguyen_van(self):
        """Đã trả một lượt hạn mức rồi thì che nữa là vô nghĩa."""
        from accounts import privacy
        privacy.unlock(self.user, self.person)
        response = self.client.get(f"/api/v1/talent/documents/{self.document.pk}/text/")
        payload = response.json()
        self.assertFalse(payload["contacts_masked"])
        self.assertIn(PHONE, payload["text"])


# ---------------------------------------------------------- POST /ask/

class AskEndpointTest(TransactionTestCase):
    """`TransactionTestCase`: đường `/talent/ask/` stream thật qua
    `to_async_iter` (core/asgi_stream.py), chạy generator gốc trên một luồng
    nền riêng. `TestCase` bọc mỗi test trong một transaction ở luồng chính —
    luồng nền ghi CSDL (persist câu trả lời) giữa lúc đó sẽ đụng transaction
    đó (SQLite: "database table is locked")."""

    URL = "/api/v1/talent/ask/"

    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("tuyen-dung-ask", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.client.force_login(self.user)

        person = Person.objects.create(display_name="Phạm Ứng Viên")
        TalentProfile.objects.create(person=person)
        document = Document.objects.create(person=person, sha256="b" * 64,
                                           parsed_text="Chuyên viên quan hệ khách hàng.")
        text = "Phạm Ứng Viên: chuyên viên quan hệ khách hàng cá nhân, sinh năm 1995."
        # `update_or_create`, không `create`: dưới TransactionTestCase, save()
        # ở trên COMMIT THẬT ngay lập tức nên `talent/signals.py`'s
        # `on_commit(rebuild)` đã tự tạo CVChunk/PersonSearchDocument cho
        # document này rồi (trước đây dùng TestCase, transaction không bao
        # giờ commit thật nên on_commit không chạy — `create` thẳng vẫn qua).
        CVChunk.objects.update_or_create(
            document=document, ordinal=0,
            defaults={"person": person, "fingerprint": "f", "text": text,
                     "text_norm": retrieve_stage._fold(text)})
        PersonSearchDocument.objects.update_or_create(
            person=person,
            defaults={"fingerprint": "f", "content": text,
                     "content_norm": retrieve_stage._fold(text)})
        self.person = person

    def _result(self):
        return engine.AnswerResult(
            text="Có 1 ứng viên: Phạm Ứng Viên [1].",
            sources=[{"n": 1, "person_id": self.person.pk, "name": "Phạm Ứng Viên",
                      "document_id": 7, "ordinal": 0, "snippet": "quan hệ khách hàng"}],
            people=[{"person_id": self.person.pk, "name": "Phạm Ứng Viên",
                     "why": "khớp", "attributes": {}, "citations": [1]}],
            provider="fake", model="m1", trace={"ms_total": 1234})

    def test_stream_phat_stage_answer_citations_roi_done(self):
        def fake_stream(*args, **kwargs):
            yield {"type": "step", "label": "Hiểu yêu cầu", "state": "done"}
            yield {"type": "reasoning", "text": "KHÔNG được ra tới client"}
            yield {"type": "answer", "text": "Có 1 ứng viên: Phạm Ứng Viên [1]."}
            yield {"type": "done", "result": self._result()}

        with mock.patch("talent.answer.engine.stream_answer", fake_stream):
            response = self.client.post(self.URL, json.dumps({
                "q": "ai làm quan hệ khách hàng?", "conversation_id": "c-ask",
                "client_turn_id": "turn-a1"}), content_type="application/json")
            # PHẢI đọc hết thân phản hồi khi patch còn hiệu lực: generator của
            # StreamingHttpResponse chạy lười, ra khỏi `with` là nó gọi LLM thật.
            body = drain_to_bytes(response.streaming_content).decode("utf-8")
        self.assertIn("event: step", body)
        self.assertIn("event: answer", body)
        self.assertIn("event: citations", body)
        self.assertIn("event: done", body)
        self.assertIn("Phạm Ứng Viên", body)
        # Suy nghĩ của model KHÔNG được đẩy ra client.
        self.assertNotIn("event: thinking", body)
        self.assertNotIn("KHÔNG được ra tới client", body)

    def test_khong_stream_tra_json_mot_lan(self):
        with mock.patch("talent.answer.engine.answer", return_value=self._result()):
            response = self.client.post(self.URL, json.dumps(
                {"q": "ai làm quan hệ khách hàng?", "stream": False}),
                content_type="application/json")
        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["grounded"])
        self.assertEqual(payload["people"][0]["name"], "Phạm Ứng Viên")
        self.assertEqual(payload["duration_ms"], 1234)

    def test_rm_thuan_bi_chan_vi_cau_tra_loi_luon_trich_cv(self):
        from accounts import roles
        rm = User.objects.create_user("rm-thuan", password="mat-khau-dai-1")
        rm.groups.add(Group.objects.get(name=roles.RB_SALES))
        self.client.force_login(rm)
        response = self.client.post(self.URL, json.dumps({"q": "ai biết Python?"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 403)

    def test_chua_dang_nhap_bi_tu_choi(self):
        self.client.logout()
        response = self.client.post(self.URL, json.dumps({"q": "ai?"}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 401)

    def test_cau_hoi_rong_bi_tu_choi(self):
        response = self.client.post(self.URL, json.dumps({"q": "  "}),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 400)


# ----------------------- MOBILE: rớt kết nối giữa chừng vẫn chạy xong + lấy lại

@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                     "LOCATION": "runner-tests"}})
class RunnerResilienceTest(TestCase):
    """Mobile treo tab → thân stream bị OS huỷ. Máy chủ phải chạy XONG và lưu
    bản đầy đủ; người dùng mở lại lấy được qua endpoint resume."""

    def setUp(self):
        # Thread mechanics use a test transaction's SQLite DB; exercise the
        # durable claim contract separately without a background DB writer.
        for name, value in (("claim", 1), ("finish", None), ("status", None)):
            patcher = mock.patch(f"talent.answer.run_state.{name}", return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("runner-user", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.client.force_login(self.user)

    def _fake_stream(self, text="Câu trả lời đầy đủ."):
        def gen(*a, **k):
            yield {"type": "step", "label": "Hiểu yêu cầu", "state": "done"}
            yield {"type": "answer", "text": text}
            yield {"type": "done", "result": engine.AnswerResult(
                text=text, people=[{"person_id": 1, "name": "X", "why": "y"}])}
        return gen

    def test_incomplete_stream_is_aborted_in_both_modes(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                persisted = []
                with mock.patch("core.answer.runner._threaded_ok", return_value=threaded), \
                        mock.patch("talent.answer.engine.stream_answer", return_value=iter([
                            {"type": "answer", "text": "partial"}])):
                    chunks = list(runner.stream("q", envelope=None, user=self.user, history=[],
                        client_turn_id=f"incomplete-{threaded}",
                        persist=lambda result, aborted=False: persisted.append(aborted)))
                self.assertEqual(persisted, [True])
                self.assertEqual(chunks[-1]["type"], "error")
                self.assertNotIn("done", [chunk["type"] for chunk in chunks])

    def test_blocked_worker_keeps_slot_after_response_timeout(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        release = threading.Event()
        cleaned = threading.Event()

        def blocked(*args, **kwargs):
            release.wait(3)
            yield {"type": "done", "result": engine.AnswerResult(text="late")}

        def request(turn):
            return list(runner.stream("q", envelope=None, user=self.user, history=[],
                        client_turn_id=turn, persist=lambda *a, **k: None))

        with self.settings(ANSWER_RUNNER_MAX_WORKERS=1), \
                mock.patch.object(core_runner, "_ACTIVE", set()), \
                mock.patch.object(core_runner, "_threaded_ok", return_value=True), \
                mock.patch.object(core_runner, "HARD_DEADLINE", .05), \
                mock.patch.object(core_runner, "close_old_connections", side_effect=cleaned.set), \
                mock.patch("talent.answer.engine.stream_answer", side_effect=blocked) as generate:
            try:
                self.assertEqual(request("slot-one")[-1]["type"], "error")
                self.assertEqual(runner.status_of(self.user, "slot-one"), "timeout")
                self.assertIn("vẫn đang xử lý", request("slot-one")[-1]["text"])
                self.assertIn("nhiều lượt", request("slot-two")[-1]["text"])
                self.assertEqual(generate.call_count, 1)
            finally:
                release.set()
                self.assertTrue(cleaned.wait(2))
                for _ in range(100):
                    with core_runner._LOCK:
                        if not core_runner._ACTIVE:
                            break
                    time.sleep(.01)
            self.assertFalse(core_runner._ACTIVE)

    def test_worker_start_failure_releases_admission_slot(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        with mock.patch.object(core_runner, "_ACTIVE", set()), \
                mock.patch.object(core_runner, "_threaded_ok", return_value=True), \
                mock.patch("core.answer.runner.threading.Thread.start", side_effect=RuntimeError("fixture")), \
                mock.patch.object(core_runner.log, "exception"):
            chunks = list(runner.stream("q", envelope=None, user=self.user, history=[],
                          client_turn_id="start-fail", persist=mock.Mock()))
            self.assertFalse(core_runner._ACTIVE)
            self.assertEqual(chunks[-1]["type"], "error")
            self.assertEqual(runner.status_of(self.user, "start-fail"), "error")

    def test_durable_duplicate_does_not_start_worker_or_persist(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        persist = mock.Mock()
        with mock.patch.object(core_runner, "_threaded_ok", return_value=True), \
                mock.patch.object(core_runner.run_state, "claim", return_value=None), \
                mock.patch("core.answer.runner.threading.Thread.start") as start:
            chunks = list(runner.stream("q", envelope=None, user=self.user, history=[],
                          client_turn_id="duplicate-db", persist=persist))
        start.assert_not_called()
        persist.assert_not_called()
        self.assertEqual(chunks[-1]["type"], "error")
        self.assertNotIn((self.user.pk, "duplicate-db"), core_runner._ACTIVE)

    def test_durable_claim_failure_fails_closed(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        with mock.patch.object(core_runner, "_threaded_ok", return_value=True), \
                mock.patch.object(core_runner.run_state, "claim", side_effect=RuntimeError("database unavailable")), \
                mock.patch.object(core_runner.log, "exception"), \
                mock.patch("core.answer.runner.threading.Thread.start") as start:
            chunks = list(runner.stream("q", envelope=None, user=self.user, history=[],
                          client_turn_id="claim-error", persist=mock.Mock()))
        start.assert_not_called()
        self.assertEqual(chunks[-1]["type"], "error")
        self.assertNotIn((self.user.pk, "claim-error"), core_runner._ACTIVE)

    def test_persistence_failure_never_emits_done(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        for threaded in (False, True):
            with self.subTest(threaded=threaded):
                with mock.patch("core.answer.runner._threaded_ok", return_value=threaded), \
                        mock.patch("talent.answer.engine.stream_answer", self._fake_stream()), \
                        mock.patch("core.answer.runner.log.exception"), \
                        mock.patch("core.answer.runner.close_old_connections"):
                    chunks = list(runner.stream("q", envelope=None, user=self.user, history=[],
                        client_turn_id=f"persist-error-{threaded}",
                        persist=mock.Mock(side_effect=RuntimeError("fixture"))))
                self.assertEqual(chunks[-1]["type"], "error")
                self.assertNotIn("done", [chunk["type"] for chunk in chunks])

    def test_client_rot_giua_chung_engine_van_chay_xong_va_luu(self):
        """Đường LUỒNG NỀN (production/PostgreSQL): client rớt → engine chạy
        nốt và persist bản đầy đủ (aborted=False)."""
        from core.answer import runner as core_runner
        from talent.answer import runner
        persisted = {}
        with mock.patch("talent.answer.engine.stream_answer", self._fake_stream("XONG")), \
                mock.patch("core.answer.runner._threaded_ok", return_value=True):
            gen = runner.stream("q", envelope=None, user=self.user, history=[],
                                client_turn_id="t-abort",
                                persist=lambda r, aborted=False: persisted.update(
                                    text=r.text, aborted=aborted))
            next(gen)                               # lấy 1 chunk rồi "rớt"
            gen.close()                            # ~ client disconnect
            for _ in range(60):
                if persisted:
                    break
                time.sleep(0.05)
        self.assertEqual(persisted.get("text"), "XONG")
        self.assertFalse(persisted.get("aborted"))

    def test_sqlite_chay_inline_khong_spawn_luong(self):
        """Đường INLINE (SQLite/test): không luồng nền, client rớt → persist
        phần dang dở như hành vi cũ."""
        from core.answer import runner as core_runner
        from talent.answer import runner
        persisted = {}
        with mock.patch("talent.answer.engine.stream_answer", self._fake_stream("Z")):
            gen = runner.stream("q", envelope=None, user=self.user, history=[],
                                client_turn_id="t-inline",
                                persist=lambda r, aborted=False: persisted.update(
                                    text=r.text, aborted=aborted))
            self.assertEqual([c["type"] for c in gen][:1], ["step"])
        self.assertEqual(persisted.get("text"), "Z")

    def test_resume_tra_ve_cau_tra_loi_da_luu(self):
        from ai import conversation_state
        conversation_state.record(
            self.user, "talent", "c-res", "câu hỏi", "Đây là câu trả lời đã lưu.",
            mode="conversation", client_turn_id="t-done",
            metadata={"cv_citations": [{"n": 1, "name": "X"}],
                      "trace": {"ms_total": 2345}, "duration_ms": 2345},
            last_result={"items": [{"id": 7, "name": "Người Bảy"}]})
        r = self.client.get("/api/v1/talent/ask/turn/t-done/")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["state"], "done")
        self.assertEqual(data["answer"], "Đây là câu trả lời đã lưu.")
        self.assertEqual(data["people"], [{"person_id": 7, "name": "Người Bảy"}])
        self.assertEqual(data["duration_ms"], 2345)
        self.assertEqual(data["trace"]["ms_total"], 2345)

    def test_resume_does_not_jump_to_another_turns_answer(self):
        from ai.models import AssistantThread, AssistantMessage
        thread = AssistantThread.objects.create(user=self.user, surface="talent", thread_id="overlap")
        AssistantMessage.objects.create(thread=thread, role="user", content="first", client_turn_id="first")
        AssistantMessage.objects.create(thread=thread, role="user", content="second", client_turn_id="second")
        AssistantMessage.objects.create(thread=thread, role="assistant", content="second answer",
                                        metadata={"client_turn_id": "second"})
        response = self.client.get("/api/v1/talent/ask/turn/first/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get("/api/v1/talent/ask/turn/second/").json()["answer"], "second answer")

    def test_resume_legacy_adjacent_answer_still_works(self):
        from ai.models import AssistantThread, AssistantMessage
        thread = AssistantThread.objects.create(user=self.user, surface="talent", thread_id="legacy-resume")
        AssistantMessage.objects.create(thread=thread, role="user", content="old", client_turn_id="old")
        AssistantMessage.objects.create(thread=thread, role="assistant", content="legacy answer")
        self.assertEqual(self.client.get("/api/v1/talent/ask/turn/old/").json()["answer"], "legacy answer")

    def test_resume_202_khi_dang_chay(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        with core_runner._LOCK:
            core_runner._INFLIGHT[("talent", self.user.pk, "t-run")] = {
                "state": "running", "at": time.monotonic(), "error": ""}
        try:
            r = self.client.get("/api/v1/talent/ask/turn/t-run/")
            self.assertEqual(r.status_code, 202)
            self.assertEqual(r.json()["state"], "running")
        finally:
            with core_runner._LOCK:
                core_runner._INFLIGHT.pop(("talent", self.user.pk, "t-run"), None)

    def test_hard_deadline_tra_loi_va_danh_dau_timeout_du_provider_con_treo(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        release = threading.Event()
        persisted = {}

        def blocked(*args, **kwargs):
            release.wait(2)
            yield {"type": "answer", "text": "quá muộn"}

        with mock.patch("talent.answer.engine.stream_answer", blocked), \
                mock.patch("core.answer.runner._threaded_ok", return_value=True), \
                mock.patch("core.answer.runner.HARD_DEADLINE", 0.05):
            started = time.monotonic()
            chunks = list(runner.stream(
                "q", envelope=None, user=self.user, history=[], client_turn_id="t-timeout",
                persist=lambda result, aborted=False: persisted.update(aborted=aborted)))
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.5)
            self.assertEqual(chunks[-1]["type"], "error")
            self.assertEqual(runner.status_of(self.user, "t-timeout"), "timeout")
            release.set()
            for _ in range(40):
                if persisted:
                    break
                time.sleep(0.01)
        self.assertTrue(persisted.get("aborted"))

    def test_resume_bao_timeout_thay_vi_404(self):
        from core.answer import runner as core_runner
        from talent.answer import runner
        with core_runner._LOCK:
            core_runner._INFLIGHT[("talent", self.user.pk, "t-timeout-api")] = {
                "state": "timeout", "at": time.monotonic(), "error": "deadline"}
        try:
            response = self.client.get("/api/v1/talent/ask/turn/t-timeout-api/")
            self.assertEqual(response.status_code, 504)
            self.assertEqual(response.json()["state"], "timeout")
        finally:
            with core_runner._LOCK:
                core_runner._INFLIGHT.pop(("talent", self.user.pk, "t-timeout-api"), None)

    def test_resume_404_khi_khong_co_gi(self):
        r = self.client.get("/api/v1/talent/ask/turn/t-nope/")
        self.assertEqual(r.status_code, 404)

    def test_resume_can_dang_nhap(self):
        self.client.logout()
        r = self.client.get("/api/v1/talent/ask/turn/t-x/")
        self.assertEqual(r.status_code, 401)


@override_settings(CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                                     "LOCATION": "shared-status-contract-tests"}})
class SharedRunnerStatusTest(SimpleTestCase):
    def setUp(self):
        patcher = mock.patch("talent.answer.run_state.status", return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_status_survives_absent_local_registry_and_is_user_scoped(self):
        from types import SimpleNamespace
        from core.answer import runner as core_runner
        from talent.answer import runner
        user, other = SimpleNamespace(pk=101), SimpleNamespace(pk=102)
        with mock.patch.object(core_runner, "_INFLIGHT", {}):
            core_runner._publish_status("talent", user, "shared-turn", "running", deadline=time.time() + 30)
            self.assertEqual(runner.status_of(user, "shared-turn"), "running")
            self.assertIsNone(runner.status_of(other, "shared-turn"))
            core_runner._publish_status("talent", user, "shared-turn", "error")
            self.assertEqual(runner.status_of(user, "shared-turn"), "error")

    def test_abandoned_running_state_becomes_timeout(self):
        from types import SimpleNamespace
        from core.answer import runner as core_runner
        from talent.answer import runner
        user = SimpleNamespace(pk=103)
        with mock.patch.object(core_runner, "_INFLIGHT", {}):
            core_runner._publish_status("talent", user, "expired-turn", "running", deadline=time.time() - 1)
            self.assertEqual(runner.status_of(user, "expired-turn"), "timeout")

    def test_local_disconnected_worker_also_observes_deadline(self):
        from types import SimpleNamespace
        from core.answer import runner as core_runner
        from talent.answer import runner
        user = SimpleNamespace(pk=105)
        with mock.patch.object(core_runner, "_INFLIGHT", {("talent", 105, "stalled"): {
                "state": "running", "at": time.monotonic(), "deadline": time.time() - 1}}):
            self.assertEqual(runner.status_of(user, "stalled"), "timeout")

    def test_cache_failure_does_not_mask_local_status(self):
        from types import SimpleNamespace
        from core.answer import runner as core_runner
        from talent.answer import runner
        user = SimpleNamespace(pk=104)
        with mock.patch.object(core_runner, "_INFLIGHT", {("talent", 104, "local"): {"state": "running", "at": time.monotonic()}}), \
                mock.patch.object(core_runner.cache, "get", side_effect=RuntimeError("cache unavailable")), \
                mock.patch.object(core_runner.log, "warning"):
            self.assertEqual(runner.status_of(user, "local"), "running")
            self.assertIsNone(runner.status_of(user, "remote"))


class SharedDatabaseRunnerStatusTest(TestCase):
    def test_database_status_is_readable_by_an_independent_cache_instance(self):
        from django.conf import settings
        from django.core.cache.backends.db import DatabaseCache
        from core.answer import runner as core_runner
        from talent.answer import runner
        from types import SimpleNamespace
        user = SimpleNamespace(pk=106)
        config = settings.CACHES["default"]
        other_cache = DatabaseCache(config["LOCATION"], config)
        core_runner._publish_status("talent", user, "database-shared", "running", deadline=time.time() + 30)
        with mock.patch.object(core_runner, "_INFLIGHT", {}), mock.patch.object(core_runner, "cache", other_cache):
            self.assertEqual(runner.status_of(user, "database-shared"), "running")


# ------------------------------------------ CV ĐÍNH KÈM — đánh giá thẳng tài liệu

class ImageAttachmentTest(SimpleTestCase):
    def test_anh_duoc_doc_bang_task_vision_ocr(self):
        import io
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from talent.attachment_text import extract_uploads

        output = io.BytesIO()
        Image.new("RGB", (120, 60), "white").save(output, format="PNG")
        upload = SimpleUploadedFile("cv-nguyen-an.png", output.getvalue(),
                                    content_type="image/png")
        completion = FakeCompletion("NGUYỄN AN\nKinh nghiệm: 5 năm Java")
        with mock.patch("ai.router.complete", return_value=completion) as complete:
            text, metadata = extract_uploads([upload])
        self.assertIn("NGUYỄN AN", text)
        self.assertEqual(metadata[0]["name"], "cv-nguyen-an.png")
        self.assertEqual(complete.call_args.kwargs["task"], "cv_ocr")
        content = complete.call_args.args[0][1]["content"]
        self.assertEqual(content[1]["type"], "image_url")


class AssessAttachmentTest(TestCase):
    """"Đánh giá ứng viên này" + CV đính kèm.

    Ảnh test 04/09: người dùng đính kèm `CV - Lê Dung.pdf`, Radar trả lời "Kho
    không có hồ sơ nào tên Lê Thị Thùy Dung". `talent/answer_views.py` bóc text
    CV rồi ghép vào câu hỏi dưới nhãn `TÀI LIỆU ĐÍNH KÈM:`; ① thấy một cái tên
    và đi TÌM tên đó trong kho, thay vì đánh giá tài liệu đang nằm trong prompt.
    """

    CV = ("LÊ THỊ THÙY DUNG\nSinh năm 1995. ĐT 0912345678.\n"
          "KINH NGHIỆM: 2018-2024 Chuyên viên khách hàng cá nhân tại Techcombank.\n"
          "HỌC VẤN: Đại học Kinh tế Quốc dân, ngành Tài chính Ngân hàng.")

    def _question(self):
        return "Đánh giá ứng viên này\n\nTÀI LIỆU ĐÍNH KÈM:\n" + self.CV

    def test_split_attachment_tach_dung_cau_hoi_va_tai_lieu(self):
        from talent.answer.engine import _split_attachment
        q, doc = _split_attachment(self._question())
        self.assertEqual(q, "Đánh giá ứng viên này")
        self.assertIn("LÊ THỊ THÙY DUNG", doc)

    def test_khong_dinh_kem_thi_khong_doi_gi(self):
        from talent.answer.engine import _split_attachment
        q, doc = _split_attachment("tìm ứng viên Java")
        self.assertEqual(q, "tìm ứng viên Java")
        self.assertEqual(doc, "")

    def test_jd_dinh_kem_de_TIM_nguoi_van_di_duong_plan(self):
        """"tìm người phù hợp" + JD là ý định KHÁC "đánh giá CV này" — giữ
        nguyên khối cho ① bóc JD rồi tra kho, không rẽ sang nhánh đánh giá."""
        from talent.answer.engine import _split_attachment
        full = ("Phân tích tài liệu đính kèm để tìm người phù hợp"
                "\n\nTÀI LIỆU ĐÍNH KÈM:\nJD: Chuyên viên QHKH, 2 năm KN...")
        q, doc = _split_attachment(full)
        self.assertEqual(doc, "")                   # không rẽ nhánh đánh giá
        self.assertIn("TÀI LIỆU ĐÍNH KÈM", q)       # ① vẫn thấy nguyên khối

    def test_dinh_kem_di_thang_nhanh_danh_gia_khong_qua_plan(self):
        from talent.answer import engine as engine_mod

        def fake_stream(messages, task="", **kwargs):
            # Prompt phải chứa nội dung CV, KHÔNG phải "tìm trong kho".
            blob = " ".join(m["content"] for m in messages)
            self.assertIn("Techcombank", blob)
            self.assertIn("ĐÁNH GIÁ", blob.upper())
            yield {"type": "answer", "text": "Ứng viên có 6 năm mảng khách hàng cá nhân."}
            yield {"type": "done", "completion": FakeCompletion("x")}

        def plan_must_not_run(*a, **k):
            raise AssertionError("① không được chạy khi có tài liệu đính kèm")

        with mock.patch("talent.answer.plan.plan", plan_must_not_run):
            chunks = list(engine_mod.stream_answer(
                self._question(), stream_fn=fake_stream))
        result = next(c["result"] for c in chunks if c["type"] == "done")
        self.assertEqual(result.trace["mode"], "assess_doc")
        self.assertIn("khách hàng cá nhân", result.text)
        # Không được nói "kho không có hồ sơ nào tên …".
        self.assertNotIn("kho không có", result.text.lower())

    def test_bao_khi_trung_ten_trong_kho(self):
        from talent.answer import engine as engine_mod
        Person.objects.create(display_name="Lê Thị Thùy Dung")

        def fake_stream(messages, task="", **kwargs):
            payload = messages[-1]["content"]
            self.assertIn("Lê Thị Thùy Dung", payload)     # twin được đưa vào prompt
            yield {"type": "answer", "text": "Đánh giá..."}
            yield {"type": "done", "completion": FakeCompletion("x")}

        chunks = list(engine_mod.stream_answer(self._question(), stream_fn=fake_stream))
        result = next(c["result"] for c in chunks if c["type"] == "done")
        self.assertEqual(result.trace["name_twin"], "Lê Thị Thùy Dung")


# ---------------------------- GIẢI ĐỊNH DANH TẤT ĐỊNH (compare / followup / tên)

class ResolveTest(TestCase):
    """Ảnh test 04/09: "So sánh A và B" lượt trước ra cả hai, lượt sau rớt một.

    Tên là ĐỊNH DANH, không phải gợi ý ngữ nghĩa — phải ghim vào pool tất định.
    """

    def setUp(self):
        self.huyen = Person.objects.create(display_name="Nguyễn Thị Huyền")
        self.khanh = Person.objects.create(display_name="Vũ Thị Khánh Huyền")
        self.hoa = Person.objects.create(display_name="Nguyễn Thị Hoa")

    def test_boc_ten_rieng_tu_search_queries(self):
        from talent.answer import resolve
        plan_obj = plan_stage.QueryPlan(
            shape="compare",
            information_need="so sánh Nguyễn Thị Huyền và Vũ Thị Khánh Huyền",
            search_queries=["Nguyễn Thị Huyền", "Vũ Thị Khánh Huyền"])
        ids = resolve.named_people(plan_obj)
        self.assertIn(self.huyen.pk, ids)
        self.assertIn(self.khanh.pk, ids)

    def test_khong_boc_cum_khong_phai_ten(self):
        from talent.answer import resolve
        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["chuyên viên tín dụng",
                                                 "quan hệ khách hàng ưu tiên"])
        self.assertEqual(resolve.named_people(plan_obj), [])

    def test_followup_lay_nguoi_cua_luot_truoc(self):
        from types import SimpleNamespace
        from talent.answer import resolve

        proj = SimpleNamespace(last_result_people=lambda limit=12: [
            {"id": self.huyen.pk, "name": "Nguyễn Thị Huyền"},
            {"id": self.khanh.pk, "name": "Vũ Thị Khánh Huyền"}])
        plan_obj = plan_stage.QueryPlan(shape="followup",
                                        search_queries=["so sánh cho vị trí X"])
        ids = resolve.pinned_for(plan_obj, proj)
        self.assertEqual(set(ids), {self.huyen.pk, self.khanh.pk})

    def test_followup_khong_ap_cho_cau_tim_moi(self):
        from types import SimpleNamespace
        from talent.answer import resolve
        proj = SimpleNamespace(last_result_people=lambda limit=12: [
            {"id": self.huyen.pk, "name": "x"}])
        plan_obj = plan_stage.QueryPlan(shape="find_people",
                                        search_queries=["kế toán trưởng"])
        self.assertEqual(resolve.followup_people(proj, plan_obj), [])

    def test_pin_giu_nguoi_du_truy_hoi_khong_ra(self):
        """`retrieve` phải trả người ghim kể cả khi RRF không xếp họ vào top-N."""
        from talent.answer import retrieve as R
        plan_obj = plan_stage.QueryPlan(
            shape="compare", search_queries=["Nguyễn Thị Huyền"])
        with mock.patch.object(R, "_fts_person_ids", return_value=[]), \
                mock.patch.object(R, "_DenseBranch") as dense:
            dense.return_value.side_effect = lambda *a, **k: []
            cands = R.retrieve(plan_obj, pinned_ids=[self.huyen.pk, self.khanh.pk])
        names = {c.name for c in cands}
        self.assertIn("Nguyễn Thị Huyền", names)
        self.assertIn("Vũ Thị Khánh Huyền", names)

    def test_retrieve_search_queries_rong_bo_han_truy_hoi_ngu_nghia(self):
        """Đường tắt 1b: `search_queries=[]` → KHÔNG gọi vector/FTS, chỉ người ghim."""
        from talent.answer import retrieve as R
        plan_obj = plan_stage.QueryPlan(shape="compare",
                                        search_queries=["Nguyễn Thị Huyền"])
        with mock.patch.object(R, "_fts_person_ids") as fts, \
                mock.patch.object(R, "_DenseBranch") as dense:
            cands = R.retrieve(plan_obj, pinned_ids=[self.huyen.pk, self.khanh.pk],
                               search_queries=[])
        fts.assert_not_called()
        dense.return_value.assert_not_called()
        self.assertEqual({c.name for c in cands},
                         {"Nguyễn Thị Huyền", "Vũ Thị Khánh Huyền"})

    def test_fts_khong_tra_nguoi_khong_phai_ung_vien(self):
        """② phải cùng phạm vi với mọi đường tất định — `Person.applicants()`.

        Trước bản sửa 16/09/2026, `_fts_person_ids` chỉ lọc `merged_into`. Hệ
        quả đo được: `count` (lọc applicants) và `find_people` (không lọc) trả
        hai con số khác nhau trên cùng một kho, và người chỉ được NHẮC TỚI
        trong CV người khác bị Radar gọi là "ứng viên".
        """
        from people.models import Document
        from talent import vector_index
        from talent.answer import retrieve as R

        nguoi_duoc_nhac = Person.objects.create(
            display_name="Lê Được Nhắc", is_applicant=False)
        Document.objects.create(person=nguoi_duoc_nhac, sha256="scope-1",
                                parse_status="done",
                                parsed_text="Kế toán trưởng công ty xây dựng. " * 30)
        # Ép vào chỉ mục bằng tay: đây là đúng trạng thái mà một lần
        # `rebuild_talent_vector_index` cũ để lại, và là thứ ② phải chịu được.
        PersonSearchDocument.objects.create(
            person=nguoi_duoc_nhac, fingerprint="scope-1",
            content="Kế toán trưởng công ty xây dựng",
            content_norm=vector_index.fold_text("Kế toán trưởng công ty xây dựng"))
        CVChunk.objects.create(
            person=nguoi_duoc_nhac, document=nguoi_duoc_nhac.documents.first(),
            ordinal=0, fingerprint="scope-1",
            text="Kế toán trưởng công ty xây dựng",
            text_norm=vector_index.fold_text("Kế toán trưởng công ty xây dựng"))

        self.assertNotIn(nguoi_duoc_nhac.pk,
                         R._fts_person_ids("ke toan truong", 50))

    def test_pipeline_bo_qua_2_khi_so_sanh_theo_ten(self):
        """"So sánh A và B" — `_pipeline` không được gọi truy hồi ngữ nghĩa."""
        from talent.answer import engine as engine_mod

        plan_obj = plan_stage.QueryPlan(
            shape="compare", search_queries=["Nguyễn Thị Huyền", "Vũ Thị Khánh Huyền"],
            information_need="so sánh Nguyễn Thị Huyền và Vũ Thị Khánh Huyền")
        seen = {}

        def fake_retrieve(qp, *, user=None, pinned_ids=(), search_queries=None, **k):
            seen["search_queries"] = search_queries
            seen["pinned"] = list(pinned_ids)
            return []

        def fake_judge(qp, cands, **k):
            from talent.answer.judge import JudgeReport
            return JudgeReport()

        with mock.patch("talent.answer.retrieve.retrieve", fake_retrieve), \
                mock.patch("talent.answer.judge.judge", fake_judge), \
                mock.patch("talent.answer.cache.key_for", return_value=None):
            engine_mod._drain(engine_mod._pipeline(
                "so sánh Nguyễn Thị Huyền và Vũ Thị Khánh Huyền",
                query_plan=plan_obj))
        self.assertEqual(seen["search_queries"], [])       # bỏ hẳn truy hồi ngữ nghĩa
        self.assertEqual(set(seen["pinned"]), {self.huyen.pk, self.khanh.pk})

    def test_dem_ten_quet_toan_kho_khong_bi_gioi_han_pool(self):
        from talent.answer import resolve
        Person.objects.create(display_name="Trần Quốc Tùng")
        Person.objects.create(display_name="Tùng Anh")
        Person.objects.create(display_name="Tungsten Test")
        result = resolve.exact_name_count("trong kho có bao nhiêu ứng viên tên Tùng")
        self.assertEqual(result["scope_total"], 6)
        self.assertEqual(result["matched"], 2)
        self.assertEqual({row["name"] for row in result["people"]},
                         {"Trần Quốc Tùng", "Tùng Anh"})

    def test_ke_hoach_dem_ten_duoc_ep_sang_count(self):
        caller = replies({plan_stage.TASK: json.dumps({
            "shape": "find_people", "search_queries": ["Tùng"]})})
        result = plan_stage.plan("trong kho có bao nhiêu ứng viên tên Tùng",
                                 complete_fn=caller)
        self.assertEqual(result.shape, "count")

    def test_pipeline_dem_ten_khong_goi_retrieve_hay_judge(self):
        plan_obj = plan_stage.QueryPlan(shape="count",
                                        information_need="bao nhiêu ứng viên tên Huyền",
                                        search_queries=["Huyền"])
        with mock.patch("talent.answer.retrieve.retrieve") as retrieve, \
                mock.patch("talent.answer.judge.judge") as judge:
            _plan, _chosen, _near, stats, trace = engine._drain(engine._pipeline(
                "trong kho có bao nhiêu ứng viên tên Huyền", query_plan=plan_obj))
        retrieve.assert_not_called()
        judge.assert_not_called()
        self.assertEqual(stats["exact_name_count"]["matched"], 2)
        self.assertEqual(stats["exact_name_count"]["scope_total"], 3)
        self.assertTrue(trace["count"]["exact"])

    def test_tra_loi_thieu_thuoc_tinh_noi_ro_da_tim_dung_nguoi(self):
        judgement = Judgement(person_id=self.huyen.pk, name=self.huyen.display_name,
                              relevant=False, confidence=.3, why="không có năm sinh",
                              extracted={"chức danh": "Android Engineer"},
                              attribute_status={"chức danh": {"status": "FACT"}},
                              gap="năm sinh")
        text = compose_stage.deterministic_text(
            plan_stage.QueryPlan(shape="followup", information_need="năm sinh"), [],
            {"identified_people": [self.huyen.display_name],
             "identified_judgements": [judgement.as_dict()], "read_failed": False})
        self.assertIn("Đã tìm đúng hồ sơ", text)
        self.assertIn("Android Engineer", text)
        self.assertIn("năm sinh", text)

    def test_nguoi_da_dinh_danh_van_duoc_luu_khi_thieu_thuoc_tinh(self):
        judgement = Judgement(person_id=self.huyen.pk, name=self.huyen.display_name,
                              relevant=False, confidence=.3,
                              why="Không thấy năm sinh", gap="năm sinh")
        people = engine._answer_people([], {"identified_judgements": [judgement.as_dict()]}, [])
        self.assertEqual(people[0]["person_id"], self.huyen.pk)
        self.assertEqual(people[0]["name"], "Nguyễn Thị Huyền")


# ------------------------------- con số "đã rà" trung thực + đếm full-text

class HonestCountTest(TestCase):
    """Ảnh test 04/09: "đã rà 16 hồ sơ" / "40" / "12" — con số nhảy mỗi lượt,
    người dùng đọc thành cỡ kho."""

    def test_payload_kem_ca_co_kho_khong_chi_so_da_ra(self):
        for _ in range(5):
            Person.objects.create(display_name=f"P{_}")
        plan_obj = plan_stage.QueryPlan(shape="find_people",
                                        information_need="kế toán")
        payload = compose_stage.build_payload(
            plan_obj, [], [], {"judged": 3, "retrieved": 3}, [])
        self.assertEqual(payload["kho_co"], 5)
        self.assertEqual(payload["da_ra_soat"], 3)
        self.assertFalse(payload["tra_theo_ten"])

    def test_tra_theo_ten_danh_dau_khi_ghim_nguoi(self):
        plan_obj = plan_stage.QueryPlan(shape="compare",
                                        information_need="so sánh A và B")
        payload = compose_stage.build_payload(
            plan_obj, [], [], {"judged": 0, "pinned": True}, [])
        self.assertTrue(payload["tra_theo_ten"])

    def test_fallback_khong_de_con_so_da_ra_dung_mot_minh(self):
        for _ in range(9):
            Person.objects.create(display_name=f"Q{_}")
        plan_obj = plan_stage.QueryPlan(shape="find_people",
                                        information_need="phi hành gia")
        txt = compose_stage.fallback_text(plan_obj, [], {"judged": 4})
        self.assertIn("trong tổng số 9", txt)

    def test_fallback_tra_theo_ten_noi_dung_khac(self):
        plan_obj = plan_stage.QueryPlan(shape="compare",
                                        information_need="so sánh X và Y")
        txt = compose_stage.fallback_text(plan_obj, [], {"judged": 0, "pinned": True})
        self.assertIn("khớp tên", txt)
        self.assertNotIn("Đã đọc kỹ 0", txt)


class FtsEstimateTest(TestCase):
    """Ảnh test 04/09: "% mảng CNTT" → "0/786 FACT" — rò thuật ngữ, và từ chối
    trong khi kho có 786 CV text đếm được."""

    def test_conditional_count_does_not_receive_fts_union_as_population(self):
        from talent.answer import engine as engine_mod
        plan_obj = plan_stage.QueryPlan(
            shape="count", information_need="ứng viên mảng công nghệ thông tin",
            search_queries=["công nghệ thông tin", "IT"])
        with mock.patch("talent.answer.corpus.facts_for_prompt",
                        return_value="SỐ LIỆU THẬT VỀ KHO:\n- ngành: chưa đủ"), \
             mock.patch("talent.answer.corpus.fts_estimate",
                          return_value={"match": 120, "total": 786}) as estimate:
            facts = engine_mod._corpus_facts(plan_obj)
        self.assertEqual(facts, "")
        estimate.assert_not_called()


class AffirmationContextTest(TestCase):
    """Kiểm tra xử lý câu xác nhận ngắn ("có", "vâng", "ok") sau câu hỏi của Radar."""

    def test_context_block_preserves_tail_of_long_answer(self):
        from types import SimpleNamespace
        from ai.projection import Projection
        from talent.answer import plan as plan_mod

        long_answer = "Đoạn mở đầu danh sách ứng viên.\n" + ("Nội dung chi tiết ứng viên.\n" * 100)
        closing_q = "Anh/chị có muốn Radar ưu tiên lọc sâu hơn các ứng viên đã xác định ở Hà Nội như Giang Lê và Tạ Nguyễn Phương Minh trước không?"
        full_answer = long_answer + "\n" + closing_q

        envelope = SimpleNamespace(projection=Projection(
            recent_turns=[{"question": "Tìm Data Analyst ở Hà Nội", "answer": full_answer}]
        ))
        ctx = plan_mod._context_block(envelope)
        self.assertIn(closing_q, ctx)

    def test_detect_last_proposal_and_clean(self):
        from types import SimpleNamespace
        from ai.projection import Projection
        from talent.answer import plan as plan_mod

        closing_q = "Anh/chị có muốn Radar ưu tiên lọc sâu hơn các ứng viên đã xác định ở Hà Nội như Giang Lê và Tạ Nguyễn Phương Minh trước không?"
        answer_text = (
            "Dưới đây là danh sách ứng viên Data Analyst:\n1. Khoa Lưu Trọng [1]\n\n"
            + closing_q + "\n"
            + "HỒ SƠ ĐƯỢC NHẮC TỚI:\nKHOA LƯU TRONG, Giang Lê, Tạ Nguyễn Phương Minh"
        )
        envelope = SimpleNamespace(projection=Projection(
            recent_turns=[{"question": "Tìm Data Analyst", "answer": answer_text}]
        ))
        proposal = plan_mod.detect_last_proposal(envelope)
        self.assertEqual(proposal, closing_q)

        need = plan_mod.clean_proposal_to_need(proposal)
        self.assertEqual(
            need,
            "Ưu tiên lọc sâu hơn các ứng viên đã xác định ở Hà Nội như Giang Lê và Tạ Nguyễn Phương Minh trước"
        )

    def test_plan_handles_short_affirmation_co(self):
        import json
        from types import SimpleNamespace
        from ai.projection import Projection
        from talent.answer import plan as plan_mod

        closing_q = "Anh/chị có muốn Radar ưu tiên lọc sâu hơn các ứng viên đã xác định ở Hà Nội như Giang Lê và Tạ Nguyễn Phương Minh trước không?"
        answer_text = (
            "Dưới đây là các ứng viên Data Analyst:\n1. Khoa Lưu Trọng\n\n"
            + closing_q + "\n"
            + "HỒ SƠ ĐƯỢC NHẮC TỚI:\nGiang Lê, Tạ Nguyễn Phương Minh"
        )
        envelope = SimpleNamespace(projection=Projection(
            recent_turns=[{"question": "Tìm Data Analyst", "answer": answer_text}],
            last_result={"items": [{"id": 101, "name": "Giang Lê"}, {"id": 102, "name": "Tạ Nguyễn Phương Minh"}]}
        ))

        # Giả lập model ① sinh nhầm câu hỏi làm rõ do chỉ nhận được chữ "có"
        def fake_complete(messages, **kwargs):
            return SimpleNamespace(text=json.dumps({
                "suy_luan": "Người dùng chỉ gõ có nên chưa rõ muốn gì",
                "shape": "general",
                "do_tin_cay": 0.2,
                "cau_hoi_lam_ro": "Anh/chị muốn yêu cầu thêm điều gì về danh sách ứng viên vừa tìm được ạ?",
                "search_queries": []
            }))

        query_plan = plan_mod.plan("có", envelope=envelope, complete_fn=fake_complete)
        self.assertFalse(query_plan.wants_clarification)
        self.assertEqual(query_plan.clarify, "")
        self.assertIn("Hà Nội", query_plan.information_need)
        self.assertIn(query_plan.shape, ("followup", "find_people"))

    def test_chat_is_smalltalk_does_not_trap_affirmation_in_active_context(self):
        from types import SimpleNamespace
        from ai.projection import Projection
        from talent.answer import chat as chat_mod

        envelope = SimpleNamespace(projection=Projection(
            recent_turns=[{"question": "Tìm DA", "answer": "Có muốn lọc tiếp ở Hà Nội không?"}]
        ))
        self.assertFalse(chat_mod._is_smalltalk("ok", envelope=envelope))
        self.assertFalse(chat_mod._is_smalltalk("vâng", envelope=envelope))
        self.assertFalse(chat_mod._is_smalltalk("được", envelope=envelope))

        # Nhưng không có ngữ cảnh hội thoại thì vẫn là smalltalk bình thường
        self.assertTrue(chat_mod._is_smalltalk("ok"))
        self.assertTrue(chat_mod._is_smalltalk("vâng"))


class AbortedEmptyTurnNotPersistedTest(TestCase):
    """Production 19–21/09: 4 lượt client rớt kết nối trước khi có gì để nói bị
    ghi thành bong bóng chat "(không có nội dung)" — ai mở lại luồng đó sau sẽ
    thấy như Radar bị lỗi. `_persist` không được lưu một lượt hỏng như vậy."""

    def setUp(self):
        self.user = User.objects.create_user("persist-user", password="x")

    def test_aborted_va_rong_thi_khong_ghi_hoi_thoai(self):
        from .answer_views import _persist

        result = engine.AnswerResult(text="", people=[], trace={"workflow_models": []})
        _persist(self.user, "thread-1", "turn-1", "", "câu hỏi bất kỳ",
                 result, aborted=True)

        from ai.models import AssistantMessage
        self.assertEqual(AssistantMessage.objects.count(), 0)

    def test_aborted_nhung_da_co_nguoi_van_duoc_ghi(self):
        """Huỷ giữa chừng SAU khi đã tìm được người thì vẫn phải lưu — dở dang
        khác hẳn với rỗng hoàn toàn."""
        from .answer_views import _persist

        result = engine.AnswerResult(
            text="Đã tìm được một phần...", people=[{"person_id": 1, "name": "A", "why": ""}],
            trace={"workflow_models": []})
        _persist(self.user, "thread-2", "turn-2", "", "câu hỏi bất kỳ",
                 result, aborted=True)

        from ai.models import AssistantMessage
        self.assertEqual(AssistantMessage.objects.filter(role="assistant").count(), 1)

    def test_khong_aborted_va_rong_van_duoc_ghi(self):
        """Rỗng nhưng KHÔNG phải do client rớt (luồng chạy xong mà không có gì
        để nói) vẫn phải lưu — im lặng bỏ chỗ này là mất lịch sử thật."""
        from .answer_views import _persist

        result = engine.AnswerResult(text="", people=[], trace={"workflow_models": []})
        _persist(self.user, "thread-3", "turn-3", "", "câu hỏi bất kỳ",
                 result, aborted=False)

        from ai.models import AssistantMessage
        self.assertEqual(AssistantMessage.objects.filter(role="assistant").count(), 1)


class ReadAllExactMatchesTest(TestCase):
    """Người thoả TẤT CẢ điều kiện bắt buộc theo từ khoá luôn được đọc.

    Đo trên production 21/09: `hits` không lọc được gì (189/200 người có hits>=2)
    vì vector luôn trả đủ top-N. Chỉ giao các nhánh AND theo từng điều kiện mới là
    tập khớp thật — và tập đó không được bị cắt bởi `pool`."""

    def _passages(self, ids):
        from talent.answer.retrieve import Passage
        return {pid: [Passage(pid, 0, 0, f"cv {pid}", source="cv")] for pid in ids}

    def test_fuse_giu_nguoi_khop_du_ke_ca_khi_vuot_pool(self):
        from talent.answer import retrieve as R

        exact = [R.Candidate(person_id=pid, name=f"E{pid}", score=0.1, hits=1,
                             exact=True) for pid in range(1, 7)]
        filler = [R.Candidate(person_id=100 + i, name=f"F{i}", score=0.9, hits=3)
                  for i in range(40)]
        # Người vector xếp trên hẳn, người khớp đủ xếp dưới — pool chỉ 8.
        out = R.fuse_candidates([(filler, 1.0), (exact, 1.0)], pool=8)
        ids = [c.person_id for c in out]
        self.assertTrue(set(range(1, 7)) <= set(ids))
        # Họ đứng trước người chỉ-vector, không bị đẩy ra sau.
        self.assertEqual(ids[:6], sorted(ids[:6]))
        self.assertTrue(all(c.exact for c in out if c.person_id <= 6))

    def test_fuse_khong_vuot_tran_read_all_max(self):
        from talent.answer import retrieve as R

        exact = [R.Candidate(person_id=pid, name=f"E{pid}", score=0.1, hits=1,
                             exact=True) for pid in range(1, R.READ_ALL_MAX + 20)]
        out = R.fuse_candidates([(exact, 1.0)], pool=8)
        self.assertEqual(len(out), R.READ_ALL_MAX)

    def test_retrieve_giao_cac_nhanh_and_va_dua_len_dau(self):
        from talent.answer import retrieve as R
        for pid in list(range(1, 13)) + list(range(100, 130)):
            Person.objects.create(pk=pid, display_name=f"P{pid}", is_applicant=True)
        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["sql python"],
            must_have=["SQL", "Python"])
        and_lists = {"SQL": list(range(1, 13)), "Python": [3, 4, 9, 10, 40]}

        def fake_fts(query, limit, *, chunks=True, require_all=False):
            return list(and_lists.get(query, [])) if require_all else []

        fillers = list(range(100, 130))
        everyone = set(range(1, 13)) | set(fillers)
        with mock.patch.object(R, "_fts_person_ids", side_effect=fake_fts), \
                mock.patch.object(R, "_DenseBranch") as dense, \
                mock.patch.object(R, "_passages_for",
                                  side_effect=lambda ids, *a, **k: self._passages(ids)), \
                mock.patch.object(R, "_profile_passages", return_value={}):
            dense.return_value.side_effect = lambda *a, **k: list(fillers)
            cands = R.retrieve(plan_obj, pool=2)
        exact_ids = {c.person_id for c in cands if c.exact}
        # Giao của hai nhánh AND = {3, 4, 9, 10}; ghi 40 không có trong kho nên
        # không thành ứng viên — nhưng bốn người còn lại PHẢI đủ mặt dù pool=2.
        self.assertEqual(exact_ids, {3, 4, 9, 10})
        self.assertTrue({3, 4, 9, 10} <= {c.person_id for c in cands})
        self.assertEqual({c.person_id for c in cands[:4]}, {3, 4, 9, 10})
        self.assertTrue({c.person_id for c in cands} <= everyone | {40})

    def test_mot_dieu_kien_khong_ai_thoa_thi_khong_co_nguoi_khop_du(self):
        """Giao rỗng ⇒ không có gì để đảm bảo; ③ vẫn phán đoán trên pool xếp hạng."""
        from talent.answer import retrieve as R
        for pid in range(1, 6):
            Person.objects.create(pk=pid, display_name=f"P{pid}", is_applicant=True)
        plan_obj = plan_stage.QueryPlan(
            shape="find_people", search_queries=["rust"], must_have=["SQL", "Rust"])
        and_lists = {"SQL": [1, 2, 3], "Rust": []}

        def fake_fts(query, limit, *, chunks=True, require_all=False):
            return list(and_lists.get(query, [])) if require_all else []

        with mock.patch.object(R, "_fts_person_ids", side_effect=fake_fts), \
                mock.patch.object(R, "_DenseBranch") as dense, \
                mock.patch.object(R, "_passages_for",
                                  side_effect=lambda ids, *a, **k: self._passages(ids)), \
                mock.patch.object(R, "_profile_passages", return_value={}):
            dense.return_value.side_effect = lambda *a, **k: [4, 5]
            cands = R.retrieve(plan_obj, pool=5)
        self.assertFalse(any(c.exact for c in cands))
