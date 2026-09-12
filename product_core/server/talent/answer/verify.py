# -*- coding: utf-8 -*-
"""Kiểm chứng câu trả lời của ⑤ — vòng tự sửa.

② đã có `widen()` khi truy hồi mỏng. ⑤ thì không có gì: nó viết ra một câu trả
lời, và dù câu đó xếp sai thứ tự hay nêu nhiều người hơn số được xin, cũng không
ai bắt được.

Ở đây chỉ kiểm những thứ **CODE tự khẳng định được** bằng cách đối chiếu văn bản
với `chosen` — dữ liệu đã chốt ở ④. Không có LLM chấm LLM: một model chấm bài
model khác thì thêm một lượt gọi, thêm độ trễ, và vẫn có thể sai theo cùng một
kiểu. Những gì máy không tự kiểm được thì để `answer_eval` và người đọc lo.

Bốn phép kiểm, đều tất định:

    thu_tu     `sort_by` được xin thì thứ tự người XUẤT HIỆN trong bài phải khớp
               thứ tự ④ đã chốt
    so_luong   số người được nhắc không vượt `limit`
    co_nguon   nêu tên người thì phải có ít nhất một [n]
    dung_nguon nguồn phải nằm trong phần viết về đúng người, không chỉ xuất
               hiện đâu đó trong toàn bài
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

#: Số người tối thiểu để việc kiểm thứ tự có nghĩa.
MIN_FOR_ORDER = 2


def _occurrences(text, chosen):
    """Mọi lần tên xuất hiện, ưu tiên tên dài khi hai tên chồng lên nhau."""
    found = []
    for index, judgement in enumerate(chosen):
        parts = [re.escape(part) for part in str(judgement.name or "").split()]
        if not parts:
            continue
        pattern = re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)
        found.extend((index, match.start(), match.end())
                     for match in pattern.finditer(text))
    # "An" must not become another mention inside "Nguyễn Văn An". Keep the
    # widest match at an identical/overlapping location.
    found.sort(key=lambda row: (row[1], -(row[2] - row[1]), row[0]))
    kept = []
    for row in found:
        if kept and row[1] < kept[-1][2]:
            continue
        kept.append(row)
    return kept


def _positions(text, chosen):
    """Vị trí xuất hiện đầu tiên của từng người trong bài, theo thứ tự ④ đã chốt.

    Trả list `(index_trong_chosen, vi_tri_trong_bai)` cho những người thật sự
    được nhắc tên. Người không được nhắc thì bỏ qua — bài viết có quyền không
    kể hết.
    """
    first = {}
    for index, start, _end in _occurrences(text, chosen):
        first.setdefault(index, start)
    return sorted(first.items(), key=lambda row: row[0])


def _citation_numbers(text):
    return {int(number) for group in re.findall(r"\[([\d,\s]+)\]", text)
            for number in re.findall(r"\d+", group)}


def citation_audit(chosen, text, sources):
    """Audit source existence and local person ownership; not entailment."""
    text = str(text or "")
    valid = {source["n"]: source for source in sources}
    numbers = _citation_numbers(text)
    occurrences = _occurrences(text, chosen)
    mentioned = sorted({index for index, _start, _end in occurrences})
    locally_cited = set()
    for position, (index, _start, end) in enumerate(occurrences):
        next_start = (occurrences[position + 1][1]
                      if position + 1 < len(occurrences) else len(text))
        local_numbers = _citation_numbers(text[end:next_start])
        if any(valid[number].get("person_id") == chosen[index].person_id
               for number in local_numbers if number in valid):
            locally_cited.add(index)
    missing = [chosen[index].name for index in mentioned if index not in locally_cited]
    invalid = sorted(numbers - valid.keys())
    return {
        "status": "PASS" if not invalid and not missing else "FAIL",
        "mentioned_people": len(mentioned),
        "locally_cited_people": len(locally_cited & set(mentioned)),
        "invalid_source_numbers": invalid,
        "missing_local_source": missing,
        # A real, correctly assigned quote can still be unrelated to the claim.
        "semantic_entailment": "NOT_MEASURED",
    }


def check(query_plan, chosen, text, sources):
    """Trả list lỗi (chuỗi mô tả). Rỗng nghĩa là không phát hiện gì."""
    problems = []
    text = str(text or "")
    if not text.strip() or not chosen:
        return problems

    mentioned = _positions(text, chosen)

    # 1. Thứ tự. ④ đã sắp xếp tất định; nếu ⑤ kể theo thứ tự khác thì người đọc
    #    nhận một bảng xếp hạng sai — đúng thứ họ hỏi ("ít tuổi nhất").
    if query_plan.sort_by and len(mentioned) >= MIN_FOR_ORDER:
        ranks = [index for index, _at in sorted(mentioned, key=lambda row: row[1])]
        if ranks != sorted(ranks):
            key = (query_plan.sort_by or {}).get("key", "")
            problems.append(
                f"Thứ tự trình bày không khớp thứ tự đã sắp theo \"{key}\". "
                f"Phải kể theo đúng thứ tự trong \"ket_qua\", từ trên xuống.")

    # 2. Số lượng. Kể nhiều hơn số được xin là trả lời sai câu hỏi.
    limit = int(getattr(query_plan, "limit", 0) or 0)
    if limit and len(mentioned) > limit:
        problems.append(
            f"Bài nhắc tên {len(mentioned)} người trong khi người hỏi chỉ xin "
            f"{limit}. Bỏ bớt cho đúng số.")

    # 3. Có nguồn. Nêu tên mà không dẫn được nguồn nào là khẳng định trần.
    if mentioned and not re.search(r"\[\d", text):
        problems.append(
            "Bài nêu tên người nhưng không có trích dẫn [n] nào. Mỗi khẳng định "
            "về một người phải kèm số hiệu nguồn của người đó.")
    elif mentioned:
        # Existence/ownership can be checked by code. Entailment still needs
        # evidence review; valid brackets alone never prove a claim is true.
        audit = citation_audit(chosen, text, sources)
        if audit["invalid_source_numbers"]:
            problems.append("Có trích dẫn không tồn tại trong danh sách nguồn đã xác minh.")
        for name in audit["missing_local_source"]:
            problems.append(
                f"Thiếu trích dẫn đúng phần viết về {name}. "
                "Đặt số nguồn của chính hồ sơ này sau nhận định tương ứng.")

    if problems:
        log.info("answer.verify: %d lỗi trong câu trả lời: %s",
                 len(problems), "; ".join(p[:60] for p in problems))
    return problems


def repair_messages(messages, problems):
    """Thêm một lượt chỉ ra lỗi và yêu cầu viết lại.

    Giữ nguyên toàn bộ ngữ cảnh của lượt đầu rồi nối thêm — model cần thấy đúng
    dữ liệu cũ để viết lại, không phải viết mù từ mô tả lỗi.
    """
    return list(messages) + [{
        "role": "user",
        "content": ("Câu trả lời vừa rồi có lỗi sau:\n"
                    + "\n".join(f"- {p}" for p in problems)
                    + "\n\nViết lại câu trả lời cho đúng. Giữ nguyên nội dung và "
                      "trích dẫn còn lại; chỉ sửa đúng những lỗi trên."),
    }]
