# -*- coding: utf-8 -*-
"""Hỏi đáp có dẫn chứng trên kho CV — kiểu NotebookLM (talent/corpus_qa.py)."""
import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from people.models import Document, Person
from talent import corpus_qa
from talent.models import CVChunk, TalentProfile


class FakeLLM:
    def __init__(self, reply="{}"):
        self.reply = reply
        self.calls = []

    def __call__(self, messages, task="", **kwargs):
        self.calls.append({"messages": messages, "task": task, "kwargs": kwargs})

        class R:
            provider, model = "fake", "glm"

            def __init__(self, text):
                self.text = text
        return R(self.reply)


def _doc(person, text, name="cv.pdf", sha="h"):
    return Document.objects.create(person=person, filename=name, sha256=sha,
                                   parsed_text=text, parse_status="done")


class RetrieveTest(TestCase):
    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn An")
        TalentProfile.objects.create(person=self.an, current_title="Data Analyst")
        _doc(self.an, "Nguyễn An có 5 năm làm phân tích dữ liệu tại ngân hàng ACB, "
                      "thành thạo SQL và Power BI, từng quản lý đội 8 người.", sha="a1")
        self.binh = Person.objects.create(display_name="Trần Bình")
        _doc(self.binh, "Trần Bình là lập trình viên Java, chưa có kinh nghiệm ngân hàng.",
             sha="b1")

    def test_lexical_fallback_reads_document_when_no_chunks(self):
        passages = corpus_qa.retrieve("ai từng làm ở ngân hàng?", limit=5)
        self.assertTrue(passages)
        self.assertIn(self.an.pk, {p.person_id for p in passages})
        self.assertIn("ngân hàng", passages[0].text.lower())

    def test_uses_cvchunk_when_present(self):
        doc = self.an.documents.first()
        CVChunk.objects.create(person=self.an, document=doc, ordinal=0,
                               fingerprint="f0",
                               text="Quản lý đội 8 người, chịu trách nhiệm KPI phân tích.")
        passages = corpus_qa.retrieve("CV nào nói đến quản lý đội nhóm?", limit=5)
        self.assertTrue(any(p.ordinal == 0 and p.person_id == self.an.pk
                            for p in passages))

    def test_retrieve_empty_for_unrelated_query(self):
        self.assertEqual(corpus_qa.retrieve("phi hành gia sao Hỏa", limit=5), [])

    def test_person_without_cv_is_found_through_profile_projection(self):
        from talent import vector_index
        edge_only = Person.objects.create(display_name="Lê Chi")
        TalentProfile.objects.create(person=edge_only,
                                     current_title="Chuyên viên Bảo hiểm",
                                     location="Đà Nẵng")
        vector_index.index_person(edge_only.pk, with_embeddings=False)
        passages = corpus_qa.retrieve("ai làm bảo hiểm?", limit=5)
        hit = next((p for p in passages if p.person_id == edge_only.pk), None)
        self.assertIsNotNone(hit, "hồ sơ chỉ có dữ liệu Edge vẫn phải trả lời được")
        self.assertEqual(hit.document_id, corpus_qa.PROFILE_DOC_ID)
        self.assertEqual(corpus_qa.source_label(hit.document_id), "hồ sơ")


class AnswerTest(TestCase):
    def setUp(self):
        self.an = Person.objects.create(display_name="Nguyễn An")
        _doc(self.an, "Nguyễn An: 5 năm phân tích dữ liệu tại ngân hàng ACB, biết SQL.",
             sha="a1")

    def test_answer_grounds_and_parses_citations(self):
        llm = FakeLLM("Có [1]. Nguyễn An từng làm tại ngân hàng ACB [1].")
        result = corpus_qa.answer("ai từng làm ngân hàng?", complete_fn=llm)
        self.assertIsNotNone(result)
        self.assertIn("ACB", result["answer"])
        self.assertEqual(result["citations"][0]["person_id"], self.an.pk)
        # prompt phải chứa nguồn đánh số
        sent = llm.calls[0]["messages"][1]["content"]
        self.assertIn("[1] Nguyễn An", sent)
        self.assertEqual(llm.calls[0]["task"], corpus_qa.TASK)

    def test_answer_none_when_nothing_retrieved(self):
        llm = FakeLLM("không bao giờ được gọi")
        self.assertIsNone(corpus_qa.answer("người chơi bóng chày ở NASA", complete_fn=llm))
        self.assertEqual(llm.calls, [])

    def test_as_reply_shapes_citations_for_ui(self):
        llm = FakeLLM("Nguyễn An làm ngân hàng ACB [1].")
        reply = corpus_qa.as_reply("ai làm ngân hàng?", complete_fn=llm)
        self.assertTrue(reply.grounded)
        self.assertEqual(reply.citations[0]["url"], f"/person/{self.an.pk}?from=talent")
        self.assertEqual(reply.corpus_citations[0]["person_id"], self.an.pk)


