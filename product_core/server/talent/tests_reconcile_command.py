# -*- coding: utf-8 -*-
"""`reconcile_talent_index` — worker hợp nhất vá projection thiếu + bù embedding
+ chốt HNSW khi hàng đợi rỗng."""
import json
from io import StringIO
from unittest import mock

from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

from people.models import Document, Person
from talent.models import CVChunk, PersonSearchDocument


def _run(*args):
    output = StringIO()
    with mock.patch("talent.vector_index.embed", return_value=([0.1] * 8, "fake-model")):
        call_command("reconcile_talent_index", *args, stdout=output)
    return output.getvalue()


class ReportOnlyTest(TestCase):
    def test_without_apply_only_reports_and_writes_nothing(self):
        person = Person.objects.create(display_name="Chưa lập chỉ mục")
        Document.objects.create(person=person, sha256="r1", parse_status="done",
                                parsed_text="Chuyên viên tín dụng. " * 40)
        output = _run()
        self.assertIn("thiếu chỉ mục: 1", output)
        self.assertFalse(PersonSearchDocument.objects.filter(person=person).exists())

    def test_json_report_shape(self):
        output = _run("--json")
        report = json.loads(output)
        self.assertIn("missing_projection", report)
        self.assertIn("profiles_embedded", report)
        self.assertIn("chunks_embedded", report)


class ApplyFixesGapsTest(TestCase):
    def test_missing_projection_is_built_and_embedded_in_one_tick(self):
        person = Person.objects.create(display_name="Vá lỗ hổng")
        Document.objects.create(person=person, sha256="r2", parse_status="done",
                                parsed_text="Chuyên viên tín dụng. " * 40)

        _run("--apply", "--batch-size", "10")

        doc = PersonSearchDocument.objects.get(person=person)
        self.assertEqual(doc.embedding_fingerprint, doc.fingerprint)
        chunk = CVChunk.objects.filter(person=person).first()
        self.assertIsNotNone(chunk)
        self.assertEqual(chunk.embedding_fingerprint, chunk.fingerprint)

    def test_empty_queue_reports_zero_and_attempts_hnsw_pin(self):
        output = _run("--apply")
        self.assertIn("Hàng đợi rỗng", output)
        self.assertIn("thiếu chỉ mục: 0", output)

    def test_gate_raises_when_batch_too_small_to_clear_backlog(self):
        for i in range(2):
            person = Person.objects.create(display_name=f"Còn thiếu {i}")
            Document.objects.create(person=person, sha256=f"r3{i}", parse_status="done",
                                    parsed_text="Chuyên viên tín dụng. " * 40)

        with self.assertRaises(CommandError):
            _run("--apply", "--batch-size", "1", "--gate")

        self.assertEqual(
            Person.applicants().filter(search_document__isnull=True).count(), 1)


class RateLimitBackoffTest(SimpleTestCase):
    """429 là provider đang giới hạn tốc độ, không phải hàng hỏng."""

    def test_429_thi_cho_roi_thu_lai_dung_hang(self):
        from unittest import mock
        from talent import vector_index
        from talent.management.commands.reconcile_talent_index import Command

        calls = {"n": 0}

        def fake_embed(text, task_type=""):
            calls["n"] += 1
            if calls["n"] < 3:
                vector_index._set_embed_error("rate_limited")
                return None, "m"
            vector_index._set_embed_error("")
            return [0.1] * 64, "m"

        with mock.patch.object(vector_index, "embed", fake_embed),                 mock.patch("talent.management.commands.reconcile_talent_index.time.sleep") as sleep:
            vector, model, limited = Command()._embed("x")
        self.assertEqual((len(vector), model, limited), (64, "m", False))
        self.assertEqual(calls["n"], 3)
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5.0, 10.0])

    def test_loi_that_thi_khong_cho(self):
        from unittest import mock
        from talent import vector_index
        from talent.management.commands.reconcile_talent_index import Command

        def fake_embed(text, task_type=""):
            vector_index._set_embed_error("error")
            return None, "m"

        with mock.patch.object(vector_index, "embed", fake_embed),                 mock.patch("talent.management.commands.reconcile_talent_index.time.sleep") as sleep:
            self.assertEqual(Command()._embed("x"), (None, "m", False))
        sleep.assert_not_called()
