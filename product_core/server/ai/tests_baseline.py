# -*- coding: utf-8 -*-
"""R0-01 (docs/RADAR_AI_AGENT_BACKLOG.md §14) — manifest baseline.

Canh đúng lý do tồn tại của module này: hai lượt gọi cách nhau phải cho cùng
kết quả khi KHÔNG có gì đổi, và phải khác nhau khi kho/route/prompt đổi thật —
nếu không thì manifest chỉ là một cục JSON vô nghĩa, không giúp so sánh được
hai lần chạy baseline.
"""
import json
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from ai.baseline import manifest as build_manifest
from people.models import Person


class ManifestContentTest(TestCase):
    def test_co_du_cac_khoi_bat_buoc(self):
        data = build_manifest()
        for key in ("captured_at", "git_commit", "corpus", "prompt_versions",
                   "eval_datasets", "effective_routes"):
            self.assertIn(key, data)

    def test_corpus_snapshot_dem_dung_nguoi_chua_gop(self):
        Person.objects.create(display_name="A")
        goc = Person.objects.create(display_name="B")
        Person.objects.create(display_name="C đã gộp", merged_into=goc)

        data = build_manifest()
        self.assertEqual(data["corpus"]["people"], 2)

    def test_prompt_versions_doi_khi_prompt_doi(self):
        """Đổi prompt mà hash không đổi thì manifest vô dụng cho việc phát hiện
        "lượt này khác lượt trước vì prompt", đúng lỗ hổng module này phải vá."""
        from talent.answer import plan as plan_stage

        before = build_manifest()["prompt_versions"]["talent_answer_plan"]
        original = plan_stage.SYSTEM
        try:
            plan_stage.SYSTEM = original + " — câu thêm để đổi hash."
            after = build_manifest()["prompt_versions"]["talent_answer_plan"]
        finally:
            plan_stage.SYSTEM = original
        self.assertNotEqual(before, after)

    def test_effective_routes_co_provider_va_config_source(self):
        data = build_manifest()
        self.assertTrue(data["effective_routes"])
        row = data["effective_routes"][0]
        for key in ("task", "provider", "model", "config_source"):
            self.assertIn(key, row)

    def test_count_contract_prompt_change_is_visible_in_manifest(self):
        from unittest.mock import patch
        from talent.answer import judge
        before = build_manifest()["prompt_versions"]
        with patch.object(judge, "COUNT_SYSTEM", judge.COUNT_SYSTEM + " extra count rule"):
            after = build_manifest()["prompt_versions"]
        self.assertNotEqual(before["talent_answer_judge_count"], after["talent_answer_judge_count"])
        self.assertEqual(before["talent_answer_judge"], after["talent_answer_judge"])

    def test_eval_dataset_version_dem_dung_so_cau(self):
        from talent.management.commands.answer_eval import QUESTIONS

        data = build_manifest()
        self.assertEqual(data["eval_datasets"]["talent_answer_eval"]["count"],
                         len(QUESTIONS))


class ManifestCommandTest(TestCase):
    def test_in_ra_stdout_la_json_hop_le(self):
        out = StringIO()
        call_command("baseline_manifest", stdout=out)
        data = json.loads(out.getvalue())
        self.assertIn("corpus", data)

    def test_ghi_file_dung_noi_dung(self, ):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            call_command("baseline_manifest", out=path, stdout=StringIO())
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle)
            self.assertIn("effective_routes", data)
        finally:
            os.remove(path)

    def test_so_sanh_khong_doi_gi_thi_khong_bao_thay_doi(self):
        import os
        import tempfile

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            call_command("baseline_manifest", out=path, stdout=StringIO())
            out = StringIO()
            call_command("baseline_manifest", compare=path, stdout=out)
            self.assertIn("Không có thay đổi", out.getvalue())
        finally:
            os.remove(path)

    def test_so_sanh_bao_dung_thay_doi_prompt(self):
        import os
        import tempfile

        from talent.answer import plan as plan_stage

        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            call_command("baseline_manifest", out=path, stdout=StringIO())
            original = plan_stage.SYSTEM
            out = StringIO()
            try:
                plan_stage.SYSTEM = original + " đổi."
                call_command("baseline_manifest", compare=path, stdout=out)
            finally:
                plan_stage.SYSTEM = original
            self.assertIn("prompt[talent_answer_plan]", out.getvalue())
        finally:
            os.remove(path)
