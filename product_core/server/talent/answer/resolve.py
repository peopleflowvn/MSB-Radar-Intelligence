# -*- coding: utf-8 -*-
"""Giải định danh TẤT ĐỊNH cho câu tra tên / so sánh / hỏi tiếp.

Truy hồi ngữ nghĩa + FTS cắt top-N là **không tất định**: cùng câu "so sánh A và
B" lần này lọt cả hai, lần sau rớt một (ảnh test 04/09 — "vừa tìm được bên trên
mà"). Với câu neo vào một cái TÊN, đó là lỗi: tên là định danh, không phải gợi
ý ngữ nghĩa.

Module này lấy ra danh sách `person_id` phải CÓ trong pool bất kể điểm truy hồi:

* tên riêng bóc từ `search_queries` / `information_need`;
* người của lượt trước (`last_result`) khi câu hỏi là `compare` / `followup`.

Khớp tên đã bỏ dấu, KHÔNG dùng làm định danh mạnh (ở VN 'Nguyễn Văn A' trùng
hàng nghìn người) — chỉ để ghim vào pool cho ③ đọc. ③ vẫn là chỗ phán đoán.
"""
from __future__ import annotations

import re

from people.normalize import normalize_name

#: Từ chức năng hay lẫn vào truy vấn nhưng KHÔNG phải một phần của tên.
_STOP = {
    "ung", "vien", "ứng", "viên", "ho", "so", "hồ", "sơ", "nguoi", "người",
    "candidate", "review", "danh", "gia", "đánh", "giá", "so", "sanh", "sánh",
    "compare", "va", "và", "voi", "với", "cho", "vi", "tri", "vị", "trí",
    "list", "profile", "cv", "the", "of", "and",
}

#: Họ Việt phổ biến — một cụm bắt đầu bằng họ thì nhiều khả năng là tên người.
_SURNAMES = {
    "nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo",
    "dang", "bui", "do", "ho", "ngo", "duong", "ly", "dinh", "mai", "trinh",
    "dao", "cao", "lam", "ha", "chu", "ta", "kieu", "ninh", "luu", "truong",
}


def _phrases(query_plan):
    """Cụm ứng viên-là-tên: từ mỗi search_query và information_need."""
    raw = list(getattr(query_plan, "search_queries", []) or [])
    need = getattr(query_plan, "information_need", "") or ""
    # "so sánh A và B" → tách theo " và ", " với ", dấu phẩy.
    for chunk in re.split(r"\s+(?:và|voi|với|,|;)\s+", need):
        raw.append(chunk)
    seen, out = set(), []
    for text in raw:
        cleaned = re.sub(r"[^\w\sÀ-ỹ]", " ", str(text or "")).strip()
        toks = [t for t in cleaned.split() if normalize_name(t) not in _STOP]
        if not (2 <= len(toks) <= 5):
            continue
        folded = normalize_name(" ".join(toks))
        if not folded or folded in seen:
            continue
        # Không phải cụm nào 2–5 từ cũng là tên: chỉ nhận khi bắt đầu bằng một
        # họ Việt, hoặc mọi token đều viết hoa chữ đầu (kiểu người ta gõ tên).
        first = folded.split()[0]
        looks_name = first in _SURNAMES or all(
            w[:1].isupper() for w in toks if w[:1].isalpha())
        if looks_name:
            seen.add(folded)
            out.append(folded)
    return out


def named_people(query_plan, *, limit=6, question=""):
    """`[person_id]` khớp tên riêng trong kế hoạch. Rỗng nếu không có tên nào."""
    folded_names = _phrases(query_plan)
    if not folded_names and not question:
        return []
    from people.models import Person

    # Một lần quét bảng tên: kho ~800 người, rẻ hơn 6 truy vấn `icontains`.
    index = {}
    for pid, name in Person.applicants().values_list("id", "display_name"):
        index.setdefault(normalize_name(name), []).append(pid)

    hits, seen = [], set()
    original = " " + normalize_name(question) + " "
    for name, pids in index.items():
        if len(name.split()) >= 2 and (" " + name + " ") in re.sub(r"[?.!,;:]", " ", original):
            for pid in pids:
                seen.add(pid)
                hits.append(pid)
    for folded in folded_names:
        want = set(folded.split())
        for key, pids in index.items():
            key_tokens = set(key.split())
            # Khớp đủ: mọi token của tên hỏi đều nằm trong tên hồ sơ (cho phép
            # hồ sơ có tên đệm dài hơn), hoặc ngược lại.
            if want <= key_tokens or key_tokens <= want:
                for pid in pids:
                    if pid not in seen:
                        seen.add(pid)
                        hits.append(pid)
        if len(hits) >= limit:
            break
    return hits[:limit]


