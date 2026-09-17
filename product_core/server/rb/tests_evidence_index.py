# -*- coding: utf-8 -*-
"""Chỉ mục bằng chứng khách hàng + nhánh tìm theo nghĩa của Growth."""
from io import StringIO
from unittest import mock

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from people.models import Person, Relationship, Signal

from . import evidence_index
from .answer import retrieve as retrieve_stage
from .answer.plan import ProspectPlan
from .models import ProductInterest, ProspectEvidenceChunk, RBProfile


def _days_ago(days):
    return timezone.now() - timezone.timedelta(days=days)


def _customer(name, **kwargs):
    person = Person.objects.create(display_name=name, is_applicant=False, **kwargs)
    RBProfile.objects.create(person=person)
    return person


def _post(person, content, days=1):
    from social.models import SocialPost
    return SocialPost.objects.create(person=person, content=content,
                                     posted_at=_days_ago(days),
                                     external_id=f"p-{person.pk}-{SocialPost.objects.count()}")


class IndexPersonTest(TestCase):
    def setUp(self):
        cache.delete(evidence_index.BACKFILL_MARKER)

    def test_moi_nguon_mot_dong_da_che_lien_he_va_bo_dau(self):
        person = _customer("Nguyễn Chỉ Mục")
        _post(person, "Em cần vay mua căn hộ, liên hệ 0901234567")
        ProductInterest.objects.create(profile=person.rb_profile, product="mortgage",
                                       confidence=0.8, observed_at=_days_ago(2))
        evidence_index.index_person(person.pk)
        rows = {r.source: r for r in ProspectEvidenceChunk.objects.filter(person=person)}
        self.assertIn("social", rows)
        self.assertIn("interest", rows)
        self.assertNotIn("0901234567", rows["social"].text)
        self.assertIn("mua can ho", rows["social"].text_norm)

    def test_noi_dung_khong_doi_thi_giu_nguyen_vector(self):
        """Ghi đè mù mỗi lần sửa hồ sơ là huỷ sạch tiền embedding đã trả."""
        person = _customer("Giữ Vector")
        _post(person, "Cần tư vấn thẻ tín dụng hoàn tiền")
        evidence_index.index_person(person.pk)
        row = ProspectEvidenceChunk.objects.get(person=person, source="social")
        ProspectEvidenceChunk.objects.filter(pk=row.pk).update(
            embedding_model="m", embedding_fingerprint=row.fingerprint)
        evidence_index.index_person(person.pk)
        row.refresh_from_db()
        self.assertEqual(row.embedding_fingerprint, row.fingerprint)
        self.assertNotIn(row, list(evidence_index.stale_chunks()))

    def test_bai_da_xoa_roi_khoi_chi_muc(self):
        person = _customer("Bài Bị Xoá")
        post = _post(person, "Đang tìm hiểu bảo hiểm sức khoẻ cho gia đình")
        evidence_index.index_person(person.pk)
        post.delete()
        evidence_index.index_person(person.pk)
        self.assertFalse(ProspectEvidenceChunk.objects.filter(
            person=person, source="social").exists())

    def test_nguoi_bi_gop_roi_khoi_chi_muc(self):
        person = _customer("Bị Gộp")
        _post(person, "Hỏi về vay mua ô tô trả góp")
        evidence_index.index_person(person.pk)
        primary = Person.objects.create(display_name="Bị Gộp (gốc)")
        Person.objects.filter(pk=person.pk).update(merged_into=primary)
        evidence_index.index_person(person.pk)
        self.assertFalse(ProspectEvidenceChunk.objects.filter(person=person).exists())

    def test_luu_bai_dang_tu_lap_chi_muc_sau_commit(self):
        person = _customer("Tự Lập Chỉ Mục")
        with self.captureOnCommitCallbacks(execute=True):
            _post(person, "Cần mở tài khoản tiết kiệm online")
        self.assertTrue(ProspectEvidenceChunk.objects.filter(
            person=person, source="social").exists())


class BackfillGateTest(TestCase):
    """Chỉ mục một phần KHÔNG được thay đường khớp chữ cũ.

    Sau deploy bảng rỗng; lần lưu đầu lập chỉ mục cho MỘT khách. Nếu cổng là
    `exists()`, từ lúc đó nhánh social/signal chỉ còn thấy đúng người ấy.
    """

    def setUp(self):
        cache.delete(evidence_index.BACKFILL_MARKER)
        self.da_index = _customer("Đã Lập Chỉ Mục")
        self.chua_index = _customer("Chưa Lập Chỉ Mục")
        _post(self.da_index, "Cần vay mua nhà gấp")
        _post(self.chua_index, "Cần vay mua nhà gấp")
        evidence_index.index_person(self.da_index.pk)
        ProspectEvidenceChunk.objects.filter(person=self.chua_index).delete()

    def _ids(self):
        return {c.person_id for c in retrieve_stage.retrieve(
            ProspectPlan(search_queries=["vay mua nhà"]))}

    def test_chi_muc_mot_phan_van_dung_duong_cu(self):
        self.assertTrue(ProspectEvidenceChunk.objects.exists())
        self.assertIn(self.chua_index.pk, self._ids())

    def test_rebuild_day_du_moi_bat_co(self):
        call_command("rebuild_prospect_evidence_index", "--limit", "1", stdout=StringIO())
        self.assertFalse(evidence_index.populated())
        call_command("rebuild_prospect_evidence_index", stdout=StringIO())
        self.assertTrue(evidence_index.populated())
        # Sau backfill đủ, người trước đây chưa có chỉ mục vẫn tìm thấy.
        self.assertIn(self.chua_index.pk, self._ids())

    def test_sau_backfill_nhanh_social_dung_full_text_co_chi_muc(self):
        call_command("rebuild_prospect_evidence_index", stdout=StringIO())
        with mock.patch.object(retrieve_stage, "_social_ids") as old_path:
            self.assertIn(self.da_index.pk, self._ids())
        old_path.assert_not_called()


