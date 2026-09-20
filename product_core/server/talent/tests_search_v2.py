# -*- coding: utf-8 -*-
import json
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from accounts import roles

from people.models import Document, Person

from .models import (CandidateSetMember, ConstraintJudgementCache,
                     SearchProjection, TalentProfile)
from .search_v2 import (EVIDENCE_CHAR_BUDGET, BranchHit, Constraint, RadarTurnPlan,
                        ablation, build_dossier, build_projection, cache_judgement,
                        compile_projection_query, create_candidate_set,
                        deterministic_group, enforce_cost_guard,
                        estimate_judgement_cost, evidence_view, from_legacy_plan,
                        lexical_branch, process_candidate_set, rank_rows,
                        recall_terms, split_sections, tsquery, union_branches)
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

    def test_nested_boolean_ast_preserves_and_or_not(self):
        data_hn = self._person("Data HN", "Data Analyst", location="Hà Nội")
        data_hcm = self._person("Data HCM", "Data Analyst", location="Hồ Chí Minh")
        self._person("Blocked", "Data Analyst", location="Đà Nẵng")
        self._person("Developer", "Python Developer", location="Hà Nội")
        plan = RadarTurnPlan(where={"op": "and", "children": [
            {"field": "title", "value": "Data Analyst"},
            {"op": "or", "children": [
                {"field": "location", "value": "Hanoi", "kind": "geo"},
                {"field": "location", "value": "ho chi minh", "kind": "geo"},
            ]},
            {"op": "not", "children": [
                {"field": "location", "value": "da nang", "kind": "geo"},
            ]},
        ]})
        query, explain = compile_projection_query(plan)
        self.assertEqual(set(query.values_list("person_id", flat=True)),
                         {data_hn.pk, data_hcm.pk})
        self.assertEqual(len(explain["applied"]), 4)
        self.assertTrue(explain["deterministic_complete"])
        self.assertEqual(RadarTurnPlan.from_dict(plan.as_dict()).as_dict(), plan.as_dict())

    def test_boolean_ast_rejects_invalid_shape_and_fails_closed_on_unknown_field(self):
        with self.assertRaises(ValueError):
            RadarTurnPlan(where={"op": "not", "children": [
                {"field": "title", "value": "A"},
                {"field": "title", "value": "B"},
            ]})
        self._person("Keep out", "Data Analyst")
        plan = RadarTurnPlan(where={"field": "unindexed", "value": "anything"})
        query, explain = compile_projection_query(plan)
        self.assertFalse(query.exists())
        self.assertFalse(explain["deterministic_complete"])
        self.assertEqual(len(explain["unresolved"]), 1)

    def test_semantic_hard_and_preference_do_not_filter_membership(self):
        first = self._person("First", "Data Analyst")
        second = self._person("Second", "Python Developer")
        plan = RadarTurnPlan(
            must=[Constraint("search_text", "chuyển đổi số tương tự",
                             classification="HARD_SEMANTIC")],
            prefer=[Constraint("skills", "Python", classification="PREFERENCE")])
        query, explain = compile_projection_query(plan)
        self.assertEqual(set(query.values_list("person_id", flat=True)),
                         {first.pk, second.pk})
        self.assertEqual(explain["semantic_requirements"],
                         [plan.must[0].constraint_id])
        self.assertEqual(explain["preference_signals"],
                         [plan.prefer[0].constraint_id])
        self.assertTrue(explain["retrieval_branches_required"])
        run = create_candidate_set(plan)
        self.assertTrue(run.retrieval_degraded)
        self.assertFalse(run.explain["branches"]["field_fts"]["ran"])

    def test_legacy_free_text_is_semantic_not_exact_contains_filter(self):
        plan = from_legacy_plan(SimpleNamespace(
            shape="find_people", must_have=["kinh nghiệm tương đương"],
            should_have=["ưu tiên ngân hàng"], search_queries=["banking transformation"]))
        self.assertEqual(plan.must[0].classification, "HARD_SEMANTIC")
        self.assertEqual(plan.prefer[0].classification, "PREFERENCE")
        query, explain = compile_projection_query(plan)
        self.assertEqual(query.count(), SearchProjection.objects.count())
        self.assertTrue(explain["retrieval_branches_required"])

    def test_boolean_where_rejects_semantic_constraint(self):
        with self.assertRaises(ValueError):
            RadarTurnPlan(where={
                "field": "search_text", "value": "lãnh đạo chuyển đổi",
                "classification": "HARD_SEMANTIC",
            })


