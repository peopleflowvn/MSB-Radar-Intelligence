# -*- coding: utf-8 -*-
"""Web search độc lập bộ não (Master Plan §23.1.3).

Backend tự chủ (searxng/duckduckgo, không khoá) và có khoá (Tavily/Brave/CSE)
đều trả kết quả thô → bộ não hiện hành tổng hợp. Gemini grounding là fallback.
DuckDuckGo bật sẵn nên web search "chạy ngay" khi ASSISTANT_WEB_SEARCH=1.
"""
from django.test import TestCase, override_settings

from . import conversation, websearch
from .adapter import ModelResponse

_DDG_OFF = {"ASSISTANT_WEBSEARCH_DDG": "0"}          # tắt fallback DDG khi test key-based


class FakeBrain:
    def __init__(self, text="Câu trả lời tổng hợp."):
        self.text = text
        self.seen = None

    def complete(self, request):
        self.seen = request
        return ModelResponse(text=self.text, provider="deepseek", model="dsv4")


def _transport(routes):
    """routes: dict[url_substr] -> (status, payload). Chữ ký backend._send.

    URL không khớp → (404, {}) để backend đó tự coi là lỗi và router lùi tiếp
    (vd DDG mặc định đứng trước nhưng test chỉ mock backend có khoá).
    """
    def send(url, method, headers, body, timeout):
        for key, resp in routes.items():
            if key in url:
                return resp
        return (404, {})
    return send


TAVILY_OK = (200, {"answer": "tóm tắt của tavily", "results": [
    {"title": "SBV", "url": "https://sbv.gov.vn/x", "content": "lãi suất 5%"},
    {"title": "VnExpress", "url": "https://vnexpress.net/y", "content": "..."},
]})
BRAVE_OK = (200, {"web": {"results": [
    {"title": "Brave A", "url": "https://a.example", "description": "mô tả A"},
]}})
CSE_OK = (200, {"items": [
    {"title": "CSE A", "link": "https://c.example", "snippet": "đoạn C"},
]})
GEMINI_OK = (200, {"candidates": [{
    "content": {"parts": [{"text": "Lãi suất quanh 5%/năm (8/2026)."}]},
    "groundingMetadata": {
        "webSearchQueries": ["lãi suất 2026"],
        "groundingChunks": [
            {"web": {"uri": "https://sbv.gov.vn/x", "title": "SBV"}},
            {"web": {"uri": "https://sbv.gov.vn/x", "title": "trùng"}},
        ]},
}]})


SEARXNG_OK = (200, {"results": [
    {"title": "SBV", "url": "https://sbv.gov.vn/x", "content": "lãi suất 5%", "score": 2.0},
    {"title": "Báo", "url": "https://vnexpress.net/y", "content": "...", "score": 3.0},
]})
DDG_HTML = (200, """
<div class="result"><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fsbv.gov.vn%2Fz&amp;rut=x">Ngân hàng Nhà nước</a>
<a class="result__snippet" href="#">Lãi suất điều hành giữ nguyên.</a></div>
<div class="result"><a class="result__a" href="https://vnexpress.net/w">VnExpress</a>
<a class="result__snippet" href="#">Tin kinh tế mới.</a></div>
""")


