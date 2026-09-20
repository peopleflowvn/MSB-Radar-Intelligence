# -*- coding: utf-8 -*-
"""`POST /api/v1/talent/ask/` — điểm vào HTTP của Answer Engine.

Tách khỏi `talent/views.py` có chủ ý: view cũ `ai_talent_search` mang theo cả
tiêu chí, cache phân tích, thẻ ứng viên và cờ quick/deep. Đường mới không có gì
trong số đó, và trộn vào file cũ sẽ khiến việc gỡ bỏ tầng cũ (§3) khó hơn.

SSE mặc định vì ①→④ mất vài giây — màn hình phải nói được hệ thống đang làm gì.
Client không nhận stream được thì gửi `"stream": false` để lấy JSON một lần.

`gen()` bên dưới là generator đồng bộ — đưa thẳng vào `StreamingHttpResponse`
sẽ KHÔNG stream thật qua ASGI (Django gom hết generator vào một list rồi mới
gửi một cục, xem `core/asgi_stream.py`). `_stream_response` bọc qua
`to_async_iter` để mỗi `yield` phía trên tới client ngay khi vừa sẵn sàng.
"""
import json
import logging

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST

from core.asgi_stream import to_async_iter

from ai import conversation_state, events
from ai import projection as projection_mod
from ai.conversation import sanitize_history

from . import corpus_qa
from .answer import engine

