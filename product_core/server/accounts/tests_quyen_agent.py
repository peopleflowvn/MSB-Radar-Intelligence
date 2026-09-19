# -*- coding: utf-8 -*-
"""§2.I dòng 3 + §2.D nhóm thứ 10 — quyền hạn, nhóm bộ vàng còn thiếu.

Bộ `answer_eval` phủ 9/10 nhóm khó mà `docs/AI_AGENT_ACCEPTANCE_CRITERIA.md`
§2.D liệt kê — phủ định, điều kiện chồng, thời gian, mơ hồ, bẫy, chèn lệnh,
nhiều tầng, không dấu, kho rỗng. Thiếu đúng nhóm **quyền hạn**, và nó là nhóm
nằm sát Cửa chặn #1.

Thiếu vì `answer_eval` chạy trên kho thật với model thật, không dựng nổi hai
tài khoản khác vai để so. Nên nhóm này đo ở đây, bằng test.

**Một điều phải nói thẳng, vì im lặng ở đây là gài bẫy người đọc sau.** §2.I
dòng 3 hỏi *"hai người dùng khác quyền có nhận kết quả KHÁC nhau đúng theo
quyền không?"* và ghi dấu hiệu không đạt là *"kết quả giống hệt nhau"*. Trong
Radar, hai tài khoản đều có quyền Talent **sẽ** nhận kết quả giống hệt nhau —
và đó KHÔNG phải lỗi.

Lý do: mô hình phân quyền ở đây là **cấp module** (`roles.can_access`), tức
"vào được phòng nào", không phải "thấy được dòng nào trong phòng". Ai vào được
Talent thì thấy chung một kho. Chiều theo-người-dùng nằm ở chỗ khác — hạn mức
mở khoá liên hệ (`accounts.privacy.unlock`) — và chiều ấy được bảo vệ bằng cách
mạnh hơn lọc: liên hệ bị che TRƯỚC KHI tới model, nên không lượt nào trả ra
liên hệ, bất kể ai hỏi.

Nên bài test ở đây khẳng định đúng ba điều thật sự phải đúng:

1. Không có quyền module thì không vào được — chặn ở cửa.
2. Có quyền thì thấy cùng một kho — và điều đó là CỐ Ý, ghi lại để lần nghiệm
   thu sau không báo động giả.
3. Cache không bao giờ dùng chung giữa hai tài khoản — lưới đỡ phòng khi mai
   này có lọc cấp dòng thật mà ai đó quên cache.
"""
from django.test import TestCase

from accounts import roles
from accounts.tests import make_user
from talent.answer import cache as cache_stage


class CuaVaoModuleTest(TestCase):
    def test_khong_co_quyen_talent_thi_khong_vao_duoc(self):
        """Vai thiếu Talent là `EDGE_OPERATOR`, KHÔNG phải `RB_SALES`.

        Bản đầu của bài này dùng `RB_SALES` và đỏ ngay — vì `RB_SALES` có
        `{MODULE_RB, MODULE_TALENT, MODULE_SOCIAL}`. Nhân viên RB xem được kho
        ứng viên là đúng nghiệp vụ (một khách hàng có thể đồng thời là ứng
        viên). Ghi lại để lần sau không ai "sửa" nhầm theo hướng siết lại.
        """
        edge = make_user("chi-edge", roles.EDGE_OPERATOR)
        self.assertFalse(roles.can_access(edge, roles.MODULE_TALENT))
        self.assertTrue(roles.can_access(edge, roles.MODULE_EDGE))

    def test_co_quyen_thi_vao_duoc(self):
        for vai in (roles.RECRUITER, roles.HIRING_MANAGER, roles.MANAGER,
                    roles.ADMIN):
            with self.subTest(vai=vai):
                u = make_user(f"vao-{vai}", vai)
                self.assertTrue(roles.can_access(u, roles.MODULE_TALENT))

    def test_tool_tu_choi_khi_thieu_quyen_module(self):
        """Lọc RBAC phải nằm ở `dispatch`, không chỉ ở tầng HTTP.

        Vòng lặp tool gọi thẳng `toolset.dispatch` trong tiến trình — nếu quyền
        chỉ được kiểm ở view thì model đi vòng qua được bằng cách gọi tool.

        Và phải soi ĐÚNG câu lỗi. Bản đầu chỉ khẳng định `ket.ok is False` —
        bài ấy xanh cả khi tool trượt vì `person_ids` không tồn tại, tức xanh
        mà không canh được gì. §0.4 gọi tên đúng cái đó.
        """
        from ai import toolset

        edge = make_user("edge-goi-tool-talent", roles.EDGE_OPERATOR)
        ket = toolset.dispatch("compare_candidates", {"person_ids": [1, 2]},
                               user=edge, surface="talent")
        self.assertFalse(ket.ok)
        self.assertIn("không có quyền", ket.error)