# `SearchCitationTest` đã bỏ cùng `ai_search._result_citations`. Hành vi tương
# đương — kết quả mang trích dẫn bấm được, trỏ đúng `document_id` — nay do
# `talent/answer/judge.py` đảm nhiệm và được `tests_answer.py` phủ.


class LooksLikeTest(TestCase):
    def test_heuristic(self):
        self.assertTrue(corpus_qa.looks_like_corpus_question("Kho mình có bao nhiêu người biết SQL?"))
        self.assertTrue(corpus_qa.looks_like_corpus_question("CV nào nhắc tới lãnh đạo đội nhóm lớn?"))
        self.assertFalse(corpus_qa.looks_like_corpus_question("chào bạn"))


class FakeStreamAdapter:
    """Adapter stream giả — trả sẵn một câu trả lời có trích dẫn [1]."""

    def __init__(self):
        self.requests = []

    def stream(self, request):
        from ai.adapter import ModelResponse
        self.requests.append(request)
        yield {"type": "answer", "text": "Nguyễn An làm ở ngân hàng ACB [1]."}
        yield {"type": "done", "response": ModelResponse(
            text="Nguyễn An làm ở ngân hàng ACB [1].", provider="fake", model="m1")}


def _people_plan():
    """Kế hoạch ① nói "câu này hỏi về người" — cổng vào nhánh kho CV."""
    from talent.answer.plan import QueryPlan
    return QueryPlan(shape="find_people", information_need="ai từng làm ngân hàng",
                     search_queries=["ngân hàng"])


