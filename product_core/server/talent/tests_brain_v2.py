"""Regressions from explicit V2 counterexamples, using real domain functions."""
from django.test import TestCase

from people.models import Person
from talent.answer import plan, retrieve


class RetrievalContractsTest(TestCase):
    def test_widen_keeps_exclusion_and_action_in_judge_request(self):
        import json
        from types import SimpleNamespace
        from talent.answer import judge
        original = plan.QueryPlan(information_need="SQL sans Python",
            search_queries=["SQL"], must_have=["SQL", "không Python"],
            next_steps=[{"shape": "action", "yeu_cau": "soạn lời mời"}])
        wider = plan.widen(original)
        seen = []
        def transport(messages, **kwargs):
            seen.append(json.loads(messages[-1]["content"]))
            return SimpleNamespace(text='{"ket_qua":[{"id":1,"thoa":false}]}')
        judge.judge(wider, [retrieve.Candidate(1, "Fixture")], complete_fn=transport)
        self.assertEqual(seen[0]["bat_buoc"], ["SQL", "không Python"])
        self.assertEqual(wider.next_steps, original.next_steps)
        self.assertEqual(original.search_queries, ["SQL"])

    def test_pinned_people_survive_a_smaller_pool_without_duplicates(self):
        people = [Person.objects.create(display_name=f"Fixture {n}") for n in range(4)]
        ids = [p.pk for p in people]
        found = retrieve.retrieve(plan.QueryPlan(), pinned_ids=ids + [ids[0]],
                                  search_queries=[], pool=2)
        self.assertEqual([c.person_id for c in found], ids)


class JudgeFailureTest(TestCase):
    def test_widen_reuses_same_dossiers_but_changed_evidence_is_read_again(self):
        import json
        from types import SimpleNamespace
        from unittest.mock import patch
        from people.models import Document
        from talent.answer import engine
        person = Person.objects.create(display_name="Reuse fixture")
        doc = Document.objects.create(person=person, sha256="reuse", parsed_text="Kỹ năng Java.")
        from talent.vector_index import index_person
        index_person(person.pk, with_embeddings=False)
        query = plan.QueryPlan(information_need="Ai có SQL?", search_queries=["Java"])
        for change in (False, True):
            calls = []
            def caller(messages, **kwargs):
                calls.append(json.loads(messages[-1]["content"])["ho_so"])
                if change and len(calls) == 1:
                    doc.parsed_text = "Kỹ năng Java và Python."
                    doc.save()
                    index_person(person.pk, with_embeddings=False)
                return SimpleNamespace(text='{"ket_qua":[{"id":1,"thoa":false}]}')
            with patch("talent.answer.cache.key_for", return_value=None):
                _, _, _, _, trace = engine._drain(engine._pipeline(query.information_need,
                    query_plan=query, complete_fn=caller))
            self.assertEqual(len(calls), 2 if change else 1)
            self.assertEqual(trace["pass2"]["judge_reused"], 0 if change else 1)

    def test_denied_and_required_experience_do_not_become_facts(self):
        from talent.answer import judge
        for text in ("Không có 5 năm kinh nghiệm.", "Yêu cầu 5 năm kinh nghiệm.",
                     "5 năm kinh nghiệm là điều chưa có."):
            candidate = retrieve.Candidate(1, "A", passages=[retrieve.Passage(1, 1, 0, text)])
            self.assertEqual(judge._attribute_status("kinh nghiệm", 5, candidate)["status"], "UNKNOWN")
        candidate = retrieve.Candidate(1, "A", passages=[retrieve.Passage(1, 1, 0, "Có 5 năm kinh nghiệm.")])
        self.assertEqual(judge._attribute_status("kinh nghiệm", 5, candidate)["status"], "FACT")
    def test_graduation_year_does_not_become_birth_year_for_sorting(self):
        import json
        from talent.answer import aggregate, judge
        candidates = [retrieve.Candidate(1, "A", passages=[retrieve.Passage(1, 1, 0,
            "Tốt nghiệp năm 2001. Có 5 năm kinh nghiệm.")]),
            retrieve.Candidate(2, "B", passages=[retrieve.Passage(2, 2, 0,
            "Sinh năm 1990. Có 8 năm kinh nghiệm.")])]
        payload = {"ket_qua": [{"id": i, "thoa": True, "do_tin": .9,
            "trich_dan": [{"doan": 1, "nguyen_van": c.passages[0].text}],
            "boc_duoc": {"năm sinh": year}}
            for i, c, year in zip((1, 2), candidates, (2001, 1990))]}
        query = plan.QueryPlan(sort_by={"key": "năm sinh", "dir": "desc"})
        rows = judge._parse_batch(json.dumps(payload), candidates, query)
        chosen, _, stats = aggregate.aggregate(query, rows)
        self.assertEqual(chosen[0].person_id, 2)
        self.assertEqual(rows[0].attribute_status["năm sinh"]["status"], "UNKNOWN")
        self.assertEqual(rows[1].fact_attributes()["năm sinh"], 1990)
        self.assertEqual(stats["missing_sort_value"], 1)

    def test_retry_only_missing_people_and_report_partial_failure(self):
        import json
        from types import SimpleNamespace
        from talent.answer import judge
        people = [retrieve.Candidate(n, f"Fixture {n}") for n in (1, 2, 3)]
        calls = []
        def partial(messages, **kwargs):
            dossiers = json.loads(messages[-1]["content"])["ho_so"]
            calls.append([d["ten"] for d in dossiers])
            rows = [{"id": 1, "thoa": False}] if len(calls) == 1 else []
            return SimpleNamespace(text=json.dumps({"ket_qua": rows}))
        result = judge.judge(plan.QueryPlan(), people, complete_fn=partial)
        self.assertEqual(calls, [["Fixture 1", "Fixture 2", "Fixture 3"], ["Fixture 2", "Fixture 3"]])
        self.assertEqual([j.person_id for j in result], [1])
        self.assertFalse(result.broken)
        self.assertTrue(result.incomplete)

    def test_adversarial_schema_and_coverage_contracts(self):
        from ai.brain_eval import contract_results
        for row in contract_results():
            self.assertTrue(row["passed"], row)


