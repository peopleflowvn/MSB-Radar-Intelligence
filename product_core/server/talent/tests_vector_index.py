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
