import io
import json
import urllib.error

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from people.models import Person

from .answer.plan import QueryPlan
from .intelligence_client import answer, retrieve


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
