# -*- coding: utf-8 -*-
"""Growth Answer Engine (`rb/answer/`).

Mỗi lớp test ghim một QUYẾT ĐỊNH SẢN PHẨM, không phải một chi tiết cài đặt. Tên
lớp nói quyết định đó là gì, docstring nói vì sao sai nó thì tốn kém. Nếu một
test ở đây đỏ sau khi ai đó sửa code, câu hỏi đúng không phải "sửa test thế
nào" mà là "quyết định này còn đúng không".
"""
import json
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from people.models import Person, Relationship, Signal

from .answer import aggregate as aggregate_stage
from .answer import cache as cache_stage
from .answer import compose as compose_stage
from .answer import engine
from .answer import evidence as evidence_stage
from .answer import judge as judge_stage
from .answer import plan as plan_stage
from .answer import retrieve as retrieve_stage
from .answer.evidence import Candidate, Passage
from .answer.judge import Judgement
from .answer.plan import ProspectPlan
from .models import (OpportunityOutcome, ProductInterest, RBOpportunity,
                     RBProfile)


class FakeCompletion:
    def __init__(self, text, provider="fake", model="fake-1"):
        self.text = text
        self.provider = provider
        self.model = model


def fake_complete(payload):
    """`complete_fn` trả đúng một JSON cố định — không bao giờ gọi mạng."""
    def caller(messages, **kwargs):
        return FakeCompletion(json.dumps(payload, ensure_ascii=False))
    return caller


def _days_ago(days):
    return timezone.now() - timezone.timedelta(days=days)


def _customer(name, *, location="Hà Nội", phone="", email="", occupation="",
              owner=None, segment=""):
    person = Person.objects.create(display_name=name, location=location,
                                   primary_phone=phone, primary_email=email,
                                   is_applicant=False)
    RBProfile.objects.create(person=person, occupation=occupation,
                             sales_owner=owner, segment=segment)
    return person


def _post(person, content, *, days=1):
    from social.models import SocialPost
    return SocialPost.objects.create(
        person=person, content=content, posted_at=_days_ago(days),
        external_id=f"post-{person.pk}-{SocialPost.objects.count()}")


# =========================================================== ① lập kế hoạch

class PlanNeverFallsIntoEightFixedKeysTest(SimpleTestCase):
    """Bộ cũ ép câu hỏi vào 8 khoá; mọi thứ khác rơi mất im lặng.

    "Có dấu hiệu chuẩn bị mua nhà" không vừa ô nào → RM nhận danh sách lọc theo
    không gì cả. Ở đây điều kiện là câu chữ tự nhiên và phải sống sót tới ③.
    """

    def test_dieu_kien_mem_song_sot_nguyen_van(self):
        plan = plan_stage.plan("khách nào có dấu hiệu chuẩn bị mua nhà", complete_fn=fake_complete({
            "suy_luan": "RM tìm khách có ý định mua nhà.",
            "shape": "find_prospects", "do_tin_cay": 0.9,
            "information_need": "khách có dấu hiệu chuẩn bị mua nhà",
            "must_have": ["có dấu hiệu chuẩn bị mua nhà"],
            "search_queries": ["mua nhà", "vay mua chung cư", "buy apartment"],
            "san_pham": ["mortgage"],
        }))
        self.assertEqual(plan.must_have, ["có dấu hiệu chuẩn bị mua nhà"])
        self.assertIn("vay mua chung cư", plan.search_queries)
        self.assertEqual(plan.products, ["mortgage"])

    def test_gia_tri_bia_ra_khong_thanh_bo_loc(self):
        """Lọc theo một giá trị không tồn tại thì kết quả luôn rỗng và RM không biết vì sao."""
        plan = plan_stage.plan("khách vip ở hà nội", complete_fn=fake_complete({
            "shape": "find_prospects", "do_tin_cay": 0.9,
            "bo_loc": {"phan_khuc": "VIP", "tinh_thanh": "Hà Nội", "cap_bac": "boss"},
            "san_pham": ["tien_ao", "credit_card"],
        }))
        self.assertNotIn("phan_khuc", plan.filters)
        self.assertNotIn("cap_bac", plan.filters)
        self.assertEqual(plan.filters["tinh_thanh"], "Hà Nội")
        self.assertEqual(plan.products, ["credit_card"])

    def test_khong_co_truy_van_thi_dung_chinh_cau_hoi(self):
        plan = plan_stage.plan("tìm khách", complete_fn=fake_complete({
            "shape": "find_prospects", "do_tin_cay": 0.9, "search_queries": []}))
        self.assertTrue(plan.search_queries)


class PlanScopeGuardTest(SimpleTestCase):
    """Chọn nhầm shape ở Growth đổi PHẠM VI DỮ LIỆU, không chỉ cách trình bày."""

    def test_general_cho_cau_ve_kho_bi_ep_ve_analyze(self):
        """Lỗi tệ nhất: "tôi không có dữ liệu" trong khi kho có hàng nghìn khách."""
        plan = plan_stage.plan("kho mình có bao nhiêu khách hàng", complete_fn=fake_complete({
            "shape": "general", "do_tin_cay": 0.5, "suy_luan": ""}))
        self.assertEqual(plan.shape, "analyze")

    def test_general_duoc_giu_khi_rat_chac_va_da_suy_luan(self):
        plan = plan_stage.plan("lãi suất vay mua nhà của msb", complete_fn=fake_complete({
            "shape": "general", "do_tin_cay": 0.95,
            "suy_luan": "Hỏi về sản phẩm của ngân hàng, không về khách trong kho."}))
        self.assertEqual(plan.shape, "general")

    def test_khach_cua_toi_bi_ep_ve_portfolio_khi_khong_chac(self):
        """Trả khách của người khác → RM gọi nhầm người đồng nghiệp đang chăm."""
        plan = plan_stage.plan("khách của tôi ai nên gọi tuần này", complete_fn=fake_complete({
            "shape": "find_prospects", "do_tin_cay": 0.6, "suy_luan": "tìm khách"}))
        self.assertEqual(plan.shape, "portfolio")

    def test_chua_ai_cham_bi_ep_ve_whitespace(self):
        plan = plan_stage.plan("khách nào chưa ai chăm ở đà nẵng", complete_fn=fake_complete({
            "shape": "find_prospects", "do_tin_cay": 0.6, "suy_luan": "tìm khách"}))
        self.assertEqual(plan.shape, "whitespace")

    def test_llm_chet_van_doan_dung_pham_vi(self):
        def dead(*a, **k):
            raise RuntimeError("provider chết")
        plan = plan_stage.plan("danh mục của tôi có ai sắp rời bỏ", complete_fn=dead)
        self.assertTrue(plan.fallback)
        self.assertEqual(plan.shape, "portfolio")


