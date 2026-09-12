# -*- coding: utf-8 -*-
"""④ Sắp xếp, cắt, thống kê — CODE thuần, tất định.

Chặng này tồn tại vì LLM **không đáng tin khi đếm và xếp thứ tự**. Câu "5 ứng
viên học cao đẳng ít tuổi nhất": ③ bóc ra `năm sinh` của từng người, ④ mới là
nơi sắp xếp và cắt đúng 5. Giao việc đó cho ⑤ viết văn thì sai thứ tự và sai số
lượng — đúng lỗi trong ba ảnh chụp màn hình hôm trước.

Do đó ⑤ nhận vào **danh sách đã chốt** và chỉ còn mỗi việc diễn đạt.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

#: Ngưỡng tin cậy tối thiểu để một người được coi là "thoả" khi trả lời.
CONFIDENCE_FLOOR = 0.35
#: Người không thoả nhưng gần đúng — giữ lại tối đa ngần này để nói "gần giống".
NEAR_MISS = 5

_YEAR = re.compile(r"(19|20)\d{2}")
_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")

#: Từ khoá nhận diện thuộc tính, đã bỏ dấu — quyết định cách chuẩn hoá giá trị.
_YEARISH = ("nam sinh", "ngay sinh", "birth", "yob", "sinh nam")
_AGEISH = ("tuoi", "age")
_NUMERIC = ("so nam", "kinh nghiem", "experience", "years", "gpa", "diem", "luong")


def _fold(text):
    stripped = unicodedata.normalize("NFD", str(text or "").lower())
    stripped = "".join(ch for ch in stripped if unicodedata.category(ch) != "Mn")
    return stripped.replace("đ", "d").replace("Đ", "d")


def _match_key(extracted, key):
    """Khớp tên thuộc tính khoan dung — ③ hay trả "năm sinh" khi ① xin "Năm sinh"."""
    if key in extracted:
        return key
    target = _fold(key)
    for name in extracted:
        folded = _fold(name)
        if folded == target or target in folded or folded in target:
            return name
    return None


def _sortable(key, value):
    """Giá trị thuộc tính → số so sánh được, hoặc None nếu không quy ra số được.

    Tuổi được quy về **năm sinh** để "ít tuổi nhất" và "sinh năm mấy" cùng một
    thang — không thì hai người, một khai tuổi một khai năm sinh, xếp lẫn lộn.
    """
    if value is None or value == "":
        return None
    folded_key = _fold(key)
    text = str(value)

    if any(token in folded_key for token in _YEARISH):
        found = _YEAR.search(text)
        return int(found.group(0)) if found else None

    if any(token in folded_key for token in _AGEISH):
        found = _YEAR.search(text)
        if found:                       # "sinh 1996 (28 tuổi)" — ưu tiên năm thật
            return int(found.group(0))
        number = _NUMBER.search(text)
        if number:
            age = float(number.group(0).replace(",", "."))
            if 14 <= age <= 80:
                return dt.date.today().year - age
        return None

    if any(token in folded_key for token in _NUMERIC) or isinstance(value, (int, float)):
        number = _NUMBER.search(text)
        return float(number.group(0).replace(",", ".")) if number else None

    return None


def _sort_direction(sort_by, key, information_need=""):
    """"Ít tuổi nhất" = sinh sau = năm sinh LỚN hơn, dù ① viết "asc" hay "desc".

    ① đôi khi nghĩ theo tuổi, đôi khi theo năm sinh. Chuẩn hoá tại đây để hướng
    sắp xếp luôn đúng với ý người hỏi.
    """
    direction = (sort_by or {}).get("dir", "desc")
    ascending = direction == "asc"
    folded_need = _fold(information_need)
    if any(t in _fold(key) for t in _YEARISH + _AGEISH):
        if any(t in folded_need for t in ("lon tuoi nhat", "nhieu tuoi nhat", "gia nhat", "oldest")):
            return True  # all ages are converted to birth years by _sortable
        if any(t in folded_need for t in ("tre nhat", "it tuoi nhat", "youngest")):
            return False
    if any(token in _fold(key) for token in _AGEISH) and "sinh" not in _fold(key):
        ascending = not ascending       # tuổi tăng dần == năm sinh giảm dần
    return ascending


def aggregate(query_plan, judgements):
    """Trả `(chosen, near_misses, stats)` — danh sách đã chốt để ⑤ diễn đạt."""
    kept, near = [], []
    for judgement in judgements:
        if judgement.relevant and judgement.confidence >= CONFIDENCE_FLOOR:
            kept.append(judgement)
        elif judgement.confidence > 0 or judgement.why:
            near.append(judgement)

    sort_by = query_plan.sort_by
    sorted_by = None
    dropped_no_value = 0

    if sort_by and kept:
        key = sort_by.get("key") or ""
        with_value, without_value = [], []
        for judgement in kept:
            facts = judgement.fact_attributes()
            actual = _match_key(facts, key)
            number = _sortable(key, facts.get(actual)) if actual else None
            (with_value if number is not None else without_value).append((number, judgement))
        if with_value:
            ascending = _sort_direction(sort_by, key, query_plan.information_need)
            with_value.sort(key=lambda row: row[0], reverse=not ascending)
            # Thiếu thuộc tính thì KHÔNG được xếp lẫn vào thứ hạng — xuống cuối,
            # và ⑤ phải nói rõ là không xác định được.
            kept = [j for _n, j in with_value] + [j for _n, j in without_value]
            sorted_by = {"key": key, "asc": ascending, "with_value": len(with_value)}
            dropped_no_value = len(without_value)
    if sorted_by is None:
        kept.sort(key=lambda j: (-j.confidence, j.name))

    near.sort(key=lambda j: -j.confidence)
    limit = max(1, int(query_plan.limit or 10))
    chosen = kept[:limit]

    stats = {
        "judged": len(judgements),
        "relevant": len(kept),
        "shown": len(chosen),
        "truncated": max(0, len(kept) - len(chosen)),
        "limit": limit,
        "sorted_by": sorted_by,
        "missing_sort_value": dropped_no_value,
        "cited": sum(1 for j in chosen if j.evidence),
    }
    return chosen, near[:NEAR_MISS], stats


def enough(chosen, stats, query_plan):
    """Có đủ để trả lời chưa, hay cần nới kế hoạch và tìm lại một lượt (§4)?"""
    if chosen:
        return True
    # Không ai thoả nhưng đã đọc kha khá hồ sơ ⇒ kho thật sự không có; nới nữa
    # cũng chỉ moi thêm hồ sơ lạc đề.
    return stats.get("judged", 0) >= 15
