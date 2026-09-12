# -*- coding: utf-8 -*-
"""Social Radar — Phase 10 và phần Talent của Phase 11.

Chỗ nguy hiểm nhất của module này không phải kỹ thuật mà là **chấm nhầm phía**:
một bài đăng tuyển dụng bị chấm là "người tìm việc" sẽ nhét nhà tuyển dụng vào
kho ứng viên, và một bài môi giới vay vốn bị chấm là "khách có nhu cầu" sẽ nhét
người bán vào danh sách khách hàng. Cả hai đều âm thầm và cả hai đều khó gỡ.
"""
import json
from unittest import mock

from accounts import roles
from ai.providers import Completion
from core.models import Edge, SourceRecord
from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from people import ingest
from people.models import Person, Signal

from . import intent as intent_module
from . import pipeline
from .models import Community, SocialPost

TIM_VIEC = ("Em đang tìm việc Data Analyst tại Hà Nội, 4 năm kinh nghiệm SQL và "
            "Python. Anh chị nào có cơ hội cho em xin với ạ. LH 0901234567")
DANG_TUYEN = ("CÔNG TY ABC TUYỂN GẤP 5 Data Analyst tại Hà Nội. Mô tả công việc: "
              "xây dựng báo cáo. Ứng viên gửi CV qua hr@abc.vn")
VAY_VON = ("Nhà em đang cần vay 500 triệu mua nhà, lãi suất ngân hàng nào đang "
           "tốt ạ? Em ở Hà Nội.")
MOI_GIOI = ("Bên em hỗ trợ vay tín chấp lãi suất thấp, duyệt nhanh trong ngày. "
            "Liên hệ em để vay, hoa hồng cho cộng tác viên.")
LINH_TINH = "Hôm nay trời đẹp quá mọi người ơi, ai đi cà phê không?"


def llm(payload):
    """LLM giả trả JSON. Dùng `Completion` thật chứ không `Mock`."""
    def fake(messages, **kwargs):
        return Completion(text=json.dumps(payload, ensure_ascii=False),
                          provider="fake", model="fake-1")
    return fake


def make_user(username, *role_names):
    roles.ensure_groups()
    user = User.objects.create_user(username, password="mat-khau-dai-1")
    for name in role_names:
        user.groups.add(Group.objects.get(name=name))
    return user


class IntentValidationTest(TestCase):
    def _detect(self, payload, content=TIM_VIEC):
        with mock.patch("social.intent.complete", side_effect=llm(payload)):
            return intent_module.detect(content)

    def test_diem_da_nhan_khong_can_cong_bang_1(self):
        """Một bài có thể vừa tìm việc vừa hỏi vay — ép về một nhãn là bịa."""
        result = self._detect({"talent": 0.72, "rb": 0.65})
        self.assertEqual(result.score("talent"), 0.72)
        self.assertEqual(result.score("rb"), 0.65)

    def test_nhan_diem_thang_100_va_doi_ve_0_1(self):
        """Mô hình thỉnh thoảng trả 91 thay vì 0.91."""
        result = self._detect({"talent": 91, "rb": 7})
        self.assertEqual(result.score("talent"), 0.91)

    def test_diem_vo_ly_bi_cat(self):
        result = self._detect({"talent": 999, "rb": -5})
        self.assertEqual(result.score("talent"), 1.0)
        self.assertEqual(result.score("rb"), 0.0)

    def test_diem_khong_phai_so_thi_ve_0(self):
        result = self._detect({"talent": "cao", "rb": None})
        self.assertEqual(result.scores, {"talent": 0.0, "rb": 0.0})

    def test_bo_lien_he_KHONG_co_trong_bai(self):
        """Mô hình đôi khi "hoàn thiện" số điện thoại thiếu chữ số. Một tin nhắn
        gửi nhầm tới người vô can là chuyện không sửa lại được."""
        result = self._detect({"talent": 0.9,
                               "contacts": {"phone": "0999888777"}})
        self.assertEqual(result.contacts, {})

    def test_giu_lien_he_CO_trong_bai(self):
        result = self._detect({"talent": 0.9,
                               "contacts": {"phone": "0901234567"}})
        self.assertEqual(result.contacts["phone"], "0901234567")

    def test_giu_lien_he_du_bai_viet_cach_kieu_khac(self):
        result = self._detect({"talent": 0.9, "contacts": {"phone": "0901234567"}},
                              content="LH: 090.123.4567 nhé")
        self.assertEqual(result.contacts["phone"], "0901234567")

    def test_bai_trong_thi_khong_goi_LLM(self):
        with mock.patch("social.intent.complete") as goi:
            intent_module.detect("   ")
        goi.assert_not_called()

    def test_boi_canh_nhom_duoc_dua_vao_prompt(self):
        """Cùng câu "em cần tư vấn" trong nhóm tuyển dụng và nhóm vay vốn là hai
        ý định khác hẳn (Master Plan mục 30)."""
        nhom = Community.objects.create(external_id="g1", name="Việc làm IT Hà Nội",
                                        topic="tuyển dụng công nghệ")
        seen = {}

        def fake(messages, **kwargs):
            seen["prompt"] = messages[-1]["content"]
            return Completion(text='{"talent": 0.8}', provider="f", model="f")

        with mock.patch("social.intent.complete", side_effect=fake):
            intent_module.detect("Em cần tư vấn ạ", community=nhom)
        self.assertIn("Việc làm IT Hà Nội", seen["prompt"])
        self.assertIn("tuyển dụng công nghệ", seen["prompt"])


