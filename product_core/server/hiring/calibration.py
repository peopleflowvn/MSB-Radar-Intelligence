# -*- coding: utf-8 -*-
"""Hiệu chỉnh xếp hạng theo đánh giá của Hiring Manager (Master Plan mục 21).

Kế hoạch nói rõ: **"Không cần fine-tuning model."** Và thật sự không cần — vì điểm
số vốn đã là tổ hợp có trọng số của các chiều tất định (xem `talent/scoring.py`),
nên "học từ phản hồi" ở đây chỉ là **chỉnh lại trọng số**.

Cách làm:

    HM đánh dấu vài hồ sơ Phù hợp / Không phù hợp
        ↓
    So điểm trung bình từng CHIỀU giữa hai nhóm
        ↓
    Chiều nào phân tách hai nhóm rõ nhất thì tăng trọng số
        ↓
    Xếp lại

Ba tính chất khiến cách này hợp với bài toán:

  • **Giải thích được.** Nói được thành lời: "bạn thiên về người khớp kỹ năng và
    ít quan tâm nơi ở, nên tôi tăng trọng số kỹ năng." Fine-tuning không nói được.
  • **Tất định.** Cùng phản hồi cho cùng trọng số.
  • **Rẻ.** Vài phép trung bình, không gọi LLM, không huấn luyện gì.

Giới hạn phải biết: cách này chỉ chỉnh được **mức quan trọng của các chiều đã có**.
Nếu HM loại người vì lý do chưa có chiều nào đo được (ví dụ "công ty này quá nhỏ"),
nó không học được — và không nên giả vờ là học được.
"""
import logging

from talent import scoring

log = logging.getLogger(__name__)

# Số phản hồi tối thiểu mỗi nhóm. Dưới mức này thì trung bình chỉ là nhiễu, và
# chỉnh trọng số theo nhiễu còn tệ hơn không chỉnh.
MIN_PER_GROUP = 2

# Trọng số được nhân trong khoảng này. Chặn hai đầu để một loạt phản hồi lệch
# không xoá sổ hoàn toàn một chiều, cũng không để một chiều nuốt hết điểm.
MIN_FACTOR = 0.4
MAX_FACTOR = 2.0

# Chiều phân tách hoàn hảo (Phù hợp toàn 1.0, Không phù hợp toàn 0.0) sẽ được
# nhân tối đa. Hệ số này quyết định độ nhạy.
SENSITIVITY = 1.0


class Calibration:
    def __init__(self, weights, insights, good_count, bad_count, applied):
        self.weights = weights
        self.insights = insights          # mô tả bằng lời, cho người dùng đọc
        self.good_count = good_count
        self.bad_count = bad_count
        self.applied = applied

    def as_dict(self):
        return {"weights": self.weights, "insights": self.insights,
                "good_count": self.good_count, "bad_count": self.bad_count,
                "applied": self.applied}


def calibrate(hiring_need):
    """Học trọng số từ phản hồi của HM trên một nhu cầu tuyển dụng."""
    from .models import Candidacy

    rows = list(hiring_need.candidacies.filter(state__in=Candidacy.FEEDBACK_STATES))
    # Shortlist tính là tín hiệu dương, và là tín hiệu MẠNH NHẤT — HM sẵn sàng
    # nhờ recruiter gọi người đó. Bỏ qua thì thao tác tự nhiên nhất (chấm phù
    # hợp rồi đưa vào shortlist) lại XOÁ mất chính tín hiệu dương mà hiệu chỉnh
    # cần, và HM càng dùng đúng thì càng học được ít.
    good = [r for r in rows if r.state != Candidacy.STATE_NOT_FIT]
    bad = [r for r in rows if r.state == Candidacy.STATE_NOT_FIT]

    if len(good) < MIN_PER_GROUP or len(bad) < MIN_PER_GROUP:
        return Calibration(
            weights={}, applied=False, good_count=len(good), bad_count=len(bad),
            insights=[f"Cần ít nhất {MIN_PER_GROUP} hồ sơ ở mỗi nhóm để hiệu chỉnh; "
                      f"hiện có {len(good)} phù hợp và {len(bad)} không phù hợp."])

    base = scoring.weights()
    good_means = _dimension_means(good)
    bad_means = _dimension_means(bad)

    weights, insights = {}, []
    for key, weight in base.items():
        if key not in good_means or key not in bad_means:
            # Chiều này không được chấm ở các hồ sơ đã đánh giá (vì tiêu chí
            # không nhắc tới nó). Không có dữ liệu thì giữ nguyên.
            weights[key] = weight
            continue

        # Khoảng cách trung bình giữa hai nhóm: dương nghĩa là chiều này giúp
        # phân biệt đúng hướng, âm nghĩa là HM chọn NGƯỢC với chiều đó.
        gap = good_means[key] - bad_means[key]
        factor = max(MIN_FACTOR, min(MAX_FACTOR, 1.0 + gap * SENSITIVITY))
        weights[key] = round(weight * factor, 4)

        if factor >= 1.25:
            insights.append(f"Bạn thiên về hồ sơ mạnh ở “{_label(key)}” — tăng trọng số.")
        elif factor <= 0.75:
            insights.append(f"“{_label(key)}” không phải thứ bạn dựa vào — giảm trọng số.")

    # Chuẩn hoá về tổng cũ để điểm giữ nguyên thang 0..1 và so sánh được giữa các
    # lần hiệu chỉnh.
    total_before, total_after = sum(base.values()), sum(weights.values())
    if total_after > 0:
        weights = {k: round(v * total_before / total_after, 4)
                   for k, v in weights.items()}

    if not insights:
        insights.append("Phản hồi chưa cho thấy thiên hướng rõ rệt; "
                        "trọng số gần như giữ nguyên.")

    return Calibration(weights=weights, insights=insights, applied=True,
                       good_count=len(good), bad_count=len(bad))


def _dimension_means(rows):
    """Điểm trung bình từng chiều trong một nhóm, lấy từ ảnh chụp lúc đề xuất."""
    totals, counts = {}, {}
    for row in rows:
        for dimension in row.dimensions_snapshot or []:
            key = dimension.get("key")
            if not key:
                continue
            totals[key] = totals.get(key, 0.0) + float(dimension.get("score") or 0)
            counts[key] = counts.get(key, 0) + 1
    return {key: totals[key] / counts[key] for key in totals if counts[key]}


LABELS = {
    "skills": "kỹ năng", "title": "chức danh", "experience": "kinh nghiệm",
    "location": "nơi ở", "industry": "lĩnh vực từng làm",
    "freshness": "độ mới của hồ sơ", "reachability": "khả năng liên hệ",
}


def _label(key):
    return LABELS.get(key, key)


def rank(people_scores, weights):
    """Xếp lại theo trọng số đã hiệu chỉnh.

    Chấm lại từ các chiều đã có thay vì gọi lại bộ chấm điểm: các chiều là dữ
    kiện về ứng viên, chỉ có trọng số thay đổi. Chấm lại sẽ tốn công vô ích và
    có thể ra kết quả khác nếu dữ liệu vừa đổi giữa chừng.
    """
    ranked = []
    for person, scored in people_scores:
        dimensions = scored.get("dimensions") or []
        total_weight = sum(weights.get(d["key"], d["weight"]) for d in dimensions) or 1.0
        total = sum(d["score"] * weights.get(d["key"], d["weight"])
                    for d in dimensions) / total_weight
        adjusted = dict(scored, score=round(total, 4))
        ranked.append((person, adjusted))
    ranked.sort(key=lambda item: item[1]["score"], reverse=True)
    return ranked
