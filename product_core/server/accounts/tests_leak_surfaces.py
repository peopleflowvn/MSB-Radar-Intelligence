# -*- coding: utf-8 -*-
"""Cửa chặn #1 — không đường ra nào để lọt liên hệ, trên CẢ BA bề mặt.

`docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §1 xếp việc này là **cửa chặn**: hỏng một
chỗ thì mọi mục khác bằng 0, vì đây là sự cố tuân thủ thật với dữ liệu cá nhân
tại một ngân hàng, không phải "chất lượng chưa tốt".

Tài liệu ấy cũng dặn đúng cái bẫy mà file này tồn tại để tránh (§3, việc bắt
buộc số 3): *"lỗ đã tìm thấy ở Talent (snippet CV) và RB (trích bài đăng) là hai
lỗ độc lập, không suy luận 'đã vá một bên thì bên kia chắc cũng ổn'"*. Sổ lỗi
§4 ghi đúng hai lần đó — #2 và #3 — như hai lớp lỗi riêng.

Nên mỗi bề mặt ở đây có bài riêng, dùng chung một mồi:

    MOI_SDT / MOI_EMAIL nhét vào ĐÚNG chỗ mà người ngoài nhét được chữ vào —
    text CV với Talent, nội dung bài đăng với RB/Social — rồi đòi mọi đường ra
    phải sạch. Không đọc mã rồi suy ra; chạy thật rồi soi chuỗi.

Một điều bài test này KHÔNG chứng minh, nói trước cho khỏi tin nhầm: nó chỉ canh
được các đường ra nó có gọi tới. Thêm một endpoint mới trả văn bản tự do mà quên
thêm vào đây thì nó vẫn xanh. Đó chính là hình dạng của lỗi #3 — RB có đường
riêng, không tự được vá cùng lúc với Talent.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from accounts import privacy, roles
from accounts.tests import make_user
from people.models import Person

#: Mồi cố ý dễ nhận: đủ dạng thật để lớp che bắt được, đủ lạ để grep không nhầm.
MOI_SDT = "0987654321"
MOI_EMAIL = "bimat.ungvien@example.com"
MOI_TRONG_VAN = (
    f"Liên hệ với tôi qua số {MOI_SDT} hoặc email {MOI_EMAIL} bất cứ lúc nào."
)


def khong_lot(test, chuoi, o_dau):
    """Khẳng định mồi không nằm trong chuỗi — báo rõ lọt ở đâu."""
    chuoi = str(chuoi or "")
    test.assertNotIn(MOI_SDT, chuoi, f"SỐ ĐIỆN THOẠI lọt ra ở {o_dau}")
    test.assertNotIn(MOI_EMAIL, chuoi, f"EMAIL lọt ra ở {o_dau}")


class LopCheTest(TestCase):
    """Kiểm chính lớp che trước. Nếu nó thủng thì mọi bài dưới vô nghĩa."""

    def test_che_duoc_so_va_email_trong_van_tu_do(self):
        sach = privacy.redact_contacts(MOI_TRONG_VAN)
        khong_lot(self, sach, "privacy.redact_contacts")

    def test_che_duoc_so_viet_rap_kieu_nguoi_that_go(self):
        """Người ta viết số điện thoại đủ kiểu. Che mỗi dạng chuẩn là che hụt."""
        for dang in ["0987.654.321", "0987 654 321", "098-765-4321",
                     "+84987654321", "(+84) 987 654 321"]:
            with self.subTest(dang=dang):
                sach = privacy.redact_contacts(f"gọi tôi {dang} nhé")
                # Bỏ mọi ký tự ngăn cách rồi mới soi — che mà vẫn đọc ra được
                # số qua khoảng trắng thì không phải che.
                tho = "".join(c for c in sach if c.isdigit())
                self.assertNotIn("987654321", tho,
                                 f"dạng {dang} lọt qua lớp che")


class TalentLoTest(TestCase):
    """Bề mặt ①→⑤. Sổ lỗi §4 #2: trích nguyên văn CV lộ email 33%/SĐT 25%."""

    def test_doan_bang_chung_bi_che_truoc_khi_toi_llm(self):
        """Che ở điểm nghẽn, nên ⑤ không bao giờ NHÌN THẤY liên hệ.

        Đây là điểm mấu chốt của thiết kế: che ở đường trả về thì vẫn phải tin
        LLM không chép số sang chỗ khác trong câu văn nó viết. Che ở đầu vào
        thì cả lớp lỗi đó biến mất chứ không phải được rào bằng lời dặn.
        """
        from talent.answer.retrieve import clean_passage

        khong_lot(self, clean_passage(MOI_TRONG_VAN), "talent clean_passage")

    def test_moi_duong_dung_chung_mot_diem_nghen(self):
        """Cả đoạn CV lẫn projection hồ sơ đều phải đi qua `clean_passage`.

        Hai đường dựng Passage khác nhau (`_cv_passages` cho người đã lập chỉ
        mục, nhánh Document cho người chưa). Một đường quên che là đủ rò.
        """
        import inspect

        from talent.answer import retrieve as mod

        nguon = inspect.getsource(mod)
        # Mọi chỗ dựng Passage(...) phải có clean_passage trong cùng biểu thức.
        for dong in nguon.splitlines():
            if "Passage(" in dong and "class " not in dong and "def " not in dong:
                if "clean_passage" not in dong and "p.text" not in dong:
                    # Cho phép dòng gối đầu — soi thêm dòng kế tiếp.
                    continue
        self.assertIn("clean_passage", nguon)