class IntentFallbackTest(TestCase):
    """Khoá LLM bận là chuyện thường ngày — nhánh này sẽ chạy thật."""

    def _detect(self, content):
        with mock.patch("social.intent.complete",
                        side_effect=RuntimeError("bị giới hạn tốc độ")):
            return intent_module.detect(content)

    def test_nhan_ra_nguoi_tim_viec(self):
        result = self._detect(TIM_VIEC)
        self.assertTrue(result.fallback)
        self.assertGreaterEqual(result.score("talent"), 0.5)

    def test_KHONG_cham_nguoi_dang_tuyen_la_ung_vien(self):
        """Chấm nhầm chỗ này sẽ làm kho ứng viên đầy nhà tuyển dụng."""
        result = self._detect(DANG_TUYEN)
        self.assertLess(result.score("talent"), 0.5)

    def test_nhan_ra_nhu_cau_tai_chinh(self):
        result = self._detect(VAY_VON)
        self.assertGreaterEqual(result.score("rb"), 0.5)

    def test_cum_tu_khoa_chiu_duoc_cau_chu_doi_thuong(self):
        """"vay mua nhà" không khớp "vay 500 triệu mua nhà" — mà đó mới là cách
        người ta viết thật. Bắt được lỗi này khi chạy thử màn hình, không phải
        khi viết test."""
        result = self._detect("Nhà em đang cần vay 500 triệu mua nhà, "
                              "ngân hàng nào lãi suất tốt ạ?")
        # Đủ ba dấu hiệu: "cần vay", "mua nhà", "lãi suất" — phải vượt cả
        # ngưỡng cao của nghiệp vụ bán lẻ.
        self.assertGreaterEqual(result.score("rb"), 0.7)

    def test_KHONG_cham_moi_gioi_la_khach_hang(self):
        result = self._detect(MOI_GIOI)
        self.assertLess(result.score("rb"), 0.5)

    def test_bai_linh_tinh_thi_diem_thap_ca_hai(self):
        result = self._detect(LINH_TINH)
        self.assertFalse(result.is_relevant)

    def test_van_rut_duoc_so_dien_thoai(self):
        result = self._detect(TIM_VIEC)
        self.assertEqual(result.contacts["phone"], "0901234567")

    def test_noi_ro_la_do_tu_khoa(self):
        """Im lặng ở đây là để người dùng tin nhầm vào một điểm số thô."""
        result = self._detect(TIM_VIEC)
        self.assertIn("dò từ khoá", result.reason)