class BranchContractTest(TestCase):
    """P1-03A/C/E: hợp đồng nhánh, tsquery và union giữ provenance."""

    def test_tsquery_keeps_intersection_for_must_and_union_for_recall(self):
        self.assertEqual(tsquery("Data Analyst"), "data & analyst")
        self.assertEqual(tsquery("Data Analyst", mode="or"), "data | analyst")

    def test_tsquery_strips_operator_injection(self):
        self.assertEqual(tsquery("python & !java | (x)"), "python & java")
        self.assertEqual(tsquery("  "), "")

    def test_recall_terms_take_semantic_and_preference_only(self):
        plan = RadarTurnPlan(
            must=[Constraint("title", "Data Analyst"),
                  Constraint("search_text", "chuyển đổi số",
                             classification="HARD_SEMANTIC")],
            prefer=[Constraint("search_text", "ngân hàng",
                               classification="PREFERENCE")],
            semantic_concepts=["banking transformation"])
        self.assertEqual(recall_terms(plan),
                         ["chuyển đổi số", "ngân hàng", "banking transformation"])

    def test_union_keeps_every_branch_hit_with_provenance(self):
        rows = union_branches(
            [BranchHit("structured", 7), BranchHit("structured", 9)],
            [BranchHit("field_fts", 9, rank=1, raw_score=.9),
             BranchHit("field_fts", 11, rank=2, raw_score=.4)])
        self.assertEqual([row["person_id"] for row in rows], [7, 9, 11])
        self.assertEqual(set(rows[1]["provenance"]), {"structured", "field_fts"})
        self.assertEqual(rows[2]["provenance"]["field_fts"]["rank"], 2)

    def test_lexical_branch_reports_why_it_did_not_run(self):
        plan = RadarTurnPlan(must=[Constraint("search_text", "chuyển đổi số",
                                              classification="HARD_SEMANTIC")])
        queryset, _explain = compile_projection_query(plan)
        hits, state = lexical_branch(queryset, plan, limit=10)
        self.assertIsNone(hits)
        # Trên SQLite nhánh này không dùng được; im lặng coi như đã tìm đủ mới là lỗi.
        self.assertEqual(state["reason"], "vendor_unsupported")
        self.assertFalse(state["ran"])

    def test_ablation_scores_each_config_separately(self):
        person = Person.objects.create(display_name="Ablation", is_applicant=True)
        TalentProfile.objects.create(person=person, current_title="Data Analyst")
        build_projection(person.pk)
        report = ablation(RadarTurnPlan(must=[Constraint("title", "Data Analyst")]))
        self.assertEqual(report["configs"]["structured"]["ids"], [person.pk])
        self.assertFalse(report["configs"]["field_fts"]["branches"]["field_fts"]["ran"])