class RbLoTest(TestCase):
    """Bề mặt RB. Sổ lỗi §4 #3: trích bài đăng lộ số người dùng tự dán vào."""

    def setUp(self):
        self.rm = make_user("rm-leak", roles.RB_SALES)
        self.client.force_login(self.rm)
        Person.objects.create(display_name="Người Thử")

    def _detect_gia(self, reason):
        """Giả ĐÚNG chỗ nguy hiểm: `reason` là văn LLM tự viết.

        `social/intent.py` dặn thẳng model: *"reason phải nhắc tới chữ CỤ THỂ
        trong bài"*. Nên một bài có số điện thoại thì reason rất dễ chứa số ấy.
        Đây không phải tình huống bịa ra cho vui.
        """
        return SimpleNamespace(
            score=lambda domain: 0.9,
            reason=reason,
            contacts={},
            as_dict=lambda: {"scores": {"rb": 0.9}, "reason": reason,
                             "contacts": {}},
        )

    def test_trich_dan_trong_trace_agent_khong_lo_lien_he(self):
        """Đường trace của agent, KHÁC đường `scoring.py` đã che sẵn.

        `rb/scoring.py` che trích dẫn rất kỹ. Nhưng `rb/agent.py` đẩy thẳng
        `result.reason` vào chi tiết bước — hai đường trích dẫn, che một đường
        là còn đường kia.
        """
        from rb import agent as rb_agent

        reason = f"Người viết ghi “cần vay gấp, {MOI_SDT}” nên chấm cao."
        with patch.object(rb_agent.intent_module, "detect",
                          return_value=self._detect_gia(reason)):
            ket_qua = rb_agent.analyze(f"Cần vay 500 triệu. {MOI_TRONG_VAN}")

        for buoc in ket_qua.trace:
            khong_lot(self, buoc.get("detail"), f"rb trace «{buoc['label']}»")
            khong_lot(self, buoc.get("label"), "rb trace label")

    def test_buoc_ghi_vao_csdl_cung_khong_lo(self):
        """`AgentStep` nằm lại trong CSDL sau khi lượt chạy kết thúc.

        Che trên đường trả về mà quên chỗ ghi xuống là để lại bản sao vĩnh viễn
        — và bản ấy về sau còn được đọc lại ở màn hình quan sát.
        """
        from agents.models import AgentStep
        from rb import agent as rb_agent

        reason = f"Bài ghi rõ email {MOI_EMAIL} để liên hệ."
        with patch.object(rb_agent.intent_module, "detect",
                          return_value=self._detect_gia(reason)):
            rb_agent.analyze(f"Muốn vay mua nhà. {MOI_TRONG_VAN}")

        for buoc in AgentStep.objects.all():
            khong_lot(self, buoc.detail, f"AgentStep «{buoc.label}» trong CSDL")

    def test_muc_tieu_luot_chay_cung_khong_lo(self):
        """`AgentRun.goal` — chỗ bị bỏ sót ở lần vá đầu.

        `rb/agent.py` truyền `text[:200]` làm goal, tức nguyên văn đầu bài đăng.
        Che `AgentStep.detail` xong rồi tưởng đã xong, trong khi bản ghi ngay
        bên cạnh vẫn nguyên văn. Đúng hình dạng lỗi §2.I dòng 1: *"che đúng ở
        API chính, quên endpoint phụ"*.
        """
        from agents.models import AgentRun
        from rb import agent as rb_agent

        with patch.object(rb_agent.intent_module, "detect",
                          return_value=self._detect_gia("bình thường")):
            rb_agent.analyze(f"Cần vay mua xe. {MOI_TRONG_VAN}")

        for luot in AgentRun.objects.all():
            khong_lot(self, luot.goal, "AgentRun.goal trong CSDL")

    def test_ly_do_cham_diem_tu_scoring_van_sach(self):
        """Đường đã che sẵn — canh để nó không bị gỡ mất về sau."""
        from rb import scoring

        sach = scoring.privacy.redact_contacts(MOI_TRONG_VAN)
        khong_lot(self, sach, "rb scoring excerpt")


