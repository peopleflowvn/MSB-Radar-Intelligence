# -*- coding: utf-8 -*-
"""Intent router — đọc hiểu câu người dùng gõ TRƯỚC khi chọn nhánh xử lý.

Ba nhánh:

* ``search``       — tìm/lọc hồ sơ hoặc khách hàng trong kho (chạy pipeline search)
* ``conversation`` — hỏi đáp thường, kiến thức về sản phẩm / cách dùng / giải thích
* ``web``          — cần thông tin ngoài kho, tra Google (chỉ khi ``ASSISTANT_WEB_SEARCH``)

Trước đây việc này là heuristic thuần (`conversation.is_conversational`): "cho tôi
biết xu hướng tuyển dụng fintech 2026" bị coi là search vì có chữ "tìm"/"biết".
Ở đây một lượt gọi model nhỏ đọc câu hỏi + vài lượt gần nhất rồi phân loại; model
lỗi / cờ tắt → tự lùi về heuristic cũ, không bao giờ ném lỗi ra nghiệp vụ.

Bảo vệ: câu hỏi dính prompt-injection hoặc PII (email/điện thoại/số định danh)
**không bao giờ** được route sang ``web`` — hạ xuống ``conversation``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from django.conf import settings

from . import pii
from .adapter import ModelRequest, get_adapter
from .conversation import common_answer, is_conversational
from .prompt_guard import scan as guard_scan

log = logging.getLogger(__name__)

KIND_SEARCH = "search"
KIND_CONVERSATION = "conversation"
KIND_WEB = "web"
_KINDS = (KIND_SEARCH, KIND_CONVERSATION, KIND_WEB)

_SYNONYMS = {
    "search": KIND_SEARCH, "tim_kiem": KIND_SEARCH, "tìm_kiếm": KIND_SEARCH,
    "retrieval": KIND_SEARCH, "candidate_search": KIND_SEARCH, "people": KIND_SEARCH,
    "conversation": KIND_CONVERSATION, "chat": KIND_CONVERSATION,
    "hoi_dap": KIND_CONVERSATION, "knowledge": KIND_CONVERSATION,
    "product": KIND_CONVERSATION, "smalltalk": KIND_CONVERSATION,
    "web": KIND_WEB, "web_search": KIND_WEB, "google": KIND_WEB,
    "internet": KIND_WEB, "external": KIND_WEB,
}


@dataclass
class IntentResult:
    kind: str = KIND_CONVERSATION
    confidence: float = 0.0
    reason: str = ""
    #: fixed = câu trả lời có sẵn · model = LLM phân loại · heuristic/fallback = luật
    source: str = "heuristic"
    raw: dict = field(default_factory=dict)

    @property
    def is_search(self):
        return self.kind == KIND_SEARCH

    @property
    def is_web(self):
        return self.kind == KIND_WEB

    def as_dict(self):
        return {"intent": self.kind, "confidence": round(self.confidence, 3),
                "reason": self.reason[:300], "source": self.source}


_RUBRIC = (
    "Bạn là bộ phân loại ý định cho trợ lý tuyển dụng/bán lẻ ngân hàng. "
    "Đọc tin nhắn mới nhất của người dùng (có ngữ cảnh vài lượt trước) và phân vào MỘT nhãn:\n"
    "- \"search\": người dùng muốn TÌM / LỌC / LIỆT KÊ hồ sơ ứng viên hoặc khách hàng "
    "trong kho dữ liệu nội bộ, hoặc tinh chỉnh tiêu chí của lần tìm trước.\n"
    "- \"conversation\": hỏi đáp thường — Radar là ai/làm được gì, cách dùng, giải thích "
    "một kết quả vừa có, xin tư vấn cách tiếp cận, câu hỏi kiến thức chung mà model tự trả lời được.\n"
    "- \"web\": cần dữ kiện CẬP NHẬT hoặc NGOÀI kho nội bộ — tin tức, số liệu thị trường, "
    "thông tin công khai về một công ty/ngành/khung lương, quy định mới. KHÔNG dùng \"web\" cho "
    "câu hỏi về một cá nhân cụ thể.\n"
    "Chỉ trả JSON, ĐÚNG THỨ TỰ khoá này: "
    "{\"reason\": \"...\", \"intent\": \"...\", \"confidence\": 0.0-1.0}.\n"
    "\"reason\" viết TRƯỚC \"intent\": một câu ngắn nói người dùng đang muốn gì và "
    "vì sao nhãn đó đúng. Đây là chỗ NGHĨ để chọn, không phải chỗ biện minh sau "
    "khi đã chọn."
)


def _context_snippet(history, limit=3):
    turns = [t for t in (history or []) if isinstance(t, dict)][-limit:]
    lines = []
    for t in turns:
        q = str(t.get("question") or "").strip()
        a = str(t.get("answer") or "").strip()
        if q:
            lines.append(f"NGƯỜI DÙNG: {q[:200]}")
        if a:
            lines.append(f"RADAR: {a[:160]}")
    return "\n".join(lines)


def _heuristic(question, history, *, source="heuristic"):
    conv = is_conversational(question, history)
    return IntentResult(
        kind=KIND_CONVERSATION if conv else KIND_SEARCH,
        confidence=0.4, source=source,
        reason="luật dự phòng: " + ("giống hội thoại" if conv else "giống yêu cầu tìm"))


def _coerce(payload):
    intent = str(payload.get("intent") or payload.get("label") or "").strip().lower()
    intent = _SYNONYMS.get(intent, intent)
    if intent not in _KINDS:
        return None
    try:
        conf = float(payload.get("confidence"))
    except (TypeError, ValueError):
        conf = 0.6
    return IntentResult(kind=intent, confidence=max(0.0, min(1.0, conf)),
                        reason=str(payload.get("reason") or "")[:300],
                        source="model", raw=payload if isinstance(payload, dict) else {})


def classify(question, *, surface="talent", user=None, history=None, adapter=None):
    """Trả `IntentResult`. Không bao giờ ném lỗi ra ngoài."""
    q = str(question or "").strip()
    if not q:
        return IntentResult(kind=KIND_CONVERSATION, confidence=0.5, source="fixed",
                            reason="câu hỏi rỗng")

    # Câu có câu trả lời cứng (bạn là ai / làm được gì) — khỏi gọi model.
    if common_answer(q, surface=surface, user=user):
        return IntentResult(kind=KIND_CONVERSATION, confidence=1.0, source="fixed",
                            reason="câu hỏi nhận diện/khả năng, có câu trả lời sẵn")

    injection = bool(guard_scan(q))
    has_pii = pii.contains_pii(q)

    if not getattr(settings, "ASSISTANT_INTENT_ROUTER", True):
        return _demote(_heuristic(q, history, source="heuristic"), injection, has_pii)

    model = adapter or get_adapter()
    ctx = _context_snippet(history)
    user_block = (f"NGỮ CẢNH:\n{ctx}\n\n" if ctx else "") + f"TIN NHẮN MỚI:\n{q[:800]}"
    request = ModelRequest(
        messages=[{"role": "system", "content": _RUBRIC},
                  {"role": "user", "content": user_block}],
        # Nới từ 180: "reason" nay đứng TRƯỚC "intent", nên hạn mức chật sẽ cắt
        # JSON trước khi model kịp viết ra nhãn, và cả bộ phân loại rơi về
        # heuristic.
        task="assistant_intent", temperature=0.0, max_tokens=320,
        response_format={"type": "json_object"},
        meta={"router": "intent", "surface": surface})
    try:
        response = model.complete(request)
        payload = json.loads(_json_slice(response.text))
        result = _coerce(payload)
    except Exception as exc:                        # noqa: BLE001
        log.info("intent classifier lùi về heuristic: %s", exc)
        return _demote(_heuristic(q, history, source="fallback"), injection, has_pii)

    if result is None:
        return _demote(_heuristic(q, history, source="fallback"), injection, has_pii)
    result.raw = {"provider": response.provider, "model": response.model,
                  **(result.raw or {})}
    return _demote(result, injection, has_pii)


def _demote(result, injection, has_pii):
    """web → conversation khi có injection / PII / web search chưa bật."""
    if result.kind != KIND_WEB:
        return result
    from . import websearch
    if injection or has_pii or not websearch.enabled():
        why = ("injection" if injection else
               "PII" if has_pii else "web search tắt")
        return IntentResult(
            kind=KIND_CONVERSATION, confidence=result.confidence,
            source=result.source,
            reason=f"hạ web→hội thoại ({why}); {result.reason}"[:300],
            raw=result.raw)
    return result


def _json_slice(text):
    """Lấy object JSON đầu tiên trong text (model đôi khi bọc ```json)."""
    raw = str(text or "")
    start = raw.find("{")
    end = raw.rfind("}")
    return raw[start:end + 1] if start != -1 and end > start else raw
