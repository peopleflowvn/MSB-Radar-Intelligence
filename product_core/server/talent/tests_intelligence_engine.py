from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from .answer import engine


@override_settings(INTELLIGENCE_V2_PRIMARY=True)
class IntelligenceEngineRoutingTest(SimpleTestCase):
    @patch("talent.answer.engine._stream_chat")
    @patch("talent.answer.engine.plan_stage.plan")
    def test_general_question_keeps_conversation_route(self, plan, stream_chat):
        plan.return_value = engine.plan_stage.QueryPlan(
            shape="general", information_need="Radar là ai?", search_queries=[])
        expected = engine.AnswerResult(text="Radar là trợ lý tuyển dụng.")
        stream_chat.return_value = iter((
            {"type": "answer", "text": expected.text},
            {"type": "done", "result": expected},
        ))

        chunks = list(engine.stream_answer("Radar là ai?", user=Mock(pk=7)))

        self.assertEqual(chunks[-1], {"type": "done", "result": expected})
        stream_chat.assert_called_once()

    @patch("talent.answer.engine._stream_assess_doc")
    def test_attachment_keeps_existing_direct_document_path(self, assess):
        # Direct attachment assessment has different evidence provenance and is
        # intentionally not sent through the corpus index.
        assess.return_value = iter((
            {"type": "done", "result": engine.AnswerResult(text="Document")},))
        list(engine.stream_answer(
            "Đánh giá\n\nTÀI LIỆU ĐÍNH KÈM:\nPython", user=Mock(pk=7)))
        assess.assert_called_once()