def direct_named_people(question):
    """Exact named subject of a factual question, using the indexed name.

    Narrow scope intentionally excludes 'people similar to X' and searches
    merely mentioning a name. Duplicate full names stay ambiguous candidates.
    """
    text = normalize_name(question)
    match = re.match(r"^(?:cho toi biet )?(.+?)\s+(?:sinh\b|co bao nhieu nam\b|bao nhieu tuoi\b|tot nghiep\b|co chung chi\b)", text)
    if not match or not 2 <= len(match.group(1).split()) <= 6:
        return []
    from people.models import Person
    from django.db.models import Q
    name = match.group(1)
    # Direct/manual imports can legitimately leave the derived name blank.
    rows = Person.applicants().filter(Q(normalized_name=name) | Q(normalized_name=""))
    return [pid for pid, display in rows.values_list("id", "display_name")
            if normalize_name(display) == name]


def exact_name_count(question):
    """Đếm tên trên TOÀN kho cho câu hỏi kiểu ``bao nhiêu ... tên Tùng``.

    Đây là phép tra chỉ mục, không phải tìm kiếm ngữ nghĩa. Một từ được hiểu là
    một thành phần tên hoàn chỉnh; ``Tùng`` không khớp ``Tùngness``. Cụm nhiều
    từ phải xuất hiện liền nhau và đúng thứ tự trong họ tên đã chuẩn hoá.
    """
    text = normalize_name(question).strip(" ?.!,;:")
    patterns = (
        r"(?:trong kho\s+)?(?:co\s+)?bao nhieu\s+(?:ung vien|ho so|nguoi|cv)\s+(?:co\s+)?ten\s+(.+)$",
        r"(?:dem|tim)\s+(?:tat ca\s+)?(?:ung vien|ho so|nguoi|cv)\s+(?:co\s+)?ten\s+(.+)$",
    )
    wanted = ""
    for pattern in patterns:
        match = re.fullmatch(pattern, text)
        if match:
            wanted = " ".join(match.group(1).split())
            break
    if not wanted or len(wanted.split()) > 6:
        return None

    from people.models import Person
    needle = f" {wanted} "
    rows = []
    for pid, display in Person.applicants().values_list("id", "display_name"):
        if needle in f" {normalize_name(display)} ":
            rows.append({"id": pid, "name": display})
    return {"query": wanted, "matched": len(rows),
            "scope_total": Person.applicants().count(), "people": rows}


def referenced_people(projection, question):
    """Resolve explicit positional references in displayed order; None = no rule.

    Empty list means the explicit ordinal is out of range, not permission to
    search for somebody else. Semantic references remain the planner's job.
    """
    if projection is None or not hasattr(projection, "last_result_people"):
        return None
    people = projection.last_result_people(limit=50)
    ids = [row["id"] for row in people if row.get("id")]
    text = normalize_name(question)
    numbers = {"mot": 1, "hai": 2, "ba": 3, "bon": 4, "nam": 5,
               "nhat": 1, "dau tien": 1, "first": 1, "second": 2, "third": 3}
    ordinal = re.search(r"(?:nguoi|ung vien|ho so)\s+(?:thu\s+)?(\d+|hai|ba|bon|nam|nhat|dau tien)(?=\s|$|[?.!,])", text)
    if ordinal:
        token = ordinal.group(1)
        n = int(token) if token.isdigit() else numbers[token]
        return ids[n - 1:n] if 1 <= n <= len(ids) else []
    first = re.search(r"(\d+|mot|hai|ba|bon|nam)\s+(?:nguoi|ung vien|ho so)\s+(?:dau|tren)", text)
    if first:
        token = first.group(1)
        n = int(token) if token.isdigit() else numbers[token]
        return ids[:n] if 1 <= n <= len(ids) else []
    if re.search(r"(?:nguoi|ung vien)\s+dau(?:\s|$|[?.!,])", text):
        return ids[:1]
    if any(mark in text for mark in ("trong so nay", "trong so do", "nhung nguoi tren", "hai nguoi tren")):
        return ids
    if any(mark in text for mark in ("nguoi do", "nguoi vua noi")) and len(ids) == 1:
        return ids
    return None


def followup_people(projection, query_plan, question=""):
    """`[person_id]` của lượt trước — chỉ khi câu này là compare/followup."""
    if getattr(query_plan, "shape", "") not in ("compare", "followup"):
        return []
    if projection is None or not hasattr(projection, "last_result_people"):
        return []
    selected = referenced_people(projection, question)
    if selected is not None:
        return selected
    return [row["id"] for row in projection.last_result_people() if row.get("id")]


def pinned_for(query_plan, projection=None, *, limit=8, question=""):
    """Hợp nhất tên riêng + người lượt trước → `[person_id]` phải có trong pool."""
    out, seen = [], set()
    selected = referenced_people(projection, question)
    if selected is not None:
        return selected
    for pid in list(followup_people(projection, query_plan, question)) + list(
            named_people(query_plan, question=question)):
        if pid not in seen:
            seen.add(pid)
            out.append(pid)
    return out[:limit]
