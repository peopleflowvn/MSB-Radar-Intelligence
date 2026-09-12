# -*- coding: utf-8 -*-
"""Radar Agent Runtime (Master Plan mục 41).

Điều bài này canh kỹ nhất KHÔNG phải "ghi log đúng" — mà là **runtime không
được quyết định gì cả.** Nó chỉ quan sát một chuỗi bước domain code đã tự viết
sẵn bằng code. Không có test nào ở đây kiểm "agent chọn tool đúng", vì không có
lựa chọn nào để kiểm — đó chính là điểm của thiết kế này.
"""
import time
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase

from . import runtime
from .models import AGENT_TALENT, AgentRun, AgentStep


class RuntimeTest(TestCase):
    def test_mo_va_dong_mot_luot_chay(self):
        with runtime.run(AGENT_TALENT, goal="tìm Data Analyst") as run:
            run.record("Đọc nhu cầu")
            run.finish({"count": 3})

        agent_run = AgentRun.objects.get()
        self.assertEqual(agent_run.status, AgentRun.STATUS_OK)
        self.assertEqual(agent_run.result_summary, {"count": 3})
        self.assertIsNotNone(agent_run.finished_at)

    def test_ghi_lai_TUNG_buoc_theo_dung_thu_tu(self):
        with runtime.run(AGENT_TALENT, goal="x") as run:
            run.record("Bước 1")
            run.record("Bước 2")
            run.record("Bước 3")
            run.finish()

        labels = list(AgentStep.objects.order_by("order").values_list("label", flat=True))
        self.assertEqual(labels, ["Bước 1", "Bước 2", "Bước 3"])

    def test_loi_ben_trong_thi_dong_lai_voi_status_error_va_NEM_TIEP(self):
        """Quan sát không được nuốt lỗi thật — code gọi runtime vẫn phải thấy
        exception để tự xử lý (hoặc để nó nổ lên, đúng như không có runtime)."""
        with self.assertRaises(ValueError):
            with runtime.run(AGENT_TALENT, goal="x"):
                raise ValueError("hỏng thật")

        agent_run = AgentRun.objects.get()
        self.assertEqual(agent_run.status, AgentRun.STATUS_ERROR)
        self.assertIn("hỏng thật", agent_run.error)

    def test_quen_goi_finish_van_duoc_TU_DONG_dong(self):
        """Không được để lại bản ghi "đang chạy" mãi mãi vì domain code quên
        gọi finish()."""
        with runtime.run(AGENT_TALENT, goal="x"):
            pass
        self.assertEqual(AgentRun.objects.get().status, AgentRun.STATUS_OK)

    def test_step_do_thoi_gian_va_ghi_lai(self):
        with runtime.run(AGENT_TALENT, goal="x") as run:
            with run.step("search_person", "Tìm kiếm") as s:
                time.sleep(0.02)
                s.detail = "8 kết quả"
            run.finish()

        step = AgentStep.objects.get()
        self.assertEqual(step.tool, "search_person")
        self.assertEqual(step.detail, "8 kết quả")
        # Windows scheduler/clock resolution can report a 20 ms sleep as 14 ms.
        # The contract is that a material, non-zero duration is persisted.
        self.assertGreaterEqual(step.duration_ms, 10)

    def test_step_loi_thi_ghi_ok_False_va_NEM_TIEP(self):
        with self.assertRaises(RuntimeError):
            with runtime.run(AGENT_TALENT, goal="x") as run:
                with run.step("x", "Bước hỏng"):
                    raise RuntimeError("bể")

        step = AgentStep.objects.get()
        self.assertFalse(step.ok)

    def test_ghi_nguoi_bat_dau(self):
        user = User.objects.create_user("hm", password="mat-khau-dai-1")
        with runtime.run(AGENT_TALENT, goal="x", user=user) as run:
            run.finish()
        self.assertEqual(AgentRun.objects.get().started_by, user)

    def test_khach_khong_dang_nhap_thi_KHONG_gan_nguoi(self):
        """`user` có thể là AnonymousUser — không được lưu nhầm thành FK lỗi."""
        from django.contrib.auth.models import AnonymousUser
        with runtime.run(AGENT_TALENT, goal="x", user=AnonymousUser()) as run:
            run.finish()
        self.assertIsNone(AgentRun.objects.get().started_by)

    def test_CSDL_hong_thi_KHONG_lam_nghiep_vu_that_bi_hong(self):
        """Quan sát hỏng không được lan sang việc đang làm — đây là hạ tầng phụ,
        không phải đường chính."""
        with mock.patch("agents.models.AgentRun.objects.create",
                        side_effect=RuntimeError("CSDL sập")):
            with runtime.run(AGENT_TALENT, goal="x") as run:
                run.record("Vẫn chạy tiếp bình thường")
                run.finish({"ok": True})
        # Không ném lỗi ra ngoài — nghiệp vụ coi như chạy xong bình thường.
        self.assertEqual(AgentRun.objects.count(), 0)


class ToolsRegistryTest(TestCase):
    def test_moi_tool_muc_41_deu_co_trong_so(self):
        from . import tools
        # Đúng 16 tool: 7 shared + 5 talent + 4 rb, theo danh sách Master Plan mục 41.
        self.assertEqual(len(tools.TOOLS), 16)

    def test_label_of_tra_ve_cau_tieng_Viet(self):
        from . import tools
        self.assertEqual(tools.label_of("match_product"), "Gợi ý nhóm sản phẩm")

    def test_ten_khong_co_thi_lui_ve_fallback(self):
        from . import tools
        self.assertEqual(tools.label_of("khong_ton_tai", fallback="X"), "X")

    def test_by_domain_luon_kem_shared(self):
        from . import tools
        rows = tools.by_domain(tools.DOMAIN_RB)
        self.assertTrue(any(r.domain == tools.DOMAIN_RB for r in rows))
        self.assertTrue(any(r.domain == tools.DOMAIN_SHARED for r in rows))
        self.assertFalse(any(r.domain == tools.DOMAIN_TALENT for r in rows))
