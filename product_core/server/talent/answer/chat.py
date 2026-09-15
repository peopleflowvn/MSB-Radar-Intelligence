# -*- coding: utf-8 -*-
"""Nhánh CÂU HỎI PHỔ THÔNG — thứ không hỏi về Kho con người.

"Radar là ai?", "MSB có bao nhiêu chi nhánh?", "lãi suất huy động hiện nay thế
nào?" — những câu này không có gì để truy hồi trong kho CV, và đưa chúng qua
①→⑤ cho ra một câu trả lời sai giọng: ⑤ viết bằng prompt tuyển dụng, trên một
danh sách ứng viên rỗng.

Trước đây màn Talent gọi `ai/assistant/stream/`, nơi có sẵn ba tầng cho loại câu
hỏi này. Khi tôi dồn mọi câu hỏi về `/talent/ask/`, cả ba tầng đó **mất đường
tới**: câu trả lời có sẵn, tra web (DuckDuckGo), và model hội thoại. Module này
nối chúng lại, dùng đúng các helper cũ chứ không viết lại:

    common_answer            câu hỏi meta có câu trả lời cố định, không tốn token
    websearch.web_answer     cần dữ liệu ngoài / thời gian thực → tra web, dẫn nguồn
    build_conversation_request  còn lại → hội thoại thường, model hội thoại
"""
from __future__ import annotations

import logging

from ai import websearch
from ai.adapter import ModelError, get_adapter
from ai.conversation import build_conversation_request, knowledge_sources, web_system

from . import corpus

log = logging.getLogger(__name__)

#: Dấu hiệu câu hỏi đang nói về KHO của chính Radar chứ không phải kiến thức
#: chung. Rộng tay có chủ đích: bơm thừa vài dòng số liệu vào prompt thì vô hại,
#: còn thiếu thì Radar chối bỏ dữ liệu nó đang có.
_STORE_WORDS = ("cv", "hồ sơ", "ho so", "ứng viên", "ung vien", "kho", "dữ liệu",
                "du lieu", "ngành", "nganh", "kỹ năng", "ky nang", "bao nhiêu",
                "bao nhieu", "tổng quan", "tong quan", "thống kê", "thong ke",
                "danh sách", "danh sach", "có gì", "co gi")


def _asks_about_store(question):
    low = str(question or "").casefold()
    return any(word in low for word in _STORE_WORDS)


def _do_web(question, wants_web):
    """Có nên tra web cho câu này không.

    `intent.is_web` bắt được các câu rõ ràng ("tin tức…", "giá vàng hôm nay"),
    nhưng KHÔNG bắt "Tổng giám đốc MSB là ai" hay "thời tiết Hà Nội" — và một
    trợ lý tuyển dụng thì không có cách nào trả lời đúng mấy câu đó từ trí nhớ
    model. Chủ dự án yêu cầu (05/09): câu kiểu này phải tra Google.

    Nguyên tắc: đã tới nhánh này (không phải câu về kho, không phải câu meta có
    sẵn) thì MẶC ĐỊNH tra web khi web bật — model hội thoại chỉ là lưới đỡ.
    `web_answer` tự chặn câu có PII.

    KHÔNG xét tài liệu tri thức nội bộ ở đây — xem `stream_chat`: nội bộ được
    tra TRƯỚC và thắng tuyệt đối nếu có, hàm này chỉ quyết định khi nội bộ
    không có gì.
    """
    if not websearch.enabled():
        return False
    if wants_web:
        return True
    # Câu quá ngắn kiểu "ok", "cảm ơn" thì khỏi tra.
    return len(str(question or "").split()) >= 2