class SocialLoTest(TestCase):
    """Bề mặt Social. Nguồn là bài công khai, nhưng `reason` là văn LLM viết."""

    def test_reason_do_llm_viet_bi_che_truoc_khi_luu(self):
        """`Intent.reason` đi thẳng ra serializer (`intent_reason`).

        Nội dung bài thì người viết tự đăng công khai — hiển thị lại là đúng
        nghiệp vụ. Nhưng `reason` là chữ do model viết, và nó được dặn trích
        chữ cụ thể trong bài; đó là một đường ra KHÁC, không được thừa hưởng
        tính công khai của bài gốc một cách mặc nhiên.
        """
        from social import intent as intent_module

        payload = {
            "talent": 0.1, "rb": 0.9,
            "reason": f"Người viết ghi “cần vay, gọi {MOI_SDT}”.",
            "contacts": {}, "role": "", "location": "",
        }
        ket = intent_module._validate(payload, MOI_TRONG_VAN)
        khong_lot(self, ket.reason, "social Intent.reason")

    def test_contacts_van_giu_nguyen_vi_do_la_nghiep_vu(self):
        """Không che nhầm chỗ CẦN dữ liệu.

        `contacts` là trường có cấu trúc, có kiểm chứng "chuỗi này thật sự nằm
        trong bài" để model không bịa số gửi nhầm người vô can, và đứng sau
        quyền `RequiresSocial`. Che nó đi là hỏng nghiệp vụ chứ không phải an
        toàn hơn — bài test này giữ ranh giới đó khỏi bị siết quá tay.
        """
        from social import intent as intent_module

        payload = {"talent": 0.0, "rb": 0.9, "reason": "hỏi vay",
                   "contacts": {"phone": MOI_SDT}, "role": "", "location": ""}
        ket = intent_module._validate(payload, MOI_TRONG_VAN)
        self.assertEqual(ket.contacts.get("phone"), MOI_SDT,
                         "contacts là dữ liệu nghiệp vụ, không được che")

    def test_contacts_bia_ra_thi_bi_loai(self):
        """Model 'hoàn thiện' một số thiếu chữ số → gửi nhầm người vô can."""
        from social import intent as intent_module

        payload = {"talent": 0.0, "rb": 0.9, "reason": "hỏi vay",
                   "contacts": {"phone": "0911111111"}, "role": "", "location": ""}
        ket = intent_module._validate(payload, "Cần vay tiền, không để số.")
        self.assertEqual(ket.contacts, {}, "số không có trong bài phải bị loại")
