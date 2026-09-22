# -*- coding: utf-8 -*-
"""`POST /api/v1/rb/ask/` — điểm vào HTTP của Growth Answer Engine.

Cùng khuôn với `talent/answer_views.py` có chủ ý: cùng sự kiện SSE (`preamble`,
`step`, `answer`, `revision`, `citations`, `done`, `error`), cùng cơ chế chạy nền
sống sót khi client rớt, cùng endpoint lấy lại lượt. Giao diện Growth dựng được
trên đúng bộ xử lý luồng mà `AiSearch.tsx` đã có.

**Ràng buộc "tiêu chí luôn hiện ra" vẫn giữ.** RM phải thấy hệ thống hiểu câu hỏi
thế nào trước khi tin danh sách. Engine mới không có 8 khoá, nên sự kiện
`preamble` mang kế hoạch của ① (phạm vi, điều kiện bắt buộc, sản phẩm, bộ lọc) —
phát ngay sau ①, TRƯỚC khi tìm và đọc — và giao diện hiện nó ở đúng thẻ mà bộ
tiêu chí cũ từng chiếm (`ProspectSearch.tsx::PlanChips`).

**`POST /api/v1/rb/prospects/` KHÔNG bị gỡ.** Giao diện dùng nó làm đường dự phòng
khi endpoint này hỏng trước khi kịp trả chữ nào — thà một danh sách lọc thô còn
hơn một ô chat trống.
"""
import json
import logging

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST

from accounts import roles
from ai import conversation_state, events
from ai import projection as projection_mod
from ai.conversation import sanitize_history
from core.asgi_stream import to_async_iter

from .answer import engine

log = logging.getLogger(__name__)