class SilverDatasetTest(TestCase):
    """Bộ silver phải chạy được và không được tự nhận là gold."""

    def _dataset(self):
        from talent.management.commands.search_ablation import (DEFAULT_DATASET,
                                                                _dataset_path,
                                                                load_cases)
        return load_cases(_dataset_path(DEFAULT_DATASET))

    def test_every_case_compiles_and_semantic_cases_await_labels(self):
        cases = self._dataset()
        self.assertGreaterEqual(len(cases), 20)
        for case in cases:
            plan = RadarTurnPlan.from_dict(case["plan"])
            compile_projection_query(plan)
            if case["truth"] == "labels":
                self.assertEqual(case["labels"]["status"], "needs_review")

    def test_ablation_command_skips_unlabelled_semantic_cases(self):
        from io import StringIO

        from django.core.management import call_command

        person = Person.objects.create(display_name="Silver", is_applicant=True,
                                       location="Hà Nội")
        TalentProfile.objects.create(person=person, current_title="Data Analyst",
                                     location="Hà Nội", years_experience=5)
        build_projection(person.pk)
        out = StringIO()
        call_command("search_ablation", stdout=out)
        summary = json.loads(out.getvalue().split("\n{")[0] if False
                             else out.getvalue()[:out.getvalue().rindex("}") + 1])
        self.assertGreater(summary["skipped_needs_review"], 0)
        # Không có PostgreSQL thì nhánh lexical không đóng góp gì, và báo cáo
        # phải nói ra điều đó chứ không mượn điểm của nhánh structured.
        self.assertEqual(summary["per_config"]["structured"]["mean_recall"], 1.0)
        self.assertEqual(summary["per_config"]["field_fts"]["mean_recall"], 0.0)


class VerificationTruthTest(TestCase):
    """T2 chỉ được nói "đã xác minh" khi thật sự đối chiếu dữ liệu."""

    def _person(self, name, title, years=4):
        person = Person.objects.create(display_name=name, is_applicant=True)
        TalentProfile.objects.create(person=person, current_title=title,
                                     years_experience=years)
        build_projection(person.pk)
        return person

    def test_semantic_plan_leaves_members_unknown_not_supported(self):
        self._person("A", "Data Analyst")
        self._person("B", "Python Developer")
        run = create_candidate_set(RadarTurnPlan(must=[
            Constraint("search_text", "đã dẫn dắt chuyển đổi số",
                       classification="HARD_SEMANTIC")]))
        finished = process_candidate_set(run.pk)
        self.assertEqual(finished.judged, 0)
        self.assertEqual(finished.unknown, 2)
        self.assertFalse(finished.complete)
        self.assertFalse(finished.explain["completeness"]["branches_complete"])
        self.assertFalse(finished.explain["completeness"]["verification_complete"])

    def test_member_no_longer_matching_is_contradicted_after_reverification(self):
        keep = self._person("Khớp", "Data Analyst")
        drift = self._person("Đổi việc", "Data Analyst")
        run = create_candidate_set(RadarTurnPlan(
            must=[Constraint("title", "Data Analyst")]))
        profile = drift.talent_profile
        profile.current_title = "Kế toán"
        profile.save(update_fields=["current_title"])
        build_projection(drift.pk)
        finished = process_candidate_set(run.pk)
        statuses = dict(finished.members.values_list("person_id",
                                                     "deterministic_status"))
        self.assertEqual(statuses[keep.pk], "supported")
        self.assertEqual(statuses[drift.pk], "contradicted")
        self.assertEqual(finished.judged, 2)
        self.assertEqual(finished.unknown, 0)

    @override_settings(SEARCH_V2_SNAPSHOT_MAX_MEMBERS=3)
    def test_snapshot_cap_blocks_instead_of_silently_truncating(self):
        for index in range(5):
            self._person(f"Đông {index}", "Data Analyst")
        run = create_candidate_set(RadarTurnPlan(
            must=[Constraint("title", "Data Analyst")]))
        self.assertEqual(run.candidate_total, 5)
        self.assertEqual(run.state, "blocked")
        self.assertTrue(run.retrieval_degraded)
        self.assertEqual(run.explain["snapshot"]["reason"], "snapshot_cap_exceeded")
        self.assertFalse(CandidateSetMember.objects.filter(run=run).exists())
        self.assertFalse(process_candidate_set(run.pk).complete)

    def test_cost_estimate_uses_the_real_evidence_budget(self):
        estimate = estimate_judgement_cost(candidates=100)
        self.assertEqual(estimate["prompt_tokens"],
                         100 * EVIDENCE_CHAR_BUDGET // 4)


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
