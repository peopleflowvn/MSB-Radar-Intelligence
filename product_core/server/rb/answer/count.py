# -*- coding: utf-8 -*-
"""Câu ĐẾM của Growth — chính xác khi làm được, dán nhãn ước lượng khi không.

Hai đường, chọn bằng `structured.analyse_plan`, KHÔNG bằng LLM:

    CHÍNH XÁC   mọi điều kiện diễn đạt được bằng cột dữ liệu → một câu SQL trên
                toàn phạm vi. "Bao nhiêu khách ở Hà Nội quan tâm vay mua nhà."
    ƯỚC LƯỢNG   còn một điều kiện cần đọc nội dung ("mới kết hôn") → lọc trước
                bằng phần có cấu trúc, đọc bằng chứng của nhóm gần câu hỏi nhất,
                và nói RÕ đã đọc bao nhiêu trên bao nhiêu. Không bao giờ trình bày
                số người thoả trong nhóm đã đọc như thể là số của toàn kho.

Trước file này Growth không phân biệt hai đường: mọi câu đếm đi qua ②③④ và trả
số người thoả trong vài chục hồ sơ vừa đọc, không kèm mẫu số.

Văn bản trả lời do CODE viết, không qua LLM: câu trả lời đếm chỉ gồm con số, định
nghĩa và mẫu số — đưa nó cho model viết lại là mở đường cho model làm tròn, đổi
đơn vị, hay bỏ mất chữ "ước lượng".
"""
from __future__ import annotations

from dataclasses import replace

from .population import scope_queryset

SCOPE_LABEL = {
    "portfolio": "danh mục anh/chị đang phụ trách",
    "whitespace": "nhóm khách chưa ai phụ trách",
}

FILTER_LABEL = {
    "tinh_thanh": lambda v: f"ở {v}",
    "phan_khuc": lambda v: f"phân khúc {v}",
    "cap_bac": lambda v: "cấp quản lý" if v == "manager" else "cấp cao",
    "phai_co_lien_he": lambda v: "có số điện thoại hoặc email",
    "loai_co_hoi_dang_mo": lambda v: "chưa có cơ hội đang mở",
    "tin_hieu_trong_ngay": lambda v: f"có tín hiệu trong {v} ngày gần đây",
}


def _scope_label(shape):
    return SCOPE_LABEL.get(shape, "toàn kho khách hàng")


def effective_plan(query_plan, analysis):
    """Kế hoạch có thêm bộ lọc cứng rút ra từ `must_have` (bổ sung, không ghi đè `bo_loc`)."""
    return replace(query_plan, filters={**analysis.filters, **(query_plan.filters or {})})


def definition(plan, analysis):
    from ..models import PRODUCT_LABELS
    parts = [FILTER_LABEL[k](v) for k, v in (plan.filters or {}).items() if k in FILTER_LABEL]
    for group in analysis.product_groups:
        labels = [PRODUCT_LABELS.get(p, p).lower() for p in group]
        parts.append("có quan tâm " + " hoặc ".join(labels) + " đã ghi nhận")
    return parts


def exact(query_plan, analysis, *, user=None):
    """SQL trên toàn phạm vi. Chỉ gọi khi `analysis.all_covered`."""
    from ..models import ProductInterest
    from .retrieve import eligible_people

    plan = effective_plan(query_plan, analysis)
    matched = eligible_people(plan, user=user)          # đã loại khách không liên hệ
    for group in analysis.product_groups:               # AND giữa các nhóm, OR trong nhóm
        matched = matched.filter(pk__in=ProductInterest.objects.filter(
            product__in=group).values("profile__person_id"))
    return {
        "method": "sql", "exact": True, "status": "FACT",
        "matched": matched.count(),
        "scope_total": scope_queryset(plan.shape, user).count(),
        "scope": plan.shape, "scope_label": _scope_label(plan.shape),
        "definition": definition(plan, analysis),
        "counts_recorded_interest_only": bool(analysis.product_groups),
    }


def inference(query_plan, analysis, stats, *, user=None):
    from .retrieve import eligible_people

    plan = effective_plan(query_plan, analysis)
    population = eligible_people(plan, user=user).count()
    reviewed = int(stats.get("judged", 0) or 0)
    return {
        "method": "evidence_review", "exact": False, "status": "INFERENCE",
        "matched_in_reviewed": int(stats.get("relevant", 0) or 0),
        "reviewed": reviewed, "population_after_structured_filters": population,
        "not_reviewed": max(0, population - reviewed),
        "scope_total": scope_queryset(plan.shape, user).count(),
        "scope": plan.shape, "scope_label": _scope_label(plan.shape),
        "definition": definition(plan, analysis),
        "needs_reading": list(analysis.uncovered),
        "read_failed": bool(stats.get("read_failed")),
    }


def text_for(count):
    scope = count["scope_label"]
    conditions = "; ".join(count["definition"])
    if count["exact"]:
        if count["scope"] == "portfolio" and count["scope_total"] == 0:
            return ("Chưa đếm được: không xác định được danh mục của anh/chị, hoặc "
                    "anh/chị chưa phụ trách khách nào.")
        head = (f"Có **{count['matched']}** khách hàng thoả: {conditions}."
                if conditions else f"Có **{count['matched']}** khách hàng.")
        lines = [head,
                 f"Trên tổng {count['scope_total']} khách trong {scope}. Đếm chính xác "
                 "bằng dữ liệu hệ thống, không tính khách đã yêu cầu không liên hệ."]
        if count["counts_recorded_interest_only"]:
            lines.append("Lưu ý: chỉ tính quan tâm sản phẩm ĐÃ được ghi nhận vào hồ sơ; "
                         "khách mới nhắc tới trong bài đăng mà hệ thống chưa xử lý thì "
                         "chưa nằm trong con số này.")
        return "\n\n".join(lines)

    if count["read_failed"]:
        return ("Chưa đếm được lúc này: dịch vụ AI đang gián đoạn nên không đọc được "
                "bằng chứng. Đây KHÔNG phải kết luận là không có khách nào.")
    needs = "; ".join(f"“{p}”" for p in count["needs_reading"])
    base = (f"trong {count['population_after_structured_filters']} khách "
            + (f"thoả {conditions}" if conditions else f"thuộc {scope}"))
    return "\n\n".join([
        f"Không đếm chính xác được trên toàn kho: điều kiện {needs} cần đọc nội dung "
        "bằng chứng, không có sẵn trong dữ liệu có cấu trúc.",
        f"Mình đã đọc bằng chứng của **{count['reviewed']}** khách gần câu hỏi nhất "
        f"{base}: **{count['matched_in_reviewed']}** người thoả.",
        f"Còn {count['not_reviewed']} khách chưa đọc, nên con số thật có thể lớn hơn. "
        "Đây là ước lượng từ phần đã đọc, không phải số đếm toàn kho.",
    ])