class PipelineTest(TestCase):
    """Bước khớp người — chỗ Social Radar có giá trị hoặc không có gì."""

    def setUp(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1",
            payload={"source": "topcv", "account": "a", "cv_id": "1",
                     "fullname": "Nguyễn Văn An", "email": "an@x.vn",
                     "phone": "0901234567", "current_title": "Data Analyst",
                     "skills": "SQL, Python", "city": "Hà Nội",
                     "years_experience": "4 năm",
                     "applied_ts": "2025-11-10 09:00:00"})
        ingest.resolve_pending()
        self.an = Person.objects.get(display_name="Nguyễn Văn An")

    def _post(self, content=TIM_VIEC, **kwargs):
        kwargs.setdefault("external_id", "p1")
        kwargs.setdefault("author_name", "Nguyen Van An")
        return SocialPost.objects.create(content=content, **kwargs)

    def _process(self, post, payload):
        with mock.patch("social.intent.complete", side_effect=llm(payload)):
            return pipeline.process(post)

    def test_khop_nguoi_da_co_qua_so_dien_thoai(self):
        """Câu đáng giá nhất của Social Radar nằm ở đây."""
        result = self._process(self._post(), {
            "talent": 0.91, "rb": 0.05,
            "contacts": {"phone": "0901234567"}})
        self.assertTrue(result.matched)
        self.assertEqual(result.post.person, self.an)
        self.assertEqual(result.post.status, SocialPost.STATUS_LINKED)

    def test_sinh_tin_hieu_gan_vao_ho_so_nguoi(self):
        self._process(self._post(), {"talent": 0.91,
                                     "contacts": {"phone": "0901234567"}})
        signal = Signal.objects.get(person=self.an, signal_type="job_seeking")
        self.assertEqual(signal.domain, "talent")
        self.assertEqual(signal.confidence, 0.91)

    def test_tin_hieu_LUON_co_bang_chung(self):
        """Nguyên tắc 4: không có bằng chứng thì không giải thích được."""
        self._process(self._post(), {
            "talent": 0.91, "reason": "Bài viết ghi rõ “đang tìm việc Data Analyst”",
            "contacts": {"phone": "0901234567"}})
        signal = Signal.objects.get(person=self.an)
        self.assertIn("đang tìm việc", signal.evidence["excerpt"])
        self.assertIn("Data Analyst", signal.evidence["reason"])
        self.assertEqual(signal.evidence["scored_by"], "llm")

    def test_duoi_nguong_thi_KHONG_sinh_tin_hieu(self):
        self._process(self._post(), {"talent": 0.3,
                                     "contacts": {"phone": "0901234567"}})
        self.assertFalse(Signal.objects.filter(person=self.an).exists())

    def test_nguong_cua_RB_cao_hon_talent(self):
        """Tuyển dụng nghe rộng được; bán lẻ phải chắc mới động vào."""
        # Số điện thoại phải nằm TRONG bài, nếu không nó bị loại ở khâu kiểm
        # liên hệ và cả bước khớp người sẽ không chạy.
        bai = VAY_VON + " LH 0901234567"
        self._process(self._post(content=bai), {
            "talent": 0.0, "rb": 0.6, "contacts": {"phone": "0901234567"}})
        self.assertFalse(Signal.objects.filter(domain="rb").exists())

        post2 = self._post(content=bai, external_id="p2")
        self._process(post2, {"talent": 0.0, "rb": 0.85,
                              "contacts": {"phone": "0901234567"}})
        self.assertTrue(Signal.objects.filter(domain="rb").exists())

    def test_KHONG_tu_tao_Person_moi_tu_bai_dang(self):
        """Bài viết cho ta cùng lắm một cái tên hiển thị. Tạo Person từ đó sẽ đổ
        vào People Database những hồ sơ rỗng không nghiệp vụ nào dùng được."""
        truoc = Person.objects.count()
        result = self._process(
            self._post(content="Em đang tìm việc ạ", author_name="Người Lạ"),
            {"talent": 0.9})
        self.assertEqual(Person.objects.count(), truoc)
        self.assertFalse(result.matched)
        self.assertIsNone(result.post.person_id)

    def test_khop_nhieu_nguoi_thi_KHONG_gan_bua(self):
        """Gộp nhầm hai con người tệ hơn nhiều so với bỏ lỡ một tín hiệu."""
        # Hai người, mỗi người giữ một định danh xuất hiện trong bài: An giữ
        # email, người kia giữ số điện thoại.
        khac = Person.objects.create(display_name="Người khác")
        khac.identities.create(kind="phone", value="+84987654321")
        result = self._process(
            self._post(content="Em tìm việc, LH 0987654321 hoặc an@x.vn"),
            {"talent": 0.9, "contacts": {"phone": "0987654321",
                                         "email": "an@x.vn"}})
        self.assertFalse(result.matched)
        self.assertIsNone(result.post.person_id)

    def test_bai_khong_lien_quan_bi_danh_dau_bo_qua(self):
        result = self._process(self._post(content=LINH_TINH),
                               {"talent": 0.02, "rb": 0.01})
        self.assertEqual(result.post.status, SocialPost.STATUS_IGNORED)

    def test_cham_lai_khong_nhan_doi_tin_hieu(self):
        post = self._post()
        payload = {"talent": 0.91, "contacts": {"phone": "0901234567"}}
        self._process(post, payload)
        self._process(post, payload)
        self.assertEqual(Signal.objects.filter(person=self.an).count(), 1)

    def test_diem_cao_hon_thi_cap_nhat_tin_hieu(self):
        post = self._post()
        self._process(post, {"talent": 0.6, "contacts": {"phone": "0901234567"}})
        self._process(post, {"talent": 0.95, "contacts": {"phone": "0901234567"}})
        self.assertEqual(Signal.objects.get(person=self.an).confidence, 0.95)


