# -*- coding: utf-8 -*-
"""Lớp trừu tượng nhà cung cấp LLM (Master Plan mục 7.1).

Phát hiện quyết định thiết kế: **cả bốn nhà cung cấp đều nói OpenAI
`/chat/completions`**, nên chỉ cần MỘT adapter với bốn cấu hình, không phải bốn
lớp riêng.

    GreenNode   https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1
                MaaS của GreenNode là OpenAI-compatible. Nhờ vậy adapter này
                chạy được với GreenNode NGAY, chỉ còn thiếu khoá và tên model —
                hai thứ lấy ở Workshop #1 ngày 28/08. Không phải chờ để viết code.
    OpenAI      https://api.openai.com/v1
    Gemini      https://generativelanguage.googleapis.com/v1beta/openai
                Google có endpoint tương thích OpenAI cho chat + embedding.
                Dùng nó thay vì API gốc để khỏi phải nuôi thêm một adapter.
    DeepSeek    https://api.deepseek.com/v1

Nghiệp vụ (Talent Agent, RB Agent, bộ phân loại ý định) gọi qua `complete()` và
không bao giờ biết phía sau là ai.

Mã model là CẤU HÌNH, không phải code — chúng đổi vài tháng một lần. Giá trị mặc
định ở đây đúng vào tháng 8/2026; đổi bằng biến môi trường, không phải sửa file này.
"""
import json
import logging
import os
import time
import urllib.error
import urllib.request

from .keypool import KeyPool, split_keys

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60


class LLMError(RuntimeError):
    """Lỗi khi gọi nhà cung cấp."""
    retryable = False


class LLMUnavailable(LLMError):
    """Sự cố tạm thời — đáng thử lại, hoặc chuyển sang provider dự phòng."""
    retryable = True


class LLMAuthError(LLMError):
    """Khoá sai hoặc hết hạn. Người dùng phải sửa."""
    retryable = False


class Completion:
    """Kết quả một lần gọi, kèm thông tin để ghi nhật ký và tính chi phí."""

    def __init__(self, text, provider, model, prompt_tokens=0, completion_tokens=0,
                 latency_ms=0, raw=None, truncated=False):
        self.text = text
        self.provider = provider
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.latency_ms = latency_ms
        self.raw = raw or {}
        #: Mô hình bị cắt giữa chừng vì hết hạn mức token (`finish_reason` là
        #: "length"). Câu trả lời cụt KHÔNG được coi như câu trả lời xong — xem
        #: `OpenAICompatibleProvider.complete`.
        self.truncated = truncated

    @property
    def reasoning(self):
        return (self.raw or {}).get("reasoning") or ""

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    def __repr__(self):
        return (f"<Completion {self.provider}/{self.model} "
                f"{self.total_tokens}tok {self.latency_ms}ms>")


#: Họ model trả HTTP 400 khi thấy `reasoning_effort` (không phải tham số chuẩn
#: OpenAI). Bỏ tham số đi còn hơn để cả lượt gọi hỏng vì một tuỳ chọn tối ưu hoá.
_NO_REASONING_EFFORT = ("deepseek",)


def _apply_reasoning_effort(body, model, reasoning_effort):
    """Gắn `reasoning_effort` vào body, trừ các model không nhận nó.

    Dùng CHUNG cho `complete` và `stream`. Trước đây chỉ `complete` có chốt chặn
    này: đường stream vẫn gửi tham số cho `deepseek-v4-pro` và nhận HTTP 400, nên
    chặng ⑤ của Answer Engine im lặng rơi về bản tóm tắt do CODE viết — mọi câu
    trả lời qua giao diện đều mất phần văn và mất trích dẫn, trong khi lệnh
    `answer_eval` (đi đường `complete`) vẫn xanh. Hai đường phải dùng một luật.
    """
    if not reasoning_effort:
        return
    name = str(model or "").lower()
    if any(token in name for token in _NO_REASONING_EFFORT):
        return
    body["reasoning_effort"] = reasoning_effort


