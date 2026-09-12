import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from .review_eval import build_batch, citation_claims, score_batch


def _report():
    return {"scope": "fixture", "model": "m", "gold_version": 7, "rows": [{
        "case": "sql", "q": "Ai biết SQL?", "answer": "An biết SQL [1].",
        "ids": [4], "sources": [{"n": 1, "person_id": 4, "name": "An",
                                   "document_id": 8, "snippet": "Kỹ năng SQL"}],
        "error": "",
    }]}


class HumanReviewEvalTest(SimpleTestCase):
    def test_claim_is_bound_to_cited_sentence(self):
        self.assertEqual(citation_claims("Mở đầu. An biết SQL [1]."),
                         {1: "An biết SQL [1]."})

    def test_export_is_versioned_and_has_three_review_surfaces(self):
        manifest, rows = build_batch(_report())
        self.assertEqual(manifest["input_gold_version"], 7)
        self.assertEqual(manifest["record_count"], 3)
        self.assertEqual({r["record_type"] for r in rows}, {"answer", "candidate", "claim"})
        self.assertTrue(all(len(r["reviews"]) == 2 for r in rows))

    def test_repeated_source_and_missing_source_are_not_dropped(self):
        report = _report()
        report["rows"][0]["answer"] = "An biết SQL [1]. An biết Python [1]. An ở Huế [99]."
        manifest, records = build_batch(report)
        claims = [row for row in records if row["record_type"] == "claim"]
        self.assertEqual([row["source_number"] for row in claims], [1, 1, 99])
        self.assertEqual(len({row["review_id"] for row in claims}), 3)
        self.assertIn("Python", claims[1]["claim"])
        self.assertIsNone(claims[2]["source"])
        self.assertTrue(claims[2]["source_missing"])
        self.assertEqual(score_batch(manifest, records)["missing_source_records"], 1)
        for row in claims:
            original = report["rows"][0]["answer"][row["answer_start"]:row["answer_end"]]
            self.assertEqual(" ".join(original.split()), row["claim"])

    def test_grouped_citations_keep_each_evidence_pair(self):
        report = _report()
        report["rows"][0]["answer"] = "An biết SQL [1, 2] [1]."
        _, records = build_batch(report)
        self.assertEqual([r["source_number"] for r in records if r["record_type"] == "claim"], [1, 2])

    def test_legacy_batches_remain_scoreable_with_explicit_coverage(self):
        from .review_eval import stable_hash
        records = [{"review_id": "legacy", "record_type": "answer", "answer": "old",
                    "reviews": [{"reviewer_id": "a", "label": "ACCEPT"},
                                {"reviewer_id": "b", "label": "ACCEPT"}], "adjudication": None}]
        manifest = {"schema_version": 1, "record_count": 1,
                    "record_identity_sha256": stable_hash([{k: v for k, v in records[0].items()
                                                            if k not in ("reviews", "adjudication")}])}
        score = score_batch(manifest, records)
        self.assertTrue(score["complete"])
        self.assertEqual(score["claim_coverage"], "legacy_first_sentence_per_source")

    def test_missing_and_disputed_labels_stay_unmeasured(self):
        manifest, rows = build_batch(_report())
        rows[0]["reviews"] = [
            {"reviewer_id": "r1", "label": "ACCEPT"},
            {"reviewer_id": "r2", "label": "REJECT"},
        ]
        score = score_batch(manifest, rows)
        self.assertFalse(score["complete"])
        self.assertEqual(score["disputed"], 1)
        self.assertIsNone(score["answer_acceptance_rate"])
        self.assertIsNone(score["claim_hallucination_rate"])

    def test_missing_record_breaks_manifest_integrity_and_gate(self):
        manifest, rows = build_batch(_report())
        score = score_batch(manifest, rows[:-1])
        self.assertFalse(score["integrity_ok"])
        self.assertFalse(score["complete"])

    def test_changed_evidence_breaks_integrity(self):
        manifest, rows = build_batch(_report())
        rows[-1]["source"]["snippet"] = "changed source"
        self.assertFalse(score_batch(manifest, rows)["integrity_ok"])

    def test_answer_eval_numeric_sources_uses_all_sources(self):
        report = _report()
        row = report["rows"][0]
        row["all_sources"] = row["sources"]
        row["sources"] = 1
        _manifest, records = build_batch(report)
        self.assertEqual(records[-1]["source"]["document_id"], 8)

    def test_two_reviewers_and_adjudicator_produce_metrics(self):
        manifest, rows = build_batch(_report())
        labels = {"answer": ("ACCEPT", "REJECT", "ACCEPT"),
                  "candidate": ("RELEVANT", "RELEVANT", None),
                  "claim": ("SUPPORTED", "CONTRADICTED", "CONTRADICTED")}
        for row in rows:
            left, right, final = labels[row["record_type"]]
            row["reviews"] = [{"reviewer_id": "r1", "label": left},
                              {"reviewer_id": "r2", "label": right}]
            if final:
                row["adjudication"] = {"reviewer_id": "r3", "label": final}
        score = score_batch(manifest, rows)
        self.assertTrue(score["complete"])
        self.assertEqual(score["claim_hallucination_rate"], 1.0)
        self.assertEqual(score["acceptance_at_returned_k"], 1.0)
        self.assertEqual(score["answer_acceptance_rate"], 1.0)

    def test_commands_export_and_refuse_incomplete_gate(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "input.json"
            source.write_text(json.dumps(_report()), encoding="utf-8")
            call_command("brain_review_export", input=str(source), out=str(root / "batch"))
            with self.assertRaises(CommandError):
                call_command("brain_review_score", file=str(root / "batch" / "reviews.jsonl"),
                             manifest=str(root / "batch" / "manifest.json"),
                             out=str(root / "score.json"), require_complete=True)
