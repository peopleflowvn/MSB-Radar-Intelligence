# -*- coding: utf-8 -*-
"""Từ tín hiệu tài chính tới cơ hội bán hàng (Master Plan mục 32, PHASE 13).

Ví dụ trong kế hoạch:

    "Sắp đi Nhật, nên đổi tiền hay dùng thẻ?"
        ↓
    Nhu cầu: đi nước ngoài / thanh toán quốc tế
        ↓
    Sản phẩm gợi ý: Ngoại tệ · Thẻ tín dụng · Bảo hiểm du lịch

Hai việc tách bạch, và tách bạch có lý do:

    **suggest_products()**   đoán nhóm sản phẩm từ nội dung — dò từ khoá, tất định
    **create_opportunity()** biến thành việc cần làm cho RM

Vì sao gợi ý sản phẩm **không** gọi LLM: danh mục sản phẩm ngân hàng là hữu hạn
và có tên gọi cố định, còn từ vựng khách hàng dùng để nói về chúng cũng hữu hạn
("vay mua nhà", "trả góp căn hộ"). Một bảng từ khoá đọc được, sửa được và giải
thích được ăn đứt một lượt gọi mô hình ở đây — và quan trọng hơn, nó **không bao
giờ gợi ý một sản phẩm MSB không bán**.

Ranh giới đạo đức giữ nguyên như thư tiếp cận bên tuyển dụng: hệ thống tạo ra
**việc để RM xem**, không tự nhắn gì cho khách.
"""
import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import (PRODUCT_AUTO_LOAN, PRODUCT_CONSUMER_LOAN,
                     PRODUCT_CREDIT_CARD, PRODUCT_FX, PRODUCT_INSURANCE,
                     PRODUCT_INVESTMENT, PRODUCT_MORTGAGE, PRODUCT_PAYROLL,
                     PRODUCT_SAVINGS, ProductInterest, RBOpportunity, RBProfile)

log = logging.getLogger(__name__)

#: Dưới mức này thì không tạo cơ hội. Cao hơn hẳn ngưỡng của tuyển dụng —
#: mời khách vay tiền khi họ không hỏi là chuyện khác hẳn về mặt cảm nhận.
MIN_CONFIDENCE = 0.5

#: Số nhóm sản phẩm tối đa cho một bài. Gợi ý sáu thứ cùng lúc thì RM không biết
#: bắt đầu từ đâu, và lời chào sẽ nghe như rao hàng.
MAX_PRODUCTS = 3

# (nhóm sản phẩm, các cụm từ, nhu cầu diễn đạt bằng lời của khách)
PRODUCT_HINTS = [
    (PRODUCT_MORTGAGE,
     ["mua nhà", "mua căn hộ", "mua chung cư", "vay mua đất", "xây nhà",
      "sửa nhà", "trả góp căn hộ"],
     "Đang tính mua hoặc sửa nhà"),
    (PRODUCT_AUTO_LOAN,
     ["mua ô tô", "mua xe hơi", "mua xe", "trả góp xe", "vay mua xe"],
     "Đang tính mua xe"),
    (PRODUCT_CONSUMER_LOAN,
     ["vay tiêu dùng", "vay tín chấp", "cần vay gấp", "vay nóng", "vay tiền"],
     "Cần một khoản vay tiêu dùng"),
    (PRODUCT_CREDIT_CARD,
     ["thẻ tín dụng", "mở thẻ", "trả góp 0%", "hoàn tiền", "cashback"],
     "Quan tâm thẻ tín dụng"),
    (PRODUCT_SAVINGS,
     ["gửi tiết kiệm", "lãi suất tiết kiệm", "sổ tiết kiệm", "đáo hạn",
      "gửi ngân hàng"],
     "Đang tìm chỗ gửi tiền"),
    (PRODUCT_INVESTMENT,
     ["đầu tư", "chứng chỉ quỹ", "trái phiếu", "cổ phiếu", "sinh lời"],
     "Quan tâm kênh đầu tư"),
    (PRODUCT_INSURANCE,
     ["bảo hiểm", "bảo hiểm nhân thọ", "bảo hiểm sức khoẻ", "bảo hiểm du lịch"],
     "Quan tâm bảo hiểm"),
    (PRODUCT_FX,
     ["đổi tiền", "ngoại tệ", "chuyển tiền quốc tế", "đi nhật", "đi hàn",
      "đi du lịch nước ngoài", "du học", "thanh toán quốc tế", "đi công tác nước ngoài"],
     "Sắp có chi tiêu ở nước ngoài"),
    (PRODUCT_PAYROLL,
     ["tài khoản lương", "nhận lương qua", "công ty trả lương"],
     "Có thể chuyển tài khoản lương"),
]