class PickBackendTest(TestCase):
    def test_duckduckgo_is_default_when_nothing_configured(self):
        b = websearch.pick_backend(env={})
        self.assertEqual(b.name, "duckduckgo")
        self.assertFalse(b.grounded)

    def test_searxng_wins_when_url_set(self):
        b = websearch.pick_backend(env={"SEARXNG_URL": "http://searxng:8080",
                                        "TAVILY_API_KEY": "k"})
        self.assertEqual(b.name, "searxng")

    def test_keyed_backend_before_grounding_but_after_selfhosted(self):
        picks = [p.name for p in websearch.pick_backends(
            env={"TAVILY_API_KEY": "k", "MSB_AI_GEMINI_API_KEY": "g"})]
        self.assertEqual(picks, ["duckduckgo", "tavily", "gemini_grounding"])

    def test_falls_to_gemini_when_ddg_off_and_only_gemini_key(self):
        b = websearch.pick_backend(env={"MSB_AI_GEMINI_API_KEY": "g", **_DDG_OFF})
        self.assertEqual(b.name, "gemini_grounding")

    def test_none_when_everything_off(self):
        self.assertIsNone(websearch.pick_backend(env=_DDG_OFF))

    def test_order_override(self):
        env = {"TAVILY_API_KEY": "k", "BRAVE_SEARCH_API_KEY": "b",
               "ASSISTANT_WEBSEARCH_BACKENDS": "brave,tavily"}
        self.assertEqual(websearch.pick_backend(env=env).name, "brave")

    def test_searxng_parses_and_sorts_by_score(self):
        b = websearch.SearxngBackend(env={"SEARXNG_URL": "http://sx:8080"},
                                     transport=_transport({"/search": SEARXNG_OK}))
        res = b.run("lãi suất")
        self.assertEqual([h.url for h in res.hits],
                         ["https://vnexpress.net/y", "https://sbv.gov.vn/x"])

    def test_duckduckgo_parses_and_unwraps_redirect(self):
        b = websearch.DuckDuckGoBackend(
            env={}, transport=_transport({"duckduckgo.com/html": DDG_HTML}))
        res = b.run("lãi suất")
        self.assertEqual(res.hits[0].url, "https://sbv.gov.vn/z")
        self.assertIn("giữ nguyên", res.hits[0].snippet)
        self.assertEqual(res.hits[1].url, "https://vnexpress.net/w")

    def test_web_answer_falls_through_failing_backend(self):
        def send(url, method, headers, body, timeout):
            if "duckduckgo.com/html" in url:
                return (429, "rate limited")
            if "generativelanguage" in url:
                return GEMINI_OK
            raise AssertionError(url)
        res = websearch.web_answer(
            "lãi suất?", env={"MSB_AI_GEMINI_API_KEY": "g"}, transport=send,
            adapter=FakeBrain())
        self.assertEqual(res.provider, "gemini_grounding")   # DDG hỏng -> lùi Gemini


@override_settings(ASSISTANT_WEB_SEARCH=True)
class EnabledTest(TestCase):
    def test_enabled_out_of_the_box_via_duckduckgo(self):
        # Không khoá, không cấu hình gì -> vẫn chạy được (DDG).
        self.assertTrue(websearch.enabled(env={}))

    def test_disabled_only_when_every_backend_off(self):
        self.assertFalse(websearch.enabled(env=_DDG_OFF))

    @override_settings(ASSISTANT_WEB_SEARCH=False)
    def test_flag_off_beats_backends(self):
        self.assertFalse(websearch.enabled(env={"TAVILY_API_KEY": "k"}))


class GenericBackendSynthesisTest(TestCase):
    def test_tavily_hits_are_synthesised_by_current_brain(self):
        brain = FakeBrain("Lãi suất huy động 12T ~5%/năm.")
        result = websearch.web_answer(
            "lãi suất mới nhất?", system="PERSONA", adapter=brain,
            env={"TAVILY_API_KEY": "k"},
            transport=_transport({"api.tavily.com": TAVILY_OK}))
        self.assertEqual(result.provider, "tavily")            # backend đã tìm
        self.assertEqual(result.synthesized_by, "deepseek")    # bộ não tổng hợp
        self.assertEqual(result.model, "dsv4")
        self.assertIn("5%/năm", result.text)
        self.assertEqual([c["url"] for c in result.citations],
                         ["https://sbv.gov.vn/x", "https://vnexpress.net/y"])
        # kết quả web được bọc guard trước khi đưa cho bộ não
        sys_msg = brain.seen.messages[0]["content"]
        self.assertIn("DỮ LIỆU NGUỒN", brain.seen.messages[1]["content"])
        self.assertIn("PERSONA", sys_msg)

    def test_brave_backend(self):
        result = websearch.web_answer(
            "câu hỏi", system="P", adapter=FakeBrain(),
            env={"BRAVE_SEARCH_API_KEY": "k"},
            transport=_transport({"api.search.brave.com": BRAVE_OK}))
        self.assertEqual(result.provider, "brave")
        self.assertEqual(result.citations[0]["url"], "https://a.example")

    def test_google_cse_backend(self):
        result = websearch.web_answer(
            "câu hỏi", system="P", adapter=FakeBrain(),
            env={"GOOGLE_CSE_KEY": "k", "GOOGLE_CSE_CX": "cx"},
            transport=_transport({"customsearch/v1": CSE_OK}))
        self.assertEqual(result.provider, "google_cse")
        self.assertEqual(result.citations[0]["url"], "https://c.example")

    def test_no_hits_raises(self):
        with self.assertRaises(websearch.WebSearchUnavailable):
            websearch.web_answer(
                "x", adapter=FakeBrain(), env={"TAVILY_API_KEY": "k"},
                transport=_transport({"api.tavily.com": (200, {"results": []})}))

    def test_http_error_raises(self):
        with self.assertRaises(websearch.WebSearchUnavailable):
            websearch.web_answer(
                "x", adapter=FakeBrain(), env={"BRAVE_SEARCH_API_KEY": "k"},
                transport=_transport({"api.search.brave.com": (403, {})}))

    def test_raises_when_all_backends_off(self):
        with self.assertRaises(websearch.WebSearchUnavailable):
            websearch.web_answer("x", adapter=FakeBrain(), env=_DDG_OFF,
                                 transport=_transport({}))


