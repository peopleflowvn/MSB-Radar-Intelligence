# -*- coding: utf-8 -*-
"""Sổ đăng ký tác vụ AI phải khớp mã nguồn — chống lệch âm thầm.

`ai/tasks.py` quyết định `/settings` cho người vận hành đổi model của những gì.
Nếu nó lệch với mã nguồn thì hỏng theo hai hướng, cả hai đều im lặng:

* **Thiếu** — tác vụ chạy thật nhưng không hiện ra, nên không đổi model được.
  Đã xảy ra với 8 tác vụ, trong đó có `cv_parsing` (chạy cho MỌI hồ sơ nhập vào).
* **Thừa** — một ô cấu hình không nối vào đâu cả. Đã xảy ra với `talent_explain`
  sau khi `talent/ai_search.py` bị gỡ.

Test này quét chính mã nguồn nên không cần ai nhớ cập nhật danh sách.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from . import tasks as tasks_registry

#: Hằng khai tên tác vụ ở đầu module, và `task="..."` truyền thẳng vào
#: complete/stream.
#:
#: Tiền tố `[A-Z_]*` không thừa. Bản đầu chỉ bắt đúng chữ `TASK`, nên bỏ sót
#: `OCR_TASK = "cv_ocr"` và `EXTRACTION_TASK = "candidate_extraction"` — hai tác
#: vụ chạy thật mà không đổi model được, đúng cái test này sinh ra để chặn. Test
#: vẫn xanh vì nó không thấy thì cũng không so. Cái canh gác có lỗ ngay chỗ cần
#: canh, nên `test_regex_bat_duoc_hang_co_tien_to` ở dưới canh chính regex này.
_DECLARED = re.compile(r'^[A-Z_]*TASK[A-Z_]*\s*=\s*"([a-z_]+)"', re.M)
_INLINE = re.compile(r'task="([a-z_]+)"')

#: Thư mục bỏ qua: test tự bịa tên tác vụ, migration giữ tên lịch sử.
_SKIP_PARTS = {"migrations", "__pycache__"}


def _source_files():
    root = Path(settings.BASE_DIR)
    for path in root.rglob("*.py"):
        parts = set(path.parts)
        if parts & _SKIP_PARTS or path.name.startswith("tests"):
            continue
        yield path


def tasks_in_source():
    found = set()
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        found.update(_DECLARED.findall(text))
        found.update(_INLINE.findall(text))
    return found


class DeclaredRegexTest(TestCase):
    """Canh chính bộ dò — nó đã từng mù và kéo theo cả hai test kia mù."""

    def test_regex_bat_duoc_hang_co_tien_to(self):
        nguon = ('TASK = "a_thuong"\n'
                 'OCR_TASK = "b_tien_to"\n'
                 'EXTRACTION_TASK = "c_tien_to_dai"\n'
                 'TASK_FALLBACK = "d_hau_to"\n')
        self.assertEqual(sorted(_DECLARED.findall(nguon)),
                         ["a_thuong", "b_tien_to", "c_tien_to_dai", "d_hau_to"])

    def test_khong_bat_nham_hang_khong_phai_ten_tac_vu(self):
        """Nới regex không được nới tới mức bắt bừa.

        Hằng cấp module nằm ở cột 0; thụt vào là biến trong hàm/lớp. Và tên tác
        vụ luôn là chuỗi thường — `TASK_TIMEOUT = 30` hay `TASK_LABEL = "Bóc
        tách"` là hằng khác, khai thừa vào sổ sẽ đẻ ra ô cấu hình rỗng.
        """
        for nguon in ('    TASK = "thut_vao_la_bien_cuc_bo"\n',
                      'TASK_TIMEOUT = 30\n',
                      'TASK_LABEL = "Có Dấu Và Hoa"\n'):
            with self.subTest(nguon=nguon.strip()):
                self.assertEqual(_DECLARED.findall(nguon), [])


class TaskRegistryTest(TestCase):
    def test_moi_tac_vu_trong_ma_nguon_deu_co_trong_so_dang_ky(self):
        """Thiếu một cái là người vận hành không đổi model của nó được."""
        missing = sorted(tasks_in_source() - set(tasks_registry.TASKS))
        self.assertEqual(missing, [], f"Chưa khai trong ai/tasks.py: {missing}")

    def test_khong_khai_thua_tac_vu_da_chet(self):
        """Ô cấu hình không nối vào đâu cả thì gây hiểu nhầm hơn là hữu ích."""
        extra = sorted(set(tasks_registry.TASKS) - tasks_in_source())
        self.assertEqual(extra, [], f"Khai trong ai/tasks.py mà mã không dùng: {extra}")

    def test_settings_hien_dung_bang_so_dang_ky(self):
        from .views import KNOWN_TASKS
        self.assertEqual(list(KNOWN_TASKS), tasks_registry.names())

    def test_moi_tac_vu_co_nhan_va_mo_ta_tieng_viet(self):
        """Người vận hành không có cách nào đoán `rb_prospect_search` là gì."""
        for row in tasks_registry.TASKS.values():
            with self.subTest(task=row.name):
                self.assertTrue(row.label.strip(), f"{row.name} thiếu nhãn")
                self.assertGreater(len(row.description), 20,
                                   f"{row.name} thiếu mô tả")
                self.assertIn(row.group, tasks_registry.GROUPS)
                self.assertIn(row.kind, tasks_registry.KINDS,
                              f"{row.name} có kind lạ — UI sẽ không biết gợi ý "
                              "hay chặn model nào")

    def test_tac_vu_doi_nang_luc_dac_biet_duoc_danh_dau(self):
        """Quên đánh dấu là mất chỗ chặn, và hỏng lặng chứ không báo lỗi."""
        self.assertEqual(tasks_registry.TASKS["talent_embedding"].kind,
                         tasks_registry.KIND_EMBEDDING)
        self.assertEqual(tasks_registry.TASKS["cv_ocr"].kind,
                         tasks_registry.KIND_VISION)

    def test_payload_du_de_dung_danh_sach_chon(self):
        payload = tasks_registry.as_payload()
        self.assertEqual(len(payload), len(tasks_registry.TASKS))
        for item in payload:
            self.assertEqual(
                set(item), {"name", "label", "description", "group", "kind",
                            "default_provider", "default_model", "default_reason"})


class DefaultRouteTest(TestCase):
    """Mặc định phải phủ hết và phải chạy được — thiếu một cái là nó lại rơi
    xuống model mặc định của nhà cung cấp, đúng cái ta vừa dọn."""

    def test_moi_tac_vu_deu_co_mac_dinh(self):
        thieu = sorted(set(tasks_registry.TASKS)
                       - set(tasks_registry.DEFAULT_ROUTE))
        self.assertEqual(thieu, [], f"Chưa có mặc định: {thieu}")

    def test_khong_dat_mac_dinh_cho_tac_vu_khong_ton_tai(self):
        thua = sorted(set(tasks_registry.DEFAULT_ROUTE)
                      - set(tasks_registry.TASKS))
        self.assertEqual(thua, [], f"Mặc định cho tác vụ không có: {thua}")

    def test_migration_da_gieo_route_cho_moi_tac_vu(self):
        """Hợp đồng mới: không tác vụ nào còn rơi xuống model mặc định của nhà
        cung cấp. Migration 0014 gieo, `/settings` sửa — env hết phần."""
        from .models import TaskModelRoute
        co = set(TaskModelRoute.objects.values_list("task", flat=True))
        thieu = sorted(set(tasks_registry.TASKS) - co)
        self.assertEqual(thieu, [], f"Chưa có route trong CSDL: {thieu}")

    def test_khong_con_tac_vu_nao_lay_model_tu_env_hay_day(self):
        """Đo trên chính hàm router dùng để quyết định, không phải trên bảng."""
        from .router import get_router
        router = get_router()
        xau = {name: router.effective_config(name)["config_source"]
               for name in tasks_registry.TASKS}
        xau = {k: v for k, v in xau.items() if v != "db_task_route"}
        self.assertEqual(xau, {}, f"Còn lấy cấu hình ngoài CSDL: {xau}")

    def test_tac_vu_moi_chua_co_migration_van_khong_roi_xuong_day(self):
        """Lỗ dễ tái phát nhất: thêm tác vụ vào `tasks.py`, quên viết migration.

        Migration 0014 gieo route cho 22 tác vụ *đang có*. Cái thứ 23 sẽ không
        có hàng nào trong CSDL, và nếu router không đỡ thì nó lại im lặng nhận
        model mặc định của nhà cung cấp — đúng cách `cv_ocr` từng nhận một model
        không đọc nổi ảnh. Nên router phải lấy mặc định từ sổ đăng ký.
        """
        from unittest.mock import patch
        from .models import TaskModelRoute
        from .router import Router

        TEN = "tac_vu_moi_toanh"
        assert not TaskModelRoute.objects.filter(task=TEN).exists()
        with patch.dict(tasks_registry.DEFAULT_ROUTE,
                        {TEN: ("greennode", "qwen/qwen3.6-flash")}):
            cau_hinh = Router(env={}).effective_config(TEN)
        self.assertEqual(cau_hinh["provider"], "greennode")
        self.assertEqual(cau_hinh["model"], "qwen/qwen3.6-flash")
        self.assertEqual(cau_hinh["config_source"], "registry_default")

    def test_mac_dinh_nam_trong_danh_muc_va_du_nang_luc(self):
        """Chặn đúng lỗi vừa tìm ra: `cv_ocr` từng trỏ vào model không có thị
        giác, và không gì báo cho tới khi có CV scan thật."""
        from . import catalog
        for name, (provider, model) in tasks_registry.DEFAULT_ROUTE.items():
            with self.subTest(task=name):
                rows = {row.id: row for row in catalog.for_provider(provider)}
                self.assertIn(model, rows,
                              f"{name}: mặc định {model!r} không có trong danh "
                              f"mục {provider} — UI sẽ hiện ô trống")
                ok, ly_do = catalog.usable_for(rows[model], name)
                self.assertTrue(ok, f"{name}: {ly_do}")


class BenchmarkDefaultsTest(TestCase):
    """Mặc định theo benchmark 19/09 — đổi thì phải đổi CÙNG lý do trong
    `DEFAULT_REASON` và chạy lại benchmark, không sửa lẻ một con số."""

    def test_doc_cv_va_hieu_cau_hoi_dung_qwen_plus(self):
        for task in ("talent_answer_plan", "talent_answer_judge", "rb_prospect_search",
                     "rb_answer_judge", "candidate_extraction"):
            self.assertEqual(tasks_registry.default_route(task), ("greennode", "qwen/qwen3.7-plus"))
            self.assertTrue(tasks_registry.DEFAULT_REASON.get(task))

    def test_viet_cau_tra_loi_dung_glm_da_do_on_dinh_hon_tren_prod(self):
        self.assertEqual(tasks_registry.default_route("talent_answer_compose"),
                         ("greennode", "z-ai/glm-5.2-hackathon"))
        self.assertIn(("greennode", "deepseek/deepseek-v4-pro"),
                      tasks_registry.fallback_models("talent_answer_compose"))
