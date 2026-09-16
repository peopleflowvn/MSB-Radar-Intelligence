# -*- coding: utf-8 -*-
"""Small, reliable conversation layer shared by Talent and RB assistants.

Search endpoints used to treat every utterance as a database query.  This module
handles conversational questions whose answer is part of the product contract,
so "bạn là ai?" can never accidentally become a full-text candidate search.
"""
import re
import unicodedata

from .adapter import ModelRequest, RouterAdapter, get_adapter
from .persona import STABLE_PROMPT_VERSION, address_for, scope_for, stable_system
from .prompt_guard import GUARD_RULE, scan as guard_scan, wrap_source

MAX_HISTORY_TURNS = 16

__all__ = ["address_for", "common_answer", "extract_thinking",
           "answer_if_conversation", "sanitize_history", "ConversationReply",
           "is_conversational", "build_conversation_request", "knowledge_sources",
           "plain_text"]


class ConversationReply(str):
    """Câu trả lời hội thoại, vẫn là `str` để call site cũ dùng nguyên như trước,
    nhưng mang thêm siêu dữ liệu để ghi event và lưu `reasoning_trace`."""

    def __new__(cls, text, *, reasoning="", provider="", model="",
                request=None, usage=None, guard_flags=None, projection_version=0,
                citations=None, web=False, intent=None, web_queries=None,
                tool_trace=None):
        obj = super().__new__(cls, text or "")
        obj.reasoning = reasoning or ""
        obj.provider = provider or ""
        obj.model = model or ""
        obj.request = request
        obj.usage = usage
        obj.guard_flags = list(guard_flags or [])
        obj.projection_version = projection_version
        #: nguồn web [{title,url}] khi câu trả lời tra Google; [] nếu không.
        obj.citations = list(citations or [])
        obj.web = bool(web)
        obj.web_queries = list(web_queries or [])
        #: [{name, ok, summary, ...}] các tool đã gọi trong lượt (agent); [] nếu không.
        obj.tool_trace = list(tool_trace or [])
        #: ai.intent.IntentResult của lượt này (để ghi event), hoặc None.
        obj.intent = intent
        return obj


def _plain(value):
    # `đ` không có dạng tổ hợp nên NFD không tách được dấu — nếu không thay tay
    # thì nó bị regex `[^a-z0-9]` xoá SẠCH: "đánh giá" → "anh gia", và mọi mẫu
    # khớp có chữ "đ" trượt.
    value = str(value or "").casefold().replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


#: Tên công khai của `_plain` cho các module khác so khớp cụm từ tiếng Việt
#: không dấu (`talent.answer.chat` dò câu chào). Viết lại bộ chuẩn hoá ở nơi
#: khác là chép lại cả cái bẫy chữ "đ" ở trên.
plain_text = _plain


def common_answer(question, surface="talent", user=None):
    """Return a grounded product answer, or an empty string for a search request."""
    text = _plain(question)
    if not text:
        return ""

    identity = any(phrase in text for phrase in (
        "ban la ai", "ban ten gi", "gioi thieu ve ban", "ai tao ra ban",
        "who are you", "what are you",
    ))
    capability = any(phrase in text for phrase in (
        "ban lam duoc gi", "ban co the lam gi", "chuc nang cua ban",
        "giup duoc gi", "what can you do", "capabilities",
        # Câu "tự đánh giá" đi thẳng vào model hội thoại rồi stream đứt giữa
        # chừng ("Mất kết nối khi đang trả lời" — ảnh test 04/09). Nó không có
        # gì để tra trong kho và cũng không có câu chốt; xử như câu hỏi năng lực.
        # Giữ HẸP: chỉ những cụm rõ là "tự nhận xét về mình", không phải mọi câu
        # có chữ "khả năng" (đó có thể là câu hỏi tiếp thật).
        "tu danh gia", "tu nhan xet", "danh gia ban than",
        "danh gia kha nang cua ban", "danh gia nang luc cua ban",
        "ban tu tin khong", "ban co gioi khong", "ban gioi den dau",
        "how good are you", "rate yourself", "assess yourself",
    ))
    if not (identity or capability):
        return ""

    if surface == "prospect":
        role = ("Radar là trợ lý Growth Radar của MSB Radar, hỗ trợ RM tìm và phân tích "
                "khách hàng tiềm năng từ dữ liệu được phép truy cập.")
        abilities = ("Radar có thể hiểu yêu cầu bằng tiếng Việt hoặc tiếng Anh, tìm khách hàng, "
                     "xếp hạng theo tín hiệu phù hợp, giải thích bằng chứng và giúp tinh chỉnh "
                     "kết quả qua nhiều lượt hỏi đáp.")
    else:
        role = ("Radar là trợ lý Talent Radar của MSB Radar, hỗ trợ Recruiter và RM tìm, "
                "so sánh và phân tích hồ sơ trong Kho con người.")
        abilities = ("Radar có thể hiểu yêu cầu tiếng Việt hoặc tiếng Anh, đọc bằng chứng trong CV, "
                     "tìm và xếp hạng ứng viên, giải thích điểm phù hợp và tinh chỉnh tiêu chí "
                     "qua nhiều lượt hỏi đáp.")
    origin = ("Radar là một chức năng AI trong hệ thống MSB Radar, được đội phát triển MSB Radar "
              "xây dựng và kết nối với mô hình AI do quản trị viên cấu hình. Radar không tự tạo ra "
              f"dữ liệu và chỉ làm việc trên thông tin mà tài khoản của {address_for(user)} được phép xem.")
    if "ai tao ra ban" in text:
        return origin
    if capability and not identity:
        return abilities
    return f"{role} {abilities} {origin}"


