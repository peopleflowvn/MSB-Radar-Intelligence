# -*- coding: utf-8 -*-
"""Agent core trên LangGraph — ngang hàng vòng lặp tay (Master Plan §23.1.1).

Chạy lại các kịch bản của `tests_agent.py` qua `graph_agent` và đối chiếu kết quả.
"""
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings

from accounts import roles
from people.models import Person
from talent.models import TalentProfile

from . import agent, agent_select, graph_agent
from .adapter import ModelResponse


def _msg(content=None, tool_calls=None):
    m = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return {"choices": [{"message": m}]}


def _call(name, args, cid="c1"):
    return {"id": cid, "type": "function",
            "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptAdapter:
    def __init__(self, *payloads):
        self._payloads = list(payloads)
        self.calls = []

    def complete(self, request):
        self.calls.append(request)
        raw = self._payloads.pop(0) if self._payloads else _msg("hết kịch bản")
        text = ((raw.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return ModelResponse(text=text, provider="fake", model="brain-x", raw=raw)


class GraphAgentParityTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles.ensure_groups()

    def setUp(self):
        self.user = User.objects.create_user("rec", password="x")
        self.user.groups.add(Group.objects.get(name=roles.RECRUITER))
        self.p1 = Person.objects.create(display_name="Ứng viên A")
        self.p2 = Person.objects.create(display_name="Ứng viên B")
        TalentProfile.objects.create(person=self.p1, current_title="Data Analyst",
                                     years_experience=4, skills=["SQL"])
        TalentProfile.objects.create(person=self.p2, current_title="BA",
                                     years_experience=2, skills=["Excel"])

    def test_no_tool_needed_returns_first_answer(self):
        ad = ScriptAdapter(_msg("Chào anh/chị, Radar đây."))
        res = graph_agent.run_turn("Radar là gì?", surface="talent",
                                   user=self.user, adapter=ad)
        self.assertEqual(res.text, "Chào anh/chị, Radar đây.")
        self.assertFalse(res.used_tools)
        self.assertEqual(len(ad.calls), 1)

    def test_executes_tool_then_answers(self):
        ad = ScriptAdapter(
            _msg(None, [_call("compare_candidates",
                              {"person_ids": [self.p1.pk, self.p2.pk]})]),
            _msg("A 4 năm, B 2 năm."))
        res = graph_agent.run_turn("so sánh A và B", surface="talent",
                                   user=self.user, adapter=ad)
        self.assertEqual(res.text, "A 4 năm, B 2 năm.")
        self.assertEqual([t.name for t in res.tool_trace], ["compare_candidates"])
        self.assertTrue(res.tool_trace[0].ok)
        self.assertEqual(ad.calls[1].messages[-1]["role"], "tool")
        self.assertIsNotNone(res.last_request)

    def test_tool_error_fed_back(self):
        ad = ScriptAdapter(
            _msg(None, [_call("compare_candidates", {"person_ids": [9999, 8888]})]),
            _msg("Không thấy hai hồ sơ."))
        res = graph_agent.run_turn("so sánh", surface="talent",
                                   user=self.user, adapter=ad)
        self.assertFalse(res.tool_trace[0].ok)
        self.assertEqual(res.text, "Không thấy hai hồ sơ.")

    @override_settings(ASSISTANT_TOOL_MAX_STEPS=2)
    def test_max_steps_forces_final_answer(self):
        loop = _msg(None, [_call("canonical_lookup",
                                 {"namespace": "skill", "value": "SQL"})])
        ad = ScriptAdapter(loop, loop, loop, _msg("Tổng hợp cuối."))
        res = graph_agent.run_turn("x", surface="talent", user=self.user, adapter=ad)
        self.assertTrue(res.tool_trace)              # đã gọi tool vài lần
        self.assertTrue(res.text)                    # vẫn có câu trả lời (force final)

    def test_iter_turn_streams_tool_then_answer_then_done(self):
        ad = ScriptAdapter(
            _msg(None, [_call("canonical_lookup",
                              {"namespace": "location", "value": "TP.HCM"})]),
            _msg("TP.HCM là VN-SG."))
        kinds = [c["type"] for c in graph_agent.iter_turn(
            "chuẩn hoá TP.HCM", surface="talent", user=self.user, adapter=ad)]
        self.assertEqual(kinds[0], "tool")
        self.assertIn("answer", kinds)
        self.assertEqual(kinds[-1], "done")

    def test_no_tools_available_delegates_to_plain(self):
        plain = User.objects.create_user("plain", password="x")   # không quyền talent
        ad = ScriptAdapter(_msg("Trả lời thường."))
        res = graph_agent.run_turn("câu hỏi", surface="talent", user=plain, adapter=ad)
        self.assertEqual(res.text, "Trả lời thường.")
        self.assertFalse(res.used_tools)

    def test_cancel_stops_stream(self):
        ad = ScriptAdapter(
            _msg(None, [_call("canonical_lookup", {"namespace": "skill", "value": "SQL"})]),
            _msg("không nên tới đây"))
        flags = {"n": 0}

        def cancel():
            flags["n"] += 1
            return flags["n"] > 1

        res = graph_agent.run_turn("x", surface="talent", user=self.user,
                                   adapter=ad, cancel=cancel)
        self.assertTrue(res.cancelled)


class AgentSelectTest(TestCase):
    def test_default_is_handwritten_agent(self):
        self.assertIs(agent_select.get_runner(), agent)

    @override_settings(ASSISTANT_GRAPH=True)
    def test_flag_switches_to_graph(self):
        self.assertIs(agent_select.get_runner(), graph_agent)
