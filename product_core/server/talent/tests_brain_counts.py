"""Count scope must survive retrieval limits, missing evidence and model failure."""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from people.models import Document, Person
from talent.answer import compose, corpus, engine, judge, plan
from talent.models import TalentProfile
from talent.vector_index import index_person


class CountScopeTest(TestCase):
    def setUp(self):
        self.people = []
        for name, body in (("An", "Có kỹ năng SQL và Python."),
                           ("Bình", "Có kỹ năng SQL. Không biết Python."),
                           ("Chi", "Có kỹ năng SQL; chưa cung cấp thông tin Python.")):
            person = Person.objects.create(display_name=name)
            Document.objects.create(person=person, sha256=name, parsed_text=body)
            index_person(person.pk, with_embeddings=False)
            self.people.append(person)
        Person.objects.create(display_name="Chưa có CV")

    def caller(self, query, selected, *, fail=False):
        def call(messages, **kwargs):
            if kwargs["task"] == plan.TASK:
                return SimpleNamespace(text=json.dumps(query.as_dict()))
            if kwargs["task"] == compose.TASK:
                count = json.loads(messages[-1]["content"])["so_lieu_chinh_xac"]["count"]
                if count["matched"] is None:
                    text = "Bước đọc hồ sơ bị lỗi nên chưa xác định được số người phù hợp."
                else:
                    text = (f"Có {count['matched']} hồ sơ phù hợp trong phần đã đọc; "
                            "số toàn kho chưa xác định vì còn hồ sơ thiếu bằng chứng.")
                return SimpleNamespace(text=text, provider="greennode", model="test-model")
            self.assertEqual(kwargs["task"], judge.TASK, "Count prose must use measured integers")
            self.assertEqual(json.loads(messages[-1]["content"])["bat_buoc"], query.must_have)
            if fail:
                raise RuntimeError("simulated provider failure")
            payload = json.loads(messages[-1]["content"])
            by_name = {p.display_name: p for p in self.people}
            rows = []
            for dossier in payload["ho_so"]:
                person = by_name[dossier["ten"]]
                quotes = [{"doan": 1, "nguyen_van": dossier["doan"][0]["text"]}]
                rows.append({"id": dossier["id"], "thoa": person.pk in selected, "do_tin": .9,
                    "trich_dan": quotes if person.pk in selected else [],
                    "dieu_kien": [{"so": c["so"], "ket_luan": "SUPPORTED" if person.pk in selected else "UNKNOWN",
                                   "trich_dan": quotes if person.pk in selected else []}
                                  for c in payload["dieu_kien_dem"]]})
            return SimpleNamespace(text=json.dumps({"ket_qua": rows}))
        return call

    def test_and_not_counts_are_evaluations_with_coverage_not_keyword_totals(self):
        for condition, selected in ((["SQL", "Python"], {self.people[0].pk}),
                                    (["SQL", "không biết Python"], {self.people[1].pk})):
            query = plan.QueryPlan(shape="count", information_need="Bao nhiêu ứng viên biết SQL và " + condition[1] + "?",
                                   must_have=condition, search_queries=["SQL", "Python"], limit=1)
            with self.subTest(condition=condition), patch("talent.answer.cache.key_for", return_value=None):
                result = engine.answer(query.information_need, complete_fn=self.caller(query, selected))
            self.assertEqual({p["person_id"] for p in result.people}, selected)
            count = result.trace["count"]
            self.assertEqual((count["matched"], count["reviewed"], count["scope_total"]), (1, 3, 4))
            self.assertFalse(count["exact"])
            self.assertIn("chưa xác định", result.text)
            self.assertIn("1 hồ sơ", result.text)

    def test_count_is_not_display_limit(self):
        query = plan.QueryPlan(shape="count", information_need="Bao nhiêu người biết SQL?",
                               must_have=["SQL"], search_queries=["SQL"], limit=1)
        with patch("talent.answer.cache.key_for", return_value=None):
            result = engine.answer(query.information_need,
                complete_fn=self.caller(query, {p.pk for p in self.people}))
        self.assertEqual(len(result.people), 1)
        self.assertEqual(result.trace["count"]["matched"], 3)
        self.assertIn("3 hồ sơ", result.text)

    def test_failed_reader_does_not_publish_zero_matches(self):
        query = plan.QueryPlan(shape="count", information_need="Bao nhiêu người biết SQL?",
                               must_have=["SQL"], search_queries=["SQL"])
        with patch("talent.answer.cache.key_for", return_value=None):
            result = engine.answer(query.information_need, complete_fn=self.caller(query, set(), fail=True))
        self.assertIsNone(result.trace["count"]["matched"])
        self.assertIn("lỗi", result.text)
        self.assertNotIn("0 hồ sơ phù hợp", result.text)

    def test_count_stream_uses_ai_prose_and_keeps_next_steps(self):
        query = plan.QueryPlan(shape="count", information_need="Bao nhiêu người biết SQL?",
                               must_have=["SQL"], search_queries=["SQL"],
                               next_steps=[{"shape": "action", "yeu_cau": "so sánh hai người đầu"}])
        with patch("talent.answer.cache.key_for", return_value=None), \
             patch("talent.answer.engine._run_next_steps", return_value=iter([
                 {"type": "step_result", "text": "Kết quả bước sau."}])) as steps:
            def stream_writer(messages, **kwargs):
                yield {"type": "answer", "text": "AI xác nhận có 1 hồ sơ phù hợp."}
                yield {"type": "done", "completion": SimpleNamespace(
                    text="AI xác nhận có 1 hồ sơ phù hợp.", provider="greennode",
                    model="test-model", truncated=False)}
            events = list(engine.stream_answer(query.information_need, query_plan=query,
                complete_fn=self.caller(query, {self.people[0].pk}),
                stream_fn=stream_writer))
        result = next(e["result"] for e in events if e["type"] == "done")
        self.assertIn("1 hồ sơ", result.text)
        self.assertIn("Kết quả bước sau.", result.text)
        self.assertEqual(steps.call_args.args[1][0]["person_id"], self.people[0].pk)

    def test_conditional_count_never_receives_keyword_population_estimate(self):
        with patch("talent.answer.corpus.fts_estimate") as estimate:
            self.assertEqual(engine._corpus_facts(plan.QueryPlan(shape="count", search_queries=["SQL Python"])), "")
        estimate.assert_not_called()

    def test_missing_duplicate_or_partially_fabricated_condition_quote_is_unknown(self):
        from talent.answer.retrieve import Candidate, Passage
        candidate = Candidate(1, "An", passages=[Passage(1, 1, 0, "Có kỹ năng SQL. Không biết Python.")])
        query = plan.QueryPlan(shape="count", information_need="Đếm SQL không Python", must_have=["SQL", "không biết Python"])
        base = {"id": 1, "thoa": True, "do_tin": .9,
                "trich_dan": [{"doan": 1, "nguyen_van": "Có kỹ năng SQL."}]}
        valid = {"so": 1, "ket_luan": "SUPPORTED",
                 "trich_dan": [{"doan": 1, "nguyen_van": candidate.passages[0].text}]}
        for rows in ([], [valid], [valid, valid]):
            self.assertEqual(judge._parse_batch(json.dumps({"ket_qua": [{**base, "dieu_kien": rows}]}), [candidate], query), [])
        for rows in ([valid, {
                "so": 2, "ket_luan": "SUPPORTED", "trich_dan": [{"doan": 1,
                    "nguyen_van": "Có kỹ năng SQL. Không bao giờ dùng Python trong cả sự nghiệp."}]}],):
            with self.subTest(rows=rows):
                result = judge._parse_batch(json.dumps({"ket_qua": [{**base, "dieu_kien": rows}]}), [candidate], query)[0]
                self.assertFalse(result.relevant)
                self.assertIn("UNKNOWN", [c["status"] for c in result.criteria])

    def test_true_verdict_cannot_override_unknown_or_contradicted_condition(self):
        from talent.answer.retrieve import Candidate, Passage
        candidate = Candidate(1, "Bình", passages=[Passage(1, 1, 0, "Có kỹ năng SQL và Excel.")])
        query = plan.QueryPlan(shape="count", information_need="Đếm SQL không Python")
        for status in ("UNKNOWN", "CONTRADICTED"):
            payload = {"ket_qua": [{"id": 1, "thoa": True, "do_tin": 1,
                "dieu_kien": [{"so": 1, "ket_luan": status, "trich_dan": [{"doan": 1,
                    "nguyen_van": candidate.passages[0].text}]}]}]}
            self.assertFalse(judge._parse_batch(json.dumps(payload), [candidate], query)[0].relevant)

    def test_supported_label_and_real_quote_cannot_prove_absence_from_silence(self):
        from talent.answer.retrieve import Candidate, Passage
        query = plan.QueryPlan(shape="count", information_need="Đếm SQL không Python", must_have=["không biết Python"])
        for text in ("Kỹ năng SQL và Excel.", "Chưa có thông tin về Python.", "Python is not mentioned."):
            candidate = Candidate(1, "Bình", passages=[Passage(1, 1, 0, text)])
            payload = {"ket_qua": [{"id": 1, "thoa": True, "do_tin": 1,
                "dieu_kien": [{"so": 1, "ket_luan": "SUPPORTED",
                              "trich_dan": [{"doan": 1, "nguyen_van": text}]}]}]}
            result = judge._parse_batch(json.dumps(payload), [candidate], query)[0]
            self.assertFalse(result.relevant)
            self.assertEqual(result.criteria[0]["status"], "UNKNOWN")
        self.assertFalse(judge._requires_explicit_absence("không dưới 5 năm kinh nghiệm"))

    def test_scoped_count_excludes_other_people_and_stale_non_applicants(self):
        query = plan.QueryPlan(shape="count", information_need="Trong số này bao nhiêu người biết SQL?",
                               must_have=["SQL"], search_queries=["SQL"])
        self.people[2].is_applicant = False
        self.people[2].save(update_fields=["is_applicant"])
        selected = [self.people[1].pk, self.people[2].pk]
        with patch("talent.answer.resolve.referenced_people", return_value=selected):
            result = engine.answer(query.information_need, complete_fn=self.caller(query, set(selected)))
        self.assertEqual([p["person_id"] for p in result.people], [self.people[1].pk])
        self.assertEqual(result.trace["count"]["scope_total"], 1)
        self.assertEqual(result.trace["count"]["scope"], "previous_result")
        self.assertIn("phần đã đọc", result.text)

    def test_resolved_group_names_are_not_conjoined_membership_conditions(self):
        query = plan.QueryPlan(shape="count", information_need="Trong số An và Bình, bao nhiêu người biết SQL?",
                               must_have=["An", "Bình", "SQL"], search_queries=["SQL"])
        selected = [p.pk for p in self.people[:2]]
        with patch("talent.answer.resolve.referenced_people", return_value=selected), \
             patch("talent.answer.judge.judge", return_value=judge.JudgeReport()) as reader:
            _, _, _, _, trace = engine._drain(engine._pipeline(query.information_need, query_plan=query))
        self.assertEqual(reader.call_args.args[0].must_have, ["SQL"])
        self.assertEqual(query.must_have, ["An", "Bình", "SQL"])
        self.assertEqual(trace["count_scope_names_removed"], 2)


class CorpusPopulationTest(TestCase):
    def test_coverage_counts_applicants_including_missing_profiles(self):
        applicant = Person.objects.create(display_name="Ứng viên")
        Person.objects.create(display_name="Chưa có profile")
        reference = Person.objects.create(display_name="Người tham chiếu", is_applicant=False)
        for person in (applicant, reference):
            TalentProfile.objects.create(person=person, skills=["SQL", "SQL"], years_experience=10)
            Document.objects.create(person=person, sha256=person.display_name, parsed_text="Kỹ năng SQL.")
            index_person(person.pk, with_embeddings=False)
        data = corpus.overview()
        self.assertEqual(data["quy_mo"]["tong_ho_so"], 2)
        self.assertEqual(data["quy_mo"]["co_file_cv"], 1)
        self.assertLessEqual(data["quy_mo"]["da_lap_chi_muc"], 1)
        self.assertEqual(data["ky_nang"]["top"], [{"value": "SQL", "count": 1}])
        self.assertEqual(data["ky_nang"]["coverage"], .5)
        self.assertEqual(data["kinh_nghiem"]["tong"], 2)
        self.assertEqual(data["kinh_nghiem"]["phan_bo"][-1], {"label": "từ 10 năm", "count": 1})