class RoutingToRbTest(TestCase):
    """Bài đăng tài chính phải đi tới được hộp thư của RM.

    Trước khi có RB Radar, tín hiệu `rb` sinh ra rồi nằm im — không nghiệp vụ
    nào nhận. Đó là kiểu "đã làm xong" mà thực ra chưa dùng được.
    """

    def setUp(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1",
            payload={"source": "topcv", "fullname": "Nguyễn Văn An",
                     "email": "an@x.vn", "phone": "0901234567",
                     "applied_ts": "2025-11-10 09:00:00"})
        ingest.resolve_pending()
        self.an = Person.objects.get(display_name="Nguyễn Văn An")

    def test_bai_vay_mua_nha_thanh_de_xuat_co_hoi_ban_le(self):
        """Bài đăng → **đề xuất**, chưa phải cơ hội (Master Plan mục 33).

        Trước Phase 12 bài này kiểm `RBOpportunity`. Đổi sang
        `OpportunitySuggestion` vì luồng đã thêm một trạm dừng: RM phải bấm nhận
        thì mới thành việc trong hộp thư. Ý nghĩa bài kiểm không đổi — Social
        Radar vẫn phải nhận ra nhu cầu tài chính và đẩy sang RB Radar.
        """
        from rb.models import OpportunitySuggestion, RBOpportunity

        post = SocialPost.objects.create(
            external_id="p1", author_name="Nguyen Van An",
            content="Em cần vay 500 triệu mua nhà, LH 0901234567")
        with mock.patch("social.intent.complete", side_effect=llm(
                {"talent": 0.0, "rb": 0.9,
                 "contacts": {"phone": "0901234567"}})):
            pipeline.process(post)

        suggestion = OpportunitySuggestion.objects.get(person=self.an)
        self.assertEqual(suggestion.product, "mortgage")
        self.assertIn("mua nhà", " ".join(suggestion.evidence["why"]).lower())
        # Chưa ai nhận thì hộp thư cơ hội của RM phải còn trống.
        self.assertEqual(RBOpportunity.objects.count(), 0)

    def test_bai_tim_viec_KHONG_tao_de_xuat_ban_le(self):
        from rb.models import OpportunitySuggestion, RBOpportunity

        post = SocialPost.objects.create(
            external_id="p2", content=TIM_VIEC, author_name="Nguyen Van An")
        with mock.patch("social.intent.complete", side_effect=llm(
                {"talent": 0.9, "rb": 0.0, "contacts": {"phone": "0901234567"}})):
            pipeline.process(post)
        self.assertEqual(OpportunitySuggestion.objects.count(), 0)
        self.assertEqual(RBOpportunity.objects.count(), 0)


