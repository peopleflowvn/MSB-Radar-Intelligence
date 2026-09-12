from django.test import TestCase
from people.models import Document, Person

from .models import TalentProfile, TalentSemanticIndex
from .semantic_index import index_person, search, similarity


class TalentSemanticIndexTest(TestCase):
    def test_bilingual_concepts_are_similar(self):
        self.assertGreaterEqual(similarity("phân tích dữ liệu", "Data Analyst"), 0.8)
        self.assertGreaterEqual(similarity("quản lý đội nhóm", "People Management"), 0.8)

    def test_search_scans_full_cv_not_only_profile_fields(self):
        person = Person.objects.create(display_name="Nguyễn Semantic")
        TalentProfile.objects.create(person=person, current_title="Chuyên viên")
        Document.objects.create(person=person, sha256="a" * 64,
                                parsed_text="Kinh nghiệm xây data warehouse và analytics ngân hàng")
        index_person(person.pk)
        self.assertEqual(TalentSemanticIndex.objects.get().source_characters > 0, True)
        self.assertIn(person.pk, search("phân tích dữ liệu banking"))

    def test_reindex_is_idempotent(self):
        person = Person.objects.create(display_name="Một Người")
        TalentProfile.objects.create(person=person, skills=["Python"])
        first = index_person(person.pk)
        second = index_person(person.pk)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(TalentSemanticIndex.objects.count(), 1)

    def test_accepted_registry_alias_applies_to_any_namespace(self):
        """Không cần thêm dictionary Talent khi Admin duyệt alias mới."""
        from intel.registry import add_alias, ensure_namespace, upsert_entry
        ns = ensure_namespace("certification", "Chứng chỉ")
        entry = upsert_entry(ns, "aws-solutions-architect", "AWS Solutions Architect")
        add_alias(ns, "AWS SAA", entry, source="test")
        person = Person.objects.create(display_name="Cloud Candidate")
        TalentProfile.objects.create(person=person, summary="Đạt AWS SAA năm 2025")
        index_person(person.pk)
        self.assertIn(person.pk, search("AWS Solutions Architect"))