class FollowupReferenceTest(TestCase):
    def test_count_of_previous_set_does_not_take_whole_store_shortcut(self):
        import json
        from types import SimpleNamespace
        from ai.projection import Projection
        from talent.answer import engine
        people = [Person.objects.create(display_name=name) for name in ("A", "B", "Outside")]
        envelope = SimpleNamespace(projection=Projection(last_result={"items": [
            {"id": p.pk, "name": p.display_name} for p in people[:2]]}))
        called = []
        def caller(messages, **kwargs):
            payload = json.loads(messages[-1]["content"])
            called.extend(d["ten"] for d in payload["ho_so"])
            return SimpleNamespace(text=json.dumps({"ket_qua": [
                {"id": i, "thoa": False, "dieu_kien": [
                    {"so": c["so"], "ket_luan": "UNKNOWN", "trich_dan": []}
                    for c in payload["dieu_kien_dem"]]}
                for i in range(1, len(payload["ho_so"]) + 1)]}))
        query = plan.QueryPlan(shape="count", information_need="Trong số này bao nhiêu người biết SQL?",
                               search_queries=["SQL"])
        _, _, _, stats, trace = engine._drain(engine._pipeline(query.information_need,
            envelope=envelope, complete_fn=caller, query_plan=query))
        self.assertEqual(called, ["A", "B"])
        self.assertEqual(stats["scope_size"], 2)
        self.assertEqual(engine._corpus_facts(query, stats), "")
        self.assertNotIn("fast_path", trace)

    def test_action_loop_blocks_model_target_outside_explicit_selection(self):
        from types import SimpleNamespace
        from django.contrib.auth.models import User
        from ai.projection import Projection
        from ai.tests_agent import ScriptAdapter, _call, _msg
        from talent.answer.act import stream_action
        user = User.objects.create_superuser("action-audit", "", "test")
        people = [Person.objects.create(display_name=name) for name in ("A", "B")]
        envelope = SimpleNamespace(projection=Projection(last_result={"items": [
            {"id": p.pk, "name": p.display_name} for p in people]}))
        adapter = ScriptAdapter(
            _msg(None, [_call("read_allowed_evidence", {"person_id": people[0].pk})]),
            _msg(None, [_call("read_allowed_evidence", {"person_id": people[1].pk})]),
            _msg("Đã đọc đúng người thứ hai."))
        events = list(stream_action("Đọc hồ sơ người thứ hai", envelope=envelope,
                                    user=user, adapter=adapter))
        payload = events[-1]["payload"]
        self.assertEqual([p["person_id"] for p in payload["people"]], [people[1].pk])
        self.assertEqual([t["ok"] for t in payload["tool_trace"]], [False, True])
        empty = ScriptAdapter()
        events = list(stream_action("Đọc người thứ 9", envelope=envelope, user=user, adapter=empty))
        self.assertEqual(empty.calls, [])
        self.assertEqual(events[-1]["payload"]["people"], [])

    def test_explicit_reference_uses_display_order(self):
        from ai.projection import Projection
        from talent.answer.resolve import referenced_people
        projection = Projection(last_result={"items": [{"id": 3}, {"id": 1}, {"id": 2}]})
        for question, ids in [("Người thứ hai có bao nhiêu năm kinh nghiệm?", [1]),
                              ("So sánh hai người đầu", [3, 1]),
                              ("trong so nay ai lam ngan hang", [3, 1, 2]),
                              ("người thứ 9", [])]:
            self.assertEqual(referenced_people(projection, question), ids)

    def test_unrelated_query_does_not_inherit_positional_filter(self):
        from ai.projection import Projection
        from talent.answer.resolve import referenced_people
        self.assertIsNone(referenced_people(Projection(), "Tìm Data Analyst tại Hà Nội"))


