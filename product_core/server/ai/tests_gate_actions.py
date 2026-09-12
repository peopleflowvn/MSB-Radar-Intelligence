# -*- coding: utf-8 -*-
"""Cửa chặn #2 — không hành động có hậu quả nào agent TỰ thực thi.

`docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §1 cửa #2: mọi hành động ghi dữ liệu
thật / gửi ra ngoài / đổi trạng thái phải qua **người bấm HOẶC luật tất định**.
`docs/AGENT_RUNTIME.md` §1 gọi đây là "phá đúng chỗ hại nhất" nếu để một agent
tool-calling tự quyết.

Cửa này dễ tưởng đã đạt vì đọc danh sách tool thấy toàn "chỉ đọc". Nhưng danh
sách tool có HAI bản trong dự án này, và chỉ một bản là thật:

* `agents/tools.py` — sổ tra cứu cho người vận hành. `implemented_by` là chuỗi,
  không có đường gọi động. Nó liệt kê cả `create_hunt_request` và
  `prioritize_lead` — hai thứ ghi dữ liệu nghiệp vụ thật.
* `ai/toolset.py::HANDLERS` — bản LLM thật sự gọi được.

Đọc nhầm bản đầu rồi kết luận "agent tạo được hunt request" là báo động giả;
đọc nhầm theo chiều ngược lại thì bỏ sót. Nên bài test bám vào bản THẬT.
"""
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts import roles
from accounts.tests import make_user
from ai import tool_handlers, toolset
from people.models import Person

#: Tool được phép ghi CSDL, kèm lý do vì sao không vi phạm cửa chặn.
#: Thêm tool mới có ghi mà không khai ở đây thì test đỏ — cố ý.
GHI_DUOC_PHEP = {
    "remember_proposal": "ghi ở trạng thái pending_review, người dùng duyệt "
                         "trong Cài đặt; có hạn mức 10 đề xuất chờ",
    "feedback": "ghi đánh giá của CHÍNH người dùng về câu trả lời họ vừa đọc — "
                "người dùng khởi xướng, không phải agent tự quyết",
}

#: Tool gửi dữ liệu ra ngoài hệ thống. Mỗi cái phải có luật tất định chặn nội
#: dung gửi (không có người bấm ở giữa).
GUI_RA_NGOAI = {"enrich_company_from_web"}


class SoDangKyToolTest(TestCase):
    def test_khong_co_duong_goi_dong_trong_so_tra_cuu(self):
        """`agents/tools.py` chỉ được là siêu dữ liệu.

        `implemented_by` là chuỗi "module.hàm" để người tra, không phải thứ
        đem `getattr` ra gọi. Có một `dispatch(tên_chuỗi)` ở đó là mở đúng cửa
        mà cả kiến trúc này dựng lên để đóng.
        """
        import inspect

        from agents import tools as so_tra_cuu

        nguon = inspect.getsource(so_tra_cuu)
        for dau_hieu in ("getattr(", "import_module", "eval(", "exec("):
            self.assertNotIn(dau_hieu, nguon,
                             f"sổ tra cứu có {dau_hieu} — thành đường gọi động")

    def test_tool_ghi_nghiep_vu_khong_nam_trong_bo_llm_goi_duoc(self):
        """Ranh giới thật: `create_hunt_request`/`prioritize_lead` có trong sổ
        tra cứu nhưng KHÔNG có handler — LLM không chạm tới được."""
        for ten in ("create_hunt_request", "prioritize_lead",
                    "draft_recruiter_message", "draft_sales_response"):
            with self.subTest(tool=ten):
                self.assertNotIn(ten, tool_handlers.HANDLERS,
                                 f"{ten} ghi/gửi dữ liệu nghiệp vụ mà LLM gọi được")