@override_settings(ASSISTANT_INTENT_ROUTER=False)
class StreamIntegrationTest(TestCase):
    URL = "/api/v1/ai/assistant/stream/"

    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("rec-stream", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.client.force_login(self.user)
        self.an = Person.objects.create(display_name="Nguyễn An")
        _doc(self.an, "Nguyễn An: 5 năm phân tích dữ liệu tại ngân hàng ACB, biết SQL.",
             sha="a1")

    def _body(self, resp):
        return b"".join(resp.streaming_content).decode("utf-8")

    def test_corpus_question_goes_through_answer_engine(self):
        """Bề mặt trợ lý chat dùng CHUNG một engine với `/talent/ask/`.

        Trước đây nó có đường trả lời riêng (`corpus_qa`), nên cùng một câu hỏi
        cho hai chất lượng khác nhau tuỳ người dùng gõ ở đâu.
        """
        from talent.answer.engine import AnswerResult

        def fake_stream(question, **kwargs):
            result = AnswerResult(
                text="Nguyễn An làm ở ngân hàng ACB [1].",
                sources=[{"n": 1, "person_id": self.an.pk, "name": "Nguyễn An",
                          "document_id": 5, "ordinal": 0, "snippet": "ngân hàng ACB"}],
                people=[], provider="fake", model="m1")
            yield {"type": "answer", "text": result.text}
            yield {"type": "done", "result": result}

        with mock.patch("talent.answer.engine.stream_answer", fake_stream), \
                mock.patch("talent.answer.plan.plan", return_value=_people_plan()):
            resp = self.client.post(self.URL, json.dumps({
                "q": "Trong kho có ai từng làm ở ngân hàng không?",
                "surface": "talent", "conversation_id": "c-corpus",
                "client_turn_id": "turn-c1"}), content_type="application/json")
            body = self._body(resp)
        self.assertIn("event: citations", body)
        self.assertIn("Nguyễn An", body)
        self.assertIn("event: answer", body)
        self.assertIn('"grounded": true', body)

        from ai.models import AssistantThread
        thread = AssistantThread.objects.get(user=self.user, thread_id="c-corpus")
        message = thread.messages.get(role="assistant")
        self.assertEqual(message.metadata["cv_citations"][0]["person_id"], self.an.pk)

    def test_cau_hoi_khong_ve_nguoi_khong_bi_day_vao_luong_tim_nguoi(self):
        """"Radar là gì?" kết thúc bằng "?" nên lọt heuristic — ① phải chặn lại.

        Không có cổng này thì câu hỏi meta bị trả lời bằng giọng tìm người
        ("chưa tìm được hồ sơ nào thoả…").
        """
        from talent.answer.plan import QueryPlan
        adapter = FakeStreamAdapter()
        with mock.patch("ai.stream_views.get_adapter", return_value=adapter), \
                mock.patch("talent.answer.plan.plan",
                           return_value=QueryPlan(shape="general", search_queries=[])):
            resp = self.client.post(self.URL, json.dumps({
                "q": "Radar chấm điểm phù hợp thế nào?",
                "surface": "talent", "conversation_id": "c-meta",
                "client_turn_id": "turn-m1"}), content_type="application/json")
            body = self._body(resp)
        self.assertNotIn("event: citations", body)
        self.assertNotIn("Chưa tìm được hồ sơ nào", body)
        self.assertIn("event: answer", body)

    def test_question_without_matching_cv_falls_back_to_normal_chat(self):
        adapter = FakeStreamAdapter()
        with mock.patch("ai.stream_views.get_adapter", return_value=adapter):
            resp = self.client.post(self.URL, json.dumps({
                "q": "Bạn giải thích giúp cách chấm điểm phù hợp được không?",
                "surface": "talent", "conversation_id": "c-plain",
                "client_turn_id": "turn-p1"}), content_type="application/json")
        body = self._body(resp)
        self.assertNotIn("event: citations", body)
        self.assertIn("event: answer", body)


# `ViewIntegrationTest` đã bỏ cùng endpoint `/talent/ai-search/`. Đường trả lời
# có dẫn chứng nay là `/talent/ask/`, do `tests_answer.AskEndpointTest` phủ.
# `corpus_qa` vẫn sống vì bề mặt trợ lý chat (`ai/stream_views.py`) dùng nó.


@override_settings(TALENT_EMBEDDING_BASE_URL="", TALENT_EMBEDDING_MODEL="")
class EmbeddingConfigApiTest(TestCase):
    def setUp(self):
        from accounts import roles
        roles.ensure_groups()
        self.user = User.objects.create_user("adm", password="mat-khau-dai-1")
        self.user.groups.add(Group.objects.get(name=roles.ADMIN))
        self.client.force_login(self.user)

    def _url(self):
        return reverse("talent-embedding-config")

    def test_get_returns_defaults_and_coverage(self):
        r = self.client.get(self._url())
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["mode"], "selfhost")
        self.assertIn("coverage", body)
        self.assertEqual({c["value"] for c in body["mode_choices"]},
                         {"greennode", "selfhost", "gemini", "off"})

    def test_switch_to_off_deactivates(self):
        r = self.client.put(self._url(), data=json.dumps({"mode": "off"}),
                            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["active"])
        from talent import vector_index
        self.assertIsNone(vector_index._embedding_config())

    def test_switch_source_marks_vectors_stale(self):
        from talent.models import EmbeddingConfig, PersonSearchDocument
        p = Person.objects.create(display_name="X")
        _doc(p, "text ngân hàng", sha="x1")
        psd = PersonSearchDocument.objects.create(
            person=p, fingerprint="fp", content="c", content_norm="c",
            embedding_fingerprint="fp")
        r = self.client.put(self._url(),
                            data=json.dumps({"mode": "selfhost",
                                             "selfhost_model": "bge-m3"}),
                            content_type="application/json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["needs_rebackfill"])
        psd.refresh_from_db()
        self.assertNotEqual(psd.embedding_fingerprint, "fp")
        self.assertEqual(EmbeddingConfig.load().selfhost_model, "bge-m3")

    def test_requires_ai_settings_role(self):
        from accounts import roles
        self.user.groups.clear()
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.assertEqual(self.client.get(self._url()).status_code, 403)
