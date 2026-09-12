# -*- coding: utf-8 -*-
"""§2.H dòng 4 — tổ hợp model × tham số dễ vỡ.

Tiêu chí hỏi: *"Có tham số bị cắt ngầm cho một số model (ví dụ
`reasoning_effort` không tương thích) mà bước gọi phụ thuộc vào nó không?"* và
đòi **test canh đúng tổ hợp**, không phải test canh riêng từng vế.

`ai/tests.py` đã canh vế thứ nhất: `_apply_reasoning_effort` có bỏ tham số cho
`deepseek/*` không. Nhưng đó mới là "cơ chế cắt có chạy đúng không". Vế còn
thiếu là vế nguy hiểm: **tác vụ nào PHỤ THUỘC tham số ấy lại đang được định
tuyến tới đúng model nuốt nó.** Hai vế đều xanh riêng lẻ mà ghép lại vẫn hỏng —
đúng hình dạng lỗi mà §0.4 mô tả.

Vì sao "nuốt" là hỏng chứ không phải vô hại: `reasoning_effort="none"` được
truyền ở những chỗ có hạn mức token chật và cần chữ, không cần model nghĩ. Model
nuốt tham số thì nó vẫn nghĩ, ăn hết hạn mức, và phần chữ bị cắt cụt. Sổ lỗi §4
ghi lỗi #4 — câu trả lời cụt giữa chừng — **lặp lại ba lần trong hai ngày ở ba
chặng khác nhau**. Đây chính là cơ chế đẻ ra nó.

Bài test quét chính mã nguồn để tìm chỗ gọi có `reasoning_effort`, đối chiếu với
`DEFAULT_ROUTE`. Quét chứ không liệt kê tay, vì danh sách tay thì lệch — đã lệch
đúng như thế ở `ai/tasks.py` (thiếu 2 tác vụ) và ở env (`TALENT_EXPLAIN` trỏ vào
module đã xoá).
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from . import providers, tasks as tasks_registry

#: Chỗ gọi model có truyền `reasoning_effort` → tác vụ nào.
#: Bắt cả `task=TASK` (hằng module) lẫn `task="ten"` (viết thẳng).
_CO_REASONING = re.compile(r"reasoning_effort")
_TASK_KWARG = re.compile(r'task=(?:([A-Z_]*TASK[A-Z_]*)|"([a-z_]+)")')
_HANG_TASK = re.compile(r'^([A-Z_]*TASK[A-Z_]*)\s*=\s*"([a-z_]+)"', re.M)

_BO_QUA = {"migrations", "__pycache__", "tests"}

#: Tác vụ được phép dùng model nuốt `reasoning_effort` — CHỈ khi hạn mức token
#: rộng tới mức phần nghĩ không ăn hết phần chữ, và điều đó đã được ĐO.
#:
#: Mỗi mục phải nêu con số hạn mức; `test_ngoai_le_khong_duoc_dung_de_don_rac_vao`
#: bắt buộc như vậy, để người thêm mục mới phải đi đo trước khi thêm.
NGOAI_LE_CO_BANG_CHUNG = {
    "talent_answer_compose":
        "Hạn mức 7000 token (STREAM_MAX_TOKENS = RETRY_MAX_TOKENS), rộng gấp "
        "gần 9 lần chỗ chật nhất. Đo trên production: câu 'tổng quan kho' trả "
        "về trọn vẹn trong 45 giây kèm 12 trích dẫn. Đây là chặng người dùng "
        "ĐỌC THẤY nên đáng đánh đổi tốc độ lấy hành văn, và hạn mức đủ rộng để "
        "phần nghĩ không cắt mất phần chữ.",
}


def _tac_vu_phu_thuoc_reasoning():
    """{tên tác vụ: đường dẫn} cho mọi chỗ gọi có `reasoning_effort`.

    Cửa sổ 12 dòng quanh `reasoning_effort` — đủ để với tới `task=` của cùng
    một lời gọi mà không vơ nhầm lời gọi kế bên.
    """
    ra = {}
    for path in Path(settings.BASE_DIR).rglob("*.py"):
        if set(path.parts) & _BO_QUA or path.name.startswith("tests"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "reasoning_effort" not in text:
            continue
        hang = dict(_HANG_TASK.findall(text))       # {TÊN_HẰNG: "gia_tri"}
        dong = text.splitlines()
        for i, d in enumerate(dong):
            if not _CO_REASONING.search(d):
                continue
            cua_so = "\n".join(dong[max(0, i - 12):i + 3])
            for ten_hang, ten_thang in _TASK_KWARG.findall(cua_so):
                ten = hang.get(ten_hang, "") if ten_hang else ten_thang
                if ten:
                    ra.setdefault(ten, str(path))
    return ra


def _model_nuot_tham_so(model):
    """Model này có nuốt `reasoning_effort` không — hỏi CHÍNH hàm quyết định."""
    body = {}
    providers._apply_reasoning_effort(body, model, "none")
    return "reasoning_effort" not in body


class ThamSoBiNuotTest(TestCase):
    def test_bo_do_tim_duoc_it_nhat_vai_cho_goi(self):
        """Canh chính bộ dò trước. Nó trả rỗng thì mọi bài dưới xanh vô nghĩa."""
        thay = _tac_vu_phu_thuoc_reasoning()
        self.assertGreaterEqual(
            len(thay), 3,
            f"bộ dò chỉ thấy {len(thay)} chỗ — regex nhiều khả năng đã hỏng, "
            "và một bộ dò mù thì bài test dưới không canh được gì")
        self.assertIn("cv_ocr", thay, "cv_ocr có reasoning_effort — dò phải thấy")

    def test_khong_tac_vu_nao_phu_thuoc_reasoning_ma_bi_route_vao_model_nuot(self):
        """Tổ hợp — vế mà hai bài test cũ cộng lại vẫn không canh được.

        Lần chạy đầu bài này bắt được **sáu** tác vụ, trong đó ba tác vụ soạn
        thư có hạn mức 700–1200 token. Đo thật thì `deepseek-v4-pro` ở 800 trả
        về **chuỗi rỗng** — phần nghĩ ăn sạch hạn mức. Không phải rủi ro lý
        thuyết; nó đang hỏng.
        """
        xau = {}
        for ten, o_dau in _tac_vu_phu_thuoc_reasoning().items():
            if ten in NGOAI_LE_CO_BANG_CHUNG:
                continue
            provider, model = tasks_registry.default_route(ten)
            if model and _model_nuot_tham_so(model):
                xau[ten] = f"{provider}/{model}  ({o_dau})"
        self.assertEqual(
            xau, {},
            "Các tác vụ này truyền `reasoning_effort` nhưng model mặc định của "
            "chúng nuốt tham số đó — model vẫn 'nghĩ', ăn hết hạn mức token, và "
            f"phần chữ bị cắt cụt (sổ lỗi §4 #4, đã lặp ba lần):\n{xau}")

    def test_route_THAT_trong_csdl_cung_phai_qua_phep_kiem_nay(self):
        """`DEFAULT_ROUTE` sạch không có nghĩa hệ đang chạy sạch.

        Cái thật sự quyết định là hàng trong `TaskModelRoute` — migration gieo
        nó, `/settings` sửa nó, và cả hai đều có thể đặt vào đó một model nuốt
        tham số. Migration 0014 làm đúng như thế: gieo `deepseek-v4-pro` cho ba
        tác vụ soạn thư có hạn mức 700–1200, và ở 800 thì model ấy trả CHUỖI
        RỖNG. Sửa mặc định trong `tasks.py` mà quên hàng CSDL là sửa chỗ không
        ai đọc.
        """
        from .router import get_router

        router = get_router()
        xau = {}
        for ten in _tac_vu_phu_thuoc_reasoning():
            if ten in NGOAI_LE_CO_BANG_CHUNG or ten not in tasks_registry.TASKS:
                continue
            cau_hinh = router.effective_config(ten)
            if cau_hinh["model"] and _model_nuot_tham_so(cau_hinh["model"]):
                xau[ten] = f"{cau_hinh['model']} ({cau_hinh['config_source']})"
        self.assertEqual(xau, {},
                         f"Route ĐANG CHẠY nuốt `reasoning_effort`:\n{xau}")

    def test_ngoai_le_khong_duoc_dung_de_don_rac_vao(self):
        """Danh sách ngoại lệ là chỗ dễ bị lạm dụng nhất trong cả file này.

        Cách "sửa" rẻ nhất khi bài trên đỏ là nhét tên tác vụ vào ngoại lệ. Nên
        ngoại lệ phải nhỏ, và mỗi mục phải kèm câu nói rõ hạn mức bao nhiêu và
        đo ở đâu — người thêm mục mới buộc phải đi đo trước.
        """
        self.assertLessEqual(
            len(NGOAI_LE_CO_BANG_CHUNG), 2,
            "ngoại lệ phình ra là dấu hiệu người ta đang dọn rác vào đây thay "
            "vì sửa định tuyến")
        for ten, ly_do in NGOAI_LE_CO_BANG_CHUNG.items():
            with self.subTest(task=ten):
                self.assertIn(ten, tasks_registry.TASKS,
                              "ngoại lệ cho tác vụ không tồn tại")
                self.assertRegex(ly_do, r"\d{3,}",
                                 "lý do phải nêu hạn mức token cụ thể, không "
                                 "nói chung chung")
