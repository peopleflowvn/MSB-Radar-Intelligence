import io
import json
import urllib.error

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from accounts import roles
from knowledge.models import KnowledgeDocument
from people.models import Person

from .answer.plan import QueryPlan
from .intelligence_client import answer, knowledge_search, retrieve


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@override_settings(
    INTELLIGENCE_BASE_URL="http://intelligence:8081",
    INTELLIGENCE_SERVICE_TOKEN="shared",
    INTELLIGENCE_REQUEST_TIMEOUT_SECONDS=9,
)
class IntelligenceClientTest(TestCase):
    def test_v2_answer_is_adapted_to_unchanged_frontend_shape(self):
        user = User.objects.create_user("recruiter")
        person = Person.objects.create(display_name="Nguyen Van A")
        captured = {}

        def opener(request, timeout):
            captured["request"], captured["timeout"] = request, timeout
            return Response(json.dumps({
                "answer": "Phu hop [1]", "people": [{"person_id": str(person.pk),
                                                       "display_name": None}],
                "evidence": [{"person_id": str(person.pk), "document_id": "12",
                              "location": "chunk 0", "text": "Python banking"}],
                "trace": [{"provider": "greennode", "model_alias": "deep"}],
                "interpreted_query": {"grounded": True},
            }).encode())

        result = answer(user, "Ai phu hop?", conversation_id="thread-1", opener=opener)
        request_body = json.loads(captured["request"].data)
        self.assertEqual(captured["request"].full_url, "http://intelligence:8081/v1/answer")
        self.assertEqual(captured["request"].headers["Authorization"], "Bearer shared")
        self.assertEqual(captured["timeout"], 9)
        self.assertTrue(request_body["scope_token"])
        self.assertEqual(result.people[0]["name"], "Nguyen Van A")
        self.assertEqual(result.sources[0]["ordinal"], 1)
        self.assertEqual(result.trace["engine"], "intelligence-v2")

    def test_v2_search_is_adapted_for_existing_judge_pipeline(self):
        user = User.objects.create_user("searcher")
        person = Person.objects.create(display_name="Tran Data")
        captured = []

        def opener(request, timeout):
            captured.append(request)
            return Response(json.dumps({"hits": [{
                "person": {"person_id": str(person.pk), "display_name": None},
                "score": 0.91,
                "matched_filters": [],
                "evidence": [{
                    "person_id": str(person.pk), "document_id": "12",
                    "location": "chunk 3", "text": "SQL Python, 5 years",
                    "source": "cv",
                }],
            }]}).encode())

        rows = retrieve(user, QueryPlan(
            information_need="Senior Data Analyst tại Hà Nội",
            search_queries=["data analyst SQL Python"]), opener=opener)

        bodies = [json.loads(request.data) for request in captured]
        self.assertEqual(len(captured), 2)
        self.assertTrue(all(request.full_url == "http://intelligence:8081/v1/search"
                            for request in captured))
        self.assertEqual({body["query"] for body in bodies}, {
            "Senior Data Analyst tại Hà Nội", "data analyst SQL Python"})
        self.assertEqual(rows[0].name, "Tran Data")
        self.assertEqual(rows[0].passages[0].ordinal, 3)

    def test_multi_query_rrf_rewards_people_found_by_multiple_variants(self):
        user = User.objects.create_user("rrf-searcher")
        first = Person.objects.create(display_name="One Query")
        repeated = Person.objects.create(display_name="Repeated")

        def hit(person, text):
            return {"person": {"person_id": str(person.pk)}, "score": .8,
                    "matched_filters": [], "evidence": [{
                        "evidence_id": f"e-{person.pk}-{text}",
                        "person_id": str(person.pk), "document_id": str(person.pk),
                        "location": "chunk 0", "text": text, "source": "cv"}]}

        def opener(request, timeout):
            query = json.loads(request.data)["query"]
            hits = ([hit(first, "first"), hit(repeated, "common")]
                    if query == "primary" else [hit(repeated, "second")])
            return Response(json.dumps({"hits": hits}).encode())

        rows = retrieve(user, QueryPlan(
            information_need="primary", search_queries=["variant"]), opener=opener)
        self.assertEqual([row.person_id for row in rows], [repeated.pk, first.pk])
        self.assertEqual(len(rows[0].passages), 2)

    def test_answer_includes_knowledge_ids_only_when_user_has_the_module(self):
        outsider = User.objects.create_user("no-kb-access")
        KnowledgeDocument.objects.create(title="Chinh sach", parsed_text="noi dung")
        captured = {}

        def opener(request, timeout):
            captured["body"] = json.loads(request.data)
            return Response(json.dumps({
                "answer": "khong co bang chung", "people": [], "evidence": [], "trace": [],
                "interpreted_query": {},
            }).encode())

        answer(outsider, "cau hoi", opener=opener)
        self.assertEqual(captured["body"]["knowledge_ids"], [])

        admin = User.objects.create_user("kb-admin", is_superuser=True)
        answer(admin, "cau hoi", opener=opener)
        self.assertEqual(len(captured["body"]["knowledge_ids"]), 1)

    def test_answer_resolves_knowledge_document_titles_for_negative_ids(self):
        user = User.objects.create_user("kb-reader", is_superuser=True)
        doc = KnowledgeDocument.objects.create(
            title="Quy trinh nghi phep", parsed_text="noi dung chinh sach")

        def opener(request, timeout):
            return Response(json.dumps({
                "answer": "Theo [1]",
                "people": [{"person_id": str(doc.radar_entity_id), "display_name": None}],
                "evidence": [{"person_id": str(doc.radar_entity_id),
                              "document_id": str(doc.radar_entity_id),
                              "location": "chunk 0", "text": "12 ngay phep"}],
                "trace": [], "interpreted_query": {},
            }).encode())

        result = answer(user, "May ngay phep?", opener=opener)
        self.assertEqual(result.people[0]["name"], "Quy trinh nghi phep")
        self.assertEqual(result.people[0]["person_id"], doc.radar_entity_id)

    def test_knowledge_search_asks_for_knowledge_only_and_returns_labelled_snippets(self):
        user = User.objects.create_user("kb-context-user", is_superuser=True)
        doc = KnowledgeDocument.objects.create(
            title="Quy trinh nghi phep", parsed_text="12 ngay phep nam")
        captured = {}

        def opener(request, timeout):
            captured["body"] = json.loads(request.data)
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            return Response(json.dumps({"hits": [{
                "person": {"person_id": str(doc.radar_entity_id), "display_name": None},
                "score": 0.9, "matched_filters": [],
                "evidence": [{"person_id": str(doc.radar_entity_id),
                              "document_id": str(doc.radar_entity_id),
                              "location": "chunk 0", "text": "12 ngay phep nam",
                              "source": "hr_policy"}],
            }]}).encode())

        sources = knowledge_search(user, "nghi phep the nao", opener=opener)
        self.assertEqual(captured["url"], "http://intelligence:8081/v1/search")
        self.assertTrue(captured["body"]["knowledge_only"])
        self.assertEqual(captured["body"]["knowledge_ids"], [str(doc.radar_entity_id)])
        # Đường nóng của chat: phải có hạn giờ riêng, ngắn hơn hạn giờ chung.
        self.assertLess(captured["timeout"], 9)
        self.assertEqual(sources, [("Quy trinh nghi phep", "12 ngay phep nam")])

    def test_knowledge_search_returns_nothing_without_the_module(self):
        user = User.objects.create_user("kb-context-outsider")
        KnowledgeDocument.objects.create(title="X", parsed_text="y")

        def opener(request, timeout):
            raise AssertionError("must not call Intelligence without the module")

        self.assertEqual(knowledge_search(user, "cau hoi", opener=opener), [])

    def test_retrieve_never_sends_knowledge_ids(self):
        user = User.objects.create_user("candidate-only-searcher", is_superuser=True)
        KnowledgeDocument.objects.create(title="X", parsed_text="y")
        captured = []

        def opener(request, timeout):
            captured.append(json.loads(request.data))
            return Response(json.dumps({"hits": []}).encode())

        retrieve(user, QueryPlan(information_need="q", search_queries=[]), opener=opener)
        for body in captured:
            self.assertNotIn("knowledge_ids", body)

    def test_multi_query_keeps_successful_variant_when_one_fails(self):
        user = User.objects.create_user("resilient-searcher")
        person = Person.objects.create(display_name="Resilient")

        def opener(request, timeout):
            query = json.loads(request.data)["query"]
            if query == "broken variant":
                raise urllib.error.URLError("synthetic timeout")
            return Response(json.dumps({"hits": [{
                "person": {"person_id": str(person.pk)}, "score": .9,
                "matched_filters": [], "evidence": [{
                    "person_id": str(person.pk), "document_id": "1",
                    "location": "chunk 0", "text": "SQL", "source": "cv"}],
            }]}).encode())

        rows = retrieve(user, QueryPlan(
            information_need="working variant",
            search_queries=["broken variant"]), opener=opener)
        self.assertEqual([row.person_id for row in rows], [person.pk])
