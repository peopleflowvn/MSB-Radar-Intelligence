# -*- coding: utf-8 -*-
"""Growth Answer Engine — điều phối ①→⑤ cho câu hỏi tìm khách hàng tiềm năng.

Hình dạng giống hệt `talent/answer/engine.py` có chủ ý: cùng khuôn sự kiện, cùng
cách cache, cùng vòng nới, cùng vòng kiểm-rồi-viết-lại. Người đã đọc một bên thì
đọc được bên kia. Khác biệt nằm TRONG từng chặng (xem docstring của gói), không
nằm ở cách nối các chặng.

## Phạm vi của bản đầu

Có: tìm khách (`find_prospects`), danh mục của RM (`portfolio`), khoảng trống
(`whitespace`), tổng hợp, đếm, so sánh, hỏi tiếp, hỏi lại khi mập mờ, câu lệnh
soạn nháp / tạo cơ hội (`act.py`), và nhánh hội thoại chung.

Chưa có, và nói rõ để không ai tưởng đã có:

* **Tài liệu đính kèm** — Talent đánh giá thẳng CV được kéo vào; Growth chưa có
  loại tài liệu tương ứng đáng làm.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, replace

from ai.conversation import extract_thinking
from ai.router import stream as router_stream
from core.answer import verify as verify_stage
from core.answer.steps import drain, step

from . import aggregate as aggregate_stage
from . import cache as cache_stage
from . import compose as compose_stage
from . import judge as judge_stage
from . import plan as plan_stage
from . import resolve as resolve_stage
from . import retrieve as retrieve_stage

log = logging.getLogger(__name__)

#: Trần thời gian mềm — vượt thì bỏ vòng nới, không cắt ngang chặng đang chạy.
BUDGET_SECONDS = 15.0

#: Trần thời gian CỨNG của chặng ③ đọc bằng chứng, tính từ lúc vào pipeline.
#: Cùng lý do và cùng con số với `talent/answer/engine.py`: `core/answer/runner.py`
#: cắt cả lượt ở 150 giây, mà số lô của ③ đi theo số khách ② trả về nên tự phình
#: theo kho. Chốt 90 giây để còn dư cho ⑤ viết bài.
READ_BUDGET_SECONDS = 90.0
STREAM_MAX_TOKENS = 2500

#: Số lượt tự sửa tối đa ở ⑤ khi bài viết không qua kiểm chứng tất định.
MAX_REPAIR_ATTEMPTS = 2


def _collect_workflow_models(trace, default_provider="", default_model=""):
    """Gom mọi mô hình AI đã tham gia xử lý qua từng vai trò/chặng."""
    models = []
    seen = set()

    def _add(stage, role, p, m, icon="🤖"):
        key = (stage, p, m)
        if (p or m) and key not in seen:
            seen.add(key)
            models.append({"stage": stage, "role": role, "provider": p, "model": m, "icon": icon})

    plan = trace.get("plan")
    if isinstance(plan, dict):
        _add("plan", "Lập kế hoạch & Phân tích", plan.get("provider", ""), plan.get("model", ""), "🎯")

    for label in ("pass1", "pass2", "judge"):
        info = trace.get(label)
        if isinstance(info, dict):
            _add("judge", "Sàng lọc & Đánh giá khách hàng", info.get("provider", ""), info.get("model", ""), "⚖️")

    compose = trace.get("compose")
    mode = trace.get("mode")
    if isinstance(compose, dict):
        _add("compose", "Tổng hợp & Phản hồi", compose.get("provider", "") or default_provider,
             compose.get("model", "") or default_model, "✍️")
    elif mode == "chat":
        _add("chat", "Hội thoại trực tiếp", default_provider, default_model, "💬")
    elif mode == "action":
        _add("action", "Thực thi tác vụ", default_provider, default_model, "⚡")
    elif mode == "clarify":
        pass
    elif default_model or default_provider:
        _add("main", "Mô hình xử lý", default_provider, default_model, "🤖")

    return models


@dataclass
class AnswerResult:
    text: str = ""
    sources: list = field(default_factory=list)      # nguồn [n] thật sự được trích
    all_sources: list = field(default_factory=list)  # mọi trích dẫn đã kiểm chứng
    people: list = field(default_factory=list)       # [{person_id, name, why, action…}]
    web_sources: list = field(default_factory=list)
    reasoning: str = ""
    provider: str = ""
    model: str = ""
    trace: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.trace is not None and isinstance(self.trace, dict):
            if "workflow_models" not in self.trace:
                self.trace["workflow_models"] = _collect_workflow_models(
                    self.trace, self.provider, self.model)

    def as_dict(self):
        return {"answer": self.text, "sources": self.sources,
                "all_sources": self.all_sources, "people": self.people,
                "web_sources": self.web_sources, "reasoning": "",
                "provider": self.provider, "model": self.model, "trace": self.trace}


def _people(chosen, actions, sources):
    """Danh sách khách cho giao diện — kèm điểm, sản phẩm, hành động, nguồn.

    Mang đủ các trường của `ProspectRow` bên web (`location`, `occupation`,
    `has_open_opportunity`, và `reasons` dạng mảng) để thẻ kết quả + nút "Tạo cơ
    hội" đang có hiển thị được kết quả của engine mới mà không phải viết lại.
    `reasons` đặt lời giải thích từ BẰNG CHỨNG lên đầu, lý do chấm điểm xuống
    sau: "tự viết cần vay mua xe 4 ngày trước" có ích cho RM hơn "nghề nghiệp
    cấp quản lý".
    """
    from people.models import Person
    from ..models import RBOpportunity

    ids = [j.person_id for j in chosen]
    facts = {row["pk"]: row for row in Person.objects.filter(pk__in=ids).values(
        "pk", "location", "headline", "rb_profile__occupation",
        "talent_profile__current_title", "talent_profile__current_company")}
    open_ids = set(RBOpportunity.objects.filter(
        person_id__in=ids, status__in=RBOpportunity.OPEN_STATUSES)
        .values_list("person_id", flat=True))

    by_person = {}
    for source in sources:
        by_person.setdefault(source["person_id"], []).append(source["n"])
    out = []
    for judgement in chosen:
        detail = (judgement.criteria or [{}])[0]
        code = actions.get(judgement.person_id, "WAIT")
        fact = facts.get(judgement.person_id) or {}
        reasons = [judgement.why] if judgement.why else []
        reasons += [str(r) for r in (detail.get("why") or [])]
        # `headline` là vị trí ỨNG TUYỂN, không phải nghề nghiệp — xem
        # `scoring.cv_title`. Chức danh trùng nó là dữ liệu cũ ghi sai.
        title = fact.get("talent_profile__current_title") or ""
        if title == (fact.get("headline") or ""):
            title = ""
        occ = fact.get("rb_profile__occupation") or title
        company = fact.get("talent_profile__current_company") or ""
        display_occ = f"{occ} tại {company}" if (occ and company and company not in occ) else occ
        out.append({
            "person_id": judgement.person_id,
            "name": judgement.name,
            "location": fact.get("location") or "",
            "occupation": display_occ,
            "has_open_opportunity": judgement.person_id in open_ids,
            "reasons": reasons,
            "why": judgement.why,
            "product": detail.get("product", ""),
            "priority_score": detail.get("priority_score", 0.0),
            "scores": detail.get("dimensions", {}),
            "need_kind": judgement.need_kind,
            "freshest_days": judgement.freshest_days,
            "action": code,
            "action_label": compose_stage.ACTION_LABELS.get(code, code),
            "sources": by_person.get(judgement.person_id, []),
            "url": f"/person/{judgement.person_id}?from=rb",
        })
    return out


def _preamble(query_plan, question):
    """Câu "đã nhận yêu cầu — đây là cách mình định làm", dựng TỪ ①. Không gọi LLM."""
    need = " ".join(((query_plan.information_need or question) or "").split())[:200]
    shape = query_plan.shape
    if shape == "portfolio":
        body = (f"Bạn hỏi về danh mục của chính mình: {need}. Mình chỉ xét những "
                "khách anh/chị đang phụ trách.")
    elif shape == "whitespace":
        body = (f"Bạn tìm khách còn bỏ trống: {need}. Mình chỉ xét khách chưa ai "
                "phụ trách và chưa có cơ hội đang mở.")
    elif shape == "count":
        body = (f"Bạn muốn đếm: {need}. Mình kiểm tra bằng chứng và nêu rõ phạm vi "
                "đã đánh giá.")
    elif shape == "compare":
        body = f"Bạn muốn so sánh: {need}. Mình đối chiếu bằng chứng từng người."
    else:
        body = (f"Mình hiểu bạn cần: {need}. Cách làm: tìm theo tín hiệu, bài đăng và "
                "lịch sử tiếp cận, đọc kỹ những khách khớp nhất, rồi xếp theo mức "
                "đáng ưu tiên.")
    return body + " Đang thực hiện…"


def _pipeline(question, *, envelope=None, user=None, complete_fn=None,
              deadline=None, query_plan=None):
    """Generator: `yield` sự kiện BƯỚC, `return` `(plan, chosen, near, stats, trace)`."""
    started = time.monotonic()
    trace = {"question": question}

    if query_plan is None:
        yield step("Hiểu yêu cầu")
        query_plan = plan_stage.plan(question, envelope=envelope, user=user,
                                     complete_fn=complete_fn)
        yield step("Hiểu yêu cầu", "done")
    trace["plan"] = query_plan.as_dict()
    trace["ms_plan"] = int((time.monotonic() - started) * 1000)

    empty = {"judged": 0, "relevant": 0, "shown": 0, "retrieved": 0,
             "read_failed": False}
    if not query_plan.needs_people:
        return query_plan, [], [], empty, trace

    # Nhóm người lượt trước — cho câu so sánh / hỏi tiếp.
    pinned_ids = []
    projection = getattr(envelope, "projection", None)
    if query_plan.shape in ("compare", "followup") and projection is not None:
        try:
            pinned_ids = [int(p["id"]) for p in projection.last_result_people(limit=12)
                          if p.get("id")]
        except Exception:                          # noqa: BLE001 - phụ, không hỏng lượt
            pinned_ids = []
    # Ghim tất định — xem `resolve.py`. Thứ tự ưu tiên: cực trị toàn kho (thứ tự
    # đã là câu trả lời), tên riêng, người lượt trước, điều kiện có cấu trúc.
    pool = None
    pinned_only = False
    try:
        # Câu đếm / tổng hợp không ghim ai: câu trả lời của chúng là số liệu toàn
        # phạm vi, và ghim người vào đó chỉ làm lệch mẫu được đọc.
        aggregate_shape = query_plan.shape in ("count", "analyze")
        attr = (resolve_stage.superlative_attr(query_plan, question)
                if query_plan.shape not in ("compare", "followup") and not aggregate_shape
                else None)
        if attr:
            yield step("Quét toàn kho theo thứ tự yêu cầu")
            limit = max(1, int(query_plan.limit or 20))
            ids = resolve_stage.superlative_ids(query_plan, attr, user=user, limit=limit)
            trace["superlative"] = {"attr": attr, "found": len(ids)}
            if attr == resolve_stage.ATTR_RECENCY:
                # ④ phải giữ đúng thứ tự "mới nhất", không xếp lại theo điểm ưu tiên.
                query_plan = replace(query_plan, sort_by={"key": aggregate_stage.RECENCY_KEY,
                                                          "dir": "asc"})
            pinned_ids, pool, pinned_only = ids, max(1, len(ids)), True
            yield step("Quét toàn kho theo thứ tự yêu cầu", "done")
        elif not aggregate_shape:
            named = resolve_stage.named_customers(query_plan, question)
            if named:
                trace["named_ids"] = len(named)
                # "so sánh Nguyễn An và Trần Bình" so ĐÚNG hai người đó, không kéo
                # theo cả danh sách lượt trước.
                pinned_ids = (named if query_plan.shape == "compare"
                              else list(dict.fromkeys(named + pinned_ids)))
            if (pinned_ids and query_plan.shape in ("compare", "followup")
                    and not query_plan.must_have):
                # "so sánh A và B": đọc đúng những người được nói tới, không
                # truy hồi thêm ai — người lạ lọt vào bài so sánh là trả lời sai.
                pool, pinned_only = len(pinned_ids), True
            elif not pinned_ids:
                structured = resolve_stage.structured_pins(query_plan, user=user)
                if structured:
                    trace["structured_pins"] = len(structured)
                    pinned_ids = structured
    except Exception:                              # noqa: BLE001 - phụ, không hỏng lượt
        log.warning("rb.answer.engine: ghim tất định hỏng, dùng truy hồi thường",
                    exc_info=True)
    if pinned_ids:
        trace["pinned_ids"] = len(pinned_ids)

    def _pass(active_plan, label):
        mark = time.monotonic()
        yield step("Tìm khách hàng")
        candidates = retrieve_stage.retrieve(active_plan, user=user,
                                             pinned_ids=pinned_ids, pool=pool)
        retrieved_ms = int((time.monotonic() - mark) * 1000)
        yield step(f"Tìm thấy {len(candidates)} khách liên quan", "done")
        yield step("Đọc bằng chứng")
        judgements = judge_stage.judge(active_plan, candidates, complete_fn=complete_fn,
                                       deadline=started + READ_BUDGET_SECONDS)
        chosen, near, stats = aggregate_stage.aggregate(active_plan, judgements, user=user)
        # ② tìm được người mà ③ không đọc nổi ⇒ KHÔNG được kết luận "không có
        # khách nào". Đánh dấu để ⑤ nói đúng chuyện đã xảy ra.
        stats["retrieved"] = len(candidates)
        stats["read_failed"] = bool(candidates) and getattr(judgements, "broken", False)
        stats["read_incomplete"] = bool(candidates) and getattr(judgements, "incomplete", False)
        stats["scope"] = active_plan.shape
        trace[label] = {"ms_retrieve": retrieved_ms,
                        "ms_total": int((time.monotonic() - mark) * 1000), **stats}
        yield step(f"Đã đọc {stats.get('judged', 0)} hồ sơ, "
                   f"{stats.get('relevant', 0)} phù hợp", "done")
        return judgements, chosen, near, stats

    cache_key = (None if query_plan.shape == "count" else
                 cache_stage.key_for(question, envelope=envelope, user=user,
                                     query_plan=query_plan))
    trace["cache_key"] = cache_key or "(tắt)"
    cached = cache_stage.load(cache_key)
    if cached is not None:
        judgements, retrieved = cached
        # ④ chạy lại trên phán đoán đã lưu — nó là CODE thuần, và chính nó mang
        # lưới DNC thứ hai (xem `aggregate.py`).
        chosen, near, stats = aggregate_stage.aggregate(query_plan, judgements, user=user)
        stats["retrieved"] = retrieved
        stats["read_failed"] = False
        stats["scope"] = query_plan.shape
        trace["cache"] = "hit"
        trace["pass1"] = dict(stats)
        return query_plan, chosen, near, stats, trace
    trace["cache"] = "miss"

    judgements, chosen, near, stats = yield from _pass(query_plan, "pass1")

    over_budget = deadline is not None and time.monotonic() > deadline
    if (not pinned_only and not over_budget
            and not aggregate_stage.enough(chosen, stats, query_plan)):
        widened = plan_stage.widen(query_plan)
        trace["widened"] = widened.as_dict()
        yield step("Nới điều kiện, tìm lại")
        judged2, chosen2, near2, stats2 = yield from _pass(widened, "pass2")
        if chosen2 or stats2.get("judged", 0) > stats.get("judged", 0):
            query_plan, chosen, near, stats = widened, chosen2, near2, stats2
            judgements = judged2
    elif over_budget:
        trace["widen_skipped"] = "hết ngân sách thời gian"

    try:
        trace["coverage"] = retrieve_stage.coverage()
    except Exception:                              # noqa: BLE001
        trace["coverage"] = {}
    # Chỉ lưu khi ③ thật sự đọc được. Lưu một lượt gãy là đóng đinh câu trả lời
    # sai suốt sáu tiếng.
    if not stats.get("read_failed") and not stats.get("read_incomplete") and stats.get("judged"):
        cache_stage.save(cache_key, judgements, stats.get("retrieved", 0))
    return query_plan, chosen, near, stats, trace


def _actions_for(chosen):
    person_cache = {}
    actions = {}
    for judgement in chosen:
        try:
            actions[judgement.person_id] = compose_stage.next_action_for(
                judgement, person_cache=person_cache)
        except Exception:                          # noqa: BLE001
            # Không chọn được hành động thì nói "chờ", không bịa "gọi ngay".
            log.warning("rb.answer.engine: không chọn được hành động (person=%s)",
                        judgement.person_id, exc_info=True)
            actions[judgement.person_id] = "WAIT"
    return actions


def _repair(messages, problems, draft, streamer):
    """Một lượt viết lại khi `verify` bắt được lỗi. Hỏng thì giữ bản cũ.

    `draft` là bài vừa bị bắt lỗi — đưa vào làm lượt `assistant` thật để model
    thấy được nó đã viết gì, xem [[core.answer.verify.repair_messages]].
    """
    try:
        parts = []
        for chunk in streamer(verify_stage.repair_messages(messages, problems, draft),
                              task=compose_stage.TASK, temperature=0.2,
                              max_tokens=STREAM_MAX_TOKENS, reasoning_effort="none"):
            if chunk.get("type") == "answer":
                parts.append(chunk.get("text") or "")
            elif chunk.get("type") == "done":
                completion = chunk.get("completion")
                if getattr(completion, "truncated", False):
                    return None
                if not parts:
                    parts.append(getattr(completion, "text", "") or "")
    except Exception as exc:                       # noqa: BLE001
        log.warning("rb.answer.verify: viết lại hỏng, giữ bản cũ: %s", exc)
        return None
    revised, _ = extract_thinking("".join(parts).strip())
    return str(revised or "").strip() or None


def _stream_clarify(question, query_plan, started):
    """① không biết RM muốn gì → HỎI LẠI, không đoán. Không gọi model lần nữa."""
    text = query_plan.clarifying_question
    yield {"type": "answer", "text": text}
    yield {"type": "done", "result": AnswerResult(
        text=text, trace={"question": question, "plan": query_plan.as_dict(),
                          "mode": "clarify",
                          "ms_total": int((time.monotonic() - started) * 1000)})}


def _stream_chat(question, query_plan, envelope, user, started, adapter=None):
    """Câu không về kho khách hàng → nhánh hội thoại chung, đúng persona Growth."""
    from talent.answer.chat import stream_chat

    payload = {}
    for chunk in stream_chat(question, envelope=envelope, user=user, adapter=adapter,
                             surface="prospect"):
        if chunk.get("type") == "done":
            payload = chunk.get("payload") or {}
        else:
            yield chunk
    yield {"type": "done", "result": AnswerResult(
        text=payload.get("text") or "",
        web_sources=payload.get("web_sources") or [],
        reasoning=(payload.get("reasoning") or "")[:6000],
        provider=payload.get("provider", ""), model=payload.get("model", ""),
        trace={"question": question, "plan": query_plan.as_dict(),
               "mode": payload.get("mode", "chat"),
               "ms_total": int((time.monotonic() - started) * 1000)})}


def _stream_action(question, query_plan, envelope, user, started):
    """Câu lệnh → `act.run`. Hành động và đối tượng do CODE quyết, xem `act.py`."""
    from . import act as act_stage

    yield step("Thực hiện yêu cầu")
    try:
        outcome = act_stage.run(question, envelope=envelope, user=user)
    except Exception:                              # noqa: BLE001
        log.exception("rb.answer.act: câu lệnh hỏng")
        outcome = {"mode": "action_error", "people": [], "actions": [],
                   "text": "Chưa thực hiện được yêu cầu này. Anh/chị thử lại giúp mình."}
    yield step("Thực hiện yêu cầu", "done")
    yield {"type": "answer", "text": outcome["text"]}
    yield {"type": "done", "result": AnswerResult(
        text=outcome["text"], people=outcome.get("people") or [],
        trace={"question": question, "plan": query_plan.as_dict(),
               "mode": outcome["mode"], "actions": outcome.get("actions") or [],
               # Lượt câu lệnh KHÔNG thay danh sách lượt trước: "soạn tin cho khách
               # thứ 2" rồi "tạo cơ hội cho khách thứ 3" phải cùng trỏ về một danh
               # sách. Xem `answer_views._persist`.
               "keeps_last_result": True,
               "ms_total": int((time.monotonic() - started) * 1000)})}


def _memories(envelope):
    """Điều RM đã chủ động bảo Radar nhớ. `projection` đã lọc injection."""
    projection = getattr(envelope, "projection", None)
    return list(getattr(projection, "memories", []) or []) if projection else []


#: Câu cần số liệu toàn phạm vi, không chỉ vài chục khách vừa đọc.
_AGGREGATE_SHAPES = ("analyze", "portfolio")


def _corpus_facts(query_plan, user):
    if query_plan.shape not in _AGGREGATE_SHAPES:
        return ""
    from .corpus import facts_for_prompt
    from .count import SCOPE_LABEL
    from .population import scope_queryset
    return facts_for_prompt(scope_queryset=scope_queryset(query_plan.shape, user),
                            scope_label=SCOPE_LABEL.get(query_plan.shape, "toàn kho khách hàng"))


def _stream_count(question, query_plan, envelope, user, started, complete_fn):
    """Câu đếm — xem `count.py`. Chính xác bằng SQL khi làm được, ước lượng có nhãn khi không."""
    from . import count as count_stage
    from .structured import analyse_plan

    analysis = analyse_plan(query_plan)
    trace = {"question": question, "plan": query_plan.as_dict(),
             "count_analysis": {"all_covered": analysis.all_covered,
                                "uncovered": analysis.uncovered,
                                "filters": analysis.filters,
                                "product_groups": analysis.product_groups}}
    people = []
    if analysis.all_covered:
        yield step("Đếm trên toàn bộ dữ liệu")
        count = count_stage.exact(query_plan, analysis, user=user)
        yield step("Đếm trên toàn bộ dữ liệu", "done")
    else:
        effective = count_stage.effective_plan(query_plan, analysis)
        effective, chosen, _near, stats, pipeline_trace = yield from _pipeline(
            question, envelope=envelope, user=user, complete_fn=complete_fn,
            deadline=started + BUDGET_SECONDS, query_plan=effective)
        trace.update({k: v for k, v in pipeline_trace.items() if k != "question"})
        count = count_stage.inference(effective, analysis, stats, user=user)
        people = _people(chosen, _actions_for(chosen), compose_stage.build_sources(chosen))
    text = count_stage.text_for(count)
    trace["count"] = count
    trace["ms_total"] = int((time.monotonic() - started) * 1000)
    trace["compose"] = {"deterministic": True}
    yield {"type": "answer", "text": text}
    yield {"type": "done", "result": AnswerResult(text=text, people=people, trace=trace)}


def stream_answer(question, *, envelope=None, user=None, history=None,
                  complete_fn=None, stream_fn=None, query_plan=None, adapter=None):
    """Phát dần một lượt trả lời. Yield dict:

        {"type": "step",     "label": "...", "state": "active"|"done"}
        {"type": "preamble", "text": "..."}
        {"type": "answer",   "text": <delta>}
        {"type": "revision", "text": <bản đã sửa>}
        {"type": "done",     "result": AnswerResult}

    `complete_fn` chi phối ①③, `stream_fn` chi phối ⑤ — hai đường gọi khác nhau
    nên phải chèn được riêng, nếu không test vẫn bắn thẳng ra nhà cung cấp thật.
    """
    started = time.monotonic()
    yield step("Hiểu yêu cầu")
    if query_plan is None:
        query_plan = plan_stage.plan(question, envelope=envelope, user=user,
                                     complete_fn=complete_fn)
    yield step("Hiểu yêu cầu", "done")

    # Hỏi lại đứng TRƯỚC mọi nhánh: không nhánh nào trả lời đúng được một câu mà
    # chính ① còn không biết nó hỏi gì.
    if query_plan.wants_clarification:
        yield from _stream_clarify(question, query_plan, started)
        return
    if query_plan.shape == "action":
        yield from _stream_action(question, query_plan, envelope, user, started)
        return
    if not query_plan.needs_people:
        yield step("Tra cứu & soạn câu trả lời")
        yield from _stream_chat(question, query_plan, envelope, user, started, adapter)
        return

    # Kế hoạch đi KÈM preamble, tức ngay sau ① và TRƯỚC ②③. Ràng buộc sản phẩm
    # "tiêu chí luôn hiện ra" nói RM phải thấy hệ thống hiểu câu hỏi thế nào
    # trước khi tin danh sách — gửi kế hoạch cùng lúc với danh sách ở `done` là
    # đúng chữ nhưng sai tinh thần.
    yield {"type": "preamble", "text": _preamble(query_plan, question),
           "plan": query_plan.as_dict()}

    if query_plan.shape == "count":
        yield from _stream_count(question, query_plan, envelope, user, started, complete_fn)
        return

    query_plan, chosen, near, stats, trace = yield from _pipeline(
        question, envelope=envelope, user=user, complete_fn=complete_fn,
        deadline=started + BUDGET_SECONDS, query_plan=query_plan)

    actions = _actions_for(chosen)
    sources = compose_stage.build_sources(chosen)
    people = _people(chosen, actions, sources)

    corpus_facts = _corpus_facts(query_plan, user)
    if corpus_facts:
        trace["corpus_facts"] = True

    # Không có gì để viết, hoặc ③ hỏng → văn bản tất định. Không gọi LLM để nói
    # "chưa tìm thấy": vừa tốn, vừa có thể bịa ra một lý do nghe hợp lý. TRỪ câu
    # tổng hợp có số liệu toàn kho: câu trả lời thật nằm ở số liệu, không ở danh
    # sách, nên danh sách rỗng không có nghĩa là không có gì để nói.
    if (not chosen and not corpus_facts) or stats.get("read_failed"):
        text = compose_stage.deterministic_text(query_plan, chosen, stats, actions=actions)
        yield {"type": "answer", "text": text}
        trace["ms_total"] = int((time.monotonic() - started) * 1000)
        trace["compose"] = {"deterministic": True}
        yield {"type": "done", "result": AnswerResult(
            text=text, sources=[], all_sources=sources, people=people, trace=trace)}
        return

    messages = compose_stage.build_messages(query_plan, chosen, near, stats, sources,
                                            user=user, history=history, actions=actions,
                                            memories=_memories(envelope),
                                            corpus_facts=corpus_facts)
    yield step("Viết câu trả lời")

    buffer, provider, model, truncated = [], "", "", False
    streamer = stream_fn or router_stream
    try:
        for chunk in streamer(messages, task=compose_stage.TASK, temperature=0.3,
                              max_tokens=STREAM_MAX_TOKENS, reasoning_effort="none"):
            kind = chunk.get("type")
            if kind == "answer":
                buffer.append(chunk.get("text") or "")
                yield chunk
            elif kind == "done":
                completion = chunk.get("completion")
                provider = getattr(completion, "provider", "") or provider
                model = getattr(completion, "model", "") or model
                truncated = bool(getattr(completion, "truncated", False))
    except Exception as exc:                       # noqa: BLE001
        log.warning("rb.answer.compose: stream hỏng, dùng văn bản tất định: %s", exc)
        buffer = []

    text, _ = extract_thinking("".join(buffer).strip())
    text = str(text or "").strip()
    deterministic = False
    if not text or truncated:
        # Bài cụt giữa chừng không được đi ra ngoài như một câu trả lời hoàn chỉnh.
        text = compose_stage.deterministic_text(query_plan, chosen, stats, actions=actions)
        deterministic = True
        # `ok: False` — đây là bỏ cuộc dùng văn bản tất định, không phải bản đã
        # sửa. Thiếu cờ này thì giao diện hiện nhầm banner "đã tự sửa".
        yield {"type": "revision", "text": text, "ok": False}

    if not deterministic:
        problems = verify_stage.check(query_plan, chosen, text, sources)
        attempts = 0
        while problems and attempts < MAX_REPAIR_ATTEMPTS:
            attempts += 1
            yield step("Kiểm tra và sửa câu trả lời")
            revised = _repair(messages, problems, text, streamer)
            if not revised:
                break
            text = revised
            problems = verify_stage.check(query_plan, chosen, text, sources)
        if attempts:
            # `ok: False` nếu sửa hết lượt vẫn còn lỗi — giao diện không được
            # gắn nhầm banner "đã tự sửa" cho bản vẫn sai.
            yield {"type": "revision", "text": text, "ok": not problems}
        trace["verify"] = {"problems": problems, "repaired": bool(attempts) and not problems,
                           "attempts": attempts}

    trace["ms_total"] = int((time.monotonic() - started) * 1000)
    trace["compose"] = {"provider": provider, "model": model,
                        "deterministic": deterministic, "sources": len(sources)}
    trace["citation_audit"] = verify_stage.citation_audit(chosen, text, sources)
    yield {"type": "done", "result": AnswerResult(
        text=text, sources=compose_stage.used_sources(text, sources),
        all_sources=sources, people=people, provider=provider, model=model,
        trace=trace)}


def answer(question, *, envelope=None, user=None, history=None, complete_fn=None,
           stream_fn=None, query_plan=None, adapter=None):
    """Như `stream_answer` nhưng trả một lần `AnswerResult`."""
    result = AnswerResult()
    for chunk in stream_answer(question, envelope=envelope, user=user, history=history,
                               complete_fn=complete_fn, stream_fn=stream_fn,
                               query_plan=query_plan, adapter=adapter):
        if chunk.get("type") == "done":
            result = chunk["result"]
    return result


# `drain`/`replace` giữ trong không gian tên cho người gọi đường không stream và
# cho test dựng kế hoạch đã chỉnh — cùng từ vựng với `talent/answer/engine.py`.
__all__ = ["AnswerResult", "answer", "stream_answer", "drain", "replace"]