class WidenNeverRelaxesComplianceTest(SimpleTestCase):
    """Nới một ràng buộc tuân thủ để có thêm kết quả là quyết định không ai được làm thay RM."""

    def test_nau_must_have_xuong_should_have_chu_khong_xoa(self):
        widened = plan_stage.widen(ProspectPlan(must_have=["vay mua nhà"],
                                                should_have=["ở Hà Nội"]))
        self.assertEqual(widened.must_have, [])
        self.assertIn("vay mua nhà", widened.should_have)

    def test_giu_loai_co_hoi_dang_mo_bo_phan_con_lai(self):
        widened = plan_stage.widen(ProspectPlan(filters={
            "loai_co_hoi_dang_mo": True, "tinh_thanh": "Hà Nội", "phan_khuc": "priority"}))
        self.assertEqual(widened.filters, {"loai_co_hoi_dang_mo": True})


# ============================================================ bằng chứng

class EvidenceHasTimeTest(TestCase):
    """Tín hiệu mua hàng mất giá theo thời gian; CV thì không. Đây là khác biệt lớn nhất."""

    def test_moi_doan_mang_thoi_diem_va_tuoi_tinh_dung(self):
        person = _customer("Nguyễn Văn Một")
        _post(person, "Có ai tư vấn vay mua chung cư giúp em không ạ", days=5)
        rows = evidence_stage.passages_for([person.pk])[person.pk]
        social = [p for p in rows if p.source == "social"]
        self.assertEqual(social[0].age_days(), 5)

    def test_nen_tinh_khong_duoc_huong_loi_the_cua_du_lieu_moi(self):
        """Không biết thời điểm thì KHÔNG phải mới — đoán theo chiều "mới" giục RM gọi sai."""
        self.assertIsNone(Passage(1, "nghề nghiệp", "profile").age_days())
        candidate = Candidate(1, "x", passages=[Passage(1, "nghề nghiệp", "profile")])
        self.assertIsNone(candidate.freshest_days())

    def test_ket_qua_tiep_can_dung_truoc_bai_dang(self):
        """Bỏ kết quả tiếp cận để nhường chỗ cho bài cũ = chào lại người vừa từ chối."""
        person = _customer("Trần Thị Hai")
        for i in range(10):
            _post(person, f"Bài đăng số {i} hỏi về thẻ tín dụng hoàn tiền", days=i + 1)
        opportunity = RBOpportunity.objects.create(person=person, product="credit_card")
        OpportunityOutcome.objects.create(opportunity=opportunity, person=person,
                                          outcome=OpportunityOutcome.OUTCOME_NOT_INTERESTED,
                                          note="Khách nói đã có thẻ ngân hàng khác")
        rows = evidence_stage.passages_for([person.pk], per_person=3)[person.pk]
        self.assertEqual(rows[0].source, "outcome")

    def test_mot_nguoi_dang_nhieu_bai_khong_lam_nguoi_khac_mu_bang_chung(self):
        """Cắt toàn cục theo độ mới → người hay đăng ăn hết hạn mức, người khác vào ③ với zero bằng chứng."""
        on_ao = _customer("Người Đăng Nhiều")
        im_lang = _customer("Người Đăng Ít")
        for i in range(40):
            _post(on_ao, f"Bài mới số {i} về vay tiêu dùng", days=0)
        _post(im_lang, "Em đang cần vay mua xe cuối năm", days=30)
        rows = evidence_stage.passages_for([on_ao.pk, im_lang.pk])
        self.assertTrue(any(p.source == "social" for p in rows[im_lang.pk]))

    def test_so_dien_thoai_trong_bai_dang_bi_che(self):
        person = _customer("Lê Văn Ba")
        _post(person, "Cần vay 500 triệu mua nhà, liên hệ 0901234567 hoặc a@b.vn")
        text = " ".join(p.text for p in evidence_stage.passages_for([person.pk])[person.pk])
        self.assertNotIn("0901234567", text)
        self.assertNotIn("a@b.vn", text)

    def test_mot_nguon_hong_khong_lam_mu_ca_luot(self):
        person = _customer("Phạm Thị Bốn", occupation="Kế toán trưởng")
        with mock.patch.object(evidence_stage, "_social_passages",
                               side_effect=RuntimeError("bảng hỏng")):
            rows = evidence_stage.passages_for([person.pk])[person.pk]
        self.assertTrue(any(p.source == "profile" for p in rows))


# ============================================================== ② truy hồi

class ComplianceIsAGateNotAFilterTest(TestCase):
    """`do_not_contact` áp ở ②, trước mọi xếp hạng — không nằm trong prompt của ⑤."""

    def setUp(self):
        self.an = _customer("Khách Bình Thường", occupation="Quản lý")
        self.cam = _customer("Khách Không Liên Hệ", occupation="Quản lý")
        Relationship.objects.create(person=self.cam, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        _post(self.an, "Cần vay mua nhà")
        _post(self.cam, "Cần vay mua nhà")

    def test_dnc_khong_bao_gio_vao_pool(self):
        ids = [c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(search_queries=["vay mua nhà"]))]
        self.assertIn(self.an.pk, ids)
        self.assertNotIn(self.cam.pk, ids)

    def test_dnc_bi_chan_KE_CA_KHI_ghim_dich_danh(self):
        """Khác Talent: ở đó ghim nghĩa là "đọc kỹ dù truy hồi xếp thấp". Ở đây DNC phủ quyết."""
        ids = [c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(shape="compare", search_queries=["x"]),
            pinned_ids=[self.cam.pk, self.an.pk])]
        self.assertNotIn(self.cam.pk, ids)


class PortfolioScopeTest(TestCase):
    """Lần đầu trong hệ thống, danh tính người hỏi ĐỔI TẬP KẾT QUẢ."""

    def setUp(self):
        User = get_user_model()
        self.rm_a = User.objects.create_user("rm-a")
        self.rm_b = User.objects.create_user("rm-b")
        self.cua_a = _customer("Khách Của A", owner=self.rm_a)
        self.cua_b = _customer("Khách Của B", owner=self.rm_b)
        self.bo_trong = _customer("Khách Bỏ Trống")
        for person in (self.cua_a, self.cua_b, self.bo_trong):
            _post(person, "Đang tìm hiểu thẻ tín dụng")

    def test_portfolio_chi_tra_khach_cua_chinh_rm(self):
        ids = {c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(shape="portfolio", search_queries=["thẻ tín dụng"]), user=self.rm_a)}
        self.assertEqual(ids, {self.cua_a.pk})

    def test_portfolio_khong_co_user_tra_rong_KHONG_roi_ve_toan_kho(self):
        """Rơi về toàn kho = trả khách của người khác cho câu "khách của tôi"."""
        self.assertEqual(retrieve_stage.retrieve(
            ProspectPlan(shape="portfolio", search_queries=["thẻ tín dụng"]), user=None), [])

    def test_whitespace_loai_khach_da_co_nguoi_cham_va_co_hoi_dang_mo(self):
        co_co_hoi = _customer("Bỏ Trống Nhưng Có Cơ Hội")
        RBOpportunity.objects.create(person=co_co_hoi, product="credit_card")
        _post(co_co_hoi, "Đang tìm hiểu thẻ tín dụng")
        ids = {c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(shape="whitespace", search_queries=["thẻ tín dụng"]))}
        self.assertEqual(ids, {self.bo_trong.pk})


