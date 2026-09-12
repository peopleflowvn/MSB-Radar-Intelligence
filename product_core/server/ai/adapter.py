# -*- coding: utf-8 -*-
"""Hợp đồng model dùng chung — một seam giữa nghiệp vụ và nhà cung cấp LLM
(Master Plan §12, §22.1).

Implementation đầu tiên `RouterAdapter` bọc `ai.router` đang chạy — **không viết
lại SDK**. Call site mới phụ thuộc `ModelProviderAdapter` thay vì gọi thẳng
`router.complete`, để sau này đo/đổi/stream ở đúng một chỗ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import router as router_module
from .providers import LLMError

_THINKING_RE = re.compile(r"<(?:think|thinking|thought|reasoning)>(.*?)</(?:think|thinking|thought|reasoning)>", re.DOTALL | re.IGNORECASE)


def split_thinking(text):
    """('câu trả lời sạch', 'khối suy nghĩ') — dùng cho model không native."""
    text = str(text or "")
    match = _THINKING_RE.search(text)
    if not match:
        return text.strip(), ""
    clean = _THINKING_RE.sub("", text).strip()
    return clean, match.group(1).strip()


class _StreamTagDemuxer:
    """Tách thẻ <think>...</think> trong luồng answer thành các chunk thinking và answer riêng biệt."""
    def __init__(self):
        self.in_think = False
        self.buf = ""

    def feed(self, delta: str):
        self.buf += delta
        out = []
        while self.buf:
            if not self.in_think:
                match_open = re.search(r"<(?:think|thinking|thought|reasoning)>", self.buf, re.IGNORECASE)
                if match_open:
                    pre = self.buf[:match_open.start()]
                    if pre:
                        out.append(("answer", pre))
                    self.buf = self.buf[match_open.end():]
                    self.in_think = True
                else:
                    if "<" in self.buf:
                        idx = self.buf.rfind("<")
                        if idx > 0:
                            out.append(("answer", self.buf[:idx]))
                            self.buf = self.buf[idx:]
                        break
                    else:
                        out.append(("answer", self.buf))
                        self.buf = ""
            else:
                match_close = re.search(r"</(?:think|thinking|thought|reasoning)>", self.buf, re.IGNORECASE)
                if match_close:
                    think_text = self.buf[:match_close.start()]
                    if think_text:
                        out.append(("thinking", think_text))
                    self.buf = self.buf[match_close.end():]
                    self.in_think = False
                else:
                    if "<" in self.buf:
                        idx = self.buf.rfind("<")
                        if idx > 0:
                            out.append(("thinking", self.buf[:idx]))
                            self.buf = self.buf[idx:]
                        break
                    else:
                        out.append(("thinking", self.buf))
                        self.buf = ""
        return out

    def flush(self):
        out = []
        if self.buf:
            kind = "thinking" if self.in_think else "answer"
            out.append((kind, self.buf))
            self.buf = ""
        return out


@dataclass
class ModelRequest:
    messages: list
    task: str = ""
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: dict | None = None
    tools: list | None = None
    timeout: float | None = None
    extra: dict = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    #: Siêu dữ liệu để ghi event/audit — KHÔNG gửi cho provider.
    metadata: dict = field(default_factory=dict)

    def as_kwargs(self):
        kwargs = {}
        for key in ("temperature", "max_tokens", "response_format", "tools", "timeout"):
            val = getattr(self, key)
            if val is not None:
                kwargs[key] = val
        kwargs.update(self.extra)
        return kwargs


@dataclass
class ModelUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    def as_dict(self):
        return {"prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "total_tokens": self.total_tokens}


@dataclass
class ModelResponse:
    text: str
    provider: str = ""
    model: str = ""
    usage: ModelUsage = field(default_factory=ModelUsage)
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)


class ModelError(Exception):
    """Lỗi model đã chuẩn hoá; bọc mọi `LLMError` của lớp provider."""


class ModelProviderAdapter:
    """Giao diện. Nghiệp vụ chỉ biết tới class này."""

    def complete(self, request: ModelRequest) -> ModelResponse:
        raise NotImplementedError

    def stream(self, request: ModelRequest):
        """Iterator các mảnh:

            {"type": "thinking", "text": <delta>}
            {"type": "answer",   "text": <delta>}
            {"type": "error",    "text": <msg>}
            {"type": "done",     "response": ModelResponse}   # chunk cuối

        Mặc định: fallback không-stream (thinking rồi answer, mỗi cái một mảnh).
        """
        response = self.complete(request)
        clean, reasoning = split_thinking(response.text)
        if reasoning:
            yield {"type": "thinking", "text": reasoning}
        yield {"type": "answer", "text": clean or response.text}
        final = ModelResponse(text=clean or response.text, provider=response.provider,
                              model=response.model, usage=response.usage,
                              latency_ms=response.latency_ms,
                              raw={**response.raw, "reasoning": reasoning})
        yield {"type": "done", "response": final}


class RouterAdapter(ModelProviderAdapter):
    """Bọc `ai.router`. `complete_fn` / `stream_fn` cho phép test tiêm hàm giả."""

    def __init__(self, complete_fn=None, stream_fn=None):
        super().__init__()
        self._complete = complete_fn or router_module.complete
        # None -> dùng fallback không-stream của lớp cha (an toàn cho test / call
        # site chỉ cần complete). Production lấy adapter qua get_adapter().
        self._stream = stream_fn

    def complete(self, request: ModelRequest) -> ModelResponse:
        try:
            result = self._complete(request.messages, task=request.task,
                                    **request.as_kwargs())
        except LLMError as exc:
            raise ModelError(str(exc)) from exc
        return _to_response(result)

    def stream(self, request: ModelRequest):
        if self._stream is None:
            yield from super().stream(request)
            return
        try:
            chunks = self._stream(request.messages, task=request.task,
                                  **request.as_kwargs())
            first = next(chunks)
        except LLMError as exc:
            raise ModelError(str(exc)) from exc
        except StopIteration:
            return

        answer_parts, reasoning_parts, saw_native_reasoning = [], [], False
        demuxer = _StreamTagDemuxer()
        current = first
        while True:
            kind = current.get("type")
            if kind == "reasoning":
                saw_native_reasoning = True
                delta = current.get("text") or ""
                reasoning_parts.append(delta)
                yield {"type": "thinking", "text": delta}
            elif kind == "answer":
                delta = current.get("text") or ""
                if saw_native_reasoning:
                    answer_parts.append(delta)
                    yield {"type": "answer", "text": delta}
                else:
                    # Demux tag think nếu model trả về trong text thông thường
                    for sub_kind, sub_text in demuxer.feed(delta):
                        if sub_kind == "thinking":
                            reasoning_parts.append(sub_text)
                            yield {"type": "thinking", "text": sub_text}
                        else:
                            answer_parts.append(sub_text)
                            yield {"type": "answer", "text": sub_text}
            elif kind == "error":
                yield current
            elif kind == "done":
                if not saw_native_reasoning:
                    for sub_kind, sub_text in demuxer.flush():
                        if sub_kind == "thinking":
                            reasoning_parts.append(sub_text)
                            yield {"type": "thinking", "text": sub_text}
                        else:
                            answer_parts.append(sub_text)
                            yield {"type": "answer", "text": sub_text}
                completion = current.get("completion")
                base = _to_response(completion) if completion is not None else ModelResponse(
                    text="".join(answer_parts))
                full_answer = "".join(answer_parts) or base.text
                full_reasoning = "".join(reasoning_parts)
                if not full_reasoning:
                    clean, reasoning = split_thinking(full_answer)
                    if reasoning:
                        full_answer, full_reasoning = clean, reasoning
                base.text = full_answer
                base.raw = {**(base.raw or {}), "reasoning": full_reasoning}
                yield {"type": "done", "response": base}
                return
            try:
                current = next(chunks)
            except StopIteration:
                if not saw_native_reasoning:
                    for sub_kind, sub_text in demuxer.flush():
                        if sub_kind == "thinking":
                            reasoning_parts.append(sub_text)
                            yield {"type": "thinking", "text": sub_text}
                        else:
                            answer_parts.append(sub_text)
                            yield {"type": "answer", "text": sub_text}
                full_answer = "".join(answer_parts)
                full_reasoning = "".join(reasoning_parts)
                yield {"type": "done",
                       "response": ModelResponse(text=full_answer,
                                                 raw={"reasoning": full_reasoning,
                                                      "truncated": True})}
                return


def _to_response(result) -> ModelResponse:
    if result is None:
        return ModelResponse(text="")
    return ModelResponse(
        text=getattr(result, "text", "") or "",
        provider=getattr(result, "provider", "") or "",
        model=getattr(result, "model", "") or "",
        usage=ModelUsage(int(getattr(result, "prompt_tokens", 0) or 0),
                         int(getattr(result, "completion_tokens", 0) or 0)),
        latency_ms=int(getattr(result, "latency_ms", 0) or 0),
        raw=getattr(result, "raw", {}) or {})


def get_adapter() -> ModelProviderAdapter:
    return RouterAdapter(stream_fn=router_module.stream)
