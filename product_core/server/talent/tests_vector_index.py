# -*- coding: utf-8 -*-
"""Projection/chunk, cột chuẩn hoá và hàng đợi embedding (talent/vector_index.py)."""
from django.db import connection
from django.test import TestCase

from people.models import Document, Person
from talent import vector_index
from talent.models import CVChunk, PersonSearchDocument, TalentProfile


class FoldTest(TestCase):
    def test_fold_removes_diacritics_and_case(self):
        self.assertEqual(vector_index.fold_text("Ngân Hàng ĐẦU Tư"), "ngan hang dau tu")

    def test_fts_tokens_are_alnum_only(self):
        tokens = vector_index.fts_tokens("Quản lý đội (nhóm) 10+ người!")
        self.assertTrue(all(token.isalnum() for token in tokens))
        self.assertIn("quan", tokens)
        self.assertIn("10", tokens)

    def test_fts_filter_returns_none_off_postgres(self):
        result = vector_index.fts_filter(CVChunk.objects.all(), "text_norm", "ngân hàng")
        if connection.vendor == "postgresql":
            self.assertIsNotNone(result)
        else:
            self.assertIsNone(result)


class IndexPersonTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(display_name="Nguyễn An")
        TalentProfile.objects.create(person=self.person, current_title="Data Analyst",
                                     location="Hà Nội")
        Document.objects.create(person=self.person, sha256="a1", parse_status="done",
                                parsed_text="Phân tích dữ liệu tại Ngân Hàng ACB. " * 90)

    def test_builds_projection_and_chunks_with_normalised_text(self):
        vector_index.index_person(self.person.pk, with_embeddings=False)
        doc = PersonSearchDocument.objects.get(person=self.person)
        self.assertTrue(doc.content_norm)
        self.assertEqual(doc.content_norm, vector_index.fold_text(doc.content))
        chunk = CVChunk.objects.filter(person=self.person).first()
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.text_norm, vector_index.fold_text(chunk.text))

    def test_rows_without_embedding_are_queued_as_stale(self):
        vector_index.index_person(self.person.pk, with_embeddings=False)
        self.assertEqual([row.person_id for row in vector_index.stale_documents()],
                         [self.person.pk])
        self.assertTrue(vector_index.stale_chunks())

    def test_application_headline_is_not_indexed_as_current_work(self):
        self.person.headline = "Finance Analyst - MSB"
        self.person.save(update_fields=["headline"])
        self.assertNotIn("Finance Analyst - MSB", vector_index.document_text(self.person))

    def test_row_with_current_embedding_leaves_the_queue(self):
        vector_index.index_person(self.person.pk, with_embeddings=False)
        doc = PersonSearchDocument.objects.get(person=self.person)
        doc.embedding_fingerprint = doc.fingerprint
        doc.save(update_fields=["embedding_fingerprint"])
        self.assertEqual(list(vector_index.stale_documents()), [])

    def test_reindex_keeps_unchanged_chunks(self):
        vector_index.index_person(self.person.pk, with_embeddings=False)
        before = list(CVChunk.objects.filter(person=self.person)
                      .values_list("pk", "fingerprint").order_by("ordinal"))
        vector_index.index_person(self.person.pk, with_embeddings=False)
        after = list(CVChunk.objects.filter(person=self.person)
                     .values_list("pk", "fingerprint").order_by("ordinal"))
        self.assertEqual(before, after)

    def test_shorter_cv_drops_leftover_chunks(self):
        vector_index.index_person(self.person.pk, with_embeddings=False)
        first_count = CVChunk.objects.filter(person=self.person).count()
        self.assertGreater(first_count, 1)
        document = self.person.documents.first()
        document.parsed_text = "Chỉ còn một dòng."
        document.save(update_fields=["parsed_text"])
        vector_index.index_person(self.person.pk, with_embeddings=False)
        self.assertEqual(CVChunk.objects.filter(person=self.person).count(), 1)