class WholeStoreEvidenceTest(TestCase):
    def test_cut_stream_is_replaced_by_complete_fallback(self):
        from types import SimpleNamespace
        from talent.answer import engine
        def cut(*args, **kwargs):
            yield {"type": "answer", "text": "Đây là câu đang dở"}
            yield {"type": "done", "completion": SimpleNamespace(truncated=True)}
        events = list(engine.stream_answer("Tìm SQL", query_plan=plan.QueryPlan(
            information_need="SQL", search_queries=["SQL"]), stream_fn=cut))
        self.assertTrue(any(e["type"] == "revision" for e in events))
        self.assertNotIn("Đây là câu đang dở", events[-1]["result"].text)
        self.assertTrue(events[-1]["result"].trace["truncated_fallback"])

    def test_scalar_count_cannot_suppress_explicit_person_ranking(self):
        import json
        from types import SimpleNamespace
        result = plan.plan("Ai nhiều kinh nghiệm nhất toàn kho?", complete_fn=lambda *a, **k:
            SimpleNamespace(text=json.dumps({"shape": "count", "search_queries": ["kinh nghiệm"],
                "sort_by": {"key": "số năm kinh nghiệm", "dir": "desc"}, "limit": 1})))
        self.assertEqual(result.shape, "find_people")
        self.assertEqual(result.sort_by["dir"], "desc")

    def test_known_numeric_result_uses_model_composition_in_json_and_stream(self):
        import json
        from types import SimpleNamespace
        from talent.answer import engine
        Person.objects.create(display_name="Count fixture")
        calls = []
        def caller(messages, task="", **kwargs):
            calls.append(task)
            if task == "talent_answer_plan":
                return SimpleNamespace(text=json.dumps({"shape": "count", "search_queries": ["kho"],
                    "information_need": "Kho có bao nhiêu hồ sơ?"}))
            self.assertEqual(task, "talent_answer_compose")
            self.assertIn('"total_count": 1', messages[-1]["content"])
            return SimpleNamespace(text="Kho hiện có 1 hồ sơ ứng viên.",
                                   provider="greennode", model="test-model")
        result = engine.answer("Kho có bao nhiêu hồ sơ?", complete_fn=caller)
        self.assertEqual(result.text, "Kho hiện có 1 hồ sơ ứng viên.")
        query = plan.QueryPlan(shape="count", information_need="Kho có bao nhiêu hồ sơ?", search_queries=["kho"])
        def ai_stream(*args, **kwargs):
            yield {"type": "answer", "text": "Kho hiện có 1 hồ sơ ứng viên."}
            yield {"type": "done", "completion": SimpleNamespace(
                text="Kho hiện có 1 hồ sơ ứng viên.", provider="greennode",
                model="test-model", truncated=False)}
        events = list(engine.stream_answer(query.information_need, query_plan=query, stream_fn=ai_stream))
        self.assertEqual(events[-1]["result"].text, result.text)
        self.assertEqual(calls, ["talent_answer_plan", "talent_answer_compose"])

    def test_original_full_name_survives_model_dropping_identity_prefix(self):
        import json
        from types import SimpleNamespace
        from people.models import Document
        from talent.answer import engine
        person = Person.objects.create(display_name="Fixture Em")
        Document.objects.create(person=person, sha256="unknown-identity", parsed_text="Chưa có năm sinh.")
        other = Person.objects.create(display_name="Other Known")
        Document.objects.create(person=other, sha256="other-identity", parsed_text="Sinh năm 1990.")
        def caller(messages, task="", **kwargs):
            if task == "talent_answer_plan":
                return SimpleNamespace(text=json.dumps({"shape": "find_people", "information_need": "Em sinh năm bao nhiêu?",
                    "search_queries": ["Em"], "extract": ["năm sinh"]}))
            if task == "talent_answer_judge":
                self.assertEqual([d["ten"] for d in json.loads(messages[-1]["content"])["ho_so"]], ["Fixture Em"])
                return SimpleNamespace(text='{"ket_qua":[{"id":1,"thoa":false}]}')
            if task == "talent_answer_compose":
                return SimpleNamespace(text="Có hồ sơ Fixture Em trong kho, nhưng chưa có năm sinh [1].",
                                       provider="greennode", model="test-model")
            raise AssertionError(task)
        result = engine.answer("Fixture Em sinh năm bao nhiêu?", complete_fn=caller)
        self.assertIn("Có hồ sơ Fixture Em trong kho", result.text)
        self.assertNotIn("không có hồ sơ", result.text)
        from talent.answer.resolve import direct_named_people
        self.assertEqual(direct_named_people("Fixture Em sinh năm bao nhiêu?"), [person.pk])
        self.assertEqual(direct_named_people("Tìm người tương tự Fixture Em"), [])

    def test_oldest_corrects_inverted_model_sort_and_uses_actual_document(self):
        from people.models import Document
        from talent.answer import superlative
        young = Person.objects.create(display_name="Young")
        old = Person.objects.create(display_name="Old")
        Document.objects.create(person=young, sha256="young", parsed_text="Sinh năm 2000.")
        correct = Document.objects.create(person=old, sha256="old", parsed_text="Sinh năm 1985.")
        Document.objects.create(person=old, sha256="other", parsed_text="Tốt nghiệp năm 2006.")
        query = plan.QueryPlan(information_need="Ai lớn tuổi nhất toàn kho?", search_queries=["tuổi"],
            sort_by={"key": "năm sinh", "dir": "desc"}, limit=1)
        chosen, stats = superlative.run(query)
        self.assertEqual(chosen[0].person_id, old.pk)
        self.assertEqual(chosen[0].evidence[0]["document_id"], correct.pk)
        self.assertIn(chosen[0].evidence[0]["quote"], correct.best_text)
        self.assertTrue(stats["sorted_by"]["asc"])

    def test_calendar_years_and_denials_cannot_become_birth_or_experience(self):
        from people.models import Document
        from talent.answer import superlative
        for text in ("Tốt nghiệp năm 2000.", "Không sinh năm 1990."):
            self.assertEqual(superlative._value_from_cv("birth_year", text, 2026), (None, None))
        missing = Person.objects.create(display_name="Unknown")
        explicit = Person.objects.create(display_name="Explicit")
        Document.objects.create(person=missing, sha256="missing", parsed_text="Sinh năm 1980. Không có 40 năm kinh nghiệm.")
        Document.objects.create(person=explicit, sha256="explicit", parsed_text="Có 5 năm kinh nghiệm.")
        values, raw = {}, {}
        superlative._fill_years_from_cv([missing.pk, explicit.pk], values, raw)
        self.assertEqual(values, {explicit.pk: 5})
