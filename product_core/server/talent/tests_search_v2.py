# -*- coding: utf-8 -*-
import json

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts import roles

from people.models import Document, Person

from .models import (CandidateSetMember, ConstraintJudgementCache,
                     SearchProjection, TalentProfile)
from .search_v2 import (Constraint, RadarTurnPlan, build_dossier,
                        build_projection, cache_judgement, compile_projection_query,
                        create_candidate_set, deterministic_group, evidence_view,
                        enforce_cost_guard, estimate_judgement_cost, rank_rows,
                        process_candidate_set, split_sections)
from .answer.engine import _set_answer_coverage


class PlanCompilerTest(TestCase):
    def _person(self, name, title, location="Hà Nội", years=4):
        person = Person.objects.create(display_name=name, is_applicant=True,
                                       location=location)
        TalentProfile.objects.create(person=person, current_title=title,
                                     location=location, years_experience=years)
        build_projection(person.pk)
        return person

    def test_typed_ast_preserves_and_not_and_range(self):
        keep = self._person("Đủ", "Data Analyst", years=5)
        self._person("Sai nghề", "Python Developer", years=6)
        self._person("Thiếu năm", "Data Analyst", years=1)
        plan = RadarTurnPlan(must=[
            Constraint("title", "Data Analyst"),
            Constraint("location", "Hanoi", kind="geo"),
            Constraint("years_experience", 3, kind="range", op="gte"),
        ], exclude=[Constraint("company", "blocked")])
        query, explain = compile_projection_query(plan)
        self.assertEqual(list(query.values_list("person_id", flat=True)), [keep.pk])
        self.assertTrue(explain["deterministic_complete"])
        self.assertEqual(len(explain["applied"]), 4)

    def test_candidate_set_has_no_hidden_sixty_cap(self):
        for index in range(75):
            self._person(f"P{index}", "Data Analyst")
        run = create_candidate_set(RadarTurnPlan(
            must=[Constraint("title", "Data Analyst")]))
        self.assertEqual(run.candidate_total, 75)
        self.assertEqual(run.not_read, 75)
        self.assertEqual(CandidateSetMember.objects.filter(run=run).count(), 75)
        self.assertEqual(list(run.members.order_by("ordinal").values_list(
            "ordinal", flat=True)[:3]), [1, 2, 3])
        finished = process_candidate_set(run.pk, batch_size=13)
        self.assertEqual(finished.state, "done")
        self.assertEqual(finished.judged, 75)
        self.assertEqual(finished.not_read, 0)
        self.assertTrue(finished.complete)


class AnswerCoverageContractTest(TestCase):
    def test_sql_aggregate_is_complete_without_claiming_deep_read(self):
        trace = {}
        value = _set_answer_coverage(trace, {"judged": 0}, candidate_total=120,
                                     method="sql_aggregate", complete=True)
        self.assertEqual(value["evaluated"], 120)
        self.assertEqual(value["judged"], 0)
        self.assertEqual(value["not_read"], 0)
        self.assertTrue(value["complete"])

    def test_partial_deep_read_keeps_unread_visible(self):
        value = _set_answer_coverage({}, {"judged": 55, "unknown": 3},
                                     candidate_total=120)
        self.assertEqual(value["not_read"], 65)
        self.assertFalse(value["complete"])


class DossierEvidenceTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(display_name="An", is_applicant=True)
        TalentProfile.objects.create(person=self.person, current_title="Data Analyst",
                                     skills=["SQL", "Python"])
        text = ("TÓM TẮT\nData analyst\n\nKỸ NĂNG\nSQL\n\nKINH NGHIỆM\n"
                + "A" * 3000 + "\nPython được dùng trong dự án cuối CV")
        Document.objects.create(person=self.person, sha256="a" * 64, parsed_text=text)

    def test_section_split_preserves_full_text_and_offsets(self):
        text = self.person.documents.first().best_text
        sections = split_sections(text)
        self.assertEqual("".join(row["text"] for row in sections), text)
        self.assertIn("Python được dùng trong dự án cuối CV", sections[-1]["text"])

    def test_evidence_reads_relevant_late_section_without_700_char_cut(self):
        dossier = build_dossier(self.person.pk)
        view = evidence_view(dossier, [Constraint("skills", "Python")], max_chars=10000)
        selected = "\n".join(row["text"] for row in view["evidence"])
        self.assertIn("Python được dùng trong dự án cuối CV", selected)
        self.assertGreater(view["selected_chars"], 700)
        self.assertTrue(all(row["evidence_id"] for row in view["evidence"]))