class HanhDongCoHauQuaTest(TestCase):
    """Quét chính mã handler, không đọc mắt — §0.4: bài test phải canh được thứ
    nó định canh, kể cả khi có người thêm handler mới mà quên báo ai."""

    def test_moi_handler_ghi_csdl_deu_phai_duoc_khai_bao(self):
        import inspect

        for ten, ham in tool_handlers.HANDLERS.items():
            nguon = inspect.getsource(ham)
            ghi = any(dau in nguon for dau in
                      ("objects.create(", ".save(", "objects.update(",
                       "objects.get_or_create(", ".delete()"))
            if ghi:
                self.assertIn(
                    ten, GHI_DUOC_PHEP,
                    f"tool {ten!r} ghi CSDL mà chưa khai trong GHI_DUOC_PHEP. "
                    "Nếu nó ghi dữ liệu nghiệp vụ thật thì đây là vi phạm Cửa "
                    "chặn #2; nếu an toàn thì khai kèm lý do.")

    def test_khong_handler_nao_gui_thu_hay_goi_http_tuy_y(self):
        import inspect

        for ten, ham in tool_handlers.HANDLERS.items():
            nguon = inspect.getsource(ham)
            for dau in ("send_mail(", "smtplib", "requests.post(", "requests.put("):
                self.assertNotIn(
                    dau, nguon,
                    f"tool {ten!r} có {dau} — gửi ra ngoài không qua người bấm")

    def test_remember_proposal_ghi_o_trang_thai_cho_duyet(self):
        """Không phải "ghi rồi báo", mà là "đề xuất rồi chờ"."""
        from ai.models import LongTermMemory

        user = make_user("nho-de-xuat", roles.RECRUITER)
        ket = tool_handlers.remember_proposal(
            {"value": "Ứng viên ưu tiên mảng ngân hàng bán lẻ."},
            user=user, surface="talent", context={})
        self.assertEqual(ket["status"], "pending_review")
        row = LongTermMemory.objects.get(pk=ket["id"])
        self.assertEqual(row.status, LongTermMemory.STATUS_PENDING,
                         "ghi thẳng trạng thái đã duyệt là bỏ qua người bấm")


@override_settings(ASSISTANT_TOOLS_TIER3=True)
class GuiRaNgoaiTest(TestCase):
    """Đường ra ngoài DUY NHẤT agent tự bấm được — phải có luật tất định.

    Bật TIER3 ở đây vì production đang bật (kiểm 04/09/2026). Test mặc định
    theo settings dev sẽ xanh một cách vô nghĩa: tool bị tắt thì không có gì
    để canh, mà production thì vẫn hở.
    """

    def setUp(self):
        self.user = make_user("tra-web", roles.RECRUITER)

    def test_tool_nay_that_su_goi_duoc_tren_cau_hinh_giong_production(self):
        self.assertIn("enrich_company_from_web", toolset._agent_tool_names(),
                      "nếu tool bị tắt thì các bài dưới canh nhầm chỗ")

    def test_khong_gui_so_dien_thoai_hay_email_ra_ngoai(self):
        """Bật `websearch` lên trước, nếu không bài này xanh vì lý do SAI.

        Không bật thì `enrich_company_from_web` cũng ném `ToolError` — nhưng là
        "web search chưa bật", không phải "chặn vì có liên hệ". Bắt đúng lớp
        ngoại lệ mà không đọc nội dung là để bài test tự lừa mình; §0.4 gọi
        đúng cái này: *"bài test này có thể xanh trong khi thứ nó định canh vẫn
        hỏng không?"*
        """
        from ai import websearch

        for xau in ["Công ty của 0987654321", "lienhe@ungvien.example.com"]:
            with self.subTest(xau=xau):
                with patch.object(websearch, "enabled", return_value=True), \
                        patch.object(websearch, "web_answer") as da_goi:
                    with self.assertRaises(tool_handlers.ToolError) as loi:
                        tool_handlers.enrich_company_from_web(
                            {"company": xau}, user=self.user, surface="talent",
                            context={})
                    da_goi.assert_not_called()
                self.assertIn("không gửi email/số điện thoại", str(loi.exception))

    def test_khong_tra_ten_nguoi_trong_kho_tren_dich_vu_ngoai(self):
        """Mô hình bị dụ — hoặc chỉ là lẫn lộn — nhét tên ứng viên vào `company`.

        Tham số tên là `company` nhưng không có gì BẮT nó phải là công ty. Đây
        là loại lỗi không rút lại được: gửi đi rồi thì bên kia đã ghi log.
        """
        Person.objects.create(display_name="Nguyễn Văn An")
        with self.assertRaises(tool_handlers.ToolError) as loi:
            tool_handlers.enrich_company_from_web(
                {"company": "nguyễn văn an"}, user=self.user,
                surface="talent", context={})
        self.assertIn("trùng tên", str(loi.exception))

    def test_ten_cong_ty_that_van_tra_duoc(self):
        """Luật chặn không được siết tới mức hỏng việc chính."""
        from ai import websearch

        goi = {}

        def gia_web_answer(query, **kwargs):
            goi["query"] = query
            return type("R", (), {"text": "Ngân hàng cổ phần.", "citations": [],
                                  "provider": "gia"})()

        with patch.object(websearch, "enabled", return_value=True), \
                patch.object(websearch, "web_answer", gia_web_answer):
            ket = tool_handlers.enrich_company_from_web(
                {"company": "Ngân hàng TMCP Hàng Hải"}, user=self.user,
                surface="talent", context={})
        self.assertEqual(ket["company"], "Ngân hàng TMCP Hàng Hải")
        self.assertIn("Hàng Hải", goi["query"])