class GroundingBackendTest(TestCase):
    def test_gemini_grounding_answers_directly(self):
        result = websearch.web_answer(
            "lãi suất?", system="P", adapter=FakeBrain("KHÔNG DÙNG"),
            env={"MSB_AI_GEMINI_API_KEY": "g"},
            transport=_transport({"generativelanguage.googleapis.com": GEMINI_OK}))
        self.assertEqual(result.provider, "gemini_grounding")
        self.assertEqual(result.synthesized_by, "")            # không cần bộ não
        self.assertIn("5%/năm", result.text)
        self.assertEqual([c["url"] for c in result.citations], ["https://sbv.gov.vn/x"])
        self.assertEqual(result.queries, ["lãi suất 2026"])

    def test_gemini_auth_error(self):
        with self.assertRaises(websearch.WebSearchUnavailable):
            websearch.web_answer(
                "x", adapter=FakeBrain(), env={"MSB_AI_GEMINI_API_KEY": "g"},
                transport=_transport({"generativelanguage.googleapis.com": (403, {})}))


class AnswerViaConversationTest(TestCase):
    class _Intent:
        kind = "web"
        raw = {}

        def as_dict(self):
            return {"intent": "web", "confidence": 0.9, "reason": "", "source": "model"}

    def test_answer_if_conversation_uses_web_result_with_any_brain(self):
        import unittest.mock as m
        result = websearch.WebResult(
            text="Câu trả lời có nguồn.",
            citations=[{"title": "Nguồn A", "url": "https://a.example"}],
            queries=["q"], provider="brave", model="dsv4", synthesized_by="deepseek")
        with m.patch.object(websearch, "web_answer", return_value=result) as mock:
            reply = conversation.answer_if_conversation(
                "tin tức mới nhất về fintech", surface="talent",
                intent=self._Intent(), adapter=FakeBrain())
        # adapter (bộ não) được chuyển xuống web_answer để tổng hợp
        self.assertIsNotNone(mock.call_args.kwargs.get("adapter"))
        self.assertEqual(str(reply), "Câu trả lời có nguồn.")
        self.assertTrue(reply.web)
        self.assertEqual(reply.citations[0]["url"], "https://a.example")
        self.assertEqual(reply.web_queries, ["q"])

    def test_web_unavailable_falls_through_to_model(self):
        import unittest.mock as m
        with m.patch.object(websearch, "web_answer",
                            side_effect=websearch.WebSearchUnavailable("tắt")):
            reply = conversation.answer_if_conversation(
                "câu hỏi kiến thức chung?", surface="talent",
                intent=self._Intent(), adapter=FakeBrain("trả lời thường"))
        self.assertEqual(str(reply), "trả lời thường")
        self.assertFalse(reply.web)