class JudgementContractTest(TestCase):
    def setUp(self):
        self.person = Person.objects.create(display_name="Cache", is_applicant=True)
        TalentProfile.objects.create(person=self.person)
        self.dossier = build_dossier(self.person.pk)
        self.constraint = Constraint("skills", "Python")

    def test_unknown_is_not_not_matched_and_is_not_cached_complete(self):
        judgement = {"status": "unknown", "confidence": .9, "evidence_ids": []}
        self.assertEqual(deterministic_group([judgement]), "UNKNOWN")
        self.assertIsNone(cache_judgement(
            self.dossier, self.constraint, judgement, scope_token="scope"))
        self.assertFalse(ConstraintJudgementCache.objects.exists())

    def test_complete_cache_is_scope_and_fingerprint_bound(self):
        judgement = {"status": "supported", "confidence": .9,
                     "evidence_ids": ["profile:1"]}
        row = cache_judgement(self.dossier, self.constraint, judgement,
                              scope_token="scope-a", model="m1", prompt_version="p1")
        self.assertTrue(row.complete)
        self.assertEqual(row.scope_token, "scope-a")
        self.assertEqual(row.dossier_fingerprint, self.dossier.fingerprint)

    def test_rank_is_stable_and_ignores_demographics(self):
        rows = [
            {"person_id": 2, "group": "HIGH", "confidence": .8,
             "age": 22, "gender": "female"},
            {"person_id": 1, "group": "HIGH", "confidence": .8,
             "age": 55, "gender": "male"},
            {"person_id": 3, "group": "UNKNOWN", "confidence": 1},
        ]
        self.assertEqual([row["person_id"] for row in rank_rows(rows)], [1, 2, 3])

    def test_exhaustive_cost_over_limit_requires_confirmation(self):
        estimate = estimate_judgement_cost(candidates=10000)
        with self.assertRaises(PermissionError):
            enforce_cost_guard(estimate, token_limit=1_000_000)
        allowed = enforce_cost_guard(estimate, token_limit=1_000_000, confirmed=True)
        self.assertTrue(allowed["allowed"])


class CandidateSetApiTest(TestCase):
    def setUp(self):
        roles.ensure_groups()
        self.user = User.objects.create_user("search-owner", password="x")
        self.user.groups.add(self.user.groups.model.objects.get(name=roles.RECRUITER))
        self.other = User.objects.create_user("search-other", password="x")
        self.other.groups.add(self.other.groups.model.objects.get(name=roles.RECRUITER))
        self.client.force_login(self.user)
        for index in range(2):
            person = Person.objects.create(display_name=f"API {index}", is_applicant=True)
            TalentProfile.objects.create(person=person, current_title="Data Analyst")
            build_projection(person.pk)
        self.plan = {"domain": "TALENT", "query_type": "list", "must": [
            {"field": "title", "value": "Data Analyst"}
        ]}

    def _post(self, path, payload):
        return self.client.post(path, json.dumps(payload), content_type="application/json")

    def _patch(self, path, payload):
        return self.client.patch(path, json.dumps(payload), content_type="application/json")

    def test_estimate_is_read_only_and_exact(self):
        response = self._post("/api/v1/talent/candidate-sets/estimate/",
                              {"plan": self.plan})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["candidate_total"], 2)
        self.assertFalse(CandidateSetMember.objects.exists())

    @override_settings(SEARCH_V2_T3_TOKEN_LIMIT=1)
    def test_create_requires_cost_confirmation_then_returns_progress(self):
        blocked = self._post("/api/v1/talent/candidate-sets/", {"plan": self.plan})
        self.assertEqual(blocked.status_code, 409)
        self.assertTrue(blocked.json()["requires_confirmation"])
        self.assertFalse(CandidateSetMember.objects.exists())

        created = self._post("/api/v1/talent/candidate-sets/",
                             {"plan": self.plan, "confirmed": True})
        self.assertEqual(created.status_code, 201)
        body = created.json()
        self.assertEqual(body["candidate_total"], 2)
        self.assertEqual(body["state"], "running")
        self.assertEqual(body["cursor"], 2)
        resumed = self._patch(f"/api/v1/talent/candidate-sets/{body['id']}/",
                              {"action": "resume"})
        self.assertEqual(resumed.status_code, 200)
        self.assertEqual(resumed.json()["state"], "done")
        self.assertEqual(resumed.json()["judged"], 2)
        detail = self.client.get(f"/api/v1/talent/candidate-sets/{body['id']}/")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["id"], body["id"])

    def test_run_is_owner_scoped_and_cancel_is_idempotent(self):
        created = self._post("/api/v1/talent/candidate-sets/",
                             {"plan": self.plan, "confirmed": True})
        run_id = created.json()["id"]
        cancelled = self._patch(f"/api/v1/talent/candidate-sets/{run_id}/",
                                {"action": "cancel"})
        self.assertEqual(cancelled.status_code, 200)
        self.assertTrue(cancelled.json()["cancel_requested"])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(
            f"/api/v1/talent/candidate-sets/{run_id}/").status_code, 404)
