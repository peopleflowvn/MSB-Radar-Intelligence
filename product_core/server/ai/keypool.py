# -*- coding: utf-8 -*-
"""Xoay vòng nhiều khoá API cho cùng một nhà cung cấp.

Vì sao cần: hạn mức tốc độ tính **theo từng khoá**, không theo tài khoản. Đo thực
tế với khoá Gemini miễn phí — 15 lượt gọi trong một phút là đã HTTP 429, đúng
nhịp một buổi demo bấm tìm vài lần. Ba khoá thì hạn mức hiệu dụng gấp ba, và
không cần đổi gì trong nghiệp vụ.

Đây KHÁC với việc chuyển nhà cung cấp:

    xoay khoá        cùng một nhà cung cấp, đổi khoá  -> chữa hết hạn mức
    chuyển provider  đổi hẳn nhà cung cấp             -> chữa nhà cung cấp sập

Hai cơ chế bổ sung cho nhau. Xoay khoá diễn ra TRƯỚC: còn khoá khác của cùng nhà
cung cấp thì dùng nốt, hết mới chuyển sang nhà cung cấp khác.

Ba loại lỗi, ba cách xử lý khác hẳn nhau:

    429 hết hạn mức   cho khoá nghỉ 60 giây rồi dùng lại — hạn mức sẽ hồi
    401/403 sai khoá  TẮT hẳn khoá; thử lại chỉ tổ phí và làm rác nhật ký
    lỗi khác          không phải lỗi của khoá, đừng phạt nó
"""
import itertools
import threading
import time

# Hạn mức của các nhà cung cấp gần như luôn tính theo phút, nên nghỉ một phút là
# đủ để hồi. Nghỉ ngắn hơn thì quay lại đúng lúc vẫn còn bị chặn.
RATE_LIMIT_COOLDOWN = 60.0


class KeyState:
    def __init__(self, key, label=""):
        self.key = key
        self.label = label or (key[:6] + "…" if len(key) > 6 else "…")
        self.disabled = False
        self.cooldown_until = 0.0
        self.uses = 0
        self.rate_limits = 0
        self.last_used = 0.0

    @property
    def available(self):
        return not self.disabled and time.time() >= self.cooldown_until

    @property
    def cooling_seconds(self):
        return max(0.0, self.cooldown_until - time.time())


class KeyPool:
    """Nhóm khoá của một nhà cung cấp, xoay vòng theo lượt.

    An toàn khi nhiều luồng dùng chung: gunicorn chạy nhiều worker, và hai yêu
    cầu cùng lúc không được nhận cùng một khoá rồi cùng đẩy nó qua hạn mức.
    """

    def __init__(self, keys, provider=""):
        seen, states = set(), []
        for item in keys:
            key = str(item or "").strip()
            if key and key not in seen:
                seen.add(key)
                states.append(KeyState(key))
        self.provider = provider
        self.states = states
        self._lock = threading.Lock()
        self._cycle = itertools.cycle(range(len(states))) if states else None

    def __len__(self):
        return len(self.states)

    @property
    def usable(self):
        """Số khoá đang dùng được ngay bây giờ."""
        return sum(1 for s in self.states if s.available)

    def acquire(self):
        """Khoá tiếp theo nên dùng. None chỉ khi MỌI khoá đều đã bị tắt.

        Xoay vòng đều thay vì luôn lấy khoá đầu: dùng cạn khoá đầu rồi mới sang
        khoá hai nghĩa là khoá đầu lúc nào cũng ở trạng thái sắp hết hạn mức,
        còn các khoá kia nhàn rỗi.

        Nếu mọi khoá đều đang nghỉ, vẫn trả về khoá sắp hết hạn nghỉ sớm nhất
        thay vì trả None. Thời gian nghỉ chỉ là phỏng đoán — cửa sổ hạn mức có
        thể đã trôi qua rồi. Bỏ cuộc trong khi còn khoá có thể dùng được là tệ
        hơn thử. Việc giãn cách các lần thử là của vòng lặp thử lại ở router.
        """
        if not self.states:
            return None
        with self._lock:
            for _ in range(len(self.states)):
                state = self.states[next(self._cycle)]
                if state.available:
                    return self._take(state)

            # Không còn khoá nào rảnh: lấy khoá hết nghỉ sớm nhất trong số các
            # khoá CHƯA bị tắt. Khoá đã tắt thì đúng là hỏng, không đụng tới.
            cooling = [s for s in self.states if not s.disabled]
            if cooling:
                return self._take(min(cooling, key=lambda s: s.cooldown_until))
        return None

    def _take(self, state):
        state.uses += 1
        state.last_used = time.time()
        return state

    def report_rate_limited(self, state):
        """Khoá hết hạn mức: cho nghỉ rồi dùng lại. KHÔNG tắt — hạn mức sẽ hồi."""
        with self._lock:
            state.cooldown_until = time.time() + RATE_LIMIT_COOLDOWN
            state.rate_limits += 1

    def report_invalid(self, state):
        """Khoá sai/hết hạn: tắt hẳn. Thử lại chỉ tổ phí và làm rác nhật ký."""
        with self._lock:
            state.disabled = True

    def status(self):
        """Trạng thái từng khoá, cho trang cài đặt hiển thị."""
        return [{
            "label": s.label,
            "disabled": s.disabled,
            "available": s.available,
            "cooling_seconds": round(s.cooling_seconds),
            "uses": s.uses,
            "rate_limits": s.rate_limits,
        } for s in self.states]


def split_keys(value):
    """Tách chuỗi nhiều khoá. Chấp nhận dấu phẩy, xuống dòng, chấm phẩy.

    Người dùng dán khoá từ nhiều chỗ nên định dạng rất tuỳ hứng; nhận cả ba dấu
    phân cách rẻ hơn nhiều so với việc họ dán nhầm rồi không hiểu sao chỉ một
    khoá được nhận.
    """
    text = str(value or "")
    for separator in (",", ";", "\n", "\r"):
        text = text.replace(separator, "\x00")
    return [part.strip() for part in text.split("\x00") if part.strip()]
