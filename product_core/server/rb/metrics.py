# -*- coding: utf-8 -*-
"""Chỉ số đo hiệu quả RB Radar (Master Plan mục 50).

Bốn chỉ số, cùng nguyên tắc với `hiring/metrics.py`: **chưa có dữ liệu thì trả
`None`, không trả 0** — số 0 đọc như "làm rồi mà kém", `None` đọc đúng như nó
là "chưa đủ dữ liệu để nói".

    Chốt thành công          Trong số cơ hội đã đóng, bao nhiêu thành công?
    Từ tín hiệu mạng xã hội  Cơ hội có thật sự đến từ việc nghe được nhu cầu,
                             hay toàn RM tự gõ tay?
    Thời gian tới liên hệ    Từ lúc có cơ hội tới lúc RM thật sự gửi gì đó.
    Cơ hội có kết quả        Vòng lặp có khép được không, hay cơ hội cứ nằm
                             mãi trong hộp thư không ai đụng tới?

Chỉ số thứ hai đáng nói riêng: nó là chỉ số duy nhất trong cả dự án đo trực
tiếp giá trị của đường nối Social Radar → RB Radar (`social/pipeline.py`
`_route_to_rb`). Nếu con số này bằng 0 thì toàn bộ phần Social Radar cho bán lẻ
(Phase 13) chỉ là hạ tầng chưa ai dùng.
"""
from .models import RBOpportunity

TOP_N = 10


def collect():
    return {
        "win_rate": _win_rate(),
        "from_signal": _from_signal(),
        "time_to_contact": _time_to_contact(),
        "resolution_rate": _resolution_rate(),
    }


def _win_rate():
    """Trong số cơ hội đã đóng (thành công hoặc không), bao nhiêu thành công."""
    closed = RBOpportunity.objects.filter(
        status__in=(RBOpportunity.STATUS_WON, RBOpportunity.STATUS_LOST))
    total = closed.count()
    if not total:
        return _empty("Chưa có cơ hội nào được chốt.")

    won = closed.filter(status=RBOpportunity.STATUS_WON).count()
    return {
        "value": round(won / total, 3),
        "label": "Chốt thành công",
        "detail": f"{won}/{total} cơ hội đã đóng là thành công",
        "unit": "ratio",
    }


def _from_signal():
    """Cơ hội có thật sự đến từ nghe được nhu cầu, hay toàn RM tự tạo tay.

    Đây là chỉ số đo trực tiếp giá trị của Social Radar cho nghiệp vụ bán lẻ —
    không có cơ hội nào tự sinh; nó luôn bắt nguồn từ `rb.routing.route_signal()`
    khi `signal` được gán, hoặc do RM tự gõ khi không.
    """
    total = RBOpportunity.objects.count()
    if not total:
        return _empty("Chưa có cơ hội bán lẻ nào.")

    from_signal = RBOpportunity.objects.filter(signal__isnull=False).count()
    return {
        "value": round(from_signal / total, 3),
        "label": "Cơ hội từ tín hiệu mạng xã hội",
        "detail": f"{from_signal}/{total} cơ hội bắt nguồn từ một bài đăng "
                  f"được Social Radar đọc được",
        "unit": "ratio",
    }


def _time_to_contact():
    """Từ lúc cơ hội xuất hiện tới lúc RM thật sự gửi lời chào đầu tiên."""
    durations = [
        (row.outreach_sent_at - row.created_at).total_seconds()
        for row in RBOpportunity.objects.filter(outreach_sent_at__isnull=False)
        .only("created_at", "outreach_sent_at")
    ]
    if not durations:
        return _empty("Chưa có cơ hội nào được liên hệ.")

    # Trung vị, không trung bình — cùng lý do với hiring/metrics.py: một cơ hội
    # bị bỏ quên hàng tuần đủ kéo lệch trung bình tới vô nghĩa.
    durations.sort()
    median = durations[len(durations) // 2]
    value, unit = _duration(median)
    return {
        "value": value,
        "label": "Thời gian tới liên hệ đầu tiên",
        "detail": f"trung vị trên {len(durations)} cơ hội",
        "unit": unit,
    }


def _duration(seconds):
    """Cùng bảng đổi đơn vị với `hiring/metrics.py` — "0.2 phút" là con số máy
    nói, chỉ số này nằm cạnh nó trên cùng một trang nên phải đọc cùng kiểu."""
    if seconds < 90:
        return round(seconds), "giây"
    if seconds < 7200:
        return round(seconds / 60), "phút"
    if seconds < 172800:
        return round(seconds / 3600, 1), "giờ"
    return round(seconds / 86400, 1), "ngày"


def _resolution_rate():
    """Bao nhiêu cơ hội đã ra tới kết quả cuối (thành công hoặc không), thay vì
    nằm mãi ở "mới"/"đang liên hệ" không ai đụng tới.

    Cùng câu hỏi với `hunt_conversion` bên Talent: vòng lặp có khép được không,
    hay dừng ở giữa. Khác `_win_rate` — chỉ số đó đo CHẤT LƯỢNG trong số đã
    đóng; chỉ số này đo có ĐÓNG được hay không, bất kể kết quả tốt hay xấu.
    """
    total = RBOpportunity.objects.count()
    if not total:
        return _empty("Chưa có cơ hội bán lẻ nào.")

    resolved = RBOpportunity.objects.filter(
        status__in=(RBOpportunity.STATUS_WON, RBOpportunity.STATUS_LOST)).count()
    return {
        "value": round(resolved / total, 3),
        "label": "Cơ hội có kết quả",
        "detail": f"{resolved}/{total} cơ hội đã ra tới kết quả cuối "
                  f"(thành công hoặc không)",
        "unit": "ratio",
    }


def _empty(reason):
    return {"value": None, "label": "", "detail": reason, "unit": ""}
