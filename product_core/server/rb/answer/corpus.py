# -*- coding: utf-8 -*-
"""Số liệu TOÀN KHO khách hàng — thứ ②③ không bao giờ nhìn thấy.

②③ đọc kỹ vài chục khách hợp nhất với câu hỏi. Cách đó trả lời tốt "ai cần vay
mua nhà", nhưng KHÔNG THỂ trả lời "kho có bao nhiêu khách" hay "khách mình tập
trung vào sản phẩm nào": vài chục trên hàng nghìn người không nói được gì về cả
kho, và LLM không đếm được. Trước file này Growth vẫn trả lời những câu đó —
bằng số người trong pool vừa đọc, như thể là số của toàn kho.

Mọi số ở đây là truy vấn CSDL: tất định, rẻ, và LUÔN kèm mẫu số. Một con số
"320 khách quan tâm vay mua nhà" mà không nói trên bao nhiêu khách, và đếm theo
định nghĩa nào, là con số gây hiểu nhầm.
"""
from __future__ import annotations

import logging

from django.db.models import Count, Q
from django.utils import timezone

log = logging.getLogger(__name__)

TOP_N = 10


def _label(product):
    from ..models import PRODUCT_LABELS
    return PRODUCT_LABELS.get(product, product)


def overview(*, scope_queryset=None):
    """Số liệu tổng thể trên `scope_queryset` (mặc định: toàn bộ khách hàng)."""
    from people.models import Signal
    from social.models import SocialPost

    from ..models import OpportunitySuggestion, ProductInterest, RBOpportunity, RBProfile
    from .population import customers, do_not_contact_ids

    people = scope_queryset if scope_queryset is not None else customers()
    ids = people.values("pk")
    total = people.count()
    now = timezone.now()

    profiles = RBProfile.objects.filter(person_id__in=ids)
    segments = list(profiles.exclude(segment="").values("segment")
                    .annotate(n=Count("id")).order_by("-n"))
    lead = list(profiles.values("lead_status").annotate(n=Count("id")).order_by("-n"))
    occupations = list(profiles.exclude(occupation="").values("occupation")
                       .annotate(n=Count("id")).order_by("-n")[:TOP_N])
    locations = list(people.exclude(location="").values("location")
                     .annotate(n=Count("id")).order_by("-n")[:TOP_N])
    interests = list(ProductInterest.objects.filter(profile__person_id__in=ids)
                     .values("product").annotate(n=Count("profile__person_id", distinct=True))
                     .order_by("-n"))
    open_opps = list(RBOpportunity.objects.filter(person_id__in=ids,
                                                  status__in=RBOpportunity.OPEN_STATUSES)
                     .values("product").annotate(n=Count("person_id", distinct=True))
                     .order_by("-n"))

    def people_with_signal(days):
        since = now - timezone.timedelta(days=days)
        signal = Signal.objects.filter(domain=Signal.DOMAIN_RB, observed_at__gte=since
                                       ).values("person_id")
        posts = SocialPost.objects.filter(posted_at__gte=since).values("person_id")
        return people.filter(Q(pk__in=signal) | Q(pk__in=posts)).count()

    return {
        "tong_khach_hang": total,
        "dinh_nghia": ("người có hồ sơ bán lẻ, hoặc tín hiệu bán lẻ, hoặc bài mạng xã "
                       "hội đã gắn — không tính ứng viên tuyển dụng thuần"),
        "co_lien_he": people.exclude(primary_phone="", primary_email="").count(),
        "yeu_cau_khong_lien_he": people.filter(pk__in=do_not_contact_ids()).count(),
        "da_co_nguoi_phu_trach": profiles.filter(sales_owner__isnull=False).count(),
        "chua_ai_phu_trach": total - profiles.filter(sales_owner__isnull=False).count(),
        "co_tin_hieu_30_ngay": people_with_signal(30),
        "co_tin_hieu_90_ngay": people_with_signal(90),
        "de_xuat_dang_mo": OpportunitySuggestion.objects.filter(
            person_id__in=ids, status__in=OpportunitySuggestion.ACTIVE_STATUSES).count(),
        "phan_khuc": [{"gia_tri": r["segment"], "so_khach": r["n"]} for r in segments],
        "trang_thai": [{"gia_tri": r["lead_status"], "so_khach": r["n"]} for r in lead],
        "quan_tam_san_pham": [{"san_pham": _label(r["product"]), "so_khach": r["n"]}
                              for r in interests],
        "co_hoi_dang_mo_theo_san_pham": [{"san_pham": _label(r["product"]), "so_khach": r["n"]}
                                         for r in open_opps],
        "nghe_nghiep_pho_bien": [{"gia_tri": r["occupation"], "so_khach": r["n"]}
                                 for r in occupations],
        "khu_vuc_pho_bien": [{"gia_tri": r["location"], "so_khach": r["n"]} for r in locations],
        "do_phu": {
            "co_phan_khuc": profiles.exclude(segment="").count(),
            "co_nghe_nghiep": profiles.exclude(occupation="").count(),
            "co_khu_vuc": people.exclude(location="").count(),
        },
    }


def facts_for_prompt(*, scope_queryset=None, scope_label="toàn kho khách hàng"):
    """Khối văn bản cho ⑤ của câu tổng hợp. Rỗng khi lỗi — không làm hỏng lượt."""
    import json
    try:
        data = overview(scope_queryset=scope_queryset)
    except Exception:                              # noqa: BLE001
        log.warning("rb.answer.corpus: không lấy được số liệu kho", exc_info=True)
        return ""
    return (f"SỐ LIỆU {scope_label.upper()} (truy vấn CSDL, CHÍNH XÁC — mọi con số "
            "về quy mô, tỷ lệ, phân bố trong câu trả lời PHẢI lấy từ đây, không được "
            "suy từ danh sách khách vừa đọc; luôn nói rõ mẫu số và độ phủ):\n"
            + json.dumps(data, ensure_ascii=False, indent=1))