# Đi nước ngoài thường kéo theo cả ba thứ này — đúng ví dụ trong Master Plan.
COMPANION = {PRODUCT_FX: [PRODUCT_CREDIT_CARD, PRODUCT_INSURANCE]}


class Suggestion:
    def __init__(self, product, confidence, need, matched):
        self.product = product
        self.confidence = confidence
        self.need = need
        self.matched = matched      # cụm từ nào trong bài dẫn tới gợi ý này

    def as_dict(self):
        return {"product": self.product, "confidence": self.confidence,
                "need": self.need, "matched": self.matched}


def suggest_products(text, base_confidence=0.6):
    """Đoán nhóm sản phẩm từ nội dung. Tất định, giải thích được.

    `base_confidence` là mức tin cậy của tín hiệu gốc — gợi ý sản phẩm không thể
    chắc chắn hơn chính tín hiệu đã sinh ra nó.
    """
    lower = str(text or "").lower()
    found = []

    for product, hints, need in PRODUCT_HINTS:
        matched = [hint for hint in hints if hint in lower]
        if not matched:
            continue
        # Khớp nhiều cụm thì chắc hơn, nhưng không bao giờ vượt tín hiệu gốc.
        bonus = min(0.2, 0.1 * (len(matched) - 1))
        found.append(Suggestion(product, round(min(base_confidence + bonus, 1.0), 3),
                                need, matched))

    direct = {s.product for s in found}
    for product in list(direct):
        for extra in COMPANION.get(product, []):
            if extra in direct:
                continue
            need = next(n for p, _h, n in PRODUCT_HINTS if p == extra)
            # Sản phẩm đi kèm chỉ là suy luận, nên tin cậy thấp hơn hẳn và phải
            # nói rõ là suy ra, không phải khách viết ra.
            found.append(Suggestion(extra, round(base_confidence * 0.6, 3),
                                    need, ["suy ra từ nhu cầu chính"]))
            direct.add(extra)

    found.sort(key=lambda s: s.confidence, reverse=True)
    return found[:MAX_PRODUCTS]


def profile_for(person, create=True):
    """Hồ sơ bán lẻ của một người. Không chép gì từ `Person` sang."""
    if create:
        profile, _ = RBProfile.objects.get_or_create(person=person)
        return profile
    return getattr(person, "rb_profile", None)


def record_interests(person, suggestions, source="", evidence=None, observed_at=None):
    """Ghi nhận quan tâm sản phẩm. Chỉ nâng mức tin cậy, không hạ."""
    profile = profile_for(person)
    observed_at = observed_at or timezone.now()
    rows = []

    for suggestion in suggestions:
        interest, created = ProductInterest.objects.get_or_create(
            profile=profile, product=suggestion.product,
            defaults={"confidence": suggestion.confidence,
                      "evidence": dict(evidence or {}, matched=suggestion.matched),
                      "source": source[:40], "observed_at": observed_at})
        if not created and suggestion.confidence > interest.confidence:
            # Chỉ nâng: một bài mới nhắc thoáng qua không được xoá đi bằng chứng
            # mạnh hơn từ lần trước.
            interest.confidence = suggestion.confidence
            interest.evidence = dict(evidence or {}, matched=suggestion.matched)
            interest.observed_at = observed_at
            interest.save(update_fields=["confidence", "evidence", "observed_at"])
        rows.append(interest)
    return rows