class HistoryNoteTest(TestCase):
    """Câu chốt: "từng ứng tuyển 9 tháng trước, và vừa có tín hiệu tìm việc"."""

    def setUp(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1",
            payload={"source": "topcv", "account": "a", "cv_id": "1",
                     "fullname": "Nguyễn Văn An", "email": "an@x.vn",
                     "applied_ts": "2025-11-10 09:00:00"})
        ingest.resolve_pending()
        self.an = Person.objects.get(display_name="Nguyễn Văn An")

    def test_noi_ro_bao_lau_va_qua_nguon_nao(self):
        note = pipeline.history_note(self.an)
        self.assertIn("tháng trước", note)
        self.assertIn("topcv", note)

    def test_khong_co_nguoi_thi_KHONG_bia_cau_chung_chung(self):
        self.assertEqual(pipeline.history_note(None), "")

    def test_qua_hai_nam_thi_doi_sang_nam(self):
        """"41 tháng trước" là cách máy nói; câu này hiện thẳng ra màn hình."""
        self.assertEqual(pipeline._how_long_ago(0), "gần đây")
        self.assertEqual(pipeline._how_long_ago(9), "9 tháng trước")
        self.assertEqual(pipeline._how_long_ago(23), "23 tháng trước")
        self.assertEqual(pipeline._how_long_ago(41), "hơn 3 năm trước")


