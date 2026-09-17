# -*- coding: utf-8 -*-
"""Ai PHẢI có mặt trong pool đọc sâu của Growth, bất kể điểm truy hồi — tất định.

Truy hồi xấp xỉ (khớp chữ, vector, RRF, cắt top-N) trả lời tốt "ai giống câu hỏi
nhất", nhưng có ba loại câu mà "giống nhất" là sai tiêu chí:

    tên riêng     "so sánh Nguyễn An và Trần Bình" — tên là định danh; lần này
                  lọt cả hai, lần sau rớt một là lỗi, không phải nhiễu
    điều kiện     "khách ở Hà Nội quan tâm vay mua nhà" — khi MỌI điều kiện bắt
    có cấu trúc   buộc là cột dữ liệu, người thoả có thể liệt kê CHÍNH XÁC; để
                  truy hồi xấp xỉ xếp họ xuống dưới hạng pool là bỏ sót người đúng
    cực trị       "khách có tín hiệu mới nhất", "khách đáng gọi nhất" — phải quét
    toàn kho      TOÀN phạm vi rồi lấy đầu; truy hồi chỉ nhìn vài chục người gần
                  câu hỏi nên "mới nhất" của nó là mới nhất trong mẫu, không phải
                  trong kho

Mọi người ghim vẫn đi qua cổng tuân thủ trong `retrieve` và vẫn được ③ đọc: ghim
nghĩa là "chắc chắn được đọc", không phải "chắc chắn được chọn".
"""
from __future__ import annotations

import re

from django.db.models import Max, OuterRef, Subquery

from core.answer import names

#: Tối đa bao nhiêu người ghim theo điều kiện có cấu trúc — phần còn lại của pool
#: dành cho truy hồi, để người thoả mà chỉ có bài đăng (chưa có quan tâm ghi nhận)
#: vẫn có chỗ.
STRUCTURED_PIN_LIMIT = 40

#: Growth thêm "khách" vào từ dừng của tên ("so sánh khách Nguyễn An…"). KHÔNG
#: thêm "hàng" — sau khi bỏ dấu nó là tên Hằng. Xem `core/answer/names.py`.
NAME_STOP = names.STOP | {"khach", "khách"}


def named_customers(query_plan, question, *, limit=8):
    """`[person_id]` khách hàng được gọi đích danh trong câu hỏi hoặc kế hoạch."""
    from .population import customers

    rows = customers().values_list("pk", "display_name")
    return names.match(query_plan, rows, question=question, limit=limit, stop=NAME_STOP)


def structured_pins(query_plan, *, user=None, limit=STRUCTURED_PIN_LIMIT):
    """Người thoả MỌI `must_have` bằng cột dữ liệu. Rỗng nếu có điều kiện cần đọc.

    Chỉ ghim khi TẤT CẢ điều kiện bắt buộc đều có cấu trúc: khi còn một điều kiện
    cần đọc ("mới kết hôn"), người thoả phần có cấu trúc ("ở Hà Nội") phần lớn
    KHÔNG thoả phần còn lại, và ghim họ là chiếm chỗ của người truy hồi tìm ra
    theo đúng điều kiện khó.
    """
    from ..models import ProductInterest
    from .count import effective_plan
    from .retrieve import eligible_people
    from .structured import analyse_plan

    if not getattr(query_plan, "must_have", None):
        return []
    analysis = analyse_plan(query_plan)
    if not analysis.all_covered:
        return []
    queryset = eligible_people(effective_plan(query_plan, analysis), user=user)
    for group in analysis.product_groups:
        queryset = queryset.filter(pk__in=ProductInterest.objects.filter(
            product__in=group).values("profile__person_id"))
    return list(queryset.order_by("-updated_at", "-pk").values_list("pk", flat=True)[:limit])


# ------------------------------------------------------------------ cực trị

ATTR_RECENCY = "recency"
ATTR_PRIORITY = "priority"