log = logging.getLogger(__name__)


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_response(iterator):
    response = StreamingHttpResponse(to_async_iter(iterator), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"      # proxy không được gom buffer
    return response


def _persist(user, conversation_id, client_turn_id, parent_turn_id, question,
             result, *, aborted=False, attachments=None):
    """Ghi lượt vào hội thoại — câu hỏi tiếp mới có ngữ cảnh để bám vào."""
    if aborted and not (result.text or "").strip() and not result.people:
        # Client rớt kết nối (đóng tab/tải lại trang) TRƯỚC KHI có gì để nói —
        # không lưu một lượt hội thoại rỗng. Đo trên production 19–21/09: 4 lượt
        # đúng kiểu này, luôn `duration_ms=0`, và nếu ai mở lại đúng luồng đó sẽ
        # thấy một bong bóng chat "(không có nội dung)" — rất dễ bị hiểu nhầm là
        # Radar bị lỗi khi đang demo. Người dùng gõ lại câu hỏi sẽ tạo
        # `client_turn_id` mới và có lượt riêng, không phụ thuộc vào bản ghi này.
        log.info("ask: lượt bị huỷ giữa chừng, không có nội dung — bỏ, không ghi hội thoại")
        return
    duration_ms = max(0, int((result.trace or {}).get("ms_total") or 0))
    metadata = {"answer_engine": True, "trace": result.trace,
                "duration_ms": duration_ms}
    if result.reasoning:
        metadata["reasoning_trace"] = result.reasoning[:6000]
    if result.sources:
        metadata["cv_citations"] = result.sources
    if aborted:
        metadata["aborted"] = True
    # Kế hoạch của lượt TÌM được lưu làm `criteria` — câu tinh chỉnh ở lượt sau
    # ("nới lỏng số năm…") cần biết lượt trước đã tìm gì mới tìm lại đúng
    # (`plan.previous_search_criteria`). Lượt hội thoại không lưu gì.
    plan = (result.trace or {}).get("plan") or {}
    if isinstance(plan, dict) and plan.get("shape") in ("find_people", "followup", "compare", "count"):
        metadata["criteria"] = {key: plan.get(key) for key in (
            "information_need", "must_have", "should_have", "search_queries", "limit")}
    # Khoá phải là "items" với shape {id, name, why} — đó là thứ
    # `ai/projection.py::last_result_lines()` và mọi chỗ đọc `last_result` mong
    # đợi. Trước đây ghi "people"/"id" nên `last_result_lines()` LUÔN trả rỗng:
    # ① không bao giờ biết "2 ứng viên này" trỏ tới ai và phải tìm lại từ đầu,
    # lần này lọt cả hai, lần sau rớt một (ảnh test 04/09, "vừa tìm được bên
    # trên mà").
    snapshot = {
        "kind": "answer",
        "count": len(result.people),
        "items": [{"id": p["person_id"], "name": p["name"],
                   "why": (p.get("why") or "")[:160]}
                  for p in result.people],
    }
    try:
        thread = conversation_state.record(
            user, "talent", conversation_id, question,
            result.text or "(không có nội dung)", mode="conversation",
            provider=result.provider, model=result.model, metadata=metadata,
            client_turn_id=client_turn_id, last_result=snapshot,
            user_metadata={"attachments": list(attachments or [])})
        events.log_conversation_turn(thread, client_turn_id, "talent", question,
                                     result.text, parent_turn_id=parent_turn_id)
    except Exception:                               # noqa: BLE001
        # Ghi nhật ký hỏng không được nuốt mất câu trả lời của người dùng.
        log.exception("ask: không ghi được lượt hội thoại")


def _payload(result, conversation_id, client_turn_id):
    return {
        "conversation_id": conversation_state.normalize_thread_id(conversation_id),
        "client_turn_id": client_turn_id,
        "answer": result.text,
        "reasoning": "",  # compatibility key; only workflow trace is public
        "citations": result.sources,
        "web_sources": result.web_sources,
        "people": result.people,
        "provider": result.provider,
        "model": result.model,
        "trace": result.trace,
        "duration_ms": max(0, int((result.trace or {}).get("ms_total") or 0)),
        "grounded": bool(result.sources),
    }


def _read_request(request):
    """Trả `(body, attachment_text, attachment_meta, error)`.

    Nhận cả JSON lẫn multipart: người dùng vẫn phải kéo được JD vào ô hỏi. Văn
    bản bóc từ tệp đính kèm được ghép vào câu hỏi để ① lập kế hoạch trên đó —
    không có đường riêng nào cho JD nữa.
    """
    if request.content_type and request.content_type.startswith("multipart/"):
        from .attachment_text import AttachmentError, extract_uploads
        body = {key: request.POST.get(key) for key in request.POST}
        if body.get("history"):
            try:
                body["history"] = json.loads(body["history"])
            except ValueError:
                body["history"] = []
        try:
            context, attachment_meta = extract_uploads(request.FILES.getlist("files"))
        except (AttachmentError, OSError, ValueError) as exc:
            return body, "", [], str(exc) or "Không đọc được tài liệu đính kèm."
        return body, context, attachment_meta, ""
    try:
        return json.loads(request.body.decode("utf-8") or "{}"), "", [], ""
    except ValueError:
        return {}, "", [], "Body không phải JSON."


@require_POST
def talent_ask(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Cần đăng nhập."}, status=401)
    body, attachment_text, attachment_meta, error = _read_request(request)
    if error:
        return JsonResponse({"detail": error}, status=400)

    question = str(body.get("q") or body.get("question") or "").strip()
    if not question:
        return JsonResponse({"detail": "Chưa nhập câu hỏi."}, status=400)
    if attachment_text:
        question = f"{question}\n\nTÀI LIỆU ĐÍNH KÈM:\n{attachment_text}"
    # RM thuần không được đọc nội dung CV — câu trả lời ở đây LUÔN trích CV nên
    # chặn ngay tại cửa, không để rò qua trích dẫn.
    if not corpus_qa.can_read_cv(request.user):
        return JsonResponse(
            {"detail": "Tài khoản của bạn không có quyền đọc nội dung CV."},
            status=403)

    conversation_id = str(body.get("conversation_id") or "")
    client_turn_id = str(body.get("client_turn_id") or "") or events.new_turn_id()
    parent_turn_id = str(body.get("parent_client_turn_id") or "")
    client_history = sanitize_history(body.get("history"))
    envelope = projection_mod.build_envelope(
        request.user, "talent", conversation_id, question,
        turn_id=client_turn_id, client_history=client_history)
    history = list(getattr(envelope.projection, "recent_turns", []) or [])

    if body.get("stream") is False:
        result = engine.answer(question, envelope=envelope, user=request.user,
                               history=history)
        _persist(request.user, conversation_id, client_turn_id, parent_turn_id,
                 question, result, attachments=attachment_meta)
        return JsonResponse(_payload(result, conversation_id, client_turn_id))

    from .answer import runner

    def _persist_full(result, aborted=False):
        _persist(request.user, conversation_id, client_turn_id, parent_turn_id,
                 question, result, aborted=aborted, attachments=attachment_meta)

    def gen():
        last_result = engine.AnswerResult()
        try:
            for chunk in runner.stream(
                    question, envelope=envelope, user=request.user,
                    history=history, client_turn_id=client_turn_id,
                    persist=_persist_full):
                kind = chunk.get("type")
                if kind == "preamble":
                    # "Đã nhận yêu cầu — đây là cách mình định làm", ngay sau ①.
                    yield _sse("preamble", {"text": chunk.get("text") or ""})
                elif kind == "step":
                    yield _sse("step", {"label": chunk.get("label") or "",
                                        "state": chunk.get("state") or "active"})
                elif kind == "stage":
                    yield _sse("step", {"label": chunk.get("text") or "",
                                        "state": "active"})
                elif kind == "reasoning":
                    pass                            # không đẩy suy nghĩ ra client
                elif kind == "answer":
                    yield _sse("answer", {"text": chunk.get("text") or ""})
                elif kind == "revision":
                    yield _sse("revision", {"text": chunk.get("text") or "",
                                            "ok": chunk.get("ok", True)})
                elif kind == "error":
                    yield _sse("error", {"text": chunk.get("text") or "Lượt trả lời bị lỗi."})
                    return
                elif kind == "done":
                    last_result = chunk["result"]
        except GeneratorExit:
            # Client rớt. `runner` giữ luồng sinh chạy tiếp và tự persist bản
            # đầy đủ — KHÔNG persist bản dang dở ở đây (sẽ đè lên bản đầy đủ).
            raise
        except Exception as exc:                    # noqa: BLE001
            log.exception("ask: lượt trả lời hỏng")
            yield _sse("error", {"text": str(exc)})
            return

        if last_result.sources:
            yield _sse("citations", {"items": last_result.sources})
        yield _sse("done", _payload(last_result, conversation_id, client_turn_id))

    return _stream_response(gen())


def talent_ask_turn(request, client_turn_id):
    """`GET` lấy lại kết quả một lượt theo `client_turn_id`.

    Mobile rớt kết nối giữa lúc chờ → client gọi endpoint này khi quay lại tab.
    200 kèm câu trả lời đã lưu nếu xong; 202 nếu `runner` còn đang chạy; 404
    nếu không có gì.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Cần đăng nhập."}, status=401)
    client_turn_id = str(client_turn_id or "")[:64]
    if not client_turn_id:
        return JsonResponse({"detail": "Thiếu client_turn_id."}, status=400)

    from ai.models import AssistantMessage
    from .answer import runner

    user_msg = (AssistantMessage.objects
                .filter(thread__user=request.user, thread__surface="talent",
                        role="user", client_turn_id=client_turn_id)
                .select_related("thread").order_by("-created_at").first())
    if user_msg is not None:
        answer_msg = (AssistantMessage.objects
                      .filter(thread=user_msg.thread, role="assistant",
                              metadata__client_turn_id=client_turn_id)
                      .order_by("created_at").first())
        if answer_msg is None:
            # Legacy answers had no explicit turn ID. Only accept the immediate
            # next message; never jump across another user's turn.
            from django.db.models import Q
            next_msg = (AssistantMessage.objects.filter(thread=user_msg.thread)
                        .filter(Q(created_at__gt=user_msg.created_at)
                                | Q(created_at=user_msg.created_at, pk__gt=user_msg.pk))
                        .order_by("created_at", "pk").first())
            if (next_msg and next_msg.role == "assistant"
                    and not (next_msg.metadata or {}).get("client_turn_id")):
                answer_msg = next_msg
        meta = (answer_msg.metadata or {}) if answer_msg else {}
        if answer_msg and not meta.get("aborted"):
            snap = meta.get("result_snapshot") or {}
            return JsonResponse({
                "state": "done",
                "conversation_id": user_msg.thread.thread_id,
                "client_turn_id": client_turn_id,
                "answer": answer_msg.content,
                "citations": meta.get("cv_citations") or [],
                "people": [{"person_id": it.get("id"), "name": it.get("name")}
                           for it in (snap.get("items") or snap.get("people") or [])],
                "provider": answer_msg.provider,
                "model": answer_msg.model,
                "trace": meta.get("trace") or {},
                "duration_ms": max(0, int(meta.get("duration_ms") or
                                           (meta.get("trace") or {}).get("ms_total") or 0)),
            })

    state = runner.status_of(request.user, client_turn_id)
    if state == "running":
        return JsonResponse({"state": "running"}, status=202)
    if state == "timeout":
        return JsonResponse({"state": "timeout",
                             "detail": "Lượt trả lời vượt quá thời gian cho phép."}, status=504)
    if state == "error":
        return JsonResponse({"state": "error",
                             "detail": "Lượt trả lời không hoàn tất."}, status=500)
    return JsonResponse({"state": "unknown"}, status=404)
