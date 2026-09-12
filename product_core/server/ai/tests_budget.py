# -*- coding: utf-8 -*-
"""Trần thời gian cho một lượt gọi AI.

Không có trần này, trường hợp xấu nhất là 4 nhà cung cấp × 60 giây × 2 vòng ≈ 8
phút màn hình đứng — mà một lượt tìm bằng AI gọi hai lần, thành 16 phút.

Trước ban giám khảo, treo 16 phút tệ hơn hẳn báo lỗi sau 25 giây rồi lùi về dò
từ khoá. Mạng hội trường chập chờn là chuyện thường, không phải giả định xa vời.
"""
import time

from django.test import TestCase

from .providers import LLMUnavailable
from .router import Router

MESSAGES = [{"role": "user", "content": "xin chào"}]

BUSY = {"error": {"message": "quá tải"}}
OK = {"choices": [{"message": {"content": "xin chào"}}],
      "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

# GreenNode cố tình không có ở đây: chưa biết mã model nên `configured()` của nó
# trả False, và bài này cần các nhà cung cấp thật sự được gọi tới.
THREE_KEYS = {
    "MSB_AI_OPENAI_API_KEY": "k",
    "MSB_AI_GEMINI_API_KEY": "k",
    "MSB_AI_DEEPSEEK_API_KEY": "k",
    "MSB_AI_PROVIDER_DEFAULT": "openai",
    "MSB_AI_PROVIDER_FALLBACK": "gemini,deepseek",
}


def busy_transport(record=None):
    """Mọi nhà cung cấp đều trả 503 — buộc router đi hết chuỗi dự phòng."""
    def transport(url, headers, body, timeout):
        if record is not None:
            record.append(timeout)
        return 503, BUSY
    return transport


class BudgetTest(TestCase):
    def test_thoi_gian_cho_TUNG_LUOT_bi_ep_theo_ngan_sach_con_lai(self):
        """Đặt trần tổng mà vẫn để mỗi lượt chờ 60 giây thì trần không có tác dụng."""
        timeouts = []
        router = Router(env=THREE_KEYS, transport=busy_transport(timeouts))
        with self.assertRaises(LLMUnavailable):
            router.complete(MESSAGES, budget_seconds=10)

        self.assertTrue(timeouts)
        # 60 giây mặc định của nhà cung cấp phải bị cắt xuống dưới ngân sách.
        self.assertLessEqual(max(timeouts), 10)

    def test_ngan_sach_khong_de_mot_provider_an_het_gio_cua_du_phong(self):
        """Provider chậm/treo không được ăn hết ngân sách: provider KHÔNG phải
        cuối cùng bị cắt xuống dưới phần còn lại để còn giây cho dự phòng."""
        timeouts = []
        router = Router(env=THREE_KEYS, transport=busy_transport(timeouts))
        with self.assertRaises(LLMUnavailable):
            router.complete(MESSAGES, budget_seconds=10)
        self.assertTrue(timeouts)
        self.assertLessEqual(max(timeouts), 10)          # không vượt ngân sách
        # THREE_KEYS = greennode + gemini + deepseek: provider đầu mỗi vòng bị
        # cắt còn ~60% phần còn lại (chừa chỗ cho hai provider sau).
        self.assertLess(timeouts[0], 10 * 0.75)

    def test_het_gio_thi_KHONG_doi_3_giay_de_thu_lai(self):
        """Đợi rồi thử lại chỉ có nghĩa nếu còn đủ giờ cho lượt sau chạy xong."""
        router = Router(env=THREE_KEYS, transport=busy_transport())
        started = time.monotonic()
        with self.assertRaises(LLMUnavailable):
            router.complete(MESSAGES, budget_seconds=2)
        self.assertLess(time.monotonic() - started, 2.5)

    def test_con_du_gio_thi_VAN_thu_lai(self):
        """Giới hạn tốc độ chỉ cần đợi vài giây — đừng bỏ mất cơ chế đó."""
        calls = []

        def transport(url, headers, body, timeout):
            calls.append(timeout)
            return (429, BUSY) if len(calls) == 1 else (200, OK)

        # Một nhà cung cấp duy nhất: không có chỗ để chuyển, chỉ còn cách đợi.
        router = Router(env={"MSB_AI_GEMINI_API_KEY": "k"}, transport=transport)
        result = router.complete(MESSAGES, budget_seconds=25)
        self.assertEqual(result.text, "xin chào")
        self.assertEqual(len(calls), 2)

    def test_ngan_sach_doc_duoc_tu_bien_moi_truong(self):
        router = Router(env=dict(THREE_KEYS, MSB_AI_BUDGET_SECONDS="7"))
        self.assertEqual(router._budget(), 7.0)

    def test_bien_moi_truong_hong_thi_dung_mac_dinh(self):
        router = Router(env=dict(THREE_KEYS, MSB_AI_BUDGET_SECONDS="nhanh lên"))
        self.assertEqual(router._budget(), Router.BUDGET_SECONDS)

    def test_goi_binh_thuong_khong_bi_anh_huong(self):
        def transport(url, headers, body, timeout):
            return 200, OK

        router = Router(env={"MSB_AI_GEMINI_API_KEY": "k"}, transport=transport)
        self.assertEqual(router.complete(MESSAGES).text, "xin chào")


class CircuitBreakerTest(TestCase):
    @staticmethod
    def _name(url):
        if "generativelanguage" in url:
            return "gemini"
        if "deepseek" in url:
            return "deepseek"
        return "openai"

    def _router(self, seq):
        """seq: hàm (name, lần_thứ)->('timeout'|'ok')."""
        calls = {"openai": 0, "gemini": 0, "deepseek": 0}

        def transport(url, headers, body, timeout):
            name = self._name(url)
            calls[name] += 1
            if seq(name, calls[name]) == "ok":
                return 200, OK
            raise LLMUnavailable(f"{name}: The read operation timed out")

        r = Router(env=THREE_KEYS, transport=transport)
        r._env_calls = calls
        return r

    def test_provider_timeout_lien_tiep_bi_ngat_va_bo_qua(self):
        # openai luôn timeout; gemini luôn ok (đứng thứ 2).
        r = self._router(lambda name, n: "timeout" if name == "openai" else "ok")
        for _ in range(3):
            self.assertEqual(r.complete(MESSAGES, budget_seconds=20).text, "xin chào")
        # sau 2 lần timeout liên tiếp, openai bị ngắt -> lần 3 không gọi nữa
        self.assertLessEqual(r._env_calls["openai"], 2)
        self.assertTrue(r._breaker_open("openai"))

    def test_goi_thanh_cong_reset_breaker(self):
        def seq(name, n):
            if name != "openai":
                return "ok"
            return "timeout" if n <= 1 else "ok"

        r = self._router(seq)
        r.complete(MESSAGES, budget_seconds=20)      # openai timeout 1 lần (chưa ngắt)
        self.assertFalse(r._breaker_open("openai"))
        r.complete(MESSAGES, budget_seconds=20)      # openai ok -> reset
        self.assertNotIn("openai", r._breaker)


class TruncationTest(TestCase):
    """Câu trả lời bị cắt giữa chừng KHÔNG phải câu trả lời.

    Đo thật với Gemini 3.5 Flash: `max_tokens` tính CẢ token suy nghĩ, nên
    `max_tokens=600` cho ra `finish_reason="length"` với đúng 24 token nhìn thấy
    được — và mảnh rò ra là chính nội dung mô hình đang tự nhủ:

        'MSB - 9) Tôi (10) ấn (11) tượng (12) với'

    Recruiter đang vội rất dễ bấm gửi luôn, và một nửa câu gửi đi dưới tên MSB
    thì không rút lại được.
    """

    @staticmethod
    def _transport(finish_reason, text="một nửa câu"):
        def transport(url, headers, body, timeout):
            return 200, {
                "choices": [{"message": {"content": text},
                             "finish_reason": finish_reason}],
                "usage": {"prompt_tokens": 300, "completion_tokens": 24},
            }
        return transport

    def _complete(self, finish_reason, **kwargs):
        router = Router(env={"MSB_AI_GEMINI_API_KEY": "k"},
                        transport=self._transport(finish_reason))
        return router.complete(MESSAGES, **kwargs)

    def test_danh_dau_khi_bi_cat(self):
        self.assertTrue(self._complete("length").truncated)

    def test_khong_danh_dau_khi_tra_loi_xong(self):
        self.assertFalse(self._complete("stop").truncated)

    def test_khong_danh_dau_khi_nha_cung_cap_khong_bao(self):
        """Không phải nhà cung cấp nào cũng trả `finish_reason`."""
        self.assertFalse(self._complete(None).truncated)


class ReasoningEffortTest(TestCase):
    """`reasoning_effort` phải đi tới nhà cung cấp, và chỉ khi được yêu cầu."""

    @staticmethod
    def _transport(record):
        def transport(url, headers, body, timeout):
            record.append(body)
            return 200, OK
        return transport

    def _call(self, **kwargs):
        sent = []
        router = Router(env={"MSB_AI_GEMINI_API_KEY": "k"},
                        transport=self._transport(sent))
        router.complete(MESSAGES, **kwargs)
        return sent[0]

    def test_gui_khi_duoc_yeu_cau(self):
        self.assertEqual(self._call(reasoning_effort="none")["reasoning_effort"],
                         "none")

    def test_KHONG_gui_khi_khong_yeu_cau(self):
        """Nhà cung cấp không hiểu tham số này có thể trả 400 — đừng gửi bừa."""
        self.assertNotIn("reasoning_effort", self._call())
