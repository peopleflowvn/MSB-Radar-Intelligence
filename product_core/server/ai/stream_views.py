# -*- coding: utf-8 -*-
"""SSE endpoint cho luồng Thinking (Master Plan §10.4, §16.5.1).

Sync generator + `StreamingHttpResponse`. Dưới ASGI/UvicornWorker, view đồng bộ
chạy trong threadpool nên một stream dài không chặn event loop (khác WSGI sync
worker). Reverse proxy phải tắt buffering — ta cũng gửi `X-Accel-Buffering: no`.

Chỉ phục vụ câu hỏi **hội thoại**. Câu hỏi tìm người trả về `event: route` để
client gọi endpoint search thường (chưa stream rerank ở batch này).
"""
import json
import logging
from types import SimpleNamespace

from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_POST

from django.conf import settings

from . import (agent_select, conversation_state, events,
               intent as intent_router, projection as projection_mod, toolset,
               websearch)
from . import telemetry
from .adapter import ModelError, get_adapter
from .conversation import (ConversationReply, web_system, build_conversation_request,
                           common_answer, knowledge_sources, sanitize_history)

log = logging.getLogger(__name__)


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _stream_response(iterator):
    resp = StreamingHttpResponse(iterator, content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    resp["X-Accel-Buffering"] = "no"
    return resp


@require_POST
def assistant_stream(request):
    # Import trong hàm: `talent.corpus_qa` phụ thuộc ngược lại `ai.*`, để ở đầu
    # module sẽ tạo vòng import khi Django nạp app.
    from talent import corpus_qa

    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Cần đăng nhập."}, status=401)
    try:
        body = json.loads(request.body.decode("utf-8") or "{}")
    except ValueError:
        return JsonResponse({"detail": "Body không phải JSON."}, status=400)

    question = str(body.get("q") or body.get("question") or "").strip()
    if not question:
        return JsonResponse({"detail": "Chưa nhập câu hỏi."}, status=400)
    surface = body.get("surface") if body.get("surface") in ("talent", "prospect") else "talent"
    conversation_id = str(body.get("conversation_id") or "")
    client_turn_id = str(body.get("client_turn_id") or "") or events.new_turn_id()
    parent_turn_id = str(body.get("parent_client_turn_id") or "")
    client_history = sanitize_history(body.get("history"))

    context = projection_mod.build_context(
        request.user, surface, conversation_id, client_history)

    fixed = common_answer(question, surface=surface, user=request.user)
    with telemetry.capture() as preflight:
        intent = intent_router.classify(
            question, surface=surface, user=request.user, history=context.recent_turns)
    preflight_calls = list(preflight["calls"])
    # `route` bảo client "câu này là tìm người, gọi endpoint search đi". Với
    # Talent thì không còn endpoint nào để gọi: `/talent/ai-search/` đã gỡ và
    # Answer Engine trả lời được cả câu tìm người — cứ đi tiếp xuống nhánh kho
    # CV bên dưới. Prospect vẫn giữ đường cũ của nó.
    if not fixed and intent.is_search and surface != "talent":
        return _stream_response(iter((_sse("route", {"mode": "search"}),)))

    user = request.user
    adapter = get_adapter()
    # Câu hỏi có tài liệu tri thức nội bộ khớp thì KHÔNG đi thẳng vào nhánh web
    # thuần (`do_web`) — cùng nguyên tắc với talent/answer/chat.py::stream_chat:
    # bộ phân loại ý định không biết gì về kho tri thức nội bộ nên có thể gắn
    # nhãn "web" cho một câu hỏi chính sách công ty một cách hợp lý theo góc
    # nhìn của nó. Nhánh hội thoại bên dưới (`else`) vẫn tra Internet song song
    # khi có `do_web_merge` — xem đó, tài liệu nội bộ không được thắng tuyệt
    # đối một mình vì nó có thể đã lỗi thời.
    internal_sources = knowledge_sources(question, user)
    do_web = not fixed and intent.is_web and websearch.enabled() and not internal_sources

    # Hỏi đáp có dẫn chứng trên kho CV → Answer Engine.
    #
    # Cổng là chặng ① của chính engine, KHÔNG phải `looks_like_corpus_question`
    # một mình: heuristic đó nhận mọi câu kết thúc bằng "?", nên "Radar là gì?"
    # cũng lọt và bị trả lời bằng giọng tìm người ("chưa tìm được hồ sơ nào
    # thoả…"). ① phân loại `shape="general"` cho những câu như vậy. Kế hoạch lập
    # ra ở đây được truyền thẳng vào engine để không lập hai lần.
    corpus_plan = None
    from talent.answer.resolve import referenced_people
    explicit_followup = (bool(context.last_result_people())
                         and referenced_people(context, question) is not None)
    if (not fixed and not do_web and surface == "talent"
            and (intent.is_search or explicit_followup
                 or corpus_qa.looks_like_corpus_question(question))
            and corpus_qa.can_read_cv(user)):
        from talent.answer import plan as answer_plan
        try:
            with telemetry.capture() as planning:
                candidate_plan = answer_plan.plan(question, envelope=SimpleNamespace(projection=context))
            preflight_calls.extend(planning["calls"])
            # `fallback=True` nghĩa là ① KHÔNG hiểu được câu hỏi (model lỗi, hết
            # hạn mức) và đang đoán "chắc là tìm người". Ở cổng này phải dè dặt:
            # đoán sai thì "Radar là gì?" bị trả lời bằng giọng tìm người. Đường
            # `/talent/ask/` thì ngược lại — ở đó người dùng đã chủ động hỏi về
            # kho người, nên dự phòng vẫn đúng.
            if candidate_plan.needs_people and not candidate_plan.fallback:
                corpus_plan = candidate_plan
        except Exception:                          # noqa: BLE001 - không hỏng lượt
            corpus_plan = None
    do_corpus = corpus_plan is not None

    do_agent = (not fixed and not do_web and not do_corpus
                and getattr(settings, "ASSISTANT_TOOLS", False)
                and bool(toolset.agent_toolset_for(surface, user)))

    # Có tài liệu nội bộ NHƯNG câu hỏi vẫn được gắn nhãn "web" (dữ kiện có thể
    # đổi theo thời gian: nhân sự lãnh đạo, lãi suất…) → nhánh hội thoại bên
    # dưới tra Internet song song và ghép làm nguồn, thay vì bỏ qua Internet.
    do_web_merge = (not fixed and not do_web and not do_corpus and not do_agent
                    and intent.is_web and websearch.enabled() and bool(internal_sources))

    def gen(active_usage):
        answer_parts, reasoning_parts = [], []
        provider = model_name = ""
        guard_flags = []
        citations = []
        cv_citations = []
        web_queries = []
        tool_trace = []
        request_obj = None
        last_result = None
        workflow = SimpleNamespace(trace={})
        failed = False
        completed = bool(fixed)
        try:
            yield _sse("status", {"state": "searching" if (do_web or do_web_merge) else "thinking"})
            if fixed:
                answer_parts.append(fixed)
                yield _sse("answer", {"text": fixed})
            elif do_agent:
                agent_ctx = {"thread_id": conversation_id, "question": question}
                for chunk in agent_select.get_runner().iter_turn(
                        question, surface=surface, user=user, projection=context,
                        adapter=adapter, context=agent_ctx):
                    kind = chunk.get("type")
                    if kind == "tool":
                        tool_trace.append(chunk["tool"])
                        yield _sse("tool", chunk["tool"])
                    elif kind == "answer":
                        answer_parts.append(chunk.get("text") or "")
                        yield _sse("answer", {"text": chunk.get("text") or ""})
                    elif kind == "error":
                        failed = True
                        yield _sse("error", {"text": chunk.get("text") or "lỗi tool"})
                        break
                    elif kind == "done":
                        res = chunk.get("result")
                        if res is not None:
                            completed = True
                            provider, model_name = res.provider, res.model
                            request_obj = res.last_request
                            if res.reasoning and not reasoning_parts:
                                reasoning_parts.append(res.reasoning)
                            if not answer_parts and res.text:
                                answer_parts.append(res.text)
            elif do_corpus:
                # Cùng một Answer Engine với `/talent/ask/`. Trước đây bề mặt này
                # có đường trả lời riêng (`corpus_qa`), nên cùng một câu hỏi cho
                # hai chất lượng khác nhau tuỳ người dùng gõ ở đâu.
                from talent.answer import engine as answer_engine
                for chunk in answer_engine.stream_answer(
                        question, user=user, history=context.recent_turns,
                        envelope=SimpleNamespace(projection=context),
                        query_plan=corpus_plan):
                    kind = chunk.get("type")
                    if kind == "preamble":
                        yield _sse("answer", {"text": (chunk.get("text") or "") + "\n\n"})
                        answer_parts.append((chunk.get("text") or "") + "\n\n")
                    elif kind in ("step", "stage"):
                        yield _sse("status", {"state": chunk.get("label")
                                              or chunk.get("text") or ""})
                    elif kind == "reasoning":
                        reasoning_parts.append(chunk.get("text") or "")
                    elif kind == "answer":
                        answer_parts.append(chunk.get("text") or "")
                        yield _sse("answer", {"text": chunk.get("text") or ""})
                    elif kind == "revision":
                        answer_parts[:] = [chunk.get("text") or ""]
                        yield _sse("revision", {"text": chunk.get("text") or ""})
                    elif kind == "error":
                        failed = True
                        yield _sse("error", {"text": "Lượt trả lời không hoàn tất. Bạn có thể thử lại."})
                        break
                    elif kind == "done":
                        completed = True
                        result = chunk["result"]
                        provider, model_name = result.provider, result.model
                        answer_parts[:] = [result.text]
                        workflow.trace.update(result.trace)
                        last_result = {"items": [{"id": p["person_id"], "name": p["name"]}
                                                 for p in result.people]}
                        cv_citations = result.sources
                        citations = [
                            {"title": f"{c['name']} · "
                                      + ("hồ sơ" if not c["document_id"]
                                         else f"CV #{c['document_id']}"),
                             "url": f"/person/{c['person_id']}?from=talent"}
                            for c in cv_citations]
                        if cv_citations:
                            yield _sse("citations", {"items": cv_citations})
            elif do_web:
                try:
                    result = websearch.web_answer(
                        question, system=web_system(surface, user), adapter=adapter)
                    citations = result.citations
                    web_queries = result.queries
                    provider, model_name = result.provider, result.model
                    completed = True
                    if citations:
                        yield _sse("sources", {"items": citations})
                    answer_parts.append(result.text)
                    yield _sse("answer", {"text": result.text})
                except Exception as exc:               # noqa: BLE001
                    failed = True
                    yield _sse("error", {"text": f"Không tra được web: {exc}"})
            else:
                sources = list(internal_sources)
                if do_web_merge:
                    try:
                        web_result = websearch.web_answer(
                            question, system=web_system(surface, user), adapter=adapter)
                        web_text = str(web_result.text or "").strip()
                        if web_text:
                            sources.append(("Kết quả tra Internet vừa thực hiện", web_text))
                            citations = web_result.citations
                            web_queries = web_result.queries
                            if citations:
                                yield _sse("sources", {"items": citations})
                    except Exception:                     # noqa: BLE001
                        # Vẫn còn tài liệu nội bộ để trả lời — bỏ qua lỗi web lặng lẽ,
                        # không biến một câu trả lời được thành lỗi.
                        pass
                request_obj, guard_flags = build_conversation_request(
                    question, surface=surface, user=user, projection=context,
                    knowledge=sources)
                if guard_flags:
                    yield _sse("guard", {"flags": guard_flags})
                for chunk in adapter.stream(request_obj):
                    kind = chunk.get("type")
                    if kind == "thinking":
                        reasoning_parts.append(chunk.get("text") or "")
                    elif kind == "answer":
                        answer_parts.append(chunk.get("text") or "")
                        yield _sse("answer", {"text": chunk.get("text") or ""})
                    elif kind == "error":
                        failed = True
                        yield _sse("error", {"text": chunk.get("text") or "lỗi stream"})
                        break
                    elif kind == "done":
                        result = chunk.get("response")
                        if result is not None:
                            completed = True
                            provider, model_name = result.provider, result.model
                            if not answer_parts and result.text:
                                answer_parts.append(result.text)
                            reason = (result.raw or {}).get("reasoning")
                            if reason and not reasoning_parts:
                                reasoning_parts.append(reason)
        except ModelError as exc:
            failed = True
            yield _sse("error", {"text": str(exc)})
        except Exception:
            failed = True
            log.exception("assistant stream failed")
            yield _sse("error", {"text": "Lượt trả lời không hoàn tất. Bạn có thể thử lại."})
        except GeneratorExit:
            _persist(user, surface, conversation_id, client_turn_id, question,
                     "".join(answer_parts), "".join(reasoning_parts),
                     provider, model_name, guard_flags, request_obj,
                     context.projection_version, parent_turn_id, intent=intent,
                     citations=citations, web_queries=web_queries,
                     tool_trace=tool_trace, cv_citations=cv_citations, aborted=True)
            raise

        telemetry.attach(workflow, active_usage)
        if not completed and not failed:
            failed = True
            yield _sse("error", {"text": "Lượt trả lời không hoàn tất. Bạn có thể thử lại."})
        answer = "".join(answer_parts).strip()
        reasoning = "".join(reasoning_parts).strip()
        _persist(user, surface, conversation_id, client_turn_id, question, answer,
                 reasoning, provider, model_name, guard_flags, request_obj,
                 context.projection_version, parent_turn_id, intent=intent,
                 citations=citations, web_queries=web_queries,
                 workflow_trace=workflow.trace, last_result=last_result,
                 tool_trace=tool_trace, cv_citations=cv_citations, aborted=failed)
        if failed:
            return
        yield _sse("done", {
            "conversation_id": conversation_state.normalize_thread_id(conversation_id),
            "client_turn_id": client_turn_id, "answer": answer,
            "reasoning": "",  # compatibility key; do not expose private reasoning
            "provider": provider, "model": model_name,
            "intent": "corpus" if do_corpus else intent.kind,
            # "grounded" nghĩa là câu trả lời CÓ nguồn dẫn được, không phải
            # "đã đi qua nhánh kho CV" — đi qua mà không trích được gì thì nói
            # là có dẫn chứng là nói quá.
            "grounded": bool(cv_citations),
            "sources": citations, "citations": cv_citations, "tools": tool_trace,
            "trace": workflow.trace})

    def measured_gen():
        with telemetry.capture() as active_usage:
            active_usage["calls"].extend(preflight_calls)
            yield from gen(active_usage)
    return _stream_response(measured_gen())


def _persist(user, surface, conversation_id, client_turn_id, question, answer,
             reasoning, provider, model_name, guard_flags, request_obj,
             projection_version=0, parent_turn_id="", *, intent=None, citations=None,
             web_queries=None, tool_trace=None, aborted=False, cv_citations=None,
             workflow_trace=None, last_result=None):
    citations = list(citations or [])
    cv_citations = list(cv_citations or [])
    tool_trace = list(tool_trace or [])
    metadata = {"streamed": True}
    if workflow_trace:
        metadata["trace"] = workflow_trace
    if intent is not None:
        metadata["intent"] = intent.as_dict()
    if reasoning:
        metadata["reasoning_trace"] = reasoning[:6000]
    if guard_flags:
        metadata["guard_flags"] = list(guard_flags)
    if citations:
        metadata["web_sources"] = citations
    if cv_citations:
        metadata["cv_citations"] = cv_citations
    if tool_trace:
        metadata["tool_trace"] = tool_trace
    if aborted:
        metadata["aborted"] = True
    stored_answer = answer or ("(đã huỷ giữa chừng)" if aborted else "(không có nội dung)")
    thread = conversation_state.record(
        user, surface, conversation_id, question, stored_answer,
        mode="conversation", provider=provider, model=model_name,
        metadata=metadata, client_turn_id=client_turn_id, last_result=last_result)
    reply = ConversationReply(answer, reasoning=reasoning, provider=provider,
                              model=model_name, guard_flags=guard_flags,
                              request=request_obj, projection_version=projection_version,
                              citations=citations, web=bool(citations), intent=intent,
                              web_queries=web_queries, tool_trace=tool_trace)
    events.log_conversation_turn(thread, client_turn_id, surface, question, reply,
                                 parent_turn_id=parent_turn_id)