def extract_thinking(raw_text):
    """Bóc tách khối suy nghĩ <think>...</think> hoặc <thinking>...</thinking> nếu có."""
    if not raw_text:
        return "", ""
    text = str(raw_text)
    pattern = r"<(?:think|thinking|thought|reasoning)>(.*?)</(?:think|thinking|thought|reasoning)>"
    match = re.search(pattern, text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        thinking = match.group(1).strip()
        clean = re.sub(pattern, "", text, flags=re.DOTALL | re.IGNORECASE).strip()
        return clean, thinking
    return text.strip(), ""


_SEARCH_WORDS = ("tim", "loc", "ung vien", "ho so", "nhan su", "khach hang",
                 "prospect", "candidate", "cv", "nguoi phu hop", "danh sach")


def is_conversational(question, history=None):
    """True nếu câu hỏi nên được trả lời hội thoại (không phải truy hồi)."""
    text = _plain(question)
    prior_criteria = any(item.get("criteria") for item in (history or []))
    looks_conversational = (not prior_criteria and
                            ("?" in str(question) or text.startswith(
                                ("tai sao", "vi sao", "nhu the nao", "la gi",
                                 "how ", "what ", "why "))))
    return looks_conversational and not any(word in text for word in _SEARCH_WORDS)


def knowledge_sources(question, user, *, limit=None):
    """[(nhãn, trích đoạn)] tài liệu tri thức nội bộ liên quan tới câu hỏi.

    Rỗng khi: tính năng tắt, người dùng không có module `knowledge`, chưa có
    tài liệu nào, hoặc Intelligence không trả lời kịp. Đây là phần LÀM GIÀU
    ngữ cảnh — hỏng thì lượt hội thoại vẫn phải chạy như trước, không được ném
    lỗi ra ngoài.
    """
    from django.conf import settings

    if not getattr(settings, "ASSISTANT_KNOWLEDGE_CONTEXT", True):
        return []
    if user is None or not getattr(user, "is_authenticated", False):
        return []
    try:
        from talent.intelligence_client import KNOWLEDGE_CONTEXT_LIMIT, knowledge_search

        return knowledge_search(user, question, limit=limit or KNOWLEDGE_CONTEXT_LIMIT)
    except Exception:                          # noqa: BLE001 - không được làm hỏng lượt
        import logging

        # Nhánh này CHỈ chạy khi `knowledge_search` thật sự NÉM lỗi (service
        # tri thức nội bộ chết/timeout/JSON hỏng) — thiếu quyền module hay
        # không có tài liệu khớp trả `[]` bình thường, không tới đây. Mức
        # WARNING để lỗi hạ tầng này lọt vào alerting thay vì chìm trong log
        # INFO — trước đây một service chết âm thầm trông giống hệt "không có
        # tài liệu nào khớp", không cách nào phân biệt trên production.
        logging.getLogger(__name__).warning("knowledge context unavailable", exc_info=True)
        return []


def build_conversation_request(question, surface="talent", user=None, projection=None,
                               knowledge=None):
    """(ModelRequest, guard_flags) cho một lượt hội thoại thường.

    Prompt xếp ba tầng (§15 GĐ1, §23.1.2):

        [system] STABLE   — persona + safety + xưng hô + scope (không đổi giữa lượt)
        [system] CONTEXT  — quyền + memory đã duyệt + summary (từ projection)
        [user]  NGUỒN     — tài liệu nội bộ liên quan (nếu có), đã bọc prompt_guard
        [user/assistant]  — các lượt gần nhất
        [user]  VOLATILE  — câu hỏi hiện tại

    Tầng NGUỒN là điểm nối DUY NHẤT của kho tri thức nội bộ vào hội thoại: mọi
    bề mặt (stream_views, answer_if_conversation, agent, talent chat) đều dựng
    prompt qua đây, nên không phải thêm nhánh riêng cho từng bề mặt.

    `knowledge`: kết quả `knowledge_sources()` nếu bên gọi đã tự tra sẵn (ví dụ
    để quyết định có tra web hay không trước khi tới đây) — tránh tra lại lần
    hai. Bỏ trống thì hàm tự tra.
    """
    guard_flags = guard_scan(question)

    messages = [{"role": "system", "content": stable_system(surface, user)}]
    if projection is not None:
        ctx = projection.context_system()
        if ctx:
            messages.append(ctx)
        messages.extend(projection.turn_messages())

    sources = knowledge_sources(question, user) if knowledge is None else knowledge
    if sources:
        messages.append({"role": "system", "content": (
            GUARD_RULE + " Khi phần DỮ LIỆU NGUỒN dưới đây trả lời được câu hỏi, "
            "hãy dựa vào đó và nói rõ tên tài liệu/nguồn cho từng phần; nếu không "
            "liên quan thì bỏ qua và trả lời như bình thường. Có nhiều nguồn cùng "
            "lúc (ví dụ vừa có tài liệu nội bộ vừa có kết quả tra Internet) thì "
            "nói rõ TỪNG Ý lấy từ đâu. Tài liệu nội bộ có thể đã LỖI THỜI với "
            "những dữ kiện đổi theo thời gian (nhân sự lãnh đạo, lãi suất, số "
            "liệu thị trường…) — khi mâu thuẫn với kết quả tra Internet (mới "
            "hơn), ưu tiên kết quả tra Internet và nói rõ tài liệu nội bộ có thể "
            "đã cũ.")})
        for label, text in sources:
            wrapped = wrap_source(text, label)
            if wrapped:
                guard_flags = sorted(set(guard_flags) | set(guard_scan(text)))
                messages.append({"role": "user", "content": wrapped})

    messages.append({"role": "user", "content": str(question)[:1000]})

    request = ModelRequest(
        messages=messages, task="assistant_conversation",
        temperature=0.2, max_tokens=600,
        # Câu hội thoại thường không cần model "nghĩ" — nó cần trả nhanh một
        # đoạn văn ngắn. Không chặn thì model có bước suy nghĩ ăn hết ngân sách
        # rồi stream đứt ở giây thứ 120 của gunicorn, client thấy "Mất kết nối".
        extra={"reasoning_effort": "none", "budget_seconds": 40},
        meta={"stable_prompt_version": STABLE_PROMPT_VERSION,
              "prompt_layers": ["stable", "context", "turns", "volatile"]})
    return request, guard_flags


def web_system(surface, user):
    """Chỉ dẫn hệ thống cho lượt tra web: persona + bắt buộc trích nguồn."""
    return (stable_system(surface, user) + " "
            + "Câu hỏi này cần thông tin ngoài kho nội bộ nên Radar được phép tra "
            "web. Trả lời bằng tiếng Việt, ngắn gọn, nêu rõ mốc thời gian của "
            "số liệu, và CHỈ dựa trên kết quả tìm được. Không suy đoán ngoài nguồn.")


def _answer_via_web(question, surface, user, projection, adapter=None):
    """`ConversationReply` từ web search (bộ não nào cũng dùng được), hoặc None nếu hỏng."""
    from . import websearch
    try:
        result = websearch.web_answer(
            question, system=web_system(surface, user), adapter=adapter)
    except websearch.WebSearchUnavailable:
        return None
    except Exception:                              # noqa: BLE001
        # Web search không được phép làm hỏng lượt — lùi về trả lời thường.
        return None
    answer = str(result.text or "").strip()[:3000]
    if not answer:
        return None
    # Nguồn đi ở trường `citations` (giao diện render riêng), không nối vào text.
    pv = projection.projection_version if projection is not None else 0
    return ConversationReply(
        answer, provider=result.provider, model=result.model,
        usage=result.usage, citations=result.citations, web=True,
        web_queries=result.queries, projection_version=pv)


def _answer_via_agent(question, surface, user, projection, model, intent, pv):
    """Dùng vòng lặp tool khi bật `ASSISTANT_TOOLS` và có tool khả dụng; None nếu không."""
    from django.conf import settings
    if not getattr(settings, "ASSISTANT_TOOLS", False):
        return None
    from . import agent_select, toolset
    if not toolset.agent_toolset_for(surface, user):
        return None
    runner = agent_select.get_runner()
    result = runner.run_turn(question, surface=surface, user=user, projection=projection,
                             adapter=model)
    if not str(result.text).strip():
        return None
    return ConversationReply(
        str(result.text).strip()[:3000], reasoning=result.reasoning[:6000],
        provider=result.provider, model=result.model, usage=result.usage,
        request=result.last_request, projection_version=pv, intent=intent,
        tool_trace=result.trace_dicts())


def answer_if_conversation(question, surface="talent", history=None, complete_fn=None,
                           user=None, adapter=None, projection=None, intent=None):
    """Trả lời câu hỏi ngoài phạm vi tìm kiếm.

    Trả `ConversationReply` (vẫn là str) khi đây là câu hỏi hội thoại; trả `""`
    khi đây là yêu cầu truy hồi (để view chạy tiếp luồng search).

    `intent` (ai.intent.IntentResult) nếu có sẽ quyết định thay heuristic; khi
    `intent.kind == "web"` thì tra Google trước, hỏng thì lùi về model thường.

    Tài liệu tri thức nội bộ (nếu có, và user có module `knowledge`) luôn được
    tra trước. Khi `intent.kind == "web"` mà KHÔNG có tài liệu nội bộ, tra
    Internet và trả thẳng kết quả (như cũ). Có CẢ HAI — bộ phân loại ý định
    không biết gì về kho tri thức nội bộ nên có thể hợp lý gắn nhãn "web" cho
    một câu hỏi chính sách công ty — thì tra Internet SONG SONG rồi ghép làm
    hai nguồn cho hội thoại thường tự đối chiếu: tài liệu nội bộ có thể đã lỗi
    thời với dữ kiện đổi theo thời gian (nhân sự lãnh đạo, lãi suất…), nên
    KHÔNG được để nó thắng tuyệt đối một mình. Xem `talent/answer/chat.py::
    stream_chat` — cùng nguyên tắc, bề mặt khác.
    """
    fixed = common_answer(question, surface=surface, user=user)
    if fixed:
        return ConversationReply(fixed, intent=intent)

    want_web = intent is not None and getattr(intent, "kind", "") == "web"
    if intent is not None:
        if getattr(intent, "kind", "") == "search":
            return ""
    elif not is_conversational(question, history):
        return ""

    model = adapter or (RouterAdapter(complete_fn) if complete_fn else get_adapter())
    internal_sources = knowledge_sources(question, user)

    web_text, web_citations = "", []
    if want_web:
        web_reply = _answer_via_web(question, surface, user, projection, adapter=model)
        if web_reply is not None:
            if not internal_sources:
                web_reply.intent = intent
                return web_reply
            web_text = str(web_reply).strip()
            web_citations = list(web_reply.citations)

    sources = list(internal_sources)
    if web_text:
        sources.append(("Kết quả tra Internet vừa thực hiện", web_text))

    scope = scope_for(surface)
    if projection is None:
        from .projection import from_turns
        projection = from_turns(history or [], user=user, surface=surface)
    pv = projection.projection_version

    agent_reply = _answer_via_agent(question, surface, user, projection, model, intent, pv)
    if agent_reply is not None:
        return agent_reply

    request, guard_flags = build_conversation_request(
        question, surface=surface, user=user, projection=projection,
        knowledge=sources)
    try:
        response = model.complete(request)
    except Exception:                          # noqa: BLE001
        return ConversationReply(
            f"Câu hỏi này không phải yêu cầu tìm kiếm. Radar là trợ lý {scope}; "
            "hiện Radar chưa thể gọi mô hình để trả lời phần kiến thức ngoài phạm vi đó.",
            request=request, guard_flags=guard_flags, projection_version=pv, intent=intent)
    clean_text, reasoning = extract_thinking(response.text)
    answer = str(clean_text or response.text or "").strip()[:3000]
    return ConversationReply(answer, reasoning=reasoning[:6000], guard_flags=guard_flags,
                             provider=response.provider, model=response.model,
                             request=request, usage=response.usage, projection_version=pv,
                             intent=intent, citations=web_citations, web=bool(web_text))


def sanitize_history(raw_history):
    """Keep eight compact turns; never trust arbitrary client-side structures."""
    if not isinstance(raw_history, list):
        return None
    rows = []
    for item in raw_history[-MAX_HISTORY_TURNS:]:
        if not isinstance(item, dict):
            continue
        row = {}
        if isinstance(item.get("criteria"), dict):
            row["criteria"] = item["criteria"]
        question = str(item.get("question") or "").strip()[:1000]
        answer = str(item.get("answer") or "").strip()[:2000]
        if question:
            row["question"] = question
        if answer:
            row["answer"] = answer
        if row:
            rows.append(row)
    return rows or None
