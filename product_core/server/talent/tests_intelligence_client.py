import io
import json

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
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
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

        body = json.loads(captured["request"].data)
        self.assertEqual(captured["request"].full_url,
                         "http://intelligence:8081/v1/search")
        self.assertEqual(body["query"], "Senior Data Analyst tại Hà Nội")
        self.assertEqual(rows[0].name, "Tran Data")
        self.assertEqual(rows[0].passages[0].ordinal, 3)