class InferredProductIsNotAGateTest(TestCase):
    """`san_pham` do ① SUY RA không được loại người chưa có `ProductInterest`.

    Lỗi tìm được bằng chính test HTTP: khách tự viết "em cần vay mua xe" — bằng
    chứng mạnh nhất — bị loại trước truy hồi chỉ vì hệ thống chưa kịp suy ra
    quan tâm `auto_loan` nào. Đó là nguyên lỗi của `rb/prospects.py` cũ, quay lại
    qua một bộ lọc trông vô hại.
    """

    def test_khach_chi_co_loi_tu_viet_van_duoc_tim_thay(self):
        tu_viet = _customer("Chỉ Có Lời Tự Viết")
        _post(tu_viet, "Em cần vay mua xe điện cuối năm nay", days=4)
        ids = [c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(search_queries=["vay mua xe"], products=["auto_loan"]))]
        self.assertIn(tu_viet.pk, ids)

    def test_san_pham_van_day_len_nguoi_co_quan_tam_ro(self):
        """Không phải cổng — nhưng vẫn là tín hiệu xếp hạng."""
        co_quan_tam = _customer("Có Quan Tâm Rõ")
        khong_co = _customer("Không Có Quan Tâm")
        ProductInterest.objects.create(profile=co_quan_tam.rb_profile, product="auto_loan",
                                       confidence=0.9, observed_at=_days_ago(3))
        order = [c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(search_queries=["khong khop gi ca"], products=["auto_loan"]))]
        self.assertIn(co_quan_tam.pk, order)
        if khong_co.pk in order:
            self.assertLess(order.index(co_quan_tam.pk), order.index(khong_co.pk))


class BranchWeightsReflectEvidenceStrengthTest(TestCase):
    """Lời khách tự viết > thuộc tính hồ sơ khớp chữ. Talent thì mọi nhánh ngang nhau — đúng cho CV, sai ở đây."""

    def test_nguoi_tu_noi_nhu_cau_dung_truoc_nguoi_chi_khop_nghe_nghiep(self):
        chi_khop_chu = _customer("Khớp Chữ", occupation="Chuyên viên vay mua nhà")
        tu_noi = _customer("Tự Nói Ra")
        _post(tu_noi, "Nhà em đang cần vay mua nhà gấp, ai tư vấn giúp")
        order = [c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(search_queries=["vay mua nhà"]))]
        self.assertLess(order.index(tu_noi.pk), order.index(chi_khop_chu.pk))


# ================================================================ ③ đọc

class JudgeRefusesUnbackedClaimsTest(SimpleTestCase):
    def _candidate(self):
        return Candidate(7, "Khách Bảy", passages=[
            Passage(7, "Em đang cần vay mua chung cư khoảng 2 tỷ", "social",
                    observed_at=_days_ago(3), ref="socialpost:1")])

    def test_trich_dan_bia_ra_bi_bo(self):
        rows = judge_stage._parse_batch(json.dumps({"ket_qua": [{
            "id": 7, "thoa": True, "do_tin": 0.9, "vi_sao": "cần vay",
            "trich_dan": [{"doan": 1, "nguyen_van": "Em có thu nhập 100 triệu mỗi tháng"}],
        }]}), [self._candidate()], ProspectPlan())
        self.assertEqual(rows[0].evidence, [])

    def test_thoa_ma_khong_trich_duoc_bi_ha_xuong_khong_thoa(self):
        """"Thoả" không có bằng chứng là khẳng định trần — cả chặng sinh ra để không còn thứ đó."""
        rows = judge_stage._parse_batch(json.dumps({"ket_qua": [{
            "id": 7, "thoa": True, "do_tin": 0.9, "trich_dan": []}]}),
            [self._candidate()], ProspectPlan())
        self.assertFalse(rows[0].relevant)

    def test_trich_dan_that_duoc_giu_kem_tuoi_bang_chung(self):
        rows = judge_stage._parse_batch(json.dumps({"ket_qua": [{
            "id": 7, "thoa": True, "do_tin": 0.9,
            "trich_dan": [{"doan": 1, "nguyen_van": "Em đang cần vay mua chung cư"}],
        }]}), [self._candidate()], ProspectPlan())
        self.assertTrue(rows[0].relevant)
        self.assertEqual(rows[0].evidence[0]["age_days"], 3)
        self.assertEqual(rows[0].freshest_days, 3)

    def test_id_bia_ra_bi_bo_khong_gan_nham_nguoi(self):
        rows = judge_stage._parse_batch(json.dumps({"ket_qua": [{
            "id": 999, "thoa": True, "do_tin": 0.9}]}), [self._candidate()], ProspectPlan())
        self.assertEqual(rows, [])

    def test_doc_duoc_loi_tu_choi(self):
        rows = judge_stage._parse_batch(json.dumps({"ket_qua": [{
            "id": 7, "thoa": False, "da_tu_choi": True,
            "nhu_cau_hay_trang_thai": "trang_thai"}]}), [self._candidate()], ProspectPlan())
        self.assertTrue(rows[0].declined)
        self.assertEqual(rows[0].need_kind, "trang_thai")

    def test_moi_lo_hong_thi_bao_broken_khong_phai_kho_rong(self):
        """Lỗi nhà cung cấp mà trông như kho rỗng thì ⑤ báo "không có khách" — sai."""
        def dead(*a, **k):
            raise RuntimeError("429")
        report = judge_stage.judge(ProspectPlan(), [self._candidate()], complete_fn=dead)
        self.assertTrue(report.broken)


# ============================================================ ④ tổng hợp

