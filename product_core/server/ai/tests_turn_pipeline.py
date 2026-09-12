# -*- coding: utf-8 -*-
"""Lát cắt dọc Giai đoạn 1: adapter model, event log, context projection.

Gate: mọi model request dựng lại được từ event log (Master Plan §15).
"""
from django.contrib.auth.models import User
from django.test import TestCase

from . import conversation_state, events, projection
from .adapter import ModelError, ModelRequest, ModelResponse, RouterAdapter
from .conversation import ConversationReply, answer_if_conversation
from .models import AssistantEvent, AssistantThread
from .providers import LLMError
from .providers import Completion


def fake_completion(text="xin chào", provider="greennode", model="m1"):
    def _fn(messages, task="", **kwargs):
        return Completion(text=text, provider=provider, model=model,
                          prompt_tokens=11, completion_tokens=7, latency_ms=123)
    return _fn


class RouterAdapterTest(TestCase):
    def test_maps_completion_to_model_response(self):
        adapter = RouterAdapter(fake_completion("kết quả"))
        resp = adapter.complete(ModelRequest(messages=[{"role": "user", "content": "hi"}],
                                             task="assistant_conversation", max_tokens=50))
        self.assertIsInstance(resp, ModelResponse)
        self.assertEqual(resp.text, "kết quả")
        self.assertEqual(resp.provider, "greennode")
        self.assertEqual(resp.usage.prompt_tokens, 11)
        self.assertEqual(resp.usage.total_tokens, 18)
        self.assertEqual(resp.latency_ms, 123)

    def test_llm_error_becomes_model_error(self):
        def boom(*a, **k):
            raise LLMError("nhà cung cấp sập")
        with self.assertRaises(ModelError):
            RouterAdapter(boom).complete(ModelRequest(messages=[]))

    def test_stream_fallback_uses_complete_when_no_stream_fn(self):
        adapter = RouterAdapter(fake_completion("<thinking>ngẫm</thinking>một mảnh"))
        chunks = list(adapter.stream(ModelRequest(messages=[])))
        self.assertEqual([c["type"] for c in chunks], ["thinking", "answer", "done"])
        self.assertEqual(chunks[1]["text"], "một mảnh")
        self.assertEqual(chunks[-1]["response"].text, "một mảnh")
        self.assertEqual(chunks[-1]["response"].raw["reasoning"], "ngẫm")

    def test_request_as_kwargs_only_includes_set_fields(self):
        req = ModelRequest(messages=[], temperature=0.2)
        self.assertEqual(req.as_kwargs(), {"temperature": 0.2})


class EventLogTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("evt")
        self.thread = AssistantThread.objects.create(
            user=self.user, surface="talent", thread_id="t-evt")

    def test_recorder_appends_with_increasing_seq(self):
        rec = events.TurnRecorder(self.thread, "turn-1")
        rec.started()
        rec.user_message("câu hỏi")
        rec.completed(count=3)
        rows = events.turn_events(self.thread, "turn-1")
        self.assertEqual([r.seq for r in rows], [1, 2, 3])
        self.assertEqual([r.kind for r in rows],
                         [events.TURN_STARTED, events.USER_MESSAGE, events.TURN_COMPLETED])

    def test_inactive_recorder_is_noop(self):
        self.assertFalse(events.TurnRecorder(None, "x").active)
        self.assertFalse(events.TurnRecorder(self.thread, "").active)
        events.TurnRecorder(self.thread, "").started()
        self.assertEqual(AssistantEvent.objects.count(), 0)

    def test_reconstruct_request_from_event_log(self):
        req = ModelRequest(messages=[{"role": "system", "content": "bạn là Radar"},
                                     {"role": "user", "content": "Radar là gì?"}],
                           task="assistant_conversation", temperature=0.2, max_tokens=600)
        rec = events.TurnRecorder(self.thread, "turn-2")
        rec.started()
        rec.model_requested(req)
        rec.completed()

        rebuilt = events.reconstruct_request(self.thread, "turn-2")
        self.assertEqual(rebuilt["messages"], req.messages)
        self.assertEqual(rebuilt["task"], "assistant_conversation")
        self.assertEqual(rebuilt["params"]["max_tokens"], 600)

    def test_duplicate_seq_is_swallowed(self):
        AssistantEvent.objects.create(thread=self.thread, turn_id="dup", seq=1,
                                      kind=events.TURN_STARTED, payload={})
        rec = events.TurnRecorder(self.thread, "dup")
        # recorder bắt đầu từ seq 1 -> đụng unique -> nuốt, không nổ
        self.assertIsNone(rec.started())


class ProjectionTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("proj")

    def test_build_context_is_versioned_and_derived(self):
        for i in range(3):
            conversation_state.record(self.user, "talent", "p1", f"hỏi {i}", f"đáp {i}",
                                      {"title": f"BA {i}"})
        ctx = projection.build_context(self.user, "talent", "p1")
        self.assertEqual(ctx.projection_version, projection.PROJECTION_VERSION)
        self.assertEqual(ctx.active_criteria, {"title": "BA 2"})
        self.assertTrue(ctx.recent_turns)
        self.assertIn("proj", ctx.permissions_note)
        self.assertEqual(ctx.as_dict()["projection_version"], 1)

    def test_empty_thread_gives_blank_projection(self):
        ctx = projection.build_context(self.user, "talent", "khong-co")
        self.assertEqual(ctx.recent_turns, [])
        self.assertEqual(ctx.active_criteria, {})


class ConversationTurnIntegrationTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("conv")

    def test_answer_if_conversation_returns_rich_reply(self):
        adapter = RouterAdapter(fake_completion("<thinking>cân nhắc</thinking>Radar là trợ lý."))
        reply = answer_if_conversation("Radar là gì?", surface="talent",
                                       user=self.user, adapter=adapter)
        self.assertIsInstance(reply, ConversationReply)
        self.assertEqual(str(reply), "Radar là trợ lý.")
        self.assertEqual(reply.reasoning, "cân nhắc")
        self.assertEqual(reply.provider, "greennode")
        self.assertIsNotNone(reply.request)

    def test_log_conversation_turn_is_replayable(self):
        adapter = RouterAdapter(fake_completion("Radar là trợ lý con người."))
        reply = answer_if_conversation("Radar hỗ trợ tuyển dụng ra sao?", surface="talent",
                                       user=self.user, adapter=adapter)
        thread = conversation_state.record(
            self.user, "talent", "c1", "Radar hỗ trợ tuyển dụng ra sao?", str(reply),
            mode="conversation", provider=reply.provider, model=reply.model,
            client_turn_id="turn-c1")
        events.log_conversation_turn(thread, "turn-c1", "talent", "Radar hỗ trợ tuyển dụng ra sao?", reply)

        kinds = [e.kind for e in events.turn_events(thread, "turn-c1")]
        self.assertEqual(kinds, [
            events.TURN_STARTED, events.USER_MESSAGE, events.MODEL_REQUESTED,
            events.MODEL_RESPONDED, events.TURN_COMPLETED])
        rebuilt = events.reconstruct_request(thread, "turn-c1")
        self.assertEqual(rebuilt["messages"], reply.request.messages)

    def test_search_word_still_returns_empty(self):
        self.assertEqual(
            answer_if_conversation("tìm ứng viên BA", surface="talent", user=self.user), "")

    def test_cau_tu_danh_gia_co_cau_tra_loi_co_dinh_khong_goi_model(self):
        """Ảnh test 04/09: "Bạn tự đánh giá khả năng của mình thế nào" → model
        stream đứt giữa chừng ("Mất kết nối"). Nó không có gì để tra và không có
        câu chốt — xử như câu hỏi năng lực, trả lời cố định, không gọi model."""
        from .conversation import common_answer

        for q in ("Bạn tự đánh giá khả năng của mình thế nào",
                  "bạn tự nhận xét đi", "đánh giá bản thân bạn xem"):
            self.assertTrue(common_answer(q, surface="talent"),
                            f"{q!r} phải có câu trả lời cố định")

    def test_cau_hoi_tiep_co_chu_kha_nang_van_di_hoi_thoai(self):
        """Không siết quá tay: "còn khả năng của bạn thì sao" trong mạch hội
        thoại là câu hỏi tiếp thật, phải qua model chứ không chặn."""
        from .conversation import common_answer
        self.assertEqual(common_answer("Còn khả năng xử lý tiếng Anh của bạn thì sao",
                                       surface="talent"), "")

    def test_prompt_is_three_layered_and_stable_prefix_is_constant(self):
        from .persona import STABLE_PROMPT_VERSION
        adapter = RouterAdapter(fake_completion("Vẫn là Radar."))
        r1 = answer_if_conversation("Radar là ai?", surface="talent", user=self.user,
                                    adapter=adapter, history=[])
        r2 = answer_if_conversation("Còn gì nữa không?", surface="talent", user=self.user,
                                    adapter=adapter,
                                    history=[{"question": "Radar là ai?", "answer": "Radar."}])
        # tầng stable (message system đầu tiên) byte-identical giữa hai lượt
        self.assertEqual(r1.request.messages[0], r2.request.messages[0])
        self.assertEqual(r1.request.messages[0]["role"], "system")
        self.assertEqual(r1.request.meta["stable_prompt_version"], STABLE_PROMPT_VERSION)
        self.assertEqual(r1.request.meta["prompt_layers"],
                         ["stable", "context", "turns", "volatile"])
        # lượt 2 có thêm tầng turns; câu hỏi hiện tại luôn ở message cuối (volatile)
        self.assertEqual(r2.request.messages[-1]["content"], "Còn gì nữa không?")
        self.assertGreater(len(r2.request.messages), len(r1.request.messages))

    def test_turn_lineage_follows_parent(self):
        user = self.user
        thread = conversation_state.record(user, "talent", "lin", "q1", "a1",
                                           client_turn_id="t1")
        events.TurnRecorder(thread, "t1").started(surface="talent")
        events.TurnRecorder(thread, "t2").started(surface="talent", parent_turn_id="t1")
        events.TurnRecorder(thread, "t3").started(surface="talent", parent_turn_id="t2")
        self.assertEqual(events.turn_lineage(thread, "t3"), ["t1", "t2", "t3"])

    def test_projection_context_reaches_the_model_request(self):
        adapter = RouterAdapter(fake_completion("Vẫn là Radar."))
        history = [{"question": "Radar là ai?", "answer": "Radar là trợ lý tuyển dụng."}]
        reply = answer_if_conversation("Còn khả năng của bạn thì sao?", surface="talent",
                                       user=self.user, adapter=adapter, history=history)
        contents = [m["content"] for m in reply.request.messages]
        self.assertIn("Radar là ai?", contents)                    # lượt trước có mặt
        self.assertIn("Radar là trợ lý tuyển dụng.", contents)
        self.assertTrue(any("conv" in m["content"] for m in reply.request.messages
                            if m["role"] == "system"))             # permissions note
        self.assertEqual(reply.projection_version, projection.PROJECTION_VERSION)