_RECENCY = re.compile(r"\b(moi nhat|gan day nhat|vua moi|som nhat|newest|latest|most recent)\b")
_PRIORITY = re.compile(r"\b(dang goi nhat|uu tien nhat|tiem nang nhat|diem cao nhat|"
                       r"nen goi truoc|goi truoc tien|dang lien he nhat|hot nhat)\b")


def superlative_attr(query_plan, question):
    """Câu hỏi có đòi CỰC TRỊ trên toàn phạm vi không, và theo thuộc tính nào."""
    from talent.vector_index import fold_text

    sort_key = fold_text((getattr(query_plan, "sort_by", None) or {}).get("key", ""))
    text = " ".join([fold_text(question), sort_key])
    if _RECENCY.search(text):
        return ATTR_RECENCY
    if _PRIORITY.search(text):
        return ATTR_PRIORITY
    return None


def superlative_ids(query_plan, attr, *, user=None, limit=20):
    """Top-`limit` khách trong TOÀN phạm vi đã qua cổng, xếp theo `attr`. CODE thuần.

    recency   thời điểm của bằng chứng MỚI NHẤT (tín hiệu RB, bài đăng, quan tâm)
    priority  điểm ưu tiên của đề xuất đang mở (`OpportunitySuggestion`), tức con
              số mà Hộp thư cơ hội đang hiển thị — cùng công thức `rb/scoring.py`
    """
    from people.models import Signal

    from ..models import OpportunitySuggestion
    from .count import effective_plan
    from .retrieve import eligible_people
    from .structured import analyse_plan

    analysis = analyse_plan(query_plan)
    plan = effective_plan(query_plan, analysis) if analysis.filters else query_plan
    queryset = eligible_people(plan, user=user)
    if attr == ATTR_PRIORITY:
        queryset = queryset.filter(pk__in=OpportunitySuggestion.objects.filter(
            status__in=OpportunitySuggestion.ACTIVE_STATUSES).values("person_id"))
        best = (OpportunitySuggestion.objects
                .filter(person_id__in=queryset.values("pk"),
                        status__in=OpportunitySuggestion.ACTIVE_STATUSES)
                .values("person_id").annotate(score=Max("priority_score"))
                .order_by("-score", "person_id")[:limit])
        return [row["person_id"] for row in best]

    # Truy vấn con cho từng nguồn, KHÔNG `Max` qua ba JOIN: ba quan hệ nhiều-nhiều
    # trong một truy vấn nhân dòng với nhau (50 bài × 30 tín hiệu × 5 quan tâm =
    # 7500 dòng trung gian cho MỘT khách).
    from social.models import SocialPost

    from ..models import ProductInterest

    def latest(model_qs, field):
        return Subquery(model_qs.order_by(f"-{field}").values(field)[:1])

    annotated = queryset.annotate(
        last_signal=latest(Signal.objects.filter(person_id=OuterRef("pk"),
                                                 domain=Signal.DOMAIN_RB), "observed_at"),
        last_post=latest(SocialPost.objects.filter(person_id=OuterRef("pk"),
                                                   posted_at__isnull=False), "posted_at"),
        last_interest=latest(ProductInterest.objects.filter(
            profile__person_id=OuterRef("pk")), "observed_at"),
    )
    rows = []
    for pid, signal, post, interest in annotated.values_list(
            "pk", "last_signal", "last_post", "last_interest").iterator(chunk_size=2000):
        moments = [m for m in (signal, post, interest) if m is not None]
        if moments:
            rows.append((max(moments), pid))
    # Lấy MAX ở Python: `Greatest` trong SQL xử lý NULL khác nhau giữa PostgreSQL
    # (bỏ qua) và SQLite (trả NULL) — cùng câu hỏi, hai môi trường, hai thứ tự.
    rows.sort(key=lambda row: (row[0], -row[1]), reverse=True)
    return [pid for _moment, pid in rows[:limit]]
