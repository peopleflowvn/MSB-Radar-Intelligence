# -*- coding: utf-8 -*-
"""Bức tranh TỔNG THỂ của kho — thứ ②③ không bao giờ nhìn thấy.

②③ là đường truy hồi: chúng đọc kỹ vài chục hồ sơ hợp nhất với câu hỏi. Cách đó
trả lời rất tốt "ai làm quan hệ khách hàng", nhưng **không thể** trả lời "kho có
những ngành nào" hay "tổng quan kho ứng viên" — 40 trên 786 hồ sơ không nói được
gì về toàn kho, và LLM thì không đếm được.

Đo trên production (ảnh người dùng gửi): hỏi *"thế bạn có cv những ngành nào"*,
Radar trả lời *"không có dữ liệu thực tế về danh sách ngành nghề"* — trong khi
kho có 786 hồ sơ. Nó không nói dối có chủ đích; nó thật sự **không có đường nào
để nhìn toàn kho**.

Module này lấp đúng chỗ đó bằng truy vấn tổng hợp trên CSDL: rẻ, tất định, và
luôn kèm ĐỘ PHỦ. Độ phủ là phần bắt buộc — trường có cấu trúc trong kho này phần
lớn để trống (chính lý do bộ chấm điểm cũ trả 0 cho mọi người), nên một bảng xếp
hạng "ngành phổ biến nhất" mà không nói nó dựa trên bao nhiêu hồ sơ là con số
gây hiểu nhầm.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from collections import Counter

from django.db.models import Count, Q

log = logging.getLogger(__name__)

#: Số giá trị phổ biến giữ lại cho mỗi trường.
TOP_N = 12
#: Dưới mức phủ này thì một bảng xếp hạng là gây hiểu nhầm hơn là hữu ích.
MEANINGFUL_COVERAGE = 0.05


def _top_from_json_list(queryset, field, limit=TOP_N):
    """Đếm giá trị trong một JSONField kiểu danh sách (skills, industries).

    Đếm ở Python chứ không trong CSDL: `JSONField` chứa danh sách nên không
    `GROUP BY` thẳng được, mà kho ở quy mô nghìn hồ sơ thì quét một vòng vẫn rẻ
    hơn nhiều so với việc dựng bảng phụ chỉ để thống kê.
    """
    counter = Counter()
    filled = 0
    for values in queryset.values_list(field, flat=True).iterator(chunk_size=500):
        if not values:
            continue
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        # Count people with a value, not duplicate array entries in one profile.
        cleaned = list(dict.fromkeys(" ".join(v.split()) for v in values
                                     if isinstance(v, str) and v.strip()))
        if not cleaned:
            continue
        filled += 1
        counter.update(cleaned)
    return counter.most_common(limit), filled


def _top_from_char(queryset, field, limit=TOP_N):
    rows = (queryset.exclude(**{field: ""}).exclude(**{f"{field}__isnull": True})
            .values(field).annotate(n=Count("id")).order_by("-n")[:limit])
    filled = queryset.exclude(**{field: ""}).exclude(**{f"{field}__isnull": True}).count()
    return [(row[field], row["n"]) for row in rows], filled


def _block(label, pairs, filled, total):
    """Một mục thống kê kèm độ phủ — độ phủ KHÔNG được phép thiếu."""
    coverage = (filled / total) if total else 0.0
    return {
        "label": label,
        "top": [{"value": value, "count": count} for value, count in pairs],
        "filled": filled,
        "total": total,
        "coverage": round(coverage, 3),
        "meaningful": coverage >= MEANINGFUL_COVERAGE and bool(pairs),
    }


def overview():
    """Số liệu tổng thể của kho. Tất định, không gọi LLM."""
    from people.models import Document, Person
    from talent.models import CVChunk, PersonSearchDocument, TalentProfile

    # "Tổng hồ sơ" phải là số người ĐÃ ỨNG TUYỂN. Đếm cả người tham chiếu bóc
    # từ CV người khác sẽ thổi phồng mẫu số và kéo tụt MỌI tỷ lệ phủ bên dưới
    # (họ không có TalentProfile, không có CV, không có kỹ năng).
    people = Person.applicants()
    total_people = people.count()
    profiles = TalentProfile.objects.filter(person__merged_into__isnull=True,
                                            person__is_applicant=True)
    total_profiles = profiles.count()

    with_cv = (Document.objects.filter(person__in=people)
               .values("person_id").distinct().count())
    indexed = PersonSearchDocument.objects.filter(
        person__in=people).count()
    chunks = CVChunk.objects.filter(person__in=people).count()

    industries, industries_filled = _top_from_json_list(profiles, "industries")
    skills, skills_filled = _top_from_json_list(profiles, "skills")
    titles, titles_filled = _top_from_char(profiles, "current_title")
    companies, companies_filled = _top_from_char(profiles, "current_company")
    locations, locations_filled = _top_from_char(profiles, "location")
    desired_locations, desired_locations_filled = _top_from_char(profiles, "desired_location")
    seniority, seniority_filled = _top_from_char(profiles, "seniority")

    experience = profiles.aggregate(
        co_so_lieu=Count("id", filter=Q(years_experience__isnull=False)))
    buckets = []
    for label, low, high in (("dưới 1 năm", 0, 1), ("từ 1 đến dưới 3 năm", 1, 3),
                             ("từ 3 đến dưới 5 năm", 3, 5), ("từ 5 đến dưới 10 năm", 5, 10),
                             ("từ 10 năm", 10, None)):
        bucket = profiles.filter(years_experience__gte=low)
        if high is not None:
            bucket = bucket.filter(years_experience__lt=high)
        buckets.append({
            "label": label,
            "count": bucket.count(),
        })

    return {
        "quy_mo": {
            "tong_ho_so": total_people,
            "co_ho_so_talent": total_profiles,
            "co_file_cv": with_cv,
            "da_lap_chi_muc": indexed,
            "so_doan_cv": chunks,
        },
        "nganh": _block("Ngành từng làm", industries, industries_filled, total_people),
        "ky_nang": _block("Kỹ năng", skills, skills_filled, total_people),
        "chuc_danh": _block("Chức danh hiện tại", titles, titles_filled, total_people),
        "cong_ty": _block("Công ty hiện tại", companies, companies_filled, total_people),
        "noi_o": _block("Nơi ở", locations, locations_filled, total_people),
        "noi_lam_viec_mong_muon": _block("Nơi làm việc mong muốn", desired_locations,
                                         desired_locations_filled, total_people),
        "cap_bac": _block("Cấp bậc", seniority, seniority_filled, total_people),
        "kinh_nghiem": {
            "co_so_lieu": experience["co_so_lieu"],
            "tong": total_people,
            "phan_bo": buckets,
        },
    }


#: Trường thống kê được: tên trường TalentProfile -> (nhãn, là danh sách JSON?).
#: Danh sách đóng — tên trường đến từ model/tool call nên không được đi thẳng vào ORM.
BREAKDOWN_FIELDS = {
    "skills": ("Kỹ năng", True),
    "industries": ("Ngành từng làm", True),
    "current_title": ("Chức danh hiện tại", False),
    "current_company": ("Công ty hiện tại", False),
    "location": ("Nơi ở", False),
    "desired_location": ("Nơi làm việc mong muốn", False),
    "seniority": ("Cấp bậc", False),
}
BREAKDOWN_MAX_LIMIT = 30
BREAKDOWN_MAX_FILTERS = 3


def _as_values(raw, is_list):
    if is_list:
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        return list(dict.fromkeys(" ".join(v.split()) for v in raw
                                  if isinstance(v, str) and v.strip()))
    text = " ".join(str(raw or "").split())
    return [text] if text else []


def _value_matches(values, needle):
    """Khớp nguyên cụm đã bỏ dấu — "java" không được khớp "javascript"."""
    target = f" {needle} "
    return any(target in f" {_fold_plain(v)} " for v in values)


def _fold_plain(text):
    folded = unicodedata.normalize("NFD", str(text or "").casefold())
    folded = "".join(ch for ch in folded if unicodedata.category(ch) != "Mn")
    return " ".join(re.sub(r"[^\w+#.]+", " ", folded.replace("đ", "d")).split())


def breakdown(field, *, filters=None, limit=TOP_N):
    """Phân bố giá trị của MỘT trường, trên nhóm hồ sơ thoả `filters`. Tất định.

    `overview()` chỉ trả lời được toàn kho; câu "kỹ năng phổ biến nhất của ứng
    viên ở Hà Nội" cần lọc trước rồi mới đếm. Lọc bằng khớp nguyên cụm đã bỏ dấu
    trên chính các trường có cấu trúc — không dùng LLM, không dùng truy hồi —
    và báo riêng độ phủ của trường lọc: hồ sơ để trống "nơi ở" KHÔNG phải là
    người ở ngoài Hà Nội, chỉ là không biết.

    Ném `ValueError` khi tên trường/giá trị lọc không hợp lệ.
    """
    from talent.models import TalentProfile

    if field not in BREAKDOWN_FIELDS:
        raise ValueError(f"trường không thống kê được: {field}")
    clean_filters = {}
    for name, value in dict(filters or {}).items():
        if name not in BREAKDOWN_FIELDS:
            raise ValueError(f"trường lọc không hợp lệ: {name}")
        needle = _fold_plain(value)
        if needle:
            clean_filters[name] = needle
    if len(clean_filters) > BREAKDOWN_MAX_FILTERS:
        raise ValueError(f"tối đa {BREAKDOWN_MAX_FILTERS} điều kiện lọc")
    limit = max(1, min(int(limit or TOP_N), BREAKDOWN_MAX_LIMIT))

    columns = list(dict.fromkeys([field, *clean_filters]))
    profiles = TalentProfile.objects.filter(person__merged_into__isnull=True,
                                            person__is_applicant=True)
    total = profiles.count()
    filter_filled = {name: 0 for name in clean_filters}
    population = filled = 0
    counter = Counter()
    for row in profiles.values_list(*columns).iterator(chunk_size=500):
        by_name = dict(zip(columns, row))
        matched = True
        for name, needle in clean_filters.items():
            values = _as_values(by_name[name], BREAKDOWN_FIELDS[name][1])
            if values:
                filter_filled[name] += 1
            if not _value_matches(values, needle):
                matched = False
        if not matched:
            continue
        population += 1
        values = _as_values(by_name[field], BREAKDOWN_FIELDS[field][1])
        if values:
            filled += 1
            counter.update(values)

    block = _block(BREAKDOWN_FIELDS[field][0], counter.most_common(limit), filled, population)
    block.update({
        "field": field,
        "filters": [{"field": name, "label": BREAKDOWN_FIELDS[name][0],
                     "value": dict(filters)[name], "filled": filter_filled[name],
                     "total": total}
                    for name in clean_filters],
        "store_total": total,
    })
    return block


def describe_breakdown(block):
    """Một đoạn văn gọn, đủ độ phủ, để nhét vào prompt."""
    scope = "toàn kho"
    if block["filters"]:
        scope = " và ".join(f"{f['label'].lower()} khớp \"{f['value']}\"" for f in block["filters"])
    lines = [f"THỐNG KÊ CÓ LỌC ({block['label']}, nhóm hồ sơ có {scope}; tính tất định trên "
             "trường có cấu trúc):",
             f"- Nhóm thoả điều kiện: {block['total']}/{block['store_total']} hồ sơ."]
    for f in block["filters"]:
        lines.append(f"- Chỉ {f['filled']}/{f['total']} hồ sơ có điền {f['label'].lower()}; "
                     "hồ sơ để trống không được tính vào nhóm, KHÔNG có nghĩa là không thoả.")
    if block["meaningful"]:
        top = ", ".join(f"{item['value']} ({item['count']})" for item in block["top"])
        lines.append(f"- {block['label']} (có ở {block['filled']}/{block['total']} hồ sơ "
                     f"trong nhóm): {top}.")
    else:
        lines.append(f"- {block['label']}: chỉ {block['filled']}/{block['total']} hồ sơ trong "
                     "nhóm có trường này nên chưa đủ để xếp hạng.")
    return "\n".join(lines)


#: Từ khoá (đã bỏ dấu) -> trường người dùng muốn xếp hạng.
_TARGET_WORDS = (
    ("ky nang", "skills"), ("skill", "skills"), ("nganh", "industries"),
    ("chuc danh", "current_title"), ("vi tri", "current_title"),
    ("cong ty", "current_company"), ("noi lam viec mong muon", "desired_location"),
    ("noi o", "location"), ("dia diem", "location"), ("tinh thanh", "location"),
    ("cap bac", "seniority"),
)
#: Trường mà một giá trị nhắc trong câu hỏi có thể dùng làm điều kiện lọc.
_FILTER_FIELDS = ("location", "industries", "current_title", "skills", "current_company")
_MIN_FILTER_LEN = 3
#: Từ của chính câu hỏi — trùng một giá trị rác trong kho ("Kho", "Nhân sự")
#: cũng không được biến thành điều kiện lọc.
_QUESTION_WORDS = {"kho", "ho so", "ung vien", "cv", "nguoi", "nhat", "nhieu",
                   "pho bien", "top", "thong ke", "trong", "cua", "nhung", "nhan su"}


def breakdown_for_question(text):
    """Nhận ra câu "<trường> phổ biến … của nhóm <giá trị có thật trong kho>".

    Chỉ trả block khi CẢ HAI chắc chắn: có từ khoá trường cần xếp hạng, và câu
    hỏi chứa nguyên cụm một giá trị ĐÃ CÓ trong kho ở trường khác. Không đoán —
    không khớp thì trả None và câu hỏi đi đường `overview()` như cũ.
    """
    from talent.models import TalentProfile

    folded = f" {_fold_plain(text)} "
    target = next((name for word, name in _TARGET_WORDS if f" {word} " in folded), None)
    if target is None:
        return None
    profiles = TalentProfile.objects.filter(person__merged_into__isnull=True,
                                            person__is_applicant=True)
    best = None
    for name in _FILTER_FIELDS:
        if name == target:
            continue
        is_list = BREAKDOWN_FIELDS[name][1]
        if is_list:
            pairs, _ = _top_from_json_list(profiles, name, limit=200)
        else:
            pairs, _ = _top_from_char(profiles, name, limit=200)
        for value, _count in pairs:
            needle = _fold_plain(value)
            if (len(needle) >= _MIN_FILTER_LEN and needle not in _QUESTION_WORDS
                    and f" {needle} " in folded):
                # Cụm dài nhất thắng: "ho chi minh" hơn "minh".
                if best is None or len(needle) > len(best[2]):
                    best = (name, value, needle)
    if best is None:
        return None
    return breakdown(target, filters={best[0]: best[1]})


def fts_estimate(queries, *, cap=800):
    """Ước lượng: bao nhiêu hồ sơ có CV NHẮC TỚI các từ khoá này.

    Dùng khi trường FACT (`industries`, `skills`…) rỗng nên `overview()` bảo
    "chưa đủ để thống kê", mà câu hỏi vẫn là "% ngành X". Kho có 786 CV text —
    đếm được bằng full-text, chỉ là chưa ai nối. KHÔNG chính xác như trường đã
    bóc (một CV nhắc "công nghệ thông tin" không chắc người đó làm IT), nên câu
    chữ phải nói rõ "đếm theo từ khoá trong CV".

    Trả `{"match": K, "total": N}` hoặc `None` nếu không tính được.
    """
    terms = [str(q or "").strip() for q in (queries or []) if str(q or "").strip()]
    if not terms:
        return None
    try:
        from talent import vector_index
        # `PersonSearchDocument` nằm ở `talent.models`, không phải `intel.models`.
        # Import sai làm cả hàm này ném ImportError ngay dòng đầu rồi bị `except`
        # bên dưới nuốt — `fts_estimate` LUÔN trả None kể từ commit bda4f9c mà
        # không ai thấy, vì nó chỉ ghi log warning.
        from talent.models import CVChunk, PersonSearchDocument

        pids = set()
        for query in terms[:6]:
            chunks = vector_index.fts_filter(
                CVChunk.objects.filter(person__merged_into__isnull=True),
                "text_norm", query)
            if chunks is None:                      # không phải PostgreSQL
                folded = [t for t in _fold(query).split() if len(t) >= 3][:6]
                if not folded:
                    continue
                cond = Q()
                for term in folded:
                    cond |= Q(text_norm__icontains=term)
                chunks = CVChunk.objects.filter(cond).filter(
                    person__merged_into__isnull=True)
            pids.update(chunks.values_list("person_id", flat=True)[:cap])
            if len(pids) >= cap:
                break
        total = PersonSearchDocument.objects.filter(
            person__merged_into__isnull=True).count() or overview()["quy_mo"]["tong_ho_so"]
        return {"match": len(pids), "total": total}
    except Exception:                              # noqa: BLE001
        log.warning("corpus.fts_estimate: không đếm được", exc_info=True)
        return None


def _fold(text):
    from talent import vector_index
    return vector_index.fold_text(text)


def facts_for_prompt(limit_per_block=8):
    """Vài dòng gọn mô tả kho, để nhét vào prompt.

    Dùng ở nhánh hội thoại: không có mấy dòng này thì hỏi "bạn có dữ liệu gì"
    Radar trả lời "tôi không có dữ liệu" — sai, và là kiểu sai tệ nhất vì nghe
    rất thuyết phục.
    """
    try:
        data = overview()
    except Exception:                              # noqa: BLE001
        log.warning("corpus.facts_for_prompt: không tổng hợp được", exc_info=True)
        return ""

    size = data["quy_mo"]
    lines = [
        "SỐ LIỆU THẬT VỀ KHO (tính ngay lúc này, không được nói khác đi):",
        f"- {size['tong_ho_so']} hồ sơ người, trong đó {size['co_file_cv']} người có "
        f"file CV, {size['da_lap_chi_muc']} đã lập chỉ mục tìm kiếm "
        f"({size['so_doan_cv']} đoạn CV).",
    ]
    for key in ("nganh", "chuc_danh", "ky_nang", "noi_o"):
        block = data[key]
        if not block["meaningful"]:
            lines.append(
                f"- {block['label']}: chỉ {block['filled']}/{block['total']} hồ sơ có "
                "trường này nên chưa đủ để thống kê — muốn biết phải đọc nội dung CV.")
            continue
        top = ", ".join(f"{item['value']} ({item['count']})"
                        for item in block["top"][:limit_per_block])
        lines.append(f"- {block['label']} (có ở {block['filled']}/{block['total']} "
                     f"hồ sơ): {top}.")
    lines.append(
        "Nếu người hỏi muốn biết sâu hơn số liệu trên (ví dụ ngành nghề thật sự "
        "trong CV), nói rõ là cần rà nội dung CV và mời họ hỏi cụ thể hơn.")
    return "\n".join(lines)