class CacheTheoNguoiHoiTest(TestCase):
    def test_hai_tai_khoan_khong_bao_gio_dung_chung_muc_cache(self):
        a = make_user("hoi-a", roles.RECRUITER)
        b = make_user("hoi-b", roles.RECRUITER)
        cau = "tìm ứng viên quan hệ khách hàng"
        # `key_for` trả None khi kho rỗng (chưa có vân tay) — dựng đủ dữ liệu
        # thì mới so được, nếu không bài test xanh vì cả hai đều None.
        from people.models import Person
        Person.objects.create(display_name="Người Một")

        khoa_a = cache_stage.key_for(cau, user=a)
        khoa_b = cache_stage.key_for(cau, user=b)
        if khoa_a is None or khoa_b is None:
            self.skipTest("kho chưa có vân tay — cache tắt, không so được")
        self.assertNotEqual(khoa_a, khoa_b,
                            "hai tài khoản dùng chung mục cache")

    def test_cung_mot_nguoi_hoi_lai_thi_trung_khoa(self):
        """Không tách quá tay: tách theo lượt thì cache thành vô dụng."""
        from people.models import Person
        Person.objects.create(display_name="Người Hai")
        a = make_user("hoi-lai", roles.RECRUITER)

        khoa1 = cache_stage.key_for("tìm chuyên viên tín dụng", user=a)
        khoa2 = cache_stage.key_for("tìm chuyên viên tín dụng", user=a)
        if khoa1 is None:
            self.skipTest("kho chưa có vân tay — cache tắt")
        self.assertEqual(khoa1, khoa2)


class KhoDungChungLaCoYTest(TestCase):
    """Ghi lại một chủ đích, để lần nghiệm thu sau không báo động giả.

    Nếu mai này thêm lọc cấp dòng thật (ví dụ recruiter chỉ thấy ứng viên mình
    phụ trách), bài test này sẽ đỏ — và đỏ đúng: nó buộc người sửa phải quay lại
    đọc docstring đầu file rồi cập nhật cả hai chỗ, thay vì để tài liệu nói một
    đằng mã chạy một nẻo.
    """

    def test_retrieve_chua_loc_theo_nguoi_dung_va_do_la_co_y(self):
        import inspect

        from talent.answer import retrieve as mod

        # `retrieve` từng nhận `user` mà không đọc lần nào — chữ ký hứa lọc theo
        # người dùng mà thân hàm không làm. Bản 16/09 bỏ hẳn tham số (xem
        # docstring của `retrieve`). Nên chủ đích "kho dùng chung" giờ được ghi
        # bằng việc KHÔNG có `user`; ai thêm lại là đang nối lọc cấp dòng.
        self.assertNotIn("user", inspect.signature(mod.retrieve).parameters,
                         "đã có lọc theo người dùng — cập nhật lại docstring "
                         "đầu file này và `talent/answer/cache.py::key_for`")