def stream_chat(question, *, envelope=None, user=None, intent=None, adapter=None):
    """Yield chunk giống `engine.stream_answer`: stage / answer / done.

    Chunk `done` mang `payload` để engine đóng gói thành `AnswerResult`.
    """
    model = adapter or get_adapter()
    projection = getattr(envelope, "projection", None)

    # Tài liệu tri thức nội bộ (chính sách/quy trình công ty) được tra TRƯỚC,
    # và THẮNG TUYỆT ĐỐI nếu có: nó do chính công ty viết, đáng tin hơn một kết
    # quả web ngẫu nhiên cho cùng câu hỏi, và né được việc đẩy một câu nghe như
    # hỏi chuyện nội bộ ra một cỗ máy tìm kiếm công khai. Rẻ cho phần lớn tài
    # khoản: `knowledge_sources` trả `[]` ngay lập tức, không gọi mạng, nếu
    # user không có module `knowledge` (accounts/roles.py::MODULE_KNOWLEDGE).
    internal_sources = knowledge_sources(question, user)

    # Cần dữ liệu ngoài kho → tra web. `intent` do người gọi cấp (đã phân
    #    loại rồi thì không phân loại lại); không có thì tự hỏi.
    wants_web = getattr(intent, "is_web", None)
    if wants_web is None:
        try:
            from ai import intent as intent_router
            wants_web = bool(intent_router.classify(
                question, surface="talent", user=user).is_web)
        except Exception:                          # noqa: BLE001
            wants_web = False

    if not internal_sources and _do_web(question, wants_web):
        yield {"type": "stage", "stage": "web", "text": "Đang tra trên internet"}
        try:
            result = websearch.web_answer(
                question, system=web_system("talent", user), adapter=model)
            text = str(getattr(result, "text", "") or "").strip()
            if text:
                yield {"type": "answer", "text": text}
                yield {"type": "done", "payload": {
                    "text": text, "mode": "web",
                    "web_sources": list(getattr(result, "citations", []) or []),
                    "provider": getattr(result, "provider", ""),
                    "model": getattr(result, "model", "")}}
                return
        except Exception as exc:                   # noqa: BLE001
            # Tra web hỏng không được làm hỏng cả lượt — lùi về hội thoại thường
            # và nói rõ giới hạn, thay vì trả về màn hình trắng.
            log.warning("answer.chat: tra web hỏng, lùi về hội thoại: %s", exc)

    # 3. Hội thoại thường — persona + quyền + memory, model hội thoại.
    yield {"type": "stage", "stage": "chat", "text": "Đang trả lời"}
    request, guard_flags = build_conversation_request(
        question, surface="talent", user=user, projection=projection,
        knowledge=internal_sources)

    # Bơm SỐ LIỆU THẬT về kho vào prompt khi câu hỏi có dính tới dữ liệu.
    #
    # Không có bước này thì hỏi "bạn có CV những ngành nào" Radar trả lời "không
    # có dữ liệu thực tế về danh sách ngành nghề" — trong khi kho có 786 hồ sơ
    # (đúng ảnh người dùng gửi). Nó không nói dối có chủ đích: nhánh này vốn
    # không có đường nào nhìn thấy kho.
    if _asks_about_store(question):
        facts = corpus.facts_for_prompt()
        if facts:
            request.messages.insert(
                max(0, len(request.messages) - 1),
                {"role": "system", "content": facts})

    parts, reasoning, provider, model_name = [], [], "", ""
    try:
        for chunk in model.stream(request):
            kind = chunk.get("type")
            if kind == "answer":
                parts.append(chunk.get("text") or "")
                yield chunk
            elif kind == "thinking":
                reasoning.append(chunk.get("text") or "")
                yield {"type": "reasoning", "text": chunk.get("text") or ""}
            elif kind == "done":
                response = chunk.get("response")
                provider = getattr(response, "provider", "") or ""
                model_name = getattr(response, "model", "") or ""
                if not parts and response is not None:
                    parts.append(getattr(response, "text", "") or "")
    except ModelError as exc:
        log.warning("answer.chat: model lỗi: %s", exc)

    text = "".join(parts).strip()

    # Model hội thoại trả RỖNG (câu factual nó không biết, hoặc bị chặn bởi
    # persona). Thử web lần cuối — thà một câu có nguồn còn hơn "không có nội
    # dung". Kể cả khi lần web đầu đã hỏng: model chạy mất vài giây, backend có
    # thể đã hết nghẽn.
    if not text and websearch.enabled():
        yield {"type": "stage", "stage": "web", "text": "Đang tra trên internet"}
        try:
            result = websearch.web_answer(
                question, system=web_system("talent", user), adapter=model)
            wtext = str(getattr(result, "text", "") or "").strip()
            if wtext:
                yield {"type": "answer", "text": wtext}
                yield {"type": "done", "payload": {
                    "text": wtext, "mode": "web",
                    "web_sources": list(getattr(result, "citations", []) or []),
                    "provider": getattr(result, "provider", ""),
                    "model": getattr(result, "model", "")}}
                return
        except Exception as exc:                   # noqa: BLE001
            log.warning("answer.chat: tra web (lần cuối) hỏng: %s", exc)

    if not text:
        text = ("Tôi chưa tra được câu này. Bạn thử hỏi lại cụ thể hơn, hoặc "
                "hỏi về hồ sơ trong Kho con người giúp tôi.")
        yield {"type": "answer", "text": text}

    yield {"type": "done", "payload": {
        "text": text, "mode": "chat", "provider": provider, "model": model_name,
        "reasoning": "".join(reasoning), "guard_flags": list(guard_flags or [])}}