class AggregateRanksByWhoToCallFirstTest(TestCase):
    """RM mở Growth Radar để biết GỌI AI TRƯỚC, không để đọc danh sách khớp chữ."""

    def _judgement(self, person, **kw):
        base = dict(person_id=person.pk, name=person.display_name, relevant=True,
                    confidence=0.9, evidence=[{"quote": "x"}], freshest_days=3)
        base.update(kw)
        return Judgement(**base)

    def test_da_tu_choi_bi_LOAI_khong_phai_ha_diem(self):
        khach = _customer("Đã Từ Chối", phone="0900000001")
        chosen, _near, stats = aggregate_stage.aggregate(
            ProspectPlan(), [self._judgement(khach, declined=True)])
        self.assertEqual(chosen, [])
        self.assertEqual(stats["declined_filtered"], 1)

    def test_luoi_dnc_thu_hai_bat_duoc_phan_doan_da_cache(self):
        """Khách bật DNC sáng nay vẫn nằm trong phán đoán cache từ tối qua."""
        khach = _customer("Vừa Bật DNC", phone="0900000002")
        cu = self._judgement(khach)
        Relationship.objects.create(person=khach, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        chosen, _near, stats = aggregate_stage.aggregate(ProspectPlan(), [cu])
        self.assertEqual(chosen, [])
        self.assertEqual(stats["dnc_filtered"], 1)

    def test_mac_dinh_xep_theo_diem_uu_tien(self):
        goi_duoc = _customer("Gọi Được", phone="0900000003", occupation="Giám đốc")
        khong_goi_duoc = _customer("Không Gọi Được", occupation="Nhân viên")
        chosen, _near, stats = aggregate_stage.aggregate(ProspectPlan(), [
            self._judgement(khong_goi_duoc, confidence=0.99),
            self._judgement(goi_duoc, confidence=0.6)])
        self.assertEqual(stats["sorted_by"]["key"], "priority_score")
        self.assertEqual(chosen[0].person_id, goi_duoc.pk)

    def test_diem_tung_chieu_duoc_gan_de_5_khong_tinh_lai(self):
        khach = _customer("Có Điểm", phone="0900000004")
        chosen, _near, _stats = aggregate_stage.aggregate(
            ProspectPlan(), [self._judgement(khach)])
        dims = chosen[0].criteria[0]["dimensions"]
        self.assertEqual(set(dims), {"fit", "need", "timing", "reachability", "value"})


# ================================================================ ⑤ viết

class PriorityBreakdownReachesComposeTest(TestCase):
    """④ tính năm chiều + lý do bằng chữ (`rb/scoring.py`) — trước đây chỉ
    `diem_uu_tien` (con số gộp) tới ⑤, nên "vì sao khách này ưu tiên cao" không
    có gì để model trả lời ngoài đoán. `diem_thanh_phan` phải mang đủ cả hai."""

    def test_diem_thanh_phan_mang_ca_so_lan_ly_do(self):
        khach = _customer("Ưu Tiên Cao", phone="0900000009")
        judgement = Judgement(person_id=khach.pk, name=khach.display_name, why="cần vay",
                              criteria=[{
                                  "priority_score": 82.0, "product": "mortgage",
                                  "dimensions": {"fit": 75.0, "need": 90.0, "timing": 60.0,
                                                "reachability": 100.0, "value": 70.0},
                                  "why": ["Phân khúc Ưu tiên", "Nghề nghiệp cấp quản lý: Giám đốc"]}])
        payload = compose_stage.build_payload(ProspectPlan(), [judgement], [],
                                              {"judged": 1, "relevant": 1}, sources=[])
        detail = payload["khach_hang"][0]["diem_thanh_phan"]
        self.assertEqual(detail, {"phu_hop": 75.0, "nhu_cau": 90.0, "thoi_diem": 60.0,
                                  "de_tiep_can": 100.0, "gia_tri": 70.0,
                                  "ly_do": ["Phân khúc Ưu tiên",
                                           "Nghề nghiệp cấp quản lý: Giám đốc"]})

    def test_khong_co_dimensions_thi_tra_so_0_khong_loi(self):
        khach = _customer("Chưa Chấm Điểm")
        judgement = Judgement(person_id=khach.pk, name=khach.display_name, criteria=[{}])
        payload = compose_stage.build_payload(ProspectPlan(), [judgement], [],
                                              {"judged": 1, "relevant": 1}, sources=[])
        detail = payload["khach_hang"][0]["diem_thanh_phan"]
        self.assertEqual(detail["ly_do"], [])
        self.assertEqual(detail["phu_hop"], 0.0)


class ActionIsChosenByCodeTest(TestCase):
    """Để model chọn hành động thì khách không có số điện thoại vẫn được đề xuất "gọi ngay"."""

    def test_khong_co_lien_he_thi_xin_thong_tin_du_diem_cao(self):
        khach = _customer("Không Có Số")
        judgement = Judgement(person_id=khach.pk, name=khach.display_name, criteria=[{
            "priority_score": 95, "product": "mortgage",
            "dimensions": {"need": 95, "timing": 95, "reachability": 0}}])
        self.assertEqual(compose_stage.next_action_for(judgement), "ASK_FOR_INFORMATION")

    def test_ket_qua_de_sau_thi_kich_hoat_lai(self):
        khach = _customer("Để Sau", phone="0900000005")
        opportunity = RBOpportunity.objects.create(person=khach, product="mortgage",
                                                   status=RBOpportunity.STATUS_LOST)
        OpportunityOutcome.objects.create(opportunity=opportunity, person=khach,
                                          outcome=OpportunityOutcome.OUTCOME_MAYBE_LATER)
        judgement = Judgement(person_id=khach.pk, name=khach.display_name, criteria=[{
            "priority_score": 60, "product": "mortgage",
            "dimensions": {"need": 60, "timing": 60, "reachability": 70}}])
        self.assertEqual(compose_stage.next_action_for(judgement), "REACTIVATE")

    def test_doc_hong_KHONG_duoc_noi_la_khong_co_khach(self):
        text = compose_stage.deterministic_text(
            ProspectPlan(), [], {"read_failed": True, "retrieved": 12, "judged": 0})
        self.assertIn("KHÔNG phải kết luận", text)
        self.assertNotIn("Chưa tìm thấy khách hàng phù hợp", text)


# ============================================================ cache

class CacheDiesWhenComplianceChangesTest(TestCase):
    def test_bat_dnc_lam_van_tay_kho_doi(self):
        """Không thì cache phục vụ tên người vừa xin không liên hệ thêm sáu tiếng."""
        khach = _customer("Vân Tay")
        truoc = cache_stage.corpus_fingerprint()
        Relationship.objects.create(person=khach, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        self.assertNotEqual(truoc, cache_stage.corpus_fingerprint())

    def test_ket_qua_tiep_can_moi_lam_van_tay_kho_doi(self):
        khach = _customer("Vừa Từ Chối")
        opportunity = RBOpportunity.objects.create(person=khach, product="fx")
        truoc = cache_stage.corpus_fingerprint()
        OpportunityOutcome.objects.create(opportunity=opportunity, person=khach,
                                          outcome=OpportunityOutcome.OUTCOME_NOT_INTERESTED)
        self.assertNotEqual(truoc, cache_stage.corpus_fingerprint())

    def test_hai_rm_khong_dung_chung_muc_portfolio(self):
        User = get_user_model()
        plan = ProspectPlan(shape="portfolio")
        a = cache_stage.key_for("khách của tôi", user=User.objects.create_user("c-a"),
                                query_plan=plan)
        b = cache_stage.key_for("khách của tôi", user=User.objects.create_user("c-b"),
                                query_plan=plan)
        self.assertNotEqual(a, b)


# ============================================================== engine

class EngineEndToEndTest(TestCase):
    """Cả dây chuyền với model giả — không có lời gọi mạng nào."""

    def setUp(self):
        self.khach = _customer("Hoàng Văn Năm", phone="0900000006",
                               occupation="Trưởng phòng kinh doanh")
        _post(self.khach, "Nhà em đang cần vay mua chung cư khoảng 2 tỷ, ai tư vấn giúp", days=2)
        ProductInterest.objects.create(profile=self.khach.rb_profile, product="mortgage",
                                       confidence=0.8, observed_at=_days_ago(2))

    def _complete(self):
        khach = self.khach

        def caller(messages, **kwargs):
            body = messages[-1]["content"]
            if "DANH SÁCH KHÁCH HÀNG" in body:
                return FakeCompletion(json.dumps({"ket_qua": [{
                    "id": khach.pk, "thoa": True, "do_tin": 0.9,
                    "nhu_cau_hay_trang_thai": "nhu_cau",
                    "vi_sao": "Tự viết cần vay mua chung cư 2 ngày trước.",
                    "trich_dan": [{"doan": 1, "nguyen_van": "đang cần vay mua chung cư"}],
                }]}, ensure_ascii=False))
            return FakeCompletion(json.dumps({
                "suy_luan": "Tìm khách cần vay mua nhà.", "shape": "find_prospects",
                "do_tin_cay": 0.9, "information_need": "khách cần vay mua nhà",
                "search_queries": ["vay mua chung cư"], "san_pham": ["mortgage"],
            }, ensure_ascii=False))
        return caller

    def _stream(self, text):
        def streamer(messages, **kwargs):
            yield {"type": "answer", "text": text}
            yield {"type": "done", "completion": FakeCompletion(text)}
        return streamer

    def test_tim_khach_tra_nguoi_co_nguon_va_hanh_dong(self):
        text = "1. **Hoàng Văn Năm** — mortgage. Cần vay mua chung cư [1]. → Gọi ngay"
        result = engine.answer("khách nào cần vay mua nhà", complete_fn=self._complete(),
                               stream_fn=self._stream(text))
        self.assertEqual([p["person_id"] for p in result.people], [self.khach.pk])
        person = result.people[0]
        self.assertTrue(person["action"])
        self.assertEqual(person["product"], "mortgage")
        self.assertTrue(result.sources)
        self.assertEqual(result.trace["citation_audit"]["status"], "PASS")

    def test_bai_viet_thieu_trich_dan_bi_verify_bat_va_viet_lai(self):
        calls = {"n": 0}
        good = "1. **Hoàng Văn Năm** — cần vay mua chung cư [1]."

        def streamer(messages, **kwargs):
            calls["n"] += 1
            text = "1. **Hoàng Văn Năm** cần vay mua nhà." if calls["n"] == 1 else good
            yield {"type": "answer", "text": text}
            yield {"type": "done", "completion": FakeCompletion(text)}

        result = engine.answer("khách nào cần vay mua nhà", complete_fn=self._complete(),
                               stream_fn=streamer)
        self.assertEqual(calls["n"], 2)
        self.assertEqual(result.text, good)

    def test_menh_lenh_di_nhanh_cau_lenh_khong_chay_tim_kiem(self):
        """Câu lệnh chạy lại ② thì có thể ra danh sách KHÁC danh sách RM đang trỏ tới."""
        with mock.patch.object(retrieve_stage, "retrieve") as retrieve:
            result = engine.answer("soạn tin cho 3 khách đầu", complete_fn=fake_complete({
                "shape": "action", "do_tin_cay": 0.9, "suy_luan": "mệnh lệnh"}))
        retrieve.assert_not_called()
        # Không có danh sách lượt trước → hỏi lại, không đoán.
        self.assertEqual(result.trace["mode"], "action_needs_list")
        self.assertTrue(result.trace["keeps_last_result"])

    def test_mo_ho_thi_hoi_lai_khong_chay_pipeline(self):
        with mock.patch.object(retrieve_stage, "retrieve") as retrieve:
            result = engine.answer("khách vay", complete_fn=fake_complete({
                "shape": "find_prospects", "do_tin_cay": 0.2,
                "cau_hoi_lam_ro": "Anh/chị muốn khách đang cần vay hay đã từng vay ạ?"}))
        retrieve.assert_not_called()
        self.assertEqual(result.trace["mode"], "clarify")

    def test_cau_chung_di_nhanh_hoi_thoai_voi_persona_growth(self):
        seen = {}

        def fake_chat(question, **kwargs):
            seen["surface"] = kwargs.get("surface")
            yield {"type": "done", "payload": {"text": "ok"}}

        with mock.patch("talent.answer.chat.stream_chat", fake_chat):
            engine.answer("lãi suất vay mua nhà của msb", complete_fn=fake_complete({
                "shape": "general", "do_tin_cay": 0.95,
                "suy_luan": "Hỏi về sản phẩm ngân hàng."}))
        self.assertEqual(seen["surface"], "prospect")


# ================================================================ HTTP

class AskEndpointTest(TestCase):
    """`/api/v1/rb/ask/` — cùng cổng module với mọi API `/rb/` khác."""

    def setUp(self):
        from accounts import roles
        from django.contrib.auth.models import Group
        roles.ensure_groups()
        User = get_user_model()
        self.rm = User.objects.create_user("ask-rm", password="mat-khau-dai-1")
        self.rm.groups.add(Group.objects.get(name=roles.RB_SALES))
        self.recruiter = User.objects.create_user("ask-recruiter", password="mat-khau-dai-1")
        self.recruiter.groups.add(Group.objects.get(name=roles.RECRUITER))

    def _post(self, body):
        return self.client.post("/api/v1/rb/ask/", data=json.dumps(body),
                                content_type="application/json")

    def test_chua_dang_nhap_401(self):
        self.assertEqual(self._post({"q": "x"}).status_code, 401)

    def test_khong_co_module_rb_403(self):
        """Nhà tuyển dụng thuần không được hỏi về kho khách hàng."""
        self.client.force_login(self.recruiter)
        self.assertEqual(self._post({"q": "khách cần vay"}).status_code, 403)

    def test_cau_hoi_rong_400(self):
        self.client.force_login(self.rm)
        self.assertEqual(self._post({"q": "   "}).status_code, 400)

    def test_luong_khong_stream_tra_payload_va_ghi_hoi_thoai(self):
        from ai.models import AssistantMessage
        self.client.force_login(self.rm)
        khach = _customer("Khách Qua HTTP", phone="0900000009")
        _post(khach, "Em cần vay mua xe điện cuối năm nay", days=4)

        def caller(messages, **kwargs):
            if "DANH SÁCH KHÁCH HÀNG" in messages[-1]["content"]:
                return FakeCompletion(json.dumps({"ket_qua": [{
                    "id": khach.pk, "thoa": True, "do_tin": 0.9,
                    "vi_sao": "Tự viết cần vay mua xe.",
                    "trich_dan": [{"doan": 1, "nguyen_van": "cần vay mua xe điện"}]}]},
                    ensure_ascii=False))
            return FakeCompletion(json.dumps({
                "shape": "find_prospects", "do_tin_cay": 0.9, "suy_luan": "tìm",
                "search_queries": ["vay mua xe"], "san_pham": ["auto_loan"]},
                ensure_ascii=False))

        def streamer(messages, **kwargs):
            text = "1. **Khách Qua HTTP** — cần vay mua xe [1]."
            yield {"type": "answer", "text": text}
            yield {"type": "done", "completion": FakeCompletion(text)}

        with mock.patch("rb.answer.plan.complete", caller), \
                mock.patch("rb.answer.judge.complete", caller), \
                mock.patch("rb.answer.engine.router_stream", streamer):
            response = self._post({"q": "khách nào cần vay mua xe", "stream": False,
                                   "conversation_id": "growth-http-thread",
                                   "client_turn_id": "http-turn-1"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual([p["person_id"] for p in data["people"]], [khach.pk])
        self.assertTrue(data["grounded"])
        # Ghi đúng shape `items` {id, name} — đó là thứ
        # `ai/projection.py::last_result_people()` đọc. Sai khoá thì câu hỏi tiếp
        # ("so sánh hai khách đầu") không biết đang nói về ai.
        assistant = AssistantMessage.objects.filter(
            thread__user=self.rm, thread__surface="prospect", role="assistant").first()
        self.assertIsNotNone(assistant)
        items = assistant.metadata["result_snapshot"]["items"]
        self.assertEqual([it["id"] for it in items], [khach.pk])

    def test_lay_lai_luot_khong_co_404(self):
        self.client.force_login(self.rm)
        response = self.client.get("/api/v1/rb/ask/turn/khong-ton-tai/")
        self.assertEqual(response.status_code, 404)


# ============================================================ câu lệnh

from .answer import act as act_stage  # noqa: E402


def _envelope(items):
    projection = SimpleNamespace(
        last_result={"kind": "answer", "items": items},
        last_result_people=lambda limit=12: [{"id": i["id"], "name": i["name"]}
                                             for i in items][:limit])
    return SimpleNamespace(projection=projection)


class CommandVerbIsDecidedByCodeTest(SimpleTestCase):
    """Tập động từ đóng: model không được tự nghĩ ra một việc để làm."""

    def test_nhan_dung_dong_tu(self):
        cases = {
            "soạn tin cho 3 khách đầu": act_stage.VERB_MESSAGE,
            "viết tin nhắn zalo cho khách thứ 2": act_stage.VERB_MESSAGE,
            "soạn kịch bản gọi cho khách đầu tiên": act_stage.VERB_CALL_SCRIPT,
            "viết lời để gọi cho cả danh sách": act_stage.VERB_CALL_SCRIPT,
            "tạo cơ hội cho cả danh sách": act_stage.VERB_CREATE,
            "tạo cơ hội rồi soạn tin sau": act_stage.VERB_CREATE,
        }
        for question, verb in cases.items():
            with self.subTest(question=question):
                self.assertEqual(act_stage.detect_verb(question), verb)

    def test_cau_hoi_tra_cuu_khong_phai_cau_lenh(self):
        for question in ("khách nào cần vay mua nhà", "khách của tôi ai nên gọi",
                         "so sánh hai khách đầu"):
            with self.subTest(question=question):
                self.assertIsNone(act_stage.detect_verb(question))

    def test_plan_ep_ve_action_khi_khong_chac(self):
        plan = plan_stage.plan("soạn tin cho 3 khách đầu", complete_fn=fake_complete({
            "shape": "find_prospects", "do_tin_cay": 0.6, "suy_luan": "tìm"}))
        self.assertEqual(plan.shape, "action")

    def test_nhan_dung_dong_tu_goi_y_san_pham(self):
        cases = ("khách bảo đang tính mua ô tô trả góp thì gợi ý sản phẩm gì",
                 "sản phẩm nào phù hợp cho khách vừa gọi",
                 "tư vấn sản phẩm gì cho nhu cầu này",
                 "nên chào gì")
        for question in cases:
            with self.subTest(question=question):
                self.assertEqual(act_stage.detect_verb(question),
                                 act_stage.VERB_SUGGEST_PRODUCT)


class SuggestProductCommandTest(SimpleTestCase):
    """Không cần danh sách khách của lượt trước — khác ba động từ kia."""

    def test_goi_y_tu_cau_mo_ta_khong_can_luot_truoc(self):
        out = act_stage.run("khách bảo đang tính mua ô tô trả góp thì gợi ý sản phẩm gì",
                            envelope=None, user=None)
        self.assertEqual(out["mode"], act_stage.VERB_SUGGEST_PRODUCT)
        self.assertIn("Vay mua xe", out["text"])
        self.assertEqual(out["people"], [])
        self.assertEqual(out["actions"], [])

    def test_khong_khop_cum_tu_nao_thi_noi_ro_khong_doan(self):
        """Model tự luận không gọi được (không cấu hình provider trong test) —
        vẫn phải nuốt lỗi và lùi về đúng câu cũ, không lộ traceback."""
        out = act_stage.run("gợi ý sản phẩm gì", envelope=None, user=None)
        self.assertEqual(out["mode"], act_stage.VERB_SUGGEST_PRODUCT)
        self.assertIn("Chưa thấy cụm từ nào", out["text"])


class SuggestProductReasoningTierTest(SimpleTestCase):
    """Tầng 2 — model tự luận gợi ý sản phẩm, CHỈ khi từ khoá tất định ra 0.

    Ghim: (a) tầng 1 khớp được thì KHÔNG gọi model; (b) model chỉ được chọn
    trong danh mục sản phẩm thật, mã lạ bị loại; (c) tin cậy luôn bị ép thấp
    hơn hẳn một tín hiệu khớp từ khoá thật; (d) câu trả lời phải nói rõ đây là
    phỏng đoán, không phải kết quả dò cụm từ.
    """

    def test_tang_1_khop_duoc_thi_khong_goi_model(self):
        with mock.patch("ai.adapter.get_adapter") as g:
            out = act_stage.run(
                "khách bảo đang tính mua ô tô trả góp thì gợi ý sản phẩm gì",
                envelope=None, user=None)
        self.assertIn("Vay mua xe", out["text"])
        g.assert_not_called()

    def test_tang_2_tu_luan_khi_tang_1_ra_0(self):
        from ai.adapter import ModelResponse

        with mock.patch("ai.adapter.get_adapter") as g:
            g.return_value.complete.return_value = ModelResponse(
                text='{"suggestions": [{"product": "insurance", '
                     '"need": "Chuẩn bị tài chính dài hạn cho con cái", '
                     '"confidence": "trung bình"}]}',
                provider="p", model="m")
            out = act_stage.run(
                "khách nói muốn chuẩn bị tài chính cho tương lai con cái, "
                "gợi ý sản phẩm gì", envelope=None, user=None)
        self.assertEqual(out["mode"], act_stage.VERB_SUGGEST_PRODUCT)
        self.assertIn("PHỎNG ĐOÁN", out["text"])
        self.assertIn("Bảo hiểm", out["text"])
        self.assertIn("40%", out["text"])  # confidence "trung bình" → 0.4, ép thấp

    def test_ma_san_pham_la_bi_loai(self):
        from ai.adapter import ModelResponse

        with mock.patch("ai.adapter.get_adapter") as g:
            g.return_value.complete.return_value = ModelResponse(
                text='{"suggestions": [{"product": "crypto_wallet", '
                     '"need": "Ví tiền số", "confidence": "trung bình"}]}',
                provider="p", model="m")
            out = act_stage.run("khách hỏi về ví tiền số thì gợi ý sản phẩm gì",
                                envelope=None, user=None)
        self.assertIn("Chưa thấy cụm từ nào", out["text"])

    def test_loi_model_khong_lam_hong_lenh(self):
        with mock.patch("ai.adapter.get_adapter") as g:
            g.return_value.complete.side_effect = RuntimeError("timeout")
            out = act_stage.run(
                "khách nói muốn để dành cho tương lai con cái, gợi ý sản phẩm gì",
                envelope=None, user=None)
        self.assertEqual(out["mode"], act_stage.VERB_SUGGEST_PRODUCT)
        self.assertIn("Chưa thấy cụm từ nào", out["text"])


class CommandNeverGuessesTargetsTest(SimpleTestCase):
    """Soạn tin cho nhầm người là lỗi không rút lại được khi RM đã bấm gửi."""

    ITEMS = [{"id": 11, "name": "Nguyễn An", "product": "mortgage", "why": ""},
             {"id": 12, "name": "Trần Bình", "product": "auto_loan", "why": ""},
             {"id": 13, "name": "Lê Chi", "product": "", "why": ""}]

    def _ids(self, question):
        rows = act_stage.resolve_targets(self.ITEMS, question)
        return None if rows is None else [r["id"] for r in rows]

    def test_theo_thu_tu_hien_thi(self):
        self.assertEqual(self._ids("soạn tin cho 2 khách đầu"), [11, 12])
        self.assertEqual(self._ids("soạn tin cho hai khách hàng đầu"), [11, 12])
        self.assertEqual(self._ids("soạn tin cho khách thứ 2"), [12])
        self.assertEqual(self._ids("soạn tin cho khách đầu tiên"), [11])
        self.assertEqual(self._ids("tạo cơ hội cho cả danh sách"), [11, 12, 13])
        self.assertEqual(self._ids("tạo cơ hội cho những khách trên"), [11, 12, 13])

    def test_theo_ten(self):
        self.assertEqual(self._ids("soạn tin cho Trần Bình"), [12])

    def test_vuot_danh_sach_tra_rong_khong_phai_nguoi_khac(self):
        self.assertEqual(self._ids("soạn tin cho khách thứ 7"), [])

    def test_khong_chi_ro_ai_thi_None_de_hoi_lai(self):
        self.assertIsNone(self._ids("soạn tin giúp tôi"))


class CommandExecutionTest(TestCase):
    def setUp(self):
        self.rm = get_user_model().objects.create_user("act-rm")
        self.an = _customer("Nguyễn An", phone="0900000101")
        self.binh = _customer("Trần Bình", phone="0900000102")
        self.items = [
            {"id": self.an.pk, "name": "Nguyễn An", "product": "mortgage",
             "why": "Tự viết cần vay mua chung cư."},
            {"id": self.binh.pk, "name": "Trần Bình", "product": "auto_loan",
             "why": "Hỏi vay mua xe."},
        ]

    def _run(self, question):
        return act_stage.run(question, envelope=_envelope(self.items), user=self.rm)

    @mock.patch("rb.outreach.complete")
    def test_soan_nhap_KHONG_luu_co_hoi_va_noi_ro_chua_gui(self, complete):
        complete.return_value = SimpleNamespace(
            text="Chào anh An, em bên MSB muốn trao đổi về khoản vay mua nhà anh quan tâm.",
            truncated=False)
        out = self._run("soạn tin cho 2 khách đầu")
        self.assertEqual(out["mode"], act_stage.VERB_MESSAGE)
        self.assertEqual(RBOpportunity.objects.count(), 0)
        self.assertIn("Chưa gửi cho ai", out["text"])
        drafted = [a for a in out["actions"] if a["status"] == "drafted"]
        self.assertEqual([a["product"] for a in drafted], ["mortgage", "auto_loan"])

    @mock.patch("rb.outreach.complete")
    def test_dnc_bi_bo_qua_KE_CA_KHI_goi_dich_danh(self, complete):
        complete.return_value = SimpleNamespace(text="x" * 60, truncated=False)
        Relationship.objects.create(person=self.an, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        out = self._run("soạn tin cho Nguyễn An")
        self.assertEqual([a["status"] for a in out["actions"]], ["do_not_contact"])
        complete.assert_not_called()

    @mock.patch("rb.outreach.complete", side_effect=RuntimeError("model bận"))
    def test_model_ban_van_tra_khung_de_viet_tiep(self, _complete):
        out = self._run("soạn tin cho khách đầu tiên")
        action = out["actions"][0]
        self.assertEqual(action["status"], "drafted")
        self.assertTrue(action["error"])
        self.assertIn("Chào anh/chị", action["draft"])

    def test_tao_co_hoi_giao_cho_rm_va_khong_tao_trung(self):
        first = self._run("tạo cơ hội cho cả danh sách")
        self.assertEqual([a["status"] for a in first["actions"]], ["created", "created"])
        row = RBOpportunity.objects.get(person=self.an)
        self.assertEqual(row.product, "mortgage")
        self.assertEqual(row.assigned_to, self.rm)
        again = self._run("tạo cơ hội cho cả danh sách")
        self.assertEqual([a["status"] for a in again["actions"]], ["exists", "exists"])
        self.assertEqual(RBOpportunity.objects.count(), 2)

    def test_khong_ro_san_pham_thi_bo_qua_khong_bia(self):
        """Mời vay người chưa từng có dấu hiệu là nhắc nhu cầu khách chưa đề cập."""
        self.items[0]["product"] = ""
        out = self._run("tạo cơ hội cho khách đầu tiên")
        self.assertEqual(out["actions"][0]["status"], "no_product")
        self.assertEqual(RBOpportunity.objects.count(), 0)

    def test_gioi_han_so_luong_moi_lan(self):
        with mock.patch.object(act_stage, "MAX_CREATE", 1):
            out = self._run("tạo cơ hội cho cả danh sách")
        self.assertEqual(len(out["actions"]), 1)
        self.assertIn("còn 1 khách chưa làm", out["text"])

    def test_dong_tu_la_thi_liet_ke_viec_lam_duoc(self):
        out = self._run("gửi email cho cả danh sách ngay")
        self.assertEqual(out["mode"], "action_unsupported")

    def test_so_thu_tu_vuot_danh_sach_thi_hoi_lai(self):
        out = self._run("tạo cơ hội cho khách thứ 5")
        self.assertEqual(out["mode"], "action_needs_target")
        self.assertEqual(RBOpportunity.objects.count(), 0)


class CommandTurnKeepsListTest(TestCase):
    """Hai câu lệnh liên tiếp phải cùng trỏ về một danh sách."""

    def test_luot_cau_lenh_khong_ghi_de_danh_sach(self):
        from ai import conversation_state
        from ai.models import AssistantThread
        from .answer_views import _persist
        rm = get_user_model().objects.create_user("keep-rm")
        found = engine.AnswerResult(text="tìm thấy", people=[
            {"person_id": 1, "name": "A", "product": "fx", "why": ""},
            {"person_id": 2, "name": "B", "product": "fx", "why": ""}], trace={})
        _persist(rm, "keep-thread", "t1", "", "khách cần đổi ngoại tệ", found)
        command = engine.AnswerResult(text="đã soạn", people=[
            {"person_id": 2, "name": "B", "product": "fx", "why": ""}],
            trace={"keeps_last_result": True})
        _persist(rm, "keep-thread", "t2", "", "soạn tin cho khách thứ 2", command)
        thread = AssistantThread.objects.get(
            user=rm, thread_id=conversation_state.normalize_thread_id("keep-thread"))
        items = thread.state["last_result_ref"]["items"]
        self.assertEqual([i["id"] for i in items], [1, 2])
        self.assertEqual(items[0]["product"], "fx")



class CustomerPopulationTest(TestCase):
    """`Person` dùng chung với Talent: ứng viên tuyển dụng KHÔNG phải khách hàng."""

    def test_ung_vien_khong_chiem_cho_cua_khach_trong_tran(self):
        """Hậu quả thật của tập cũ: ứng viên ăn hết trần, khách thật bị cắt."""
        from .answer.population import customers
        khach = _customer("Khách Thật")
        _post(khach, "em cần vay mua nhà")
        for i in range(3):                       # ứng viên MỚI hơn, đứng đầu theo -updated_at
            Person.objects.create(display_name=f"Ứng Viên {i}")
        self.assertEqual(set(customers().values_list("pk", flat=True)), {khach.pk})
        with mock.patch.object(retrieve_stage, "MAX_ELIGIBLE", 2):
            got = [c.person_id for c in retrieve_stage.retrieve(
                ProspectPlan(search_queries=["vay mua nhà"]))]
        self.assertIn(khach.pk, got)

    def test_nguoi_chi_co_bai_dang_hoac_tin_hieu_van_la_khach(self):
        from .answer.population import customers
        chi_bai = Person.objects.create(display_name="Chỉ Có Bài")
        _post(chi_bai, "hỏi vay")
        chi_tin_hieu = Person.objects.create(display_name="Chỉ Có Tín Hiệu")
        Signal.objects.create(person=chi_tin_hieu, domain=Signal.DOMAIN_RB,
                              signal_type="loan", observed_at=timezone.now())
        ids = set(customers().values_list("pk", flat=True))
        self.assertTrue({chi_bai.pk, chi_tin_hieu.pk} <= ids)


class BusinessProspectingReasoningTest(TestCase):
    """Kiểm tra trí tuệ phán đoán và suy luận kinh doanh từ dữ liệu CV cho RB."""

    def test_cv_profile_evidence_passages(self):
        """Bằng chứng trích xuất từ CV/TalentProfile cung cấp đủ bối cảnh cho AI suy luận."""
        from talent.models import TalentProfile
        from .answer import evidence as evidence_stage

        person = _customer("Trần Văn Quản Lý", location="Hà Nội")
        TalentProfile.objects.create(
            person=person,
            current_title="Trưởng phòng Kỹ thuật",
            current_company="Tập đoàn FPT",
            years_experience=7.5,
            seniority="manager",
            education="Đại học Bách Khoa",
            marital_status="Đã kết hôn",
            current_salary="40 triệu",
        )
        passages = evidence_stage._cv_profile_passages([person.pk], timezone.now())
        self.assertEqual(len(passages), 1)
        text = passages[0].text
        self.assertIn("Trưởng phòng Kỹ thuật", text)
        self.assertIn("Tập đoàn FPT", text)
        self.assertIn("7.5", text)
        self.assertIn("manager", text)
        self.assertIn("Đã kết hôn", text)

    def test_score_fit_fallback_to_talent_profile(self):
        """score_fit đọc được chức danh và thâm niên từ TalentProfile khi RBProfile trống."""
        from talent.models import TalentProfile
        from . import scoring

        person = Person.objects.create(display_name="Lê Giám Đốc", is_applicant=False)
        TalentProfile.objects.create(
            person=person,
            current_title="Giám đốc Kinh doanh",
            current_company="VinCommerce",
            years_experience=10,
            seniority="executive",
        )
        score, reasons = scoring.score_fit(person, scoring.PRODUCT_MORTGAGE)
        # 50 base + 25 senior + 10 yoe >= 5 + 5 employer = 90
        self.assertGreaterEqual(score, 75.0)
        reasons_text = " ".join(reasons)
        self.assertIn("Giám đốc Kinh doanh", reasons_text)
        self.assertIn("Thâm niên 10", reasons_text)

    def test_score_need_with_judgement_confidence(self):
        """score_need lượng hoá điểm cho cơ hội suy luận có căn cứ từ AI thay vì trả 0."""
        from . import scoring

        # Không có interest, không có signal nhưng AI suy luận confidence=0.65
        score, reasons = scoring.score_need(judgement_confidence=0.65)
        self.assertEqual(score, 65.0)
        self.assertIn("AI suy luận cơ hội", reasons[0])

    def test_retrieve_profile_ids_matches_cv_title(self):
        """_profile_ids tìm ra người khớp chức danh trong TalentProfile."""
        from talent.models import TalentProfile
        from .answer import retrieve as retrieve_stage

        person = _customer("Nguyễn Trưởng Phòng")
        TalentProfile.objects.create(
            person=person,
            current_title="Trưởng phòng Tài chính",
            current_company="Masan Group",
        )
        found = retrieve_stage._profile_ids([person.pk], ["tài", "chính", "trưởng", "phòng"], limit=10)
        self.assertIn(person.pk, found)

