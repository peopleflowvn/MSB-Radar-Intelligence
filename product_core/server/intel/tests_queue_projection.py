# -*- coding: utf-8 -*-
"""Hàng đợi trích xuất (§21.3) + Materialized projection (§21.7)."""
from unittest.mock import patch

from django.test import TestCase

from core.models import Edge, SourceRecord
from people.models import Person

from . import seeds
from .extraction import run_for_person
from .models import ExtractedFact, ExtractionJob, MaterializedProfile
from .projection import PROJECTION_VERSION, audit, build_for_person, rebuild_all
from .queue import claim_batch, enqueue, process_job, run_worker


class QueueTest(TestCase):
    def setUp(self):
        self.p1 = Person.objects.create(display_name="A")
        self.p2 = Person.objects.create(display_name="B")

    def test_enqueue_dedupes_pending_job(self):
        job, created1 = enqueue(self.p1)
        job2, created2 = enqueue(self.p1)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(job.pk, job2.pk)
        self.assertEqual(ExtractionJob.objects.filter(person=self.p1).count(), 1)

    def test_claim_batch_leases_and_prevents_double_claim(self):
        enqueue(self.p1)
        enqueue(self.p2)
        first = claim_batch(5, worker="w1")
        self.assertEqual(len(first), 2)
        self.assertTrue(all(j.status == ExtractionJob.STATUS_LEASED for j in first))
        # worker khác không claim lại được (đã leased, chưa hết hạn)
        self.assertEqual(claim_batch(5, worker="w2"), [])

    def test_process_job_marks_done(self):
        job, _ = enqueue(self.p1)
        [claimed] = claim_batch(1)
        result = process_job(claimed)
        self.assertEqual(result.status, ExtractionJob.STATUS_DONE)
        self.assertIsNotNone(result.last_run_id)

    def test_worker_once_drains_queue(self):
        enqueue(self.p1)
        enqueue(self.p2)
        totals = run_worker(batch_size=10, once=True)
        self.assertEqual(totals["done"], 2)
        self.assertFalse(ExtractionJob.objects.filter(
            status__in=["queued", "leased"]).exists())

    def test_failed_run_requeues_then_fails_at_max_attempts(self):
        enqueue(self.p1)

        def _failed_run(person, **kw):
            from .models import ExtractionRun
            run = ExtractionRun.objects.create(person=person, status=ExtractionRun.STATUS_FAILED,
                                               error="giả lập lỗi")
            return run

        with patch("intel.queue.run_for_person", side_effect=_failed_run):
            [j1] = claim_batch(1)
            r1 = process_job(j1)
            self.assertEqual(r1.status, ExtractionJob.STATUS_QUEUED)   # attempt 1 -> requeue
            [j2] = claim_batch(1)
            process_job(j2)
            [j3] = claim_batch(1)
            r3 = process_job(j3)
            self.assertEqual(r3.status, ExtractionJob.STATUS_FAILED)   # attempt 3 -> fail
            self.assertIn("giả lập lỗi", r3.error)


class ProjectionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        seeds.seed_all()

    def setUp(self):
        edge = Edge.objects.create(label="M", edge_id="e")
        self.person = Person.objects.create(display_name="C")
        SourceRecord.objects.create(
            edge=edge, entity_type="source_record", entity_key="k", content_hash="h",
            person=self.person,
            payload={"city": "Hà Nội", "skills": "SQL, Python",
                     "current_title": "Data Analyst", "job_level": "Senior",
                     "applied_ts": "2026-07-01 09:00:00"})
        run_for_person(self.person, use_ai=False)

    def test_projection_holds_only_accepted_current_facts(self):
        # thêm một fact proposed (sensitive) — không được vào projection
        from .facts import record_fact
        record_fact(self.person, "expected_salary", "40tr",
                    source_kind=ExtractedFact.SOURCE_AI, confidence=0.9, extractor="radar_ai")

        proj = build_for_person(self.person)
        self.assertEqual(proj.projection_version, PROJECTION_VERSION)
        self.assertNotIn("expected_salary", proj.data)
        self.assertEqual(proj.codes["location"], ["VN-HN"])
        self.assertEqual(set(proj.codes["skill"]), {"sql", "python"})
        self.assertIsInstance(proj.data["skills"], list)          # merge field -> list
        self.assertEqual(proj.data["current_title"]["code"], "data-analyst")
        title = proj.data["current_title"]
        self.assertTrue(title["fact_id"])
        self.assertEqual(title["status"], ExtractedFact.STATUS_ACCEPTED)
        self.assertEqual(title["source"]["source_record_revision"], 1)
        self.assertTrue(title["fact_fingerprint"])

    def test_rebuild_all_builds_for_people_with_accepted_facts(self):
        empty = Person.objects.create(display_name="Không có fact")
        stats = rebuild_all()
        self.assertGreaterEqual(stats["built"], 2)
        self.assertTrue(MaterializedProfile.objects.filter(person=self.person).exists())
        empty_projection = MaterializedProfile.objects.get(person=empty)
        self.assertEqual(empty_projection.fact_count, 0)
        self.assertEqual(empty_projection.data, {})

    def test_audit_blocks_stale_or_incomplete_projection(self):
        projection = build_for_person(self.person)
        report = audit()
        self.assertTrue(report["ready"])
        self.assertTrue(report["integrity_ready"])
        self.assertEqual(report["extraction_coverage_rate"], 1.0)
        projection.projection_version = PROJECTION_VERSION - 1
        projection.save(update_fields=["projection_version"])
        report = audit()
        self.assertFalse(report["ready"])
        self.assertEqual(report["stale_profiles"], 1)

    def test_audit_detects_changed_fact_without_new_id(self):
        build_for_person(self.person)
        fact = ExtractedFact.objects.filter(person=self.person, status="accepted",
                                            is_current=True).first()
        fact.evidence = "Changed source evidence"
        fact.save(update_fields=["evidence", "updated_at"])
        self.assertFalse(audit()["integrity_ready"])
        build_for_person(self.person)
        self.assertTrue(audit()["integrity_ready"])
