# -*- coding: utf-8 -*-
"""Điều kiện nào của RM diễn đạt được HOÀN TOÀN bằng cột dữ liệu — tất định.

① viết điều kiện bằng lời tự nhiên ("ở Hà Nội", "quan tâm vay mua nhà", "mới kết
hôn"). Ba nơi cần biết điều kiện nào là CÓ CẤU TRÚC:

    đếm       điều kiện có cấu trúc hết ⇒ đếm CHÍNH XÁC bằng SQL trên toàn kho;
              còn một điều kiện cần đọc nội dung ⇒ chỉ ước lượng được, phải nói
    ghim      người thoả điều kiện có cấu trúc được đưa vào pool đọc sâu, không
              phụ thuộc truy hồi xấp xỉ có xếp họ đủ cao hay không
    lọc       bộ lọc cứng bổ sung cho `bo_loc` mà ① có thể quên điền

## Bảo thủ có chủ đích

Một cụm chỉ được coi là "có cấu trúc" khi SAU KHI bỏ các từ đã khớp và từ chức
năng thì KHÔNG CÒN chữ nào. "quan tâm vay mua nhà" → có cấu trúc. "quan tâm vay
mua nhà vì mới kết hôn" → còn "moi ket hon" → KHÔNG. Gặp phủ định ("không",
"chưa", "trừ") ngoài các mẫu đã biết → KHÔNG: "không quan tâm vay mua nhà" khớp
đúng từ khoá sản phẩm, và đếm nó như có quan tâm là đếm ngược nghĩa.

Sai theo chiều bảo thủ chỉ tốn một lượt đọc bằng chứng và cho ra con số được
dán nhãn ước lượng. Sai theo chiều ngược lại cho ra một con số dán nhãn CHÍNH
XÁC mà không đúng — thứ tệ nhất một phép đếm có thể làm.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Từ chức năng: không mang điều kiện nào. Không có "khong"/"chua" ở đây.
_STOP = set("""
co dang da quan tam nhu cau khach hang o tai ve cac nhung nguoi la va can muon
tim hieu san pham song lam viec thuoc khu vuc tinh thanh pho tp nhom phan khuc mot
so cho voi duoc hoac trong vong ngay gan day tuan thang nay nam lien he dien thoai
email goi cap bac hien nao ai bao nhieu kho minh toi vay tin
""".split())

_NEGATION = re.compile(r"\b(khong|chua|tru|ngoai tru|except|not)\b")

_OPEN_OPP = re.compile(r"\b(chua|khong)\s+(co|duoc tao)\s+co hoi(\s+dang mo)?\b")
_CONTACT = re.compile(r"\b(co\s+(so dien thoai|sdt|lien he|email|so|thong tin lien he)"
                      r"|lien he duoc|goi duoc)\b")
_RECENCY = [
    (re.compile(r"\btrong\s+(?:vong\s+)?(\d{1,4})\s+ngay(?:\s+qua)?\b"), None),
    (re.compile(r"\btuan (nay|qua)\b"), 7),
    (re.compile(r"\bthang (nay|qua)\b"), 30),
    (re.compile(r"\bgan day\b"), 90),
]
_SEGMENTS = [
    (re.compile(r"\b(phan khuc uu tien|khach hang uu tien|priority)\b"), "priority"),
    (re.compile(r"\b(phan khuc kha gia|kha gia|affluent)\b"), "affluent"),
    (re.compile(r"\b(phan khuc pho thong|pho thong|mass)\b"), "mass"),
]
_SENIORITY = [
    (re.compile(r"\b(cap cao|ceo|cfo|cto|chu tich|tong giam doc|executive)\b"), "executive"),
    (re.compile(r"\b(quan ly|truong phong|giam doc|manager|director|head of)\b"), "manager"),
]


def _fold(text):
    from talent.vector_index import fold_text
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", fold_text(text)).split())


def _consume(text, pattern):
    """Khớp `pattern`; trả (match, văn bản đã xoá phần khớp)."""
    match = pattern.search(text)
    if not match:
        return None, text
    return match, (text[:match.start()] + " " + text[match.end():])


@dataclass
class PhraseAnalysis:
    phrase: str
    filters: dict = field(default_factory=dict)
    products: list = field(default_factory=list)
    covered: bool = False
    leftover: str = ""


def analyse_phrase(phrase):
    from core.vn_locations import ALIASES

    from ..routing import PRODUCT_HINTS

    text = f" {_fold(phrase)} "
    out = PhraseAnalysis(phrase=phrase)

    match, text = _consume(text, _OPEN_OPP)
    if match:
        out.filters["loai_co_hoi_dang_mo"] = True
    match, text = _consume(text, _CONTACT)
    if match:
        out.filters["phai_co_lien_he"] = True
    for pattern, days in _RECENCY:
        match, text = _consume(text, pattern)
        if match:
            out.filters["tin_hieu_trong_ngay"] = int(match.group(1)) if days is None else days
            break
    for pattern, value in _SEGMENTS:
        match, text = _consume(text, pattern)
        if match:
            out.filters["phan_khuc"] = value
            break
    for pattern, value in _SENIORITY:
        match, text = _consume(text, pattern)
        if match:
            out.filters["cap_bac"] = value
            break
    for canonical, variants in ALIASES.items():
        for variant in sorted({canonical, *variants}, key=len, reverse=True):
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(_fold(variant)) + r"(?![a-z0-9])")
            match, text = _consume(text, pattern)
            if match:
                out.filters["tinh_thanh"] = canonical
                break
        if "tinh_thanh" in out.filters:
            break
    for product, hints, _need in PRODUCT_HINTS:
        for hint in sorted(hints, key=len, reverse=True):
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(_fold(hint)) + r"(?![a-z0-9])")
            match, text = _consume(text, pattern)
            if match:
                if product not in out.products:
                    out.products.append(product)
    # Phủ định còn sót lại (không nằm trong mẫu "chưa có cơ hội" đã tiêu thụ ở
    # trên) ⇒ không bao giờ là có cấu trúc. Xem docstring module.
    negated = bool(_NEGATION.search(text))
    leftover = [t for t in text.split() if t not in _STOP and not t.isdigit()]
    out.leftover = " ".join(leftover)
    matched_anything = bool(out.filters or out.products)
    out.covered = matched_anything and not leftover and not negated
    return out


@dataclass
class PlanAnalysis:
    filters: dict
    #: Mỗi nhóm là các sản phẩm của MỘT cụm (OR trong nhóm); các nhóm AND với
    #: nhau. "quan tâm vay mua nhà" + "quan tâm thẻ tín dụng" là hai nhóm — khách
    #: phải có cả hai; "mua nhà hoặc mua xe" là một nhóm hai sản phẩm.
    product_groups: list
    all_covered: bool
    uncovered: list

    @property
    def products(self):
        return list(dict.fromkeys(p for group in self.product_groups for p in group))


def analyse_plan(query_plan):
    """Gộp phân tích mọi `must_have`. Không có `must_have` nào ⇒ phủ trọn (đếm cả phạm vi).

    `should_have` là tiêu chí XẾP HẠNG, không xác định nhóm cần đếm — không xét.
    """
    filters, groups, uncovered = {}, [], []
    for phrase in getattr(query_plan, "must_have", None) or []:
        result = analyse_phrase(phrase)
        conflict = any(key in filters and filters[key] != value
                       for key, value in result.filters.items())
        if not result.covered or conflict:
            # Mâu thuẫn trên cùng một cột ("ở Hà Nội" và "ở Đà Nẵng") không phải
            # một bộ lọc AND có nghĩa — đẩy sang đọc bằng chứng, không đoán.
            uncovered.append(phrase)
            continue
        filters.update(result.filters)
        if result.products:
            groups.append(list(result.products))
    return PlanAnalysis(filters=filters, product_groups=groups,
                        all_covered=not uncovered, uncovered=uncovered)