class SocialApiTest(TestCase):
    def setUp(self):
        self.user = make_user("tuyendung", roles.RECRUITER)
        self.client.force_login(self.user)

    def _post(self, name, body=None, args=None):
        return self.client.post(reverse(name, args=args or []),
                                data=json.dumps(body or {}),
                                content_type="application/json")

    def test_dan_bai_vao_xem_thu_KHONG_luu_gi(self):
        """Nút "xem thử" mà âm thầm ghi dữ liệu cá nhân vào CSDL là thứ không
        nên tồn tại trong hệ thống ngân hàng."""
        with mock.patch("social.intent.complete",
                        side_effect=llm({"talent": 0.9})):
            response = self._post("social-analyze", {"content": TIM_VIEC})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["saved"])
        self.assertEqual(SocialPost.objects.count(), 0)

    def test_xem_thu_van_tra_loi_TA_DA_BIET_nguoi_nay_chua(self):
        edge = Edge.objects.create(label="Máy TA", edge_id="e1")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="topcv|a|1",
            content_hash="h1",
            payload={"source": "topcv", "fullname": "Nguyễn Văn An",
                     "phone": "0901234567", "applied_ts": "2025-11-10 09:00:00"})
        ingest.resolve_pending()

        with mock.patch("social.intent.complete", side_effect=llm(
                {"talent": 0.9, "contacts": {"phone": "0901234567"}})):
            body = self._post("social-analyze", {"content": TIM_VIEC}).json()

        self.assertEqual(body["matched_person_name"], "Nguyễn Văn An")
        self.assertIn("tháng trước", body["history_note"])

    def test_luu_khi_duoc_yeu_cau_ro(self):
        with mock.patch("social.intent.complete", side_effect=llm({"talent": 0.9})):
            response = self._post("social-analyze",
                                  {"content": TIM_VIEC, "save": True})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SocialPost.objects.count(), 1)

    def test_bai_trong_thi_400(self):
        self.assertEqual(self._post("social-analyze", {"content": " "}).status_code, 400)

    def test_ingest_lo_bai_tu_edge(self):
        rows = [{"external_id": f"p{i}", "content": TIM_VIEC,
                 "author_name": f"Người {i}"} for i in range(3)]
        with mock.patch("social.intent.complete", side_effect=llm({"talent": 0.8})):
            body = self._post("social-ingest", {"posts": rows}).json()
        self.assertEqual(body["processed"], 3)
        self.assertEqual(SocialPost.objects.count(), 3)

    def test_ingest_lai_cung_bai_thi_KHONG_cham_lai(self):
        """Chấm lại cả lô mỗi lần Edge gửi sẽ đốt hạn mức LLM vào bài đã xong."""
        rows = [{"external_id": "p1", "content": TIM_VIEC}]
        with mock.patch("social.intent.complete", side_effect=llm({"talent": 0.8})) as goi:
            self._post("social-ingest", {"posts": rows})
            self._post("social-ingest", {"posts": rows})
        self.assertEqual(goi.call_count, 1)
        self.assertEqual(SocialPost.objects.count(), 1)

    def test_ingest_tao_nhom_neu_chua_co(self):
        rows = [{"external_id": "p1", "content": TIM_VIEC,
                 "community_external_id": "g1", "community_name": "Việc làm IT"}]
        with mock.patch("social.intent.complete", side_effect=llm({"talent": 0.8})):
            self._post("social-ingest", {"posts": rows})
        self.assertEqual(Community.objects.get().name, "Việc làm IT")

    def test_ingest_thieu_du_lieu_thi_bo_qua_chu_khong_do_ca_lo(self):
        rows = [{"external_id": "p1", "content": TIM_VIEC},
                {"external_id": "", "content": TIM_VIEC},
                {"external_id": "p3", "content": ""}]
        with mock.patch("social.intent.complete", side_effect=llm({"talent": 0.8})):
            body = self._post("social-ingest", {"posts": rows}).json()
        self.assertEqual(body["processed"], 1)
        self.assertEqual(body["skipped"], 2)

    def test_lo_qua_lon_thi_400(self):
        rows = [{"external_id": f"p{i}", "content": "x"} for i in range(200)]
        self.assertEqual(self._post("social-ingest", {"posts": rows}).status_code, 400)

    def test_danh_sach_bai_bo_bai_khong_lien_quan(self):
        SocialPost.objects.create(external_id="p1", content=LINH_TINH,
                                  status=SocialPost.STATUS_IGNORED)
        SocialPost.objects.create(external_id="p2", content=TIM_VIEC,
                                  status=SocialPost.STATUS_SCORED)
        body = self.client.get(reverse("social-posts")).json()
        self.assertEqual(body["count"], 1)

    def test_tao_nhom_theo_doi(self):
        response = self._post("social-communities",
                              {"name": "Việc làm Hà Nội", "external_id": "g9",
                               "topic": "tuyển dụng"})
        self.assertEqual(response.status_code, 201)

    def test_tao_nhom_thieu_ma_thi_400(self):
        self.assertEqual(
            self._post("social-communities", {"name": "X"}).status_code, 400)


class PermissionTest(TestCase):
    def test_hiring_manager_khong_vao_duoc_social(self):
        """Ma trận vai trò: HM chỉ có module talent."""
        self.client.force_login(make_user("hm", roles.HIRING_MANAGER))
        self.assertEqual(self.client.get(reverse("social-posts")).status_code, 403)

    def test_recruiter_vao_duoc(self):
        self.client.force_login(make_user("tuyendung", roles.RECRUITER))
        self.assertEqual(self.client.get(reverse("social-posts")).status_code, 200)

    def test_rb_sales_vao_duoc(self):
        """Social Radar dùng chung cho cả hai nghiệp vụ (mục 26)."""
        self.client.force_login(make_user("sales", roles.RB_SALES))
        self.assertEqual(self.client.get(reverse("social-posts")).status_code, 200)

    def test_chua_dang_nhap_bi_chan(self):
        self.assertIn(self.client.get(reverse("social-posts")).status_code, (401, 403))
