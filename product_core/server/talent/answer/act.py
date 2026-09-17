# -*- coding: utf-8 -*-
"""Nhánh HÀNH ĐỘNG — khi người dùng bảo làm việc gì thay vì hỏi điều gì.

"Soạn thư cho 3 người đầu", "nhớ giúp tôi là chỉ tuyển ở Hà Nội", "dữ kiện này
lấy từ đâu ra" — đây là mệnh lệnh, không phải câu hỏi tra cứu. Đưa chúng qua
①→⑤ là sai từ gốc: ② sẽ đi tìm lại từ đầu và có thể ra một danh sách KHÁC với
danh sách người dùng đang nói tới.

Nhánh này không viết vòng lặp tool mới. Dự án đã có `ai/agent.py` (vòng lặp gọi
tool, có trần bước, có hợp đồng huỷ, có lọc RBAC ở `ai/toolset.py`) cùng 8 tool
đã viết xong và đang bật trên production. Việc ở đây chỉ là **nối lại** —
`talent/ask/` trước đó không có tool nào, nên cả 8 cái đó không chạm tới được.

Ranh giới giữ nguyên như `agents/runtime.py` đã đặt: tool ở đây **chỉ đọc hoặc
chỉ đề xuất**. Không gửi thư, không đăng gì, không sửa hồ sơ. `draft_outreach`
trả bản nháp để người dùng tự quyết.
"""
from __future__ import annotations

import logging

from ai import agent as agent_mod
from ai import toolset

log = logging.getLogger(__name__)

#: Số người của lượt trước bơm vào ngữ cảnh cho model biết "3 người đầu" là ai.
CONTEXT_PEOPLE = 10


def people_in_context(envelope, history=None):
    """Danh sách người của lượt trước — đối tượng mà mệnh lệnh đang trỏ tới."""
    projection = getattr(envelope, "projection", None)
    last = dict(getattr(projection, "last_result", None) or {}) if projection else {}
    items = list(last.get("items") or last.get("people") or [])[:CONTEXT_PEOPLE]
    return [{"person_id": item.get("id") or item.get("person_id"),
             "name": item.get("name") or ""}
            for item in items if (item.get("id") or item.get("person_id"))]


def _system(people):
    lines = [
        "Bạn là Radar — trợ lý tuyển dụng của MSB. Người dùng đang BẢO BẠN LÀM "
        "một việc, không phải hỏi một câu.",
        "",
        "Dùng tool được cấp để làm. Quy tắc:",
        "- Chỉ làm đúng việc được bảo. Không tự ý làm thêm.",
        "- Tool ở đây chỉ ĐỌC hoặc chỉ ĐỀ XUẤT. Bạn không gửi thư, không đăng gì,"
        " không sửa hồ sơ. Bản nháp soạn ra là để người dùng tự quyết.",
        "- Không viết ra email hay số điện thoại của ứng viên.",
        "- Thiếu một chi tiết mà bối cảnh SUY RA ĐƯỢC thì cứ làm, và nói rõ giả "
        "định đã dùng. Ví dụ tìm 'ứng viên biết Java' rồi bảo soạn thư: lấy luôn "
        "vị trí lập trình viên Java làm lý do tiếp cận, ghi rõ 'giả định vị trí "
        "…' để người dùng sửa nếu sai. Đứng lại hỏi khi bối cảnh đã đủ để đoán "
        "hợp lý là bắt người dùng gõ thêm một lượt cho việc họ vừa mới nhờ.",
        "- Chỉ HỎI LẠI khi thật sự không suy ra nổi, và hỏi đúng MỘT câu ngắn.",
        "- Dùng tool `estimate_profile_gaps` xong thì KHÔNG được viết số ước tính "
        "như một dữ kiện đã xác nhận. Luôn gắn rõ đây là ước tính, VÀ phân biệt "
        "hai mức: method='formula' nói 'ước tính khoảng 6 năm kinh nghiệm (suy từ "
        "năm tốt nghiệp 2018, CV không ghi trực tiếp)'; method='model_reasoning' "
        "phải nói rõ hơn là PHỎNG ĐOÁN CHƯA CHẮC CHẮN, ví dụ 'phỏng đoán (chưa "
        "chắc) khoảng 5 năm kinh nghiệm, dựa trên chức danh Senior trong CV — "
        "không có mốc thời gian nào để tính chính xác hơn'. Không viết trống "
        "'có 6 năm kinh nghiệm' cho cả hai mức.",
        "- Trả lời tiếng Việt, gọn, nói rõ bạn đã làm gì.",
    ]
    if people:
        lines += ["", "Những người đang được nhắc tới ở lượt trước (theo thứ tự):"]
        lines += [f"{i}. {p['name']} (person_id={p['person_id']})"
                  for i, p in enumerate(people, start=1)]
    return "\n".join(lines)