SURFACE = "prospect"


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_response(iterator):
    response = StreamingHttpResponse(to_async_iter(iterator), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"      # proxy không được gom buffer
    return response


def _persist(user, conversation_id, client_turn_id, parent_turn_id, question,
             result, *, aborted=False):
    """Ghi lượt vào hội thoại — câu hỏi tiếp ("so sánh 2 người đầu") mới có chỗ bám."""
    if aborted and not (result.text or "").strip() and not result.people:
        # Xem lý do đầy đủ ở `talent/answer_views.py::_persist` — cùng một lỗi
        # đo được ở Talent, áp cùng cách chữa cho Growth.
        log.info("rb.ask: lượt bị huỷ giữa chừng, không có nội dung — bỏ, không ghi hội thoại")
        return
    duration_ms = max(0, int((result.trace or {}).get("ms_total") or 0))
    metadata = {"answer_engine": True, "trace": result.trace,
                "duration_ms": duration_ms,
                "steps": (result.trace or {}).get("steps") or []}
    if result.reasoning:
        metadata["reasoning_trace"] = result.reasoning[:6000]
    if result.sources:
        metadata["prospect_citations"] = result.sources
    if aborted:
        metadata["aborted"] = True
    plan = (result.trace or {}).get("plan") or {}
    if isinstance(plan, dict) and plan.get("shape") in (
            "find_prospects", "portfolio", "whitespace", "followup", "compare", "count"):
        metadata["criteria"] = {key: plan.get(key) for key in (
            "information_need", "must_have", "should_have", "search_queries", "limit", "products", "filters")}
    # Khoá "items" với shape {id, name, why} — đúng thứ
    # `ai/projection.py::last_result_people()` đọc. Ghi sai khoá thì câu hỏi tiếp
    # không biết "hai khách đầu" là ai, và phải tìm lại từ đầu (lỗi đã gặp bên
    # Talent ngày 04/09).
    snapshot = {
        "kind": "answer",
        "count": len(result.people),
        # `product` đi kèm để câu lệnh sau ("soạn tin cho khách thứ 2") soạn đúng
        # sản phẩm ④ đã chọn, không phải đoán lại.
        "items": [{"id": p["person_id"], "name": p["name"],
                   "product": p.get("product") or "",
                   "why": (p.get("why") or "")[:160]}
                  for p in result.people],
    }
    if (result.trace or {}).get("keeps_last_result"):
        # None = giữ nguyên danh sách lượt trước (`ai/thread_state.apply_turn`).
        snapshot = None
    try:
        thread = conversation_state.record(
            user, SURFACE, conversation_id, question,
            result.text or "(không có nội dung)", mode="conversation",
            provider=result.provider, model=result.model, metadata=metadata,
            client_turn_id=client_turn_id, last_result=snapshot)
        events.log_conversation_turn(thread, client_turn_id, SURFACE, question,
                                     result.text, parent_turn_id=parent_turn_id)
    except Exception:                               # noqa: BLE001
        # Ghi nhật ký hỏng không được nuốt mất câu trả lời của RM.
        log.exception("rb.ask: không ghi được lượt hội thoại")


def _payload(result, conversation_id, client_turn_id):
    return {
        "conversation_id": conversation_state.normalize_thread_id(conversation_id),
        "client_turn_id": client_turn_id,
        "answer": result.text,
        "citations": result.sources,
        "web_sources": result.web_sources,
        "people": result.people,
        "provider": result.provider,
        "model": result.model,
        "trace": result.trace,
        "steps": (result.trace or {}).get("steps") or [],
        "duration_ms": max(0, int((result.trace or {}).get("ms_total") or 0)),
        "grounded": bool(result.sources),
    }


def _forbidden(user):
    """Cùng cổng module với mọi API `/rb/` khác (`accounts.permissions.RequiresRB`)."""
    return not roles.can_access(user, roles.MODULE_RB)


@require_POST
def prospect_ask(request):
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Cần đăng nhập."}, status=401)
    if _forbidden(request.user):
        return JsonResponse({"detail": "Tài khoản của bạn không có quyền dùng Growth Radar."},
                            status=403)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return JsonResponse({"detail": "Body không phải JSON."}, status=400)

    question = str(body.get("q") or body.get("question") or "").strip()
    if not question:
        return JsonResponse({"detail": "Chưa nhập câu hỏi."}, status=400)
    if len(question) > 2000:
        return JsonResponse({"detail": "Câu hỏi quá dài."}, status=400)

    conversation_id = str(body.get("conversation_id") or "")
    client_turn_id = str(body.get("client_turn_id") or "") or events.new_turn_id()
    parent_turn_id = str(body.get("parent_client_turn_id") or "")
    client_history = sanitize_history(body.get("history"))
    envelope = projection_mod.build_envelope(
        request.user, SURFACE, conversation_id, question,
        turn_id=client_turn_id, client_history=client_history)
    history = list(getattr(envelope.projection, "recent_turns", []) or [])

    if body.get("stream") is False:
        result = engine.answer(question, envelope=envelope, user=request.user,
                               history=history)
        _persist(request.user, conversation_id, client_turn_id, parent_turn_id,
                 question, result)
        return JsonResponse(_payload(result, conversation_id, client_turn_id))

    from .answer import runner

    def _persist_full(result, aborted=False):
        _persist(request.user, conversation_id, client_turn_id, parent_turn_id,
                 question, result, aborted=aborted)

    def gen():
        last_result = engine.AnswerResult()
        try:
            for chunk in runner.stream(
                    question, envelope=envelope, user=request.user,
                    history=history, client_turn_id=client_turn_id,
                    persist=_persist_full):
                kind = chunk.get("type")
                if kind == "preamble":
                    yield _sse("preamble", {"text": chunk.get("text") or "",
                                            "plan": chunk.get("plan") or {}})
                elif kind == "step":
                    yield _sse("step", {"label": chunk.get("label") or "",
                                        "state": chunk.get("state") or "active"})
                elif kind == "stage":
                    yield _sse("step", {"label": chunk.get("text") or "",
                                        "state": "active"})
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
            # Client rớt. `runner` giữ luồng sinh chạy tiếp và tự persist bản đầy
            # đủ — KHÔNG persist bản dang dở ở đây (sẽ đè lên bản đầy đủ).
            raise
        except Exception:                           # noqa: BLE001
            log.exception("rb.ask: lượt trả lời hỏng")
            # Không đẩy `str(exc)` ra client: thông điệp ngoại lệ có thể chứa tên
            # bảng, đường dẫn, hay nội dung truy vấn.
            yield _sse("error", {"text": "Lượt trả lời bị lỗi. Bạn có thể thử lại."})
            return

        if last_result.sources:
            yield _sse("citations", {"items": last_result.sources})
        yield _sse("done", _payload(last_result, conversation_id, client_turn_id))

    return _stream_response(gen())


def prospect_ask_turn(request, client_turn_id):
    """`GET` lấy lại kết quả một lượt — khi mobile rớt kết nối giữa lúc chờ.

    200 kèm câu trả lời đã lưu nếu xong; 202 nếu còn đang chạy; 404 nếu không có.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Cần đăng nhập."}, status=401)
    if _forbidden(request.user):
        return JsonResponse({"detail": "Không có quyền."}, status=403)
    client_turn_id = str(client_turn_id or "")[:64]
    if not client_turn_id:
        return JsonResponse({"detail": "Thiếu client_turn_id."}, status=400)

    from ai.models import AssistantMessage
    from .answer import runner

    user_msg = (AssistantMessage.objects
                .filter(thread__user=request.user, thread__surface=SURFACE,
                        role="user", client_turn_id=client_turn_id)
                .select_related("thread").order_by("-created_at").first())
    if user_msg is not None:
        answer_msg = (AssistantMessage.objects
                      .filter(thread=user_msg.thread, role="assistant",
                              metadata__client_turn_id=client_turn_id)
                      .order_by("created_at").first())
        meta = (answer_msg.metadata or {}) if answer_msg else {}
        if answer_msg and not meta.get("aborted"):
            snap = meta.get("result_snapshot") or {}
            return JsonResponse({
                "state": "done",
                "conversation_id": user_msg.thread.thread_id,
                "client_turn_id": client_turn_id,
                "answer": answer_msg.content,
                "citations": meta.get("prospect_citations") or [],
                "people": [{"person_id": it.get("id"), "name": it.get("name")}
                           for it in (snap.get("items") or [])],
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