class MissingProjectionTest(TestCase):
    """`missing_projection_ids` — lưới an toàn cho worker `reconcile_talent_index`:
    ứng viên hợp lệ nhưng chưa có `PersonSearchDocument`, bất kể lý do thiếu."""

    def test_applicant_without_projection_is_reported(self):
        person = Person.objects.create(display_name="Chưa lập chỉ mục")
        Document.objects.create(person=person, sha256="c1", parse_status="done",
                                parsed_text="Chuyên viên tín dụng. " * 40)
        self.assertIn(person.pk, vector_index.missing_projection_ids())

    def test_applicant_with_projection_is_not_reported(self):
        person = Person.objects.create(display_name="Đã lập chỉ mục")
        Document.objects.create(person=person, sha256="c2", parse_status="done",
                                parsed_text="Chuyên viên tín dụng. " * 40)
        vector_index.index_person(person.pk, with_embeddings=False)
        self.assertNotIn(person.pk, vector_index.missing_projection_ids())

    def test_non_applicant_without_projection_is_not_reported(self):
        person = Person.objects.create(display_name="Chỉ được nhắc tới",
                                       is_applicant=False)
        self.assertNotIn(person.pk, vector_index.missing_projection_ids())

    def test_merged_person_without_projection_is_not_reported(self):
        primary = Person.objects.create(display_name="Gốc")
        merged = Person.objects.create(display_name="Trùng", merged_into=primary)
        self.assertNotIn(merged.pk, vector_index.missing_projection_ids())


class IndexScopeTest(TestCase):
    """Chỉ ỨNG VIÊN được vào chỉ mục — lưới chống rò rỉ của ② (audit 16/09/2026).

    `intel/contacts.py` đặt `is_applicant=False` cho người chỉ được NHẮC TỚI
    trong CV của người khác (sếp cũ, người giới thiệu), kèm đúng câu "để tìm
    kiếm ứng viên và thống kê corpus không đếm họ". Ý định đó trước đây chỉ
    được `Person.applicants()` thực thi, mà `Person.applicants()` thì không có
    mặt ở tầng chỉ mục lẫn tầng truy hồi — nên sau một lần
    `rebuild_talent_vector_index`, họ vào pool đọc sâu và bị Radar gọi là
    "ứng viên".
    """

    def setUp(self):
        self.ung_vien = Person.objects.create(display_name="Nguyễn Ứng Viên")
        Document.objects.create(person=self.ung_vien, sha256="b1", parse_status="done",
                                parsed_text="Chuyên viên tín dụng tại ngân hàng. " * 40)
        self.nguoi_duoc_nhac = Person.objects.create(
            display_name="Trần Được Nhắc", is_applicant=False)
        Document.objects.create(person=self.nguoi_duoc_nhac, sha256="b2",
                                parse_status="done",
                                parsed_text="Chuyên viên tín dụng tại ngân hàng. " * 40)

    def test_non_applicant_is_not_indexed(self):
        vector_index.index_person(self.nguoi_duoc_nhac.pk, with_embeddings=False)
        self.assertFalse(PersonSearchDocument.objects.filter(
            person=self.nguoi_duoc_nhac).exists())
        self.assertFalse(CVChunk.objects.filter(person=self.nguoi_duoc_nhac).exists())

    def test_losing_applicant_flag_removes_existing_index_rows(self):
        """Mất cờ ứng viên phải RỜI HẲN chỉ mục, cả projection lẫn chunk.

        Chỉ xoá projection thì nhánh dense đoạn CV vẫn trả người đó về mãi.
        """
        vector_index.index_person(self.ung_vien.pk, with_embeddings=False)
        self.assertTrue(CVChunk.objects.filter(person=self.ung_vien).exists())

        Person.objects.filter(pk=self.ung_vien.pk).update(is_applicant=False)
        vector_index.index_person(self.ung_vien.pk, with_embeddings=False)

        self.assertFalse(PersonSearchDocument.objects.filter(person=self.ung_vien).exists())
        self.assertFalse(CVChunk.objects.filter(person=self.ung_vien).exists())

    def test_merged_person_also_leaves_the_index(self):
        vector_index.index_person(self.ung_vien.pk, with_embeddings=False)
        primary = Person.objects.create(display_name="Nguyễn Ứng Viên (gốc)")
        Person.objects.filter(pk=self.ung_vien.pk).update(merged_into=primary)
        vector_index.index_person(self.ung_vien.pk, with_embeddings=False)
        self.assertFalse(PersonSearchDocument.objects.filter(person=self.ung_vien).exists())
        self.assertFalse(CVChunk.objects.filter(person=self.ung_vien).exists())