def available(user):
    """Có tool nào dùng được cho tài khoản này không (đã lọc RBAC)."""
    return bool(toolset.agent_toolset_for("talent", user))


def stream_action(question, *, envelope=None, user=None, history=None,
                  adapter=None):
    """Yield chunk giống `engine.stream_answer`: stage / answer / done.

    Chuyển tiếp sự kiện của `ai.agent.iter_turn` và gắn nhãn tiếng Việt cho từng
    tool để người dùng thấy Radar đang làm gì, không phải một thanh chờ câm.
    """
    people = people_in_context(envelope, history)
    projection = getattr(envelope, "projection", None)
    from .resolve import referenced_people
    selected = referenced_people(projection, question)
    if selected is not None:
        if not selected:
            text = "Không xác định được người ở vị trí đó trong kết quả trước. Bạn chọn lại người cần thao tác."
            yield {"type": "answer", "text": text}
            yield {"type": "done", "payload": {"text": text, "people": [], "tool_trace": []}}
            return
        # Use the full displayed set when an ordinal lies beyond the prompt cap.
        rows = projection.last_result_people(limit=50)
        by_id = {p["id"]: p for p in rows}
        people = [{"person_id": pid, "name": by_id[pid].get("name", "")} for pid in selected]
    context = {"people": people, "question": question}
    if selected is not None:
        context["selected_person_ids"] = selected

    yield {"type": "stage", "stage": "act", "text": "Đang thực hiện yêu cầu"}

    tool_trace, answer_parts = [], []
    result = None
    for chunk in agent_mod.iter_turn(
            question, surface="talent", user=user, projection=projection,
            adapter=adapter, system=_system(people), context=context):
        kind = chunk.get("type")
        if kind == "tool":
            call = chunk["tool"]
            tool_trace.append(call)
            yield {"type": "stage", "stage": "tool",
                   "text": toolset.label_of(call.get("name", ""))}
        elif kind == "answer":
            answer_parts.append(chunk.get("text") or "")
            yield {"type": "answer", "text": chunk.get("text") or ""}
        elif kind == "error":
            log.warning("answer.act: tool lỗi: %s", chunk.get("text"))
        elif kind == "done":
            result = chunk.get("result")

    text = "".join(answer_parts).strip()
    if not text and result is not None:
        text = getattr(result, "text", "") or ""
    if not text:
        text = ("Tôi chưa thực hiện được yêu cầu này. Bạn nói rõ hơn giúp tôi "
                "cần làm gì với ai không?")
        yield {"type": "answer", "text": text}

    return_people = [{"person_id": p["person_id"], "name": p["name"], "why": "",
                      "attributes": {}, "citations": []} for p in people]
    yield {"type": "done", "payload": {
        "text": text,
        "people": return_people,
        "tool_trace": tool_trace,
        "provider": getattr(result, "provider", "") if result else "",
        "model": getattr(result, "model", "") if result else "",
        "reasoning": getattr(result, "reasoning", "") if result else "",
    }}