def create_opportunities(person, suggestions, signal=None, evidence=None):
    """Biến gợi ý thành việc cần làm cho RM.

    Không tạo trùng: đã có cơ hội đang mở cho cùng sản phẩm thì cập nhật mức tin
    cậy, không đẻ thêm một dòng nữa trong hộp thư.
    """
    made = []
    for suggestion in suggestions:
        if suggestion.confidence < MIN_CONFIDENCE:
            continue

        existing = RBOpportunity.objects.filter(
            person=person, product=suggestion.product,
            status__in=RBOpportunity.OPEN_STATUSES).first()
        if existing is not None:
            if suggestion.confidence > existing.confidence:
                existing.confidence = suggestion.confidence
                existing.evidence = evidence or existing.evidence
                existing.save(update_fields=["confidence", "evidence", "updated_at"])
            made.append(existing)
            continue

        try:
            with transaction.atomic():
                created = RBOpportunity.objects.create(
                    person=person, product=suggestion.product,
                    need=suggestion.need, confidence=suggestion.confidence,
                    evidence=dict(evidence or {}, matched=suggestion.matched),
                    suggested_action=_next_action(suggestion.product),
                    signal=signal)
        except IntegrityError:
            created = RBOpportunity.objects.get(
                person=person, product=suggestion.product,
                status__in=RBOpportunity.OPEN_STATUSES)
        made.append(created)
    return made


NEXT_ACTIONS = {
    PRODUCT_MORTGAGE: "Gọi hỏi kế hoạch mua nhà và khoản đã có sẵn.",
    PRODUCT_AUTO_LOAN: "Gọi hỏi dòng xe và thời điểm dự định mua.",
    PRODUCT_CONSUMER_LOAN: "Gọi tìm hiểu nhu cầu và khả năng trả nợ.",
    PRODUCT_CREDIT_CARD: "Giới thiệu hạng thẻ phù hợp mức chi tiêu.",
    PRODUCT_SAVINGS: "Gửi biểu lãi suất kỳ hạn đang áp dụng.",
    PRODUCT_INVESTMENT: "Mời tham gia buổi tư vấn danh mục.",
    PRODUCT_INSURANCE: "Hỏi nhu cầu bảo vệ cho gia đình.",
    PRODUCT_FX: "Tư vấn hạn mức ngoại tệ và thẻ dùng ở nước ngoài.",
    PRODUCT_PAYROLL: "Hỏi công ty đang trả lương qua ngân hàng nào.",
}


def _next_action(product):
    return NEXT_ACTIONS.get(product, "Gọi tìm hiểu thêm nhu cầu.")


def route_signal(signal):
    """Tín hiệu tài chính → quan tâm sản phẩm + **đề xuất** cơ hội.

    Đây là chỗ Social Radar nối vào RB Radar. Trước Phase 12, tín hiệu `rb` sinh
    ra rồi nằm im vì không có nghiệp vụ nào nhận.

    **Đổi hành vi (Master Plan mục 33):** hàm này từng tạo thẳng `RBOpportunity`.
    Giờ nó tạo `OpportunitySuggestion` và dừng lại đó — RM phải bấm nhận thì mới
    thành cơ hội thật. Lý do đầy đủ nằm trong docstring của `suggestions.py`;
    ngắn gọn là: hộp thư của RM chỉ nên chứa việc đã có người nhận, còn thứ máy
    đoán phải nằm ở một chỗ khác để RM chọn.

    `create_opportunities()` bên dưới **vẫn còn nguyên và vẫn được dùng** cho
    luồng RM tự tạo cơ hội thủ công từ Profile 360 — ở đó người đã quyết định
    rồi, không cần trạm dừng nữa.
    """
    from . import suggestions as suggestions_module

    made = suggestions_module.from_signal(signal)
    if not made:
        log.info("Tín hiệu %s không sinh đề xuất nào", signal.pk)
    return made