class OpenAICompatibleProvider:
    """Một nhà cung cấp nói giao thức OpenAI chat completions.

    Dùng urllib chứ không phải SDK của từng hãng: bốn SDK là bốn bộ phụ thuộc,
    bốn lịch phát hành và bốn kiểu lỗi khác nhau — trong khi thứ ta cần chỉ là
    một lời gọi POST JSON.
    """

    def __init__(self, name, base_url, api_key, model, timeout=DEFAULT_TIMEOUT,
                 transport=None, extra_headers=None, stream_transport=None):
        self.name = name
        self.base_url = str(base_url or "").rstrip("/")
        self.model = model
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self._transport = transport or _urllib_transport
        self._stream_transport = stream_transport or _urllib_stream_transport

        # `api_key` nhận cả một khoá lẫn nhiều khoá (chuỗi phân cách hoặc danh
        # sách). Hạn mức tốc độ tính THEO TỪNG KHOÁ, nên ba khoá là hạn mức gấp ba.
        keys = api_key if isinstance(api_key, (list, tuple)) else split_keys(api_key)
        self.keys = KeyPool(keys, provider=name)

    @property
    def api_key(self):
        """Khoá đầu tiên. Giữ lại cho code cũ và cho lời gọi không xoay vòng."""
        return self.keys.states[0].key if len(self.keys) else ""

    def configured(self):
        return bool(self.base_url and len(self.keys) and self.model)

    def complete(self, messages, model=None, temperature=0.2, max_tokens=None,
                 response_format=None, tools=None, timeout=None,
                 reasoning_effort=None):
        """Gọi một lượt chat. `messages` theo đúng dạng OpenAI.

        `timeout` ghi đè thời gian chờ cho riêng lượt này. Router dùng nó để ép
        mỗi lượt nằm gọn trong phần ngân sách thời gian còn lại — xem
        `Router.BUDGET_SECONDS`.

        `reasoning_effort` tắt hoặc giảm phần "suy nghĩ" của model. Cần thiết vì
        **`max_tokens` tính CẢ token suy nghĩ**: đo thật với Gemini 3.5 Flash,
        `max_tokens=600` cho ra `finish_reason="length"` và chỉ 24 token nhìn
        thấy được — phần còn lại bị suy nghĩ ăn hết, và mảnh rò ra là chính nội
        dung mô hình đang tự nhủ (*"Let's count: Chào (1"*). Với
        `reasoning_effort="none"` thì cùng hạn mức đó cho ra câu trả lời hoàn
        chỉnh. Chỉ gửi khi người gọi yêu cầu, để không đụng vào nhà cung cấp
        không hiểu tham số này.
        """
        if not self.configured():
            raise LLMError(f"Nhà cung cấp '{self.name}' chưa được cấu hình đầy đủ.")

        wait = self.timeout if timeout is None else max(1.0, float(timeout))

        chosen_model = model or self.model
        body = {
            "model": chosen_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens:
            body["max_tokens"] = max_tokens
        if response_format:
            body["response_format"] = response_format
        if tools:
            body["tools"] = tools
        _apply_reasoning_effort(body, chosen_model, reasoning_effort)

        # Thử lần lượt các khoá của CHÍNH nhà cung cấp này trước khi bỏ cuộc.
        # Hạn mức tính theo từng khoá, nên khoá này hết không có nghĩa nhà cung
        # cấp hết — chuyển provider ngay là bỏ phí hạn mức còn lại.
        last_error = None
        for _ in range(max(1, len(self.keys))):
            state = self.keys.acquire()
            if state is None:
                break

            headers = {
                "Authorization": f"Bearer {state.key}",
                "Content-Type": "application/json",
            }
            headers.update(self.extra_headers)

            started = time.time()
            try:
                status, payload = self._transport(
                    self.base_url + "/chat/completions", headers, body, wait)
            except LLMError:
                raise
            except Exception as exc:
                raise LLMUnavailable(f"Không gọi được {self.name}: {exc}") from exc
            latency_ms = int((time.time() - started) * 1000)

            try:
                self._raise_for_status(status, payload)
            except LLMAuthError as exc:
                # Khoá hỏng hẳn: tắt nó rồi thử khoá tiếp theo. Chỉ báo lỗi ra
                # ngoài khi MỌI khoá đều hỏng.
                self.keys.report_invalid(state)
                last_error = exc
                log.warning("%s: khoá %s không hợp lệ, đã tắt", self.name, state.label)
                continue
            except LLMUnavailable as exc:
                if status == 429:
                    self.keys.report_rate_limited(state)
                    last_error = exc
                    log.info("%s: khoá %s hết hạn mức, chuyển khoá khác",
                             self.name, state.label)
                    continue
                # 5xx là lỗi của nhà cung cấp, không phải của khoá. Đổi khoá
                # không giúp gì, và phạt khoá là phạt nhầm.
                raise

            choices = payload.get("choices") or []
            if not choices:
                raise LLMUnavailable(f"{self.name} trả về không có lựa chọn nào.")
            msg_obj = choices[0].get("message") or {}
            text = msg_obj.get("content") or ""
            reasoning = msg_obj.get("reasoning_content") or msg_obj.get("reasoning") or msg_obj.get("thought") or ""
            raw_payload = dict(payload)
            if reasoning:
                raw_payload["reasoning"] = reasoning
            usage = payload.get("usage") or {}

            # Câu trả lời bị cắt giữa chừng KHÔNG phải câu trả lời. Trả về lặng
            # lẽ nghĩa là recruiter nhận một nửa câu để gửi cho ứng viên, hoặc
            # JSON cụt được đem đi phân tích. Đánh dấu và ghi nhật ký để người
            # gọi quyết định — xem `Completion.truncated`.
            truncated = choices[0].get("finish_reason") == "length"
            if truncated:
                log.warning(
                    "%s: câu trả lời bị cắt vì hết hạn mức token "
                    "(%s token nhìn thấy được). Với model có bước suy nghĩ, "
                    "hãy đặt reasoning_effort='none' hoặc nới max_tokens.",
                    self.name, usage.get("completion_tokens"))

            return Completion(
                text=text, provider=self.name, model=body["model"],
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
                completion_tokens=int(usage.get("completion_tokens") or 0),
                latency_ms=latency_ms, raw=raw_payload, truncated=truncated)

        if last_error is not None:
            raise last_error
        # Đến đây nghĩa là acquire() trả None, tức MỌI khoá đều đã bị tắt vì sai.
        raise LLMAuthError(
            f"{self.name}: cả {len(self.keys)} khoá đều không hợp lệ, cần nhập lại.")

    def stream(self, messages, model=None, temperature=0.2, max_tokens=None,
               response_format=None, timeout=None, reasoning_effort=None):
        """Stream một lượt chat. Yield dict:

            {"type": "reasoning", "text": <delta>}   # chỉ model có native thinking
            {"type": "answer",    "text": <delta>}
            {"type": "error",     "text": <msg>}     # lỗi giữa chừng, không nổ
            {"type": "done", "completion": Completion}  # luôn là chunk cuối

        Xoay khoá CHỈ khi mở kết nối lỗi (401/429) và **chưa** có nội dung nào.
        Có nội dung rồi thì lỗi là terminal — không đổi provider giữa chừng.
        """
        if not self.configured():
            raise LLMError(f"Nhà cung cấp '{self.name}' chưa được cấu hình đầy đủ.")

        wait = self.timeout if timeout is None else max(1.0, float(timeout))
        body = {"model": model or self.model, "messages": messages,
                "temperature": temperature, "stream": True,
                "stream_options": {"include_usage": True}}
        if max_tokens:
            body["max_tokens"] = max_tokens
        if response_format:
            body["response_format"] = response_format
        _apply_reasoning_effort(body, body["model"], reasoning_effort)

        last_error = None
        for _ in range(max(1, len(self.keys))):
            state = self.keys.acquire()
            if state is None:
                break
            headers = {"Authorization": f"Bearer {state.key}",
                       "Content-Type": "application/json",
                       "Accept": "text/event-stream"}
            headers.update(self.extra_headers)
            started = time.time()
            try:
                lines = self._stream_transport(
                    self.base_url + "/chat/completions", headers, body, wait)
            except LLMAuthError as exc:
                self.keys.report_invalid(state)
                last_error = exc
                log.warning("%s: khoá %s không hợp lệ (stream), đã tắt", self.name, state.label)
                continue
            except LLMUnavailable as exc:
                self.keys.report_rate_limited(state)
                last_error = exc
                log.info("%s: khoá %s hết hạn mức (stream), đổi khoá", self.name, state.label)
                continue
            yield from _parse_sse_stream(lines, provider=self.name,
                                        model=body["model"], started=started)
            return

        raise last_error or LLMAuthError(
            f"{self.name}: cả {len(self.keys)} khoá đều không hợp lệ (stream).")

    def _raise_for_status(self, status, payload):
        if 200 <= status < 300:
            return
        detail = ""
        if isinstance(payload, dict):
            error = payload.get("error")
            detail = (error.get("message") if isinstance(error, dict) else str(error or "")) or ""

        # Một số OpenAI-compatible gateway trả "Selected model is at capacity"
        # bằng 400/409 thay vì 429. Đây không phải lỗi cấu hình model: phải để
        # Router thử fallback model/provider, nếu không cả Radar đứng lại.
        unavailable_markers = ("at capacity", "model capacity", "capacity exceeded",
                               "temporarily unavailable", "overloaded", "try a different model")
        if any(marker in detail.casefold() for marker in unavailable_markers):
            raise LLMUnavailable(f"{self.name}: model đang quá tải. {detail}".strip())

        if status in (401, 403):
            raise LLMAuthError(f"{self.name}: khoá API không hợp lệ. {detail}".strip())
        if status == 429:
            raise LLMUnavailable(f"{self.name}: bị giới hạn tốc độ. {detail}".strip())
        if status >= 500:
            raise LLMUnavailable(f"{self.name}: sự cố máy chủ (HTTP {status}). {detail}".strip())
        # 400/404 gần như luôn là lỗi cấu hình: sai tên model, sai đường dẫn.
        # Thử lại chỉ tốn thời gian.
        raise LLMError(f"{self.name}: yêu cầu bị từ chối (HTTP {status}). {detail}".strip())


def _urllib_transport(url, headers, body, timeout):
    request = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Thân phản hồi lỗi mới là chỗ chứa thông báo hữu ích; đừng vứt đi.
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except Exception:
            return exc.code, {}


def _urllib_stream_transport(url, headers, body, timeout):
    """Mở kết nối SSE, yield từng dòng text. Lỗi HTTP -> raise trước khi yield."""
    request = urllib.request.Request(
        url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers, method="POST")
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = json.loads(exc.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception:                       # noqa: BLE001
            pass
        if exc.code in (401, 403):
            raise LLMAuthError(f"khoá API không hợp lệ. {detail}".strip()) from exc
        if exc.code == 429:
            raise LLMUnavailable(f"bị giới hạn tốc độ. {detail}".strip()) from exc
        if exc.code >= 500:
            raise LLMUnavailable(f"sự cố máy chủ (HTTP {exc.code}). {detail}".strip()) from exc
        raise LLMError(f"yêu cầu bị từ chối (HTTP {exc.code}). {detail}".strip()) from exc
    except Exception as exc:                    # noqa: BLE001
        raise LLMUnavailable(f"không mở được stream: {exc}") from exc

    def _iter():
        with response:
            for raw in response:
                yield raw.decode("utf-8", "replace").rstrip("\r\n")
    return _iter()


def _parse_sse_stream(lines, *, provider, model, started):
    """Bóc các frame `data: {...}` của OpenAI chat.completions stream.

    Yield `{"type": "reasoning"|"answer"|"error", "text": ...}`, và luôn kết thúc
    bằng `{"type": "done", "completion": Completion}`.
    """
    answer_parts, reasoning_parts = [], []
    prompt_tokens = completion_tokens = 0
    finish_reason = ""
    saw_done = False
    try:
        for line in lines:
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[len("data:"):].strip()
            if data == "[DONE]":
                saw_done = True
                break
            try:
                frame = json.loads(data)
            except ValueError:
                continue
            if isinstance(frame.get("error"), (dict, str)):
                err = frame["error"]
                msg = err.get("message") if isinstance(err, dict) else str(err)
                yield {"type": "error", "text": str(msg or "lỗi stream")}
                break
            usage = frame.get("usage") or {}
            if usage:
                prompt_tokens = int(usage.get("prompt_tokens") or prompt_tokens)
                completion_tokens = int(usage.get("completion_tokens") or completion_tokens)
            for choice in frame.get("choices") or []:
                delta = choice.get("delta") or {}
                reason = delta.get("reasoning_content") or delta.get("reasoning")
                if reason:
                    reasoning_parts.append(reason)
                    yield {"type": "reasoning", "text": reason}
                content = delta.get("content")
                if content:
                    answer_parts.append(content)
                    yield {"type": "answer", "text": content}
                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]
    except (LLMError, GeneratorExit):
        raise
    except Exception as exc:                    # noqa: BLE001
        yield {"type": "error", "text": f"stream gián đoạn: {exc}"}

    completion = Completion(
        text="".join(answer_parts), provider=provider, model=model,
        prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        latency_ms=int((time.time() - started) * 1000),
        raw={"reasoning": "".join(reasoning_parts), "finish_reason": finish_reason,
             "stream_complete": saw_done},
        truncated=(finish_reason == "length") or not saw_done)
    yield {"type": "done", "completion": completion}


# Mặc định của từng nhà cung cấp. base_url và model đều ghi đè được bằng biến
# môi trường — mã model đổi vài tháng một lần, không nên nằm trong code.
PROVIDER_DEFAULTS = {
    "greennode": {
        "base_url": "https://maas-llm-aiplatform-hcm.api.vngcloud.vn/v1",
        # Chưa biết mã model của GreenNode: lấy ở Workshop #1 ngày 28/08 bằng
        # cách gọi GET {base_url}/models. Đặt MSB_AI_GREENNODE_MODEL là chạy.
        "model": "",
        "env_key": "MSB_AI_GREENNODE_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-5.5",
        "env_key": "MSB_AI_OPENAI_API_KEY",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-3.5-flash",
        "env_key": "MSB_AI_GEMINI_API_KEY",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        # deepseek-chat / deepseek-reasoner đã khai tử 24/07/2026.
        "model": "deepseek-v4-flash",
        "env_key": "MSB_AI_DEEPSEEK_API_KEY",
    },
}


class AgentBaseProvider:
    """Uỷ quyền lượt chat cho Prospect Agent trên GreenNode AgentBase.

    Không phải OpenAI-compatible: gọi `POST {endpoint}/invocations` với
    `{"action": "chat", "messages": [...]}`. Lợi ích: agent nằm TRONG datacenter
    GreenNode, cạnh endpoint MaaS — Hub gọi ra internet thì chậm/treo. Không có
    khoá phía Hub (agent tự giữ khoá). Không stream (router bỏ qua khi cần stream).
    """

    def __init__(self, name="agentbase", base_url="", model="", timeout=DEFAULT_TIMEOUT,
                 transport=None):
        self.name = name
        self.base_url = str(base_url or "").rstrip("/")
        self.model = model or "z-ai/glm-5.2-hackathon"
        self.timeout = int(timeout or DEFAULT_TIMEOUT)
        self.api_key = ""          # để tương thích các chỗ đọc .api_key
        self._transport = transport or _urllib_transport

    def configured(self):
        return bool(self.base_url)

    def complete(self, messages, model=None, temperature=0.2, max_tokens=None,
                 response_format=None, tools=None, timeout=None, reasoning_effort=None):
        if not self.configured():
            raise LLMError("agentbase: chưa đặt MSB_AGENT_ENDPOINT.")
        wait = self.timeout if timeout is None else max(1.0, float(timeout))
        body = {"action": "chat", "messages": list(messages),
                "temperature": temperature}
        if max_tokens:
            body["max_tokens"] = int(max_tokens)
        if response_format:
            body["response_format"] = response_format
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort

        started = time.time()
        try:
            status, payload = self._transport(
                self.base_url + "/invocations",
                {"Content-Type": "application/json"}, body, wait)
        except LLMError:
            raise
        except Exception as exc:                     # noqa: BLE001
            raise LLMUnavailable(f"agentbase: không gọi được: {exc}") from exc

        if status == 429:
            raise LLMUnavailable("agentbase: bị giới hạn tốc độ.")
        if status >= 500:
            raise LLMUnavailable(f"agentbase: sự cố máy chủ (HTTP {status}).")
        if status >= 400:
            raise LLMError(f"agentbase: yêu cầu bị từ chối (HTTP {status}).")

        if not isinstance(payload, dict) or payload.get("error"):
            raise LLMUnavailable(
                f"agentbase: {(payload or {}).get('error') or 'khuôn trả về lạ'}")
        text = payload.get("text") or ""
        if not str(text).strip():
            raise LLMUnavailable("agentbase: trả về nội dung rỗng.")
        usage = payload.get("usage") or {}
        return Completion(
            text=text, provider=self.name, model=payload.get("model") or self.model,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=int((time.time() - started) * 1000),
            raw=payload, truncated=bool(payload.get("truncated")))


def build_provider(name, transport=None, env=None):
    """Dựng một nhà cung cấp từ biến môi trường. Trả None nếu chưa có khoá."""
    env = env if env is not None else os.environ
    key = str(name or "").strip().lower()

    if key == "agentbase":
        endpoint = (env.get("MSB_AI_AGENTBASE_BASE_URL")
                    or env.get("MSB_AGENT_ENDPOINT", "")).strip()
        if not endpoint:
            return None
        return AgentBaseProvider(
            base_url=endpoint,
            model=env.get("MSB_AI_AGENTBASE_MODEL") or env.get("LLM_MODEL", ""),
            timeout=int(env.get("MSB_AI_AGENTBASE_TIMEOUT")
                        or env.get("MSB_AGENT_TIMEOUT") or DEFAULT_TIMEOUT),
            transport=transport)

    defaults = PROVIDER_DEFAULTS.get(key)
    if not defaults:
        raise LLMError(f"Nhà cung cấp không hỗ trợ: {name!r}")

    api_key = env.get(defaults["env_key"], "")
    if not api_key:
        return None

    upper = key.upper()
    return OpenAICompatibleProvider(
        name=key,
        base_url=env.get(f"MSB_AI_{upper}_BASE_URL") or defaults["base_url"],
        api_key=api_key,
        model=env.get(f"MSB_AI_{upper}_MODEL") or defaults["model"],
        timeout=int(env.get(f"MSB_AI_{upper}_TIMEOUT") or DEFAULT_TIMEOUT),
        transport=transport)


def list_models(provider):
    """Liệt kê mã model nhà cung cấp đang phục vụ.

    Chính là cách lấy mã model của GreenNode sau workshop, thay vì đoán.
    """
    if not provider.base_url or not provider.api_key:
        raise LLMError("Chưa cấu hình đủ để liệt kê model.")
    request = urllib.request.Request(
        provider.base_url + "/models",
        headers={"Authorization": f"Bearer {provider.api_key}"})
    try:
        with urllib.request.urlopen(request, timeout=provider.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LLMError(f"Không liệt kê được model (HTTP {exc.code}).") from exc
    except Exception as exc:
        raise LLMUnavailable(f"Không kết nối được: {exc}") from exc
    return [row.get("id") for row in (payload.get("data") or []) if row.get("id")]