class FtsTest(TestCase):
    def test_khop_khong_dau_va_loc_theo_nguon(self):
        person = _customer("Không Dấu")
        _post(person, "Nhà em muốn mua căn hộ chung cư")
        evidence_index.index_person(person.pk)
        self.assertEqual(evidence_index.fts_person_ids("mua can ho", [person.pk]), [person.pk])
        self.assertEqual(evidence_index.fts_person_ids(
            "mua can ho", [person.pk], sources=("signal",)), [])


class SemanticBranchTest(TestCase):
    """Nhánh vector: đúng thứ khớp chữ không làm được, và không được phá cổng."""

    def setUp(self):
        cache.delete(evidence_index.BACKFILL_MARKER)

    def test_khach_khop_nghia_ma_khong_khop_chu_van_duoc_tim_thay(self):
        can_ho = _customer("Nói Căn Hộ")
        _post(can_ho, "Nhà em đang tính mua một căn hộ nhỏ")
        # Một khách khớp CHỮ, để có ít nhất một nhánh ra kết quả. Không có thì
        # `retrieve` cố ý trả mọi người qua cổng (để ③ nói thật "không có bằng
        # chứng"), và test không phân biệt được có nhánh vector hay không.
        khop_chu = _customer("Khớp Chữ")
        _post(khop_chu, "apartment financing options")
        # Truy vấn KHÔNG trùng chữ nào với bài của `can_ho` — chỉ nhánh vector tìm ra.
        plan = ProspectPlan(search_queries=["apartment financing"])
        with mock.patch.object(evidence_index, "dense_person_ids", return_value=[]):
            self.assertNotIn(can_ho.pk, [c.person_id for c in retrieve_stage.retrieve(plan)])
        with mock.patch.object(evidence_index, "dense_person_ids",
                               return_value=[can_ho.pk]):
            ids = [c.person_id for c in retrieve_stage.retrieve(plan)]
        self.assertIn(can_ho.pk, ids)

    def test_nhanh_vector_tra_nguoi_DNC_van_bi_chan(self):
        """Cổng tuân thủ không được phụ thuộc vào việc nhánh mới nhớ tôn trọng nó."""
        cam = _customer("Không Liên Hệ")
        Relationship.objects.create(person=cam, domain=Signal.DOMAIN_RB,
                                    state="cold", do_not_contact=True)
        _post(cam, "Muốn mua căn hộ")
        # Phải có ít nhất một khách HỢP LỆ: không có thì tập cho phép rỗng, `retrieve`
        # thoát trước khi chạy nhánh nào, và test xanh mà không đi qua lưới cần kiểm.
        hop_le = _customer("Khách Hợp Lệ")
        _post(hop_le, "Muốn mua căn hộ")
        with mock.patch.object(evidence_index, "dense_person_ids",
                               return_value=[cam.pk, hop_le.pk]):
            ids = [c.person_id for c in retrieve_stage.retrieve(
                ProspectPlan(search_queries=["zzz khong khop chu nao"]))]
        self.assertIn(hop_le.pk, ids)
        self.assertNotIn(cam.pk, ids)

    def test_loi_embedding_tat_nhanh_cho_ca_luot(self):
        """Provider chết mà thử đủ mọi truy vấn thì timeout ăn hết ngân sách lượt."""
        person = _customer("Provider Chết")
        _post(person, "Cần vay tiêu dùng")
        with mock.patch.object(evidence_index, "dense_person_ids",
                               side_effect=RuntimeError("timeout")) as dense:
            ids = [c.person_id for c in retrieve_stage.retrieve(
                ProspectPlan(search_queries=["vay tiêu dùng", "cần tiền", "xoay vốn"]))]
        self.assertEqual(dense.call_count, 1)
        self.assertIn(person.pk, ids)                 # nhánh khớp chữ vẫn chạy

    def test_khong_phai_postgres_thi_khong_goi_embedding(self):
        with mock.patch("talent.vector_index.embed") as embed:
            self.assertEqual(evidence_index.dense_person_ids("x", [1]), [])
        embed.assert_not_called()


class CoverageTest(TestCase):
    def test_trang_thai_noi_that(self):
        self.assertEqual(retrieve_stage.coverage()["semantic_retrieval"], "INDEX_EMPTY")
        person = _customer("Độ Phủ")
        _post(person, "Hỏi vay mua xe")
        evidence_index.index_person(person.pk)
        self.assertEqual(retrieve_stage.coverage()["semantic_retrieval"], "INDEX_NOT_EMBEDDED")
        row = ProspectEvidenceChunk.objects.filter(person=person).first()
        ProspectEvidenceChunk.objects.filter(pk=row.pk).update(
            embedding_fingerprint=row.fingerprint)
        self.assertEqual(retrieve_stage.coverage()["semantic_retrieval"], "ENABLED")
