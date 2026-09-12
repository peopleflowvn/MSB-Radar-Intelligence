# -*- coding: utf-8 -*-
"""Cực trị trên TOÀN kho — "ứng viên lớn tuổi nhất", "nhiều kinh nghiệm nhất".

Vì sao KHÔNG dùng truy hồi ngữ nghĩa cho loại câu này:

    Truy hồi vector trả lời "ai GIỐNG câu hỏi nhất", không phải "ai có GIÁ TRỊ
    lớn nhất của thuộc tính X". Nhúng cụm "lớn tuổi nhất" thành vector thì kéo
    về CV có chữ gần nghĩa ("nhiều tuổi", "40 năm kinh nghiệm", "sinh năm
    197x") — một phép xấp xỉ mờ, bỏ sót người sinh 1965 mà CV chỉ ghi "1965".

    Cực trị = cần GIÁ TRỊ của MỌI người rồi `MAX()`. Đó là phép tổng hợp trên
    dữ liệu, khác lớp với truy hồi. Phải quét toàn kho một cách tất định.

Đường này quét đúng một lần qua tất cả người (chưa gộp) có CV, bóc thuộc tính
cần sắp bằng LUẬT (regex năm/tuổi, cột `TalentProfile.years_experience`), sắp
toàn bộ, trả top-N kèm ĐỘ PHỦ ("sắp theo K/N hồ sơ có dữ liệu"). Không gọi LLM,
chạy vài trăm mili-giây, và mở rộng tuyến tính khi kho lớn.

Trường chưa có dữ liệu cấu trúc thì đây là lưới đỡ. Đường tốt hơn là bóc-có-nhãn
lúc ingest (`intel/extraction.py`) rồi query thẳng — xem docs.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

from .judge import Judgement

log = logging.getLogger(__name__)

_YEAR = re.compile(r"\b(19[3-9]\d|20[0-2]\d)\b")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")

#: Câu hỏi phải neo vào MỘT thuộc tính sắp được và KHÔNG kèm bộ lọc mạnh nào
#: khác — nếu không thì "java dev nhiều KN nhất" cũng lọt và trả sai (đường này
#: không lọc theo kỹ năng).
_STORE_HINTS = ("trong kho", "toan kho", "ca kho", "hien co", "cua radar",
                "trong he thong", "toan bo")


def _fold(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(text or "").lower())
                   if unicodedata.category(c) != "Mn")


#: Nhóm thuộc tính → cách lấy giá trị. `kind`: year (năm — lớn = mới/trẻ),
#: number (số — lớn = nhiều), yearcol/numcol (đọc thẳng cột CSDL).
_ATTR = {
    "nam sinh": "birth_year", "ngay sinh": "birth_year", "sinh nam": "birth_year",
    "tuoi": "age", "age": "age",
    "nam tot nghiep": "grad_year", "tot nghiep": "grad_year",
    "so nam kinh nghiem": "years_exp", "nam kinh nghiem": "years_exp",
    "kinh nghiem": "years_exp", "experience": "years_exp",
}


def _attr_of(sort_key):
    folded = _fold(sort_key)
    for phrase, attr in _ATTR.items():
        if phrase in folded:
            return attr
    return None


def wants_whole_store(query_plan):
    """Câu này có phải "top-N theo thuộc tính X trên TOÀN kho, không lọc gì khác"?"""
    sort_by = getattr(query_plan, "sort_by", None) or {}
    if not sort_by.get("key"):
        return None
    attr = _attr_of(sort_by["key"])
    if attr is None:
        return None
    # Có tiêu chí lọc mạnh → không phải cực trị thuần; để đường ngữ nghĩa lo.
    if getattr(query_plan, "must_have", None):
        return None
    if len(getattr(query_plan, "should_have", []) or []) > 1:
        return None
    need = _fold(getattr(query_plan, "information_need", "")
                or " ".join(getattr(query_plan, "search_queries", []) or []))
    # Phải có dấu hiệu "toàn kho" HOẶC câu cực trị trần ("ai lớn tuổi nhất")
    # không kèm nghề nghiệp cụ thể.
    if any(h in need for h in _STORE_HINTS):
        return attr
    if "nhat" in need and len(need.split()) <= 8:
        return attr
    return None


def _year_from(text, *, newest_first):
    years = [int(m.group(0)) for m in _YEAR.finditer(text or "")]
    if not years:
        return None
    return max(years) if newest_first else min(years)


_BIRTH_RE = re.compile(
    r"(?:sinh\s+(?:năm\s*)?|(?:birth(?:\s*year)?|dob|d\.o\.b)\s*[:=]?\s*)"
    r"(?:\d{1,2}[/\-.]\d{1,2}[/\-.])?(\d{4})", re.I)
_AGE_RE = re.compile(r"(\d{2})\s*(?:tuổi|tuoi|years old)", re.I)


def _value_from_cv(attr, head, now_year, name=""):
    """`(số so sánh được, câu mô tả)` hoặc `(None, None)`. `head` = đầu CV."""
    def statement(pattern):
        for sentence in re.split(r"[;\n.!?,]+(?!\d)", head):
            sentence = sentence.strip()
            if name and sentence.casefold().startswith(name.casefold() + " "):
                sentence = sentence[len(name):].strip()
            found = pattern.fullmatch(sentence)
            if found:
                return found
        return None
    if attr in ("birth_year", "age"):
        m = statement(_AGE_RE) if attr == "age" else None
        if m and 14 <= int(m.group(1)) <= 80:
            return float(now_year - int(m.group(1))), f"{m.group(1)} tuổi"
        m = statement(_BIRTH_RE)
        yr = int(m.group(1)) if m else None
        if yr and 1935 <= yr <= now_year - 14:
            return float(yr), m.group(0)
        return None, None
    if attr == "grad_year":
        m = statement(re.compile(r"(?:tốt nghiệp|tot nghiep|graduated)\s+(?:năm\s+|nam\s+|in\s+)?(\d{4})", re.I))
        yr = int(m.group(1)) if m else None
        if yr and 1950 <= yr <= now_year + 1:
            return float(yr), m.group(0)
        return None, None
    return None, None


def _cv_texts(person_ids):
    """{person_id: text CV THẬT} — KHÔNG đọc `Document.parsed_text` trực tiếp.

    Bẫy đã bắt được trên production 05/09: `parsed_text` (cột thô) rỗng cho
    TOÀN BỘ 433 Document — text thật nằm ở `primary_text_version.text` (bảng
    `ParsedTextVersion`, dùng chung cho nhiều Document/Person), và
    `Document.best_text` (property) mới là chỗ nối hai nguồn đó lại.
    `.values_list("parsed_text")` đọc thẳng cột nên bỏ qua property,
    và lưới đỡ regex chạy "đúng" mà ra 0/798 — không lỗi, không cảnh báo,
    chỉ lặng lẽ vô dụng. Đây đúng thứ khiến việc này cần một pipeline có kiểm
    chứng (P1–P3) thay vì mỗi chỗ tự đọc text CV theo cách riêng của nó.
    """
    from people.models import Document

    out = {}
    docs = (Document.objects
            .filter(person_id__in=person_ids, document_type="cv")
            .select_related("primary_text_version")
            .only("id", "person_id", "parsed_text", "primary_text_version").order_by("id"))
    for doc in docs.iterator(chunk_size=200):
        if doc.person_id in out:
            continue
        text = doc.best_text
        if text:
            out[doc.person_id] = text
    return out


def run(query_plan, *, user=None, attr=None):
    """Trả `(chosen, stats)` — top-`limit` theo thuộc tính, quét TOÀN kho."""
    from people.models import Document, Person
    from talent.models import TalentProfile

    attr = attr or wants_whole_store(query_plan)
    if attr is None:
        return [], {}

    sort_by = query_plan.sort_by or {}
    limit = max(1, int(getattr(query_plan, "limit", 10) or 10))
    now_year = dt.date.today().year

    people = {p.pk: (p.display_name or f"#{p.pk}")
              for p in Person.applicants().only("id", "display_name")}
    total = len(people)
    values: dict[int, float] = {}
    raw: dict[int, str] = {}

    if attr == "years_exp":
        for pid, yrs in (TalentProfile.objects
                         .filter(person_id__in=people, years_experience__isnull=False)
                         .values_list("person_id", "years_experience")):
            values[pid] = float(yrs)
            raw[pid] = f"{yrs:g} năm KN (hồ sơ)"
        # Bổ sung từ text CV cho người chưa có cột.
        need_scan = [pid for pid in people if pid not in values]
        if need_scan:
            _fill_years_from_cv(need_scan, values, raw)
    else:
        # birth_year / grad_year / age — regex trên text CV THẬT (best_text).
        for pid, text in _cv_texts(list(people)).items():
            # Năm sinh / tốt nghiệp gần như luôn ở đầu CV.
            value, label = _value_from_cv(attr, text[:1500], now_year, people[pid])
            if value is not None:
                values[pid] = value
                raw[pid] = label

    if not values:
        return [], {"judged": total, "relevant": 0, "shown": 0, "retrieved": total,
                    "read_failed": False, "sorted_by": None,
                    "whole_store": True, "coverage_have": 0, "coverage_total": total}

    # "lớn tuổi nhất" = sinh SỚM = năm sinh NHỎ. "ít tuổi nhất" = năm sinh LỚN.
    # `age` đã quy về năm sinh ở trên nên cùng thang.
    from .aggregate import _sort_direction
    ascending = _sort_direction(sort_by, sort_by.get("key", ""), query_plan.information_need)
    folded = _fold(sort_by.get("key", ""))
    if attr in ("birth_year", "age") and ("lon tuoi" in folded or "nhieu tuoi" in folded
                                          or "gia nhat" in folded):
        ascending = True                          # năm sinh nhỏ trước
    elif attr in ("birth_year", "age") and ("it tuoi" in folded or "tre" in folded):
        ascending = False

    ranked = sorted(values.items(), key=lambda kv: kv[1], reverse=not ascending)
    top_ids = [pid for pid, _v in ranked[:limit]]
    # Một nguồn [n] cho mỗi người: mở đúng CV đã quét ra giá trị.
    # Find the actual document containing the excerpt, including when a person
    # has several CVs. Structured facts without source text get no fake quote.
    doc_of = {}
    for doc in (Document.objects.filter(person_id__in=top_ids, document_type="cv")
                .select_related("primary_text_version").order_by("id")):
        quote = raw.get(doc.person_id, "")
        if doc.person_id not in doc_of and quote and quote in doc.best_text:
            doc_of[doc.person_id] = doc.pk
    chosen = [
        Judgement(
            person_id=pid, name=people[pid], relevant=True, confidence=0.9,
            why=raw.get(pid, ""),
            extracted={sort_by.get("key", "giá trị"): raw.get(pid, "")},
            evidence=([{"document_id": doc_of[pid], "ordinal": 0,
                        "quote": raw.get(pid, "")}] if pid in doc_of else []))
        for pid in top_ids
    ]
    stats = {
        "judged": len(values), "relevant": len(values), "shown": len(chosen),
        "retrieved": total, "read_failed": False, "truncated": max(0, len(values) - limit),
        "limit": limit, "missing_sort_value": total - len(values),
        "sorted_by": {"key": sort_by.get("key"), "asc": ascending,
                      "with_value": len(values)},
        "whole_store": True, "coverage_have": len(values), "coverage_total": total,
    }
    return chosen, stats


def _fill_years_from_cv(person_ids, values, raw):
    """Use explicit experience statements; calendar spans do not prove tenure."""
    pattern = re.compile(r"(?<![\d.,])(\d+(?:[.,]\d+)?)\s*(?:năm kinh nghiệm|nam kinh nghiem|years? (?:of )?experience)", re.I)
    for pid, text in _cv_texts(person_ids).items():
        for sentence in re.split(r"[;\n.!?]+(?!\d)", text[:4000]):
            match = pattern.fullmatch(sentence.strip()) or re.fullmatch(
                r"(?:Có|Co)\s+" + pattern.pattern, sentence.strip(), re.I)
            if match:
                span = float(match.group(1).replace(",", "."))
                if 0 <= span <= 80:
                    values[pid] = span
                    raw[pid] = match.group(0)
                    break
