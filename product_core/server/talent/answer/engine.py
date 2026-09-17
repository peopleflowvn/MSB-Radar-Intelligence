# -*- coding: utf-8 -*-
"""Nhạc trưởng của năm chặng — điểm vào duy nhất của tầng sinh phản hồi.

    ① plan → ② retrieve → ③ judge → ④ aggregate → ⑤ compose

Có đúng MỘT vòng nới: truy hồi/phán đoán về tay không thì `plan.widen()` một lần
rồi chạy lại ②③④. Không nới vô hạn — quá ngân sách thì thà nói thẳng "kho không
có" còn hơn bắt người dùng chờ để nhận một câu trả lời loãng.

Mọi chặng đều ghi vào `trace` để `/settings` và test hồi quy soi được lượt trả
lời hỏng ở đâu, thay vì đoán như trước.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from ai.conversation import extract_thinking
from ai.router import stream as router_stream
from ai.telemetry import traced_answer, traced_stream
from core.answer.steps import drain, step
from django.conf import settings

from . import act as act_stage
from . import aggregate as aggregate_stage
from . import cache as cache_stage
from . import chat as chat_stage
from . import compose as compose_stage
from . import corpus as corpus_stage
from . import judge as judge_stage
from . import plan as plan_stage
from . import resolve as resolve_stage
from . import structured_match
from . import superlative as superlative_stage
from . import retrieve as retrieve_stage
from . import verify as verify_stage

log = logging.getLogger(__name__)

#: Trần thời gian mềm — vượt thì bỏ vòng nới, không cắt ngang chặng đang chạy.
BUDGET_SECONDS = 15.0

#: Số lượt tự sửa tối đa ở ⑤ khi bài viết không qua kiểm chứng tất định.
MAX_REPAIR_ATTEMPTS = 2


@dataclass
class AnswerResult:
    text: str = ""
    sources: list = field(default_factory=list)      # nguồn [n] thật sự được trích
    all_sources: list = field(default_factory=list)  # mọi trích dẫn đã kiểm chứng
    people: list = field(default_factory=list)       # [{person_id, name, why, ...}]
    #: Nguồn web [{title, url}] khi câu hỏi được trả lời bằng cách tra internet.
    #: Tách khỏi `sources` vì khác hẳn về bản chất: một bên là đoạn CV trong kho
    #: (bấm vào mở nguyên văn), một bên là liên kết ra ngoài.
    web_sources: list = field(default_factory=list)
    reasoning: str = ""
    provider: str = ""
    model: str = ""
    trace: dict = field(default_factory=dict)

    def as_dict(self):
        return {"answer": self.text, "sources": self.sources,
                "all_sources": self.all_sources, "people": self.people,
                "web_sources": self.web_sources,
                "reasoning": "", "provider": self.provider,
                "model": self.model, "trace": self.trace}


def _memories(envelope):
    """Điều người dùng đã chủ động bảo Radar nhớ. `projection` đã lọc injection."""
    projection = getattr(envelope, "projection", None)
    return list(getattr(projection, "memories", []) or []) if projection else []


#: Dạng câu hỏi cần nhìn TOÀN kho, không phải vài chục hồ sơ truy hồi được.
_AGGREGATE_SHAPES = ("analyze",)


def _corpus_facts(query_plan, stats=None):
    """Số liệu toàn kho cho câu hỏi tổng hợp; rỗng cho câu tìm người.

    Tính có điều kiện vì nó quét vài bảng — câu "tìm ứng viên Java" không cần
    biết phân bố ngành nghề toàn kho, trả tiền cho nó là lãng phí.
    """
    if (stats or {}).get("scope") in ("previous_result", "explicit_people"):
        return ""
    if getattr(query_plan, "shape", "") not in _AGGREGATE_SHAPES:
        return ""
    try:
        facts = corpus_stage.facts_for_prompt()
    except Exception:                              # noqa: BLE001
        log.warning("answer: không lấy được số liệu kho", exc_info=True)
        return ""
    # Search expansions are retrieval hints, never a Boolean count predicate.
    # In particular, unioning FTS results cannot implement AND or NOT.
    return _with_breakdown(facts, query_plan)


def _with_breakdown(facts, query_plan):
    """Thêm thống kê CÓ LỌC khi câu tổng hợp nhắc một nhóm có thật trong kho.

    `facts_for_prompt()` chỉ có số toàn kho; "kỹ năng phổ biến của ứng viên ở Hà
    Nội" mà chỉ đưa số toàn kho thì ⑤ sẽ lấy nhầm nó làm câu trả lời.
    """
    text = " ".join([getattr(query_plan, "information_need", "") or "",
                     *(getattr(query_plan, "must_have", []) or [])])
    if not text.strip():
        return facts
    try:
        block = corpus_stage.breakdown_for_question(text)
    except Exception:                              # noqa: BLE001
        log.warning("answer: không tính được thống kê có lọc", exc_info=True)
        return facts
    if block is None:
        return facts
    return "\n\n".join(part for part in (facts, corpus_stage.describe_breakdown(block)) if part)


def _people(chosen, sources):
    """Danh sách người gọn cho giao diện — KHÔNG phải thẻ ứng viên cũ.

    Chỉ đủ để hiện tên bấm được và mở hồ sơ; mọi nội dung đánh giá nằm trong văn
    bản trả lời, không nhân đôi ra thẻ (§3, yêu cầu "bỏ hết mấy cái thẻ").
    """
    return [{
        "person_id": j.person_id,
        "name": j.name,
        "why": j.why,
        "attributes": j.fact_attributes(),
        "inferences": j.inference_attributes(),
        "attribute_status": j.attribute_status,
        "criteria": j.criteria,
        "judgement_status": "INFERENCE",
        "confidence": j.confidence,
        "citations": [s["n"] for s in sources if s["person_id"] == j.person_id],
    } for j in chosen]


def _answer_people(chosen, stats, sources, near=None):
    """Giữ người đã định danh và người gần đúng trong ngữ cảnh để Frontend gắn link mở hồ sơ."""
    rows = list(chosen)
    seen = {j.person_id for j in rows}
    identified = stats.get("identified_judgements", []) or []
    for judgement in identified:
        if isinstance(judgement, dict):
            continue
        if judgement.person_id not in seen:
            rows.append(judgement)
            seen.add(judgement.person_id)
    people = _people(rows, sources)
    for row in identified:
        if not isinstance(row, dict) or row.get("person_id") in seen:
            continue
        statuses, extracted = row.get("attribute_status") or {}, row.get("extracted") or {}
        people.append({"person_id": row["person_id"], "name": row.get("name", ""),
                       "why": row.get("why", ""),
                       "attributes": {k: v for k, v in extracted.items()
                                      if statuses.get(k, {}).get("status", "FACT") == "FACT"},
                       "inferences": {k: v for k, v in extracted.items()
                                      if statuses.get(k, {}).get("status") == "INFERENCE"},
                       "attribute_status": statuses, "criteria": row.get("criteria", []),
                       "judgement_status": "INFERENCE", "confidence": row.get("confidence", 0),
                       "citations": [s["n"] for s in sources
                                     if s["person_id"] == row["person_id"]]})
        seen.add(row["person_id"])
    if near:
        for j in near:
            pid = getattr(j, "person_id", None) if not isinstance(j, dict) else j.get("person_id")
            if pid and pid not in seen:
                name = getattr(j, "name", "") if not isinstance(j, dict) else j.get("name", "")
                why = (getattr(j, "why", "") or getattr(j, "gap", "")) if not isinstance(j, dict) else (j.get("why") or j.get("gap") or "")
                fact_attr = j.fact_attributes() if hasattr(j, "fact_attributes") else (j.get("attributes") or {})
                inf_attr = j.inference_attributes() if hasattr(j, "inference_attributes") else (j.get("inferences") or {})
                people.append({
                    "person_id": pid,
                    "name": name,
                    "why": why,
                    "attributes": fact_attr,
                    "inferences": inf_attr,
                    "attribute_status": getattr(j, "attribute_status", {}) if not isinstance(j, dict) else (j.get("attribute_status") or {}),
                    "criteria": getattr(j, "criteria", []) if not isinstance(j, dict) else (j.get("criteria") or []),
                    "judgement_status": "SUGGESTION",
                    "confidence": (getattr(j, "confidence", 0.5) if not isinstance(j, dict) else j.get("confidence", 0.5)) or 0.5,
                    "citations": [s["n"] for s in sources if s.get("person_id") == pid],
                })
                seen.add(pid)
    if not people and stats.get("exact_name_count"):
        people = [{"person_id": row["id"], "name": row["name"], "why": "Khớp thành phần tên",
                   "attributes": {}, "inferences": {}, "attribute_status": {},
                   "criteria": [], "judgement_status": "FACT", "confidence": 1.0,
                   "citations": []}
                  for row in stats["exact_name_count"].get("people", [])[:50]]
    return people


#: Sự kiện BƯỚC — hợp đồng với giao diện nằm ở `core/answer/steps.py`.
_step = step


def _preamble(query_plan, question):
    """Câu "đã nhận yêu cầu — đây là cách mình định làm", dựng TỪ ① plan.

    KHÔNG gọi thêm LLM: ghép từ `shape` + `information_need` + `search_queries` +
    `next_steps` mà ① đã trả. Phát ngay sau khi hiểu câu hỏi, TRƯỚC khi ②③ chạy —
    để người dùng có ngay một câu thực chất thay vì chỉ nhìn chấm nháy.
    """
    shape = getattr(query_plan, "shape", "") or ""
    need = (getattr(query_plan, "information_need", "") or question or "").strip()
    need = " ".join(need.split())[:200]
    nq = len(getattr(query_plan, "search_queries", []) or [])
    steps = [s.get("yeu_cau", "") for s in
             (getattr(query_plan, "next_steps", []) or []) if s.get("yeu_cau")]

    if shape == "compare":
        body = (f"Bạn muốn so sánh: {need}. Mình lấy đúng các hồ sơ đó trong kho "
                "và đối chiếu từng mặt (kinh nghiệm, kỹ năng, học vấn, mức phù hợp).")
    elif shape == "count":
        body = (f"Bạn muốn đếm: {need}. Mình kiểm tra dữ liệu và nêu rõ phạm vi "
                "đã đánh giá cùng phần chưa xác định được.")
    elif shape == "analyze":
        body = (f"Đây là câu tổng hợp/thống kê về kho: {need}. Mình tính trên số "
                "liệu TOÀN kho, không phải vài hồ sơ mẫu.")
    elif shape == "followup":
        body = (f"Câu hỏi tiếp về kết quả vừa rồi: {need}. Mình dùng lại đúng "
                "nhóm người ở lượt trước, không tìm lại từ đầu.")
    else:  # find_people và mặc định
        body = (f"Mình hiểu bạn cần: {need}. Cách làm: tìm trong kho CV theo "
                f"{nq or 'vài'} hướng, đọc kỹ những hồ sơ khớp nhất rồi tổng hợp.")
    if steps:
        body += " Sau đó: " + "; ".join(steps) + "."
    return body + " Đang thực hiện…"


#: Chạy hết generator, lấy `return`-value — xem `core/answer/steps.py`.
_drain = drain


def _pipeline(question, *, envelope=None, user=None, history=None,
              complete_fn=None, deadline=None, query_plan=None):
    """Generator: `yield` các sự kiện BƯỚC, `return` `(query_plan, chosen, near,
    stats, trace)`.

    Người gọi stream: `... = yield from _pipeline(...)` — bước chảy ra client,
    tuple bắt lại. Người gọi không stream (`answer()`): `_drain(_pipeline(...))`.

    `query_plan` cho sẵn thì bỏ qua ①: người gọi đã lập kế hoạch để QUYẾT ĐỊNH có
    đi đường này không (xem `ai/stream_views.py`), lập lại là trả tiền hai lần.
    """
    started = time.monotonic()
    trace = {"question": question}

    if query_plan is None:
        yield _step("Hiểu yêu cầu")
        query_plan = plan_stage.plan(question, envelope=envelope,
                                     complete_fn=complete_fn)
        yield _step("Hiểu yêu cầu", "done")
    trace["plan"] = query_plan.as_dict()
    trace["ms_plan"] = int((time.monotonic() - started) * 1000)

    if not query_plan.needs_people:
        return query_plan, [], [], {"judged": 0, "relevant": 0, "shown": 0,
                                    "retrieved": 0, "read_failed": False}, trace

    projection = getattr(envelope, "projection", None)
    referenced_ids = resolve_stage.referenced_people(projection, question)
    scope_kind = "previous_result"
    if referenced_ids is None:
        direct_ids = resolve_stage.direct_named_people(question)
        if direct_ids:
            referenced_ids = direct_ids
            scope_kind = "explicit_people"
    if referenced_ids == []:
        trace["reference"] = "out_of_range"
        return query_plan, [], [], {"reference_unknown": True, "judged": 0}, trace

    if query_plan.shape == "count" and referenced_ids is not None:
        from dataclasses import replace
        from people.models import Person
        from people.normalize import normalize_name
        names = {normalize_name(n) for n in Person.applicants().filter(pk__in=referenced_ids)
                 .values_list("display_name", flat=True)}
        conditions = [c for c in query_plan.must_have if normalize_name(c) not in names]
        if conditions != query_plan.must_have:
            # A resolved group [A, B] is a union of identities, never a request
            # for every candidate to be simultaneously named A AND B.
            trace["count_scope_names_removed"] = len(query_plan.must_have) - len(conditions)
            query_plan = replace(query_plan, must_have=conditions)
            trace["plan"] = query_plan.as_dict()

    # Only the unconditional population count has a proven SQL predicate.
    # Conditional counts need the same evidence evaluation as candidate search.
    if query_plan.shape == "count" and referenced_ids is None:
        stats = {"judged": 0, "relevant": 0, "shown": 0, "retrieved": 0, "read_failed": False}
        from people.normalize import normalize_name
        plain = normalize_name(question).strip(" ?.!")
        name_count = resolve_stage.exact_name_count(question)
        if name_count is not None:
            stats["exact_name_count"] = name_count
            trace["fast_path"] = "count — full-store normalized name index"
            trace["count"] = {"method": "name_index", "exact": True,
                              "matched": name_count["matched"],
                              "scope_total": name_count["scope_total"]}
            return query_plan, [], [], stats, trace
        if not query_plan.must_have and re.fullmatch(
                r"(?:kho |trong kho |toan kho )?(?:hien tai |hien )?(?:co )?bao nhieu "
                r"(?:ho so|ung vien|nguoi|cv)(?: trong kho| hien tai| tat ca)?", plain):
            from people.models import Person
            stats["total_count"] = Person.applicants().count()
            trace["fast_path"] = "count — SQL applicant population"
            trace["count"] = {"method": "sql_population", "exact": True,
                              "matched": stats["total_count"], "scope_total": stats["total_count"]}
            return query_plan, [], [], stats, trace

    def finish_count(stats):
        if query_plan.shape != "count":
            return
        from people.models import Person
        population = Person.applicants()
        if referenced_ids is not None:
            population = population.filter(pk__in=referenced_ids)
        total = population.count()
        reviewed = stats.get("judged", 0)
        count = {"method": "evidence_review", "status": "INFERENCE", "exact": False,
                 "scope": stats.get("scope", "applicant_store"), "scope_total": total,
                 "reviewed": reviewed, "not_reviewed": max(0, total - reviewed),
                 "matched": stats.get("relevant", 0) if reviewed else None,
                 "read_failed": bool(stats.get("read_failed")),
                 "read_incomplete": bool(stats.get("read_incomplete")),
                 "criteria_unknown": stats.get("criteria_unknown", 0),
                 "criteria_contradicted": stats.get("criteria_contradicted", 0),
                 "unresolved_reviewed": max(0, reviewed - stats.get("relevant", 0))}
        # Rejected/unsupported dossiers are not a proven negative population.
        # Even full candidate coverage does not imply full CV/evidence coverage.
        stats["count"] = count
        trace["count"] = dict(count)

    # CỰC TRỊ TRÊN TOÀN KHO — "ứng viên lớn tuổi nhất", "nhiều KN nhất trong
    # kho". Truy hồi ngữ nghĩa chỉ đọc ~60 người gần câu hỏi nhất; "lớn tuổi
    # nhất" thì phải quét MỌI người rồi lấy cực trị. `superlative.run` bóc
    # thuộc tính bằng LUẬT (regex năm/tuổi, cột years_experience) trên toàn
    # kho — vài trăm mili-giây, không LLM, mở rộng tuyến tính.
    _sup_attr = None
    try:
        _sup_attr = superlative_stage.wants_whole_store(query_plan)
    except Exception:                             # noqa: BLE001 - phụ, không hỏng lượt
        _sup_attr = None
    if _sup_attr and referenced_ids is None and query_plan.shape != "count":
        yield _step("Quét toàn kho theo tiêu chí sắp xếp")
        chosen, stats = superlative_stage.run(query_plan, user=user, attr=_sup_attr)
        trace["fast_path"] = f"cực trị toàn kho theo '{_sup_attr}'"
        trace["superlative"] = {"attr": _sup_attr, **{k: stats.get(k) for k in
                                ("coverage_have", "coverage_total")}}
        yield _step(f"Đã xét {stats.get('coverage_have', 0)}/"
                    f"{stats.get('coverage_total', 0)} hồ sơ có dữ liệu", "done")
        return query_plan, chosen, [], stats, trace

    # Tên riêng trong câu + người của lượt trước (khi là so sánh / hỏi tiếp) →
    # GHIM vào pool. Truy hồi ngữ nghĩa không tất định; với câu neo vào một cái
    # tên thì "lần này ra, lần sau rớt" là lỗi, không phải nhiễu chấp nhận được.
    try:
        pinned_ids = (referenced_ids if referenced_ids is not None else
                      resolve_stage.pinned_for(query_plan, projection, question=question))
    except Exception:                              # noqa: BLE001 - phụ, không hỏng lượt
        pinned_ids = []
    # Chỉ các hồ sơ người dùng gọi đích danh / tham chiếu từ lượt trước mới là
    # ``identified``. Structured pins chỉ giúp recall cho điều kiện bắt buộc;
    # nếu trộn hai loại này, ⑤ sẽ nhận thêm hồ sơ ngoài top-N trong khối
    # ``nguoi_da_xac_dinh`` và có thể viết 11 người khi người dùng xin 10.
    identified_ids = set(pinned_ids)

    # `must_have` khớp được trường có cấu trúc (skills/industries/years_experience…)
    # → ghim thêm, quét trên TOÀN kho chứ không chỉ pool ngữ nghĩa. "must_have"
    # nghĩa là BẮT BUỘC; truy hồi ngữ nghĩa là xấp xỉ và có thể xếp người thoả
    # thật xuống dưới hạng pool nếu câu hỏi có nhiều tiêu chí cạnh tranh điểm.
    try:
        structured_pins = (None if referenced_ids is not None else
                           structured_match.must_have_pins(query_plan))
    except Exception:                              # noqa: BLE001 - phụ, không hỏng lượt
        structured_pins = None
    if structured_pins:
        trace["structured_pins"] = len(structured_pins)
        pinned_ids = list(dict.fromkeys(list(pinned_ids) + list(structured_pins)))

    if pinned_ids:
        trace["pinned_ids"] = len(pinned_ids)

    # 1b — đường tắt: câu neo HOÀN TOÀN vào tên ("so sánh A và B", "trong số đó
    # ai trẻ nhất"), không tiêu chí lọc nào khác. Bỏ hẳn ② truy hồi ngữ nghĩa
    # (~5s + mấy lời gọi embedding) — đọc thẳng đúng người ghim. `retrieve` với
    # `search_queries=[]` chỉ trả người ghim.
    pinned_only = referenced_ids is not None or bool(
        pinned_ids
        and getattr(query_plan, "shape", "") in ("compare", "followup")
        and not getattr(query_plan, "must_have", None)
        and len(getattr(query_plan, "should_have", []) or []) <= 1)
    if pinned_only:
        trace["fast_path_pinned"] = "bỏ ② — đọc thẳng người đã giải định danh"

    reusable_judgements = {}  # request only; widened queries may find new passages
    def _pass(active_plan, label):
        mark = time.monotonic()
        yield _step("Tìm trong kho")
        queries = [] if pinned_only else None
        retrieval_engine = "product-core"
        if getattr(settings, "INTELLIGENCE_V2_PRIMARY", False) and not pinned_only:
            try:
                from talent.intelligence_client import retrieve as intelligence_retrieve
                conversation_id = getattr(getattr(envelope, "thread", None), "thread_id", "")
                candidates = intelligence_retrieve(
                    user, active_plan, limit=retrieve_stage.pool_for(active_plan),
                    conversation_id=conversation_id)
                retrieval_engine = "intelligence-v2-haystack"
                # Deterministic pins represent exact names, prior results or
                # hard structured matches. They must not disappear merely
                # because approximate retrieval ranked them below its window.
                missing_pins = [pid for pid in pinned_ids
                                if pid not in {row.person_id for row in candidates}]
                if missing_pins:
                    pinned = retrieve_stage.retrieve(
                        active_plan, pinned_ids=missing_pins, search_queries=[])
                    candidates = pinned + candidates
            except Exception as exc:               # noqa: BLE001
                log.warning("answer: Intelligence retrieval failed; using local fallback: %s", exc)
                candidates = retrieve_stage.retrieve(
                    active_plan, pinned_ids=pinned_ids, search_queries=queries)
                retrieval_engine = "product-core-fallback"
        else:
            candidates = retrieve_stage.retrieve(
                active_plan, pinned_ids=pinned_ids, search_queries=queries)
        if active_plan.shape == "count":
            from people.models import Person
            eligible = set(Person.applicants().filter(
                pk__in=[c.person_id for c in candidates]).values_list("pk", flat=True))
            candidates = [c for c in candidates if c.person_id in eligible]
        retrieved_ms = int((time.monotonic() - mark) * 1000)
        yield _step(f"Tìm thấy {len(candidates)} hồ sơ liên quan", "done")
        yield _step("Đọc hồ sơ")
        keys = {c.person_id: judge_stage.dossier_key(active_plan, c) for c in candidates}
        unread = [c for c in candidates if keys[c.person_id] not in reusable_judgements]
        fresh = judge_stage.judge(active_plan, unread, complete_fn=complete_fn)
        for row in fresh:
            reusable_judgements[keys[row.person_id]] = row
        judgements = judge_stage.JudgeReport(
            [reusable_judgements[keys[c.person_id]] for c in candidates
             if keys[c.person_id] in reusable_judgements],
            batches=getattr(fresh, "batches", 0), failed=getattr(fresh, "failed", 0))
        chosen, near, stats = aggregate_stage.aggregate(active_plan, judgements)
        # ② tìm được người mà ③ không đọc nổi ⇒ KHÔNG được kết luận "kho không
        # có ai". Đánh dấu để ⑤ nói đúng chuyện đã xảy ra.
        stats["retrieved"] = len(candidates)
        stats["pinned"] = bool(pinned_ids)
        stats["read_failed"] = bool(candidates) and getattr(judgements, "broken", False)
        stats["read_incomplete"] = bool(candidates) and getattr(judgements, "incomplete", False)
        stats["unread"] = max(0, len(candidates) - len(judgements))
        stats["judge_sent"] = len(unread)
        stats["judge_reused"] = len(candidates) - len(unread)
        stats["deep_read_selection"] = (
            "identified_people" if pinned_only else "top_hybrid_retrieval_from_full_store")
        stats["deep_read_pool_limit"] = retrieve_stage.pool_for(active_plan)
        stats["deep_read_ranked"] = not pinned_only
        if active_plan.shape == "count":
            stats["criteria_unknown"] = sum(any(c["status"] == "UNKNOWN" for c in j.criteria) for j in judgements)
            stats["criteria_contradicted"] = sum(any(c["status"] == "CONTRADICTED" for c in j.criteria) for j in judgements)
        stats["identified_people"] = [c.name for c in candidates if c.person_id in identified_ids][:8]
        stats["identified_judgements"] = [j.as_dict() for j in judgements if j.person_id in identified_ids][:8]
        if referenced_ids is not None:
            stats.update(scope=scope_kind, scope_size=len(referenced_ids))
        trace[label] = {"ms_retrieve": retrieved_ms,
                        "retrieval_engine": retrieval_engine,
                        "ms_total": int((time.monotonic() - mark) * 1000), **stats}
        if pinned_only:
            read_label = f"Đã đọc {stats.get('judged', 0)} hồ sơ được hỏi đích danh"
        else:
            read_label = (f"Đã đọc sâu {stats.get('judged', 0)} hồ sơ tiềm năng nhất "
                          "sau khi xếp hạng toàn kho")
        yield _step(f"{read_label}, {stats.get('relevant', 0)} phù hợp", "done")
        return candidates, judgements, chosen, near, stats

    # Câu hỏi đã gặp (và kho chưa đổi) thì bỏ qua ②③④ — chúng chiếm gần trọn chi
    # phí một lượt. ⑤ vẫn chạy để câu chữ hợp với ngữ cảnh lượt này.
    # Keep conditional counts fresh: their per-condition evidence contract and
    # unknown coverage are not stored as an exact reusable population query.
    cache_key = (None if query_plan.shape == "count" else
                 cache_stage.key_for(question, envelope=envelope, user=user,
                                     query_plan=query_plan))
    # Khoá vào trace: cache trượt là loại hỏng ÂM THẦM — mọi thứ vẫn chạy, chỉ
    # đắt gấp đôi. Không nhìn được khoá thì chỉ còn cách đoán (đã phải đoán một
    # lần rồi).
    trace["cache_key"] = cache_key or "(tắt)"
    cached = cache_stage.load(cache_key)
    if cached is not None:
        judgements, retrieved = cached
        # ④ chạy lại với `limit`/`sort_by` của LƯỢT NÀY — nó là CODE thuần.
        chosen, near, stats = aggregate_stage.aggregate(query_plan, judgements)
        stats["retrieved"] = retrieved
        stats["read_failed"] = False
        stats["identified_people"] = [j.name for j in judgements if j.person_id in identified_ids][:8]
        stats["identified_judgements"] = [j.as_dict() for j in judgements if j.person_id in identified_ids][:8]
        if referenced_ids is not None:
            stats.update(scope=scope_kind, scope_size=len(referenced_ids))
        trace["cache"] = "hit"
        trace["pass1"] = dict(stats)
        finish_count(stats)
        return query_plan, chosen, near, stats, trace
    trace["cache"] = "miss"

    candidates, judgements, chosen, near, stats = yield from _pass(query_plan, "pass1")

    over_budget = deadline is not None and time.monotonic() > deadline
    # Câu neo vào tên: không nới. `widen()` thêm truy vấn ngữ nghĩa → phá đúng
    # đường tắt vừa dựng, và "so sánh A và B" thì không có gì để nới sang.
    if (not pinned_only and not over_budget
            and not aggregate_stage.enough(chosen, stats, query_plan)):
        widened = plan_stage.widen(query_plan)
        trace["widened"] = widened.as_dict()
        yield _step("Nới điều kiện, tìm lại")
        _c2, judged2, chosen2, near2, stats2 = yield from _pass(widened, "pass2")
        if chosen2 or stats2.get("judged", 0) > stats.get("judged", 0):
            query_plan, chosen, near, stats = widened, chosen2, near2, stats2
            judgements = judged2
    elif over_budget:
        trace["widen_skipped"] = "hết ngân sách thời gian"

    trace["coverage"] = retrieve_stage.coverage()
    # Chỉ lưu khi ③ thật sự đọc được. Lưu một lượt gãy là đóng đinh câu trả lời
    # sai suốt sáu tiếng.
    if not stats.get("read_failed") and not stats.get("read_incomplete") and stats.get("judged"):
        cache_stage.save(cache_key, judgements, stats.get("retrieved", 0))
    finish_count(stats)
    return query_plan, chosen, near, stats, trace


@traced_answer
def answer(question, *, envelope=None, user=None, history=None, complete_fn=None,
           adapter=None):
    """Một lượt trả lời hoàn chỉnh, không stream. Không bao giờ ném lỗi lên view."""
    started = time.monotonic()

    clean_q, doc_text = _split_attachment(question)
    from django.conf import settings
    if doc_text:
        result = AnswerResult()
        for chunk in _stream_assess_doc(clean_q, doc_text, envelope, user, started):
            if chunk.get("type") == "done":
                result = chunk["result"]
        return result

    query_plan = plan_stage.plan(question, envelope=envelope, complete_fn=complete_fn)
    branch = None
    internal_knowledge = None
    # `shape=="analyze"` là nhánh cứu hộ đã biết (MSB ngân hàng bị nhầm thành
    # kho CV). `query_plan.fallback` là một khe hở KHÁC, rộng hơn: bất kỳ lỗi
    # nào của ① (timeout, JSON hỏng, provider chết) đều rơi về `_fallback()`,
    # vốn LUÔN đặt `shape="find_people"` — một câu hỏi chính sách kiểu "thể lệ
    # giới thiệu nội bộ ứng viên" gặp đúng lúc ① trục trặc sẽ bị đẩy thẳng vào
    # pipeline tìm CV mà không ai kiểm tra kho tri thức nội bộ trước. Cùng một
    # lưới đỡ, không phụ thuộc việc ① có phân loại đúng hay không.
    if (query_plan.shape == "analyze" or query_plan.fallback) and query_plan.needs_people:
        from ai.conversation import knowledge_sources
        internal_knowledge = knowledge_sources(question, user)
        # Câu không hề nhắc CV/hồ sơ/ứng viên/kho (vd "tổng giám đốc msb là ai")
        # mà vẫn bị ① xếp "analyze" là phân loại nhầm: "MSB" ở đây là ngân hàng
        # thật, không phải kho. Đẩy sang nhánh hội thoại (có tra web) thay vì
        # chạy ②→⑤ trên kho CV rồi báo "không có dữ liệu". Xem `chat.py::_do_web`.
        # Nhưng nếu lượt trước vừa trả về người (has_recent_candidates), câu này
        # nhiều khả năng là follow-up ("ai trong số đó…") chứ không lạc đề.
        if internal_knowledge or not (plan_stage.mentions_store(question)
                                       or plan_stage.has_recent_candidates(envelope)):
            from dataclasses import replace
            query_plan = replace(query_plan, shape="general")
    if query_plan.wants_clarification:
        branch = _stream_clarify(question, query_plan, started)
    elif query_plan.wants_action and act_stage.available(user):
        branch = _stream_action(question, query_plan, envelope, user, history, started)
    elif not query_plan.needs_people:
        branch = _stream_chat(question, query_plan, envelope, user, started, adapter,
                              knowledge=internal_knowledge)
    if branch is not None:
        result = AnswerResult()
        for chunk in branch:
            if chunk.get("type") == "done":
                result = chunk["result"]
        return result

    query_plan, chosen, near, stats, trace = _drain(_pipeline(
        question, envelope=envelope, user=user, history=history,
        complete_fn=complete_fn, deadline=started + BUDGET_SECONDS,
        query_plan=query_plan))

    text, used, sources, meta = compose_stage.compose(
        query_plan, chosen, near, stats, history=history, complete_fn=complete_fn,
        user=user, memories=_memories(envelope),
        corpus_facts=_corpus_facts(query_plan, stats))
    trace["ms_total"] = int((time.monotonic() - started) * 1000)
    trace["compose"] = {"provider": meta["provider"], "model": meta["model"],
                        "fallback": meta["fallback"], "sources": len(sources),
                        "cited": len(used), "deterministic": meta.get("deterministic", False),
                        "fallback_reason": meta.get("fallback_reason", "")}
    trace["citation_audit"] = verify_stage.citation_audit(
        compose_stage.evidence_rows(chosen, stats), text, sources)

    return AnswerResult(text=text, sources=used, all_sources=sources,
                        people=_answer_people(chosen, stats, sources, near=near), reasoning=meta["reasoning"],
                        provider=meta["provider"], model=meta["model"], trace=trace)


#: Trần thời gian cho các bước nối tiếp. Vượt thì dừng và nói thẳng còn việc
#: chưa làm — thà bỏ dở có báo còn hơn để người dùng chờ vô hạn.
NEXT_STEP_BUDGET = 60.0


def _repair(messages, problems, draft, streamer):
    """Một lượt viết lại khi phát hiện lỗi. Hỏng thì trả None, giữ bản cũ.

    `draft` là bài vừa bị bắt lỗi, đưa vào làm lượt `assistant` thật để model
    THẤY được nó đã viết gì — không có `draft` thì lời dặn "giữ nguyên phần
    còn lại, chỉ sửa đúng lỗi" là mù, và model dễ viết lại một bài mới mắc
    đúng lỗi cũ.
    """
    try:
        parts = []
        for chunk in streamer(verify_stage.repair_messages(messages, problems, draft),
                              task=compose_stage.TASK, temperature=0.2,
                              max_tokens=compose_stage.STREAM_MAX_TOKENS,
                              reasoning_effort="none"):
            if chunk.get("type") == "answer":
                parts.append(chunk.get("text") or "")
            elif chunk.get("type") == "done":
                completion = chunk.get("completion")
                if getattr(completion, "truncated", False):
                    return None
                if not parts:
                    parts.append(getattr(completion, "text", "") or "")
    except Exception as exc:                        # noqa: BLE001
        log.warning("answer.verify: viết lại hỏng, giữ bản cũ: %s", exc)
        return None
    revised, _reasoning = extract_thinking("".join(parts).strip())
    revised = str(revised or "").strip()
    return revised or None


def _steps_envelope(people):
    """Envelope giả mang danh sách người của bước trước.

    Bước sau nhận người qua `last_result` — ĐÚNG cơ chế câu hỏi tiếp vẫn dùng
    (`act.people_in_context`), không phải một đường dây riêng. Nhờ vậy "soạn thư
    cho người đầu" ở bước 2 hiểu "người đầu" y hệt như khi người dùng gõ câu đó
    thành một lượt riêng.
    """
    from types import SimpleNamespace

    from ai.projection import Projection

    # Phải là `Projection` THẬT, không phải một `SimpleNamespace` cùng hình dạng:
    # `ai/agent.py` gọi `projection.context_system()`, và một namespace giả sẽ nổ
    # `AttributeError` giữa lượt. Đã xảy ra thật trên production ở lần thử đầu —
    # bước "soạn thư" chết, bước tìm người thì vẫn chạy nên nhìn qua tưởng ổn.
    items = [{"id": p["person_id"], "name": p["name"]} for p in people]
    return SimpleNamespace(projection=Projection(last_result={"items": items}))


def _run_next_steps(query_plan, people, user, history, started):
    """Chạy các việc còn lại. Yield `step_result` (chữ) hoặc `stage` (tiến độ)."""
    steps = list(getattr(query_plan, "next_steps", []) or [])
    if not steps:
        return
    if not people:
        # Bước sau thao tác trên người của bước trước; không có ai thì không có
        # gì để làm, và im lặng bỏ qua sẽ khiến người dùng tưởng đã làm rồi.
        yield {"type": "step_result",
               "text": "Chưa làm được phần việc tiếp theo vì bước tìm kiếm không "
                       "ra hồ sơ nào."}
        return

    envelope = _steps_envelope(people)
    for index, step in enumerate(steps, start=1):
        if time.monotonic() - started > NEXT_STEP_BUDGET:
            yield {"type": "step_result",
                   "text": f"Còn {len(steps) - index + 1} việc nữa trong yêu cầu "
                           "nhưng đã quá thời gian chờ. Bạn nhắn lại giúp tôi."}
            return
        need = step.get("yeu_cau") or ""
        yield _step(f"Làm tiếp: {need[:50]}")
        # Kèm việc của bước TRƯỚC: nhiều tool đòi một "lý do tiếp cận" mà chỉ
        # câu lệnh bước sau thì không có. Không có nó, agent đứng lại hỏi
        # "tiếp cận cho vị trí nào?" cho đúng việc người dùng vừa mới nhờ.
        origin = (query_plan.information_need or "").strip()
        instruction = (f"{need}\n\n(Bối cảnh: danh sách này đến từ yêu cầu "
                       f"\"{origin}\".)") if origin else need
        if step.get("shape") == "action" and act_stage.available(user):
            payload = {}
            for chunk in act_stage.stream_action(instruction, envelope=envelope,
                                                 user=user, history=history):
                if chunk.get("type") == "done":
                    payload = chunk["payload"]
                elif chunk.get("type") == "stage":
                    yield chunk
            # Tool ĐÃ chạy thật ở đây — `act_stage` đi qua `ai/agent.py`, vòng
            # lặp tool có lọc RBAC. Nhưng bản đầu chỉ lấy `text` rồi vứt
            # `tool_trace`, nên `trace.tools` rỗng và người soi trace kết luận
            # "tool chưa được khai thác thật". Kết luận ấy sai; cái hỏng là
            # đường quan sát, không phải kiến trúc. Mất dấu vết còn tệ hơn mất
            # tính năng: nó làm người ta đi sửa nhầm chỗ.
            if payload.get("tool_trace"):
                yield {"type": "tool_trace", "tools": payload["tool_trace"]}
            if payload.get("text"):
                yield {"type": "step_result", "text": payload["text"]}
            else:
                # Nói rõ việc NÀO chưa làm được. Câu chung chung ("tôi chưa
                # thực hiện được yêu cầu này") nối vào sau một phần đã làm xong
                # khiến câu trả lời tự mâu thuẫn.
                yield {"type": "step_result",
                       "text": f"Riêng phần \"{need}\" tôi chưa làm được ở lượt "
                               "này — bạn nhắn lại thành một yêu cầu riêng giúp tôi."}
        else:
            log.info("answer: bỏ bước %r (shape=%s, không thực hiện được)",
                     need[:60], step.get("shape"))
            yield {"type": "step_result",
                   "text": f"Phần \"{need}\" tôi chưa thực hiện được ở lượt này."}


#: `talent/answer_views.py` ghép text tệp đính kèm vào câu hỏi dưới nhãn này.
#: Trước đây ① coi cả khối là "câu hỏi", thấy một cái tên trong CV rồi đi TÌM
#: tên đó trong kho — trong khi nội dung cần đánh giá đang nằm ngay trong prompt.
#: Người dùng đính kèm CV chính vì người này CHƯA có trong kho.
_ATTACH_MARKER = "\n\nTÀI LIỆU ĐÍNH KÈM:\n"

_ASSESS_SYSTEM = """Bạn là Radar — trợ lý tuyển dụng của MSB. Người dùng vừa đính
kèm một tài liệu (thường là CV) và nhờ bạn ĐÁNH GIÁ CHÍNH TÀI LIỆU ĐÓ.

Đây KHÔNG phải câu tra cứu kho. Đừng nói "kho không có hồ sơ nào tên …". Nội
dung cần đánh giá nằm trong "tai_lieu" bên dưới.

Cách viết:
1. Câu đầu: tóm tắt một dòng ứng viên là ai (chức danh gần nhất, số năm kinh
   nghiệm, lĩnh vực).
2. Điểm mạnh: 2–4 gạch đầu dòng, bám vào chi tiết CỤ THỂ trong tài liệu.
3. Điểm cần lưu ý / còn thiếu: 1–3 gạch đầu dòng — khoảng trống kinh nghiệm,
   thông tin thiếu, dấu hiệu cần hỏi thêm.
4. Nếu người dùng có nêu vị trí/nhu cầu cụ thể trong câu hỏi: một câu kết luận
   mức phù hợp và vì sao.
5. Nếu "trung_ten_trong_kho" có giá trị: thêm một câu — kho đã có hồ sơ trùng
   tên (nêu tên), người dùng nên kiểm tra xem có phải cùng một người không.

TUYỆT ĐỐI: không bịa chi tiết ngoài tài liệu; không suy diễn thu nhập/sức
khoẻ/khả năng vay; KHÔNG viết ra email hay số điện thoại dù tài liệu có.

Giọng: đồng nghiệp giỏi nghề, nói thẳng. Tiếng Việt. Không markdown tiêu đề,
không emoji. Tối đa ~250 từ."""


#: Câu hỏi ĐÍNH KÈM có hai ý định khác hẳn nhau:
#:   1. "đánh giá ứng viên này" + CV  → đánh giá THẲNG tài liệu (ảnh test 04/09)
#:   2. "tìm người phù hợp" + JD      → bóc JD rồi TÌM trong kho (đường cũ)
#: Chỉ nhận diện (1); (2) để nguyên cho ① như trước.
_ASSESS_WORDS = ("đánh giá", "danh gia", "nhận xét", "nhan xet", "review",
                 "ứng viên này", "ung vien nay", "hồ sơ này", "ho so nay",
                 "cv này", "cv nay", "người này", "nguoi nay", "phân tích cv",
                 "phan tich cv", "assess", "evaluate", "xem giúp", "xem giup",
                 "tài liệu này", "tai lieu nay")
_FIND_WORDS = ("tìm", "tim ", "tuyển", "tuyen", "phù hợp", "phu hop", "shortlist",
               "ai làm", "ai lam", "ứng viên nào", "ung vien nao", "liệt kê",
               "liet ke", "search", "match")


def _wants_assessment(clean_question):
    """Mặc định là đánh giá tài liệu; chỉ trả False khi câu RÕ RÀNG là tìm người."""
    low = " ".join(str(clean_question or "").casefold().split())
    if not low:
        return True                                # đính kèm trần → đánh giá
    finds = any(w in low for w in _FIND_WORDS)
    assesses = any(w in low for w in _ASSESS_WORDS)
    return not (finds and not assesses)


def _split_attachment(question):
    """`(câu hỏi thật, text tài liệu)` — hoặc `(câu hỏi, "")` nếu không đính kèm.

    Chỉ trả `doc_text` khác rỗng khi câu hỏi là "đánh giá tài liệu này". Câu
    "tìm người phù hợp với JD đính kèm" giữ nguyên khối để ① xử như trước.
    """
    marker = _ATTACH_MARKER.strip()
    if marker not in question:
        return question, ""
    sep = _ATTACH_MARKER if _ATTACH_MARKER in question else marker
    head, _, tail = question.partition(sep)
    head, tail = (head.strip() or head), tail.strip()
    if not tail or not _wants_assessment(head):
        return question, ""
    return head, tail


def _name_twin_in_store(doc_text):
    """Tên ở đầu tài liệu có trùng hồ sơ nào trong kho không (chỉ để nhắc)."""
    from people.models import Person
    from people.normalize import normalize_name

    first_lines = [ln.strip() for ln in doc_text.splitlines()[:6] if ln.strip()]
    for line in first_lines:
        if not (2 <= len(line.split()) <= 5) or any(ch.isdigit() for ch in line):
            continue
        folded = normalize_name(line)
        if len(folded) < 4:
            continue
        match = next((p for p in Person.objects.only("id", "display_name")
                      if normalize_name(p.display_name) == folded), None)
        if match:
            return match.display_name
    return ""


def _stream_assess_doc(question, doc_text, envelope, user, started, stream_fn=None):
    """Đánh giá THẲNG tài liệu đính kèm — không truy hồi kho."""
    streamer = stream_fn or router_stream
    yield {"type": "preamble",
           "text": "Bạn nhờ đánh giá tài liệu đính kèm. Mình đọc thẳng nội dung "
                   "CV này (không tra trong kho), rút điểm mạnh — điểm cần lưu ý "
                   "— mức phù hợp. Đang đọc…"}
    yield _step("Đọc tài liệu đính kèm")
    ask = question or "Đánh giá ứng viên trong tài liệu này."
    twin = ""
    try:
        twin = _name_twin_in_store(doc_text)
    except Exception:                              # noqa: BLE001 - phụ, không hỏng lượt
        twin = ""
    payload = {
        "yeu_cau": ask,
        "tai_lieu": doc_text[:16000],
        "trung_ten_trong_kho": twin or None,
    }
    import json as _json
    messages = [
        {"role": "system", "content": _ASSESS_SYSTEM},
        {"role": "user", "content": _json.dumps(payload, ensure_ascii=False)},
    ]
    yield _step("Viết đánh giá")
    buffer, reasoning, provider, model = [], [], "", ""
    try:
        for chunk in streamer(messages, task=compose_stage.TASK,
                              temperature=0.3,
                              max_tokens=compose_stage.STREAM_MAX_TOKENS,
                              reasoning_effort="none"):
            kind = chunk.get("type")
            if kind == "answer":
                buffer.append(chunk.get("text") or "")
                yield chunk
            elif kind == "reasoning":
                reasoning.append(chunk.get("text") or "")
                yield chunk
            elif kind == "done":
                completion = chunk.get("completion")
                provider = getattr(completion, "provider", "") or ""
                model = getattr(completion, "model", "") or ""
                if not buffer and completion is not None:
                    buffer.append(getattr(completion, "text", "") or "")
    except Exception as exc:                        # noqa: BLE001
        log.warning("answer.assess: ⑤ lỗi: %s", exc)
    text, inline = extract_thinking("".join(buffer).strip())
    text = str(text or "").strip()
    if not text:
        text = ("Tôi chưa đọc được tài liệu đính kèm. Bạn thử tải lại tệp, "
                "hoặc dán nội dung CV thẳng vào ô chat giúp tôi.")
        yield {"type": "answer", "text": text}
    yield {"type": "done", "result": AnswerResult(
        text=text,
        reasoning=("".join(reasoning) or inline or "")[:6000],
        provider=provider, model=model,
        trace={"question": ask, "mode": "assess_doc",
               "doc_chars": len(doc_text), "name_twin": twin,
               "ms_total": int((time.monotonic() - started) * 1000)})}


def _stream_chat(question, query_plan, envelope, user, started, adapter=None,
                 knowledge=None):
    """Câu hỏi phổ thông: câu trả lời có sẵn → tra web → hội thoại thường.

    Đưa loại câu hỏi này qua ①→⑤ cho ra câu trả lời sai giọng — ⑤ viết bằng
    prompt tuyển dụng trên một danh sách ứng viên rỗng.
    """
    payload = {}
    for chunk in chat_stage.stream_chat(question, envelope=envelope, user=user,
                                        adapter=adapter, knowledge=knowledge):
        if chunk.get("type") == "done":
            payload = chunk["payload"]
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


def _stream_clarify(question, query_plan, started):
    """① không biết người dùng muốn gì → HỎI LẠI, không đoán.

    Đoán bừa rồi chạy hết ①→⑤ mất vài chục giây, đốt một lượt truy hồi toàn kho,
    để cuối cùng trả lời nhầm câu hỏi — rồi người dùng vẫn phải gõ lại. Một câu
    hỏi lại rẻ hơn tất cả những thứ đó. Chỉ chạy khi ① vừa tự chấm là không chắc
    vừa viết ra được câu hỏi cụ thể (`QueryPlan.wants_clarification`).

    Không gọi model lần nữa: câu hỏi đã có sẵn trong kế hoạch.
    """
    text = query_plan.clarify
    yield {"type": "answer", "text": text}
    yield {"type": "done", "result": AnswerResult(
        text=text,
        trace={"question": question, "plan": query_plan.as_dict(),
               "mode": "clarify",
               "ms_total": int((time.monotonic() - started) * 1000)})}


def _stream_action(question, query_plan, envelope, user, history, started):
    """Chuyển tiếp nhánh hành động, đóng gói `AnswerResult` như nhánh trả lời."""
    payload = {}
    for chunk in act_stage.stream_action(question, envelope=envelope, user=user,
                                         history=history):
        if chunk.get("type") == "done":
            payload = chunk["payload"]
        else:
            yield chunk
    yield {"type": "done", "result": AnswerResult(
        text=payload.get("text") or "",
        people=payload.get("people") or [],
        reasoning=(payload.get("reasoning") or "")[:6000],
        provider=payload.get("provider", ""), model=payload.get("model", ""),
        trace={"question": question, "plan": query_plan.as_dict(), "mode": "action",
               "tools": payload.get("tool_trace") or [],
               "ms_total": int((time.monotonic() - started) * 1000)})}


@traced_stream
def stream_answer(question, *, envelope=None, user=None, history=None,
                  complete_fn=None, stream_fn=None, query_plan=None, adapter=None):
    """Như `answer()` nhưng phát dần. Yield dict:

        {"type": "stage",     "stage": "...", "text": "..."}   # tiến độ ①→④
        {"type": "reasoning", "text": <delta>}
        {"type": "answer",    "text": <delta>}
        {"type": "done",      "result": AnswerResult}

    ①→④ mất vài giây và không có gì để phát; phát trạng thái để người dùng thấy
    hệ thống đang làm gì, rồi mới stream chữ của ⑤.

    `complete_fn` chi phối ①③, `stream_fn` chi phối ⑤ — hai đường gọi khác nhau
    nên phải chèn được riêng, nếu không test vẫn bắn thẳng ra nhà cung cấp thật.
    """
    started = time.monotonic()
    yield _step("Hiểu yêu cầu")

    # Có tệp đính kèm → đánh giá THẲNG tài liệu, không tra kho. Kiểm trước ①: ①
    # thấy tên trong CV rồi đi tìm tên đó, trả "kho không có hồ sơ nào tên …".
    clean_q, doc_text = _split_attachment(question)
    if doc_text:
        yield _step("Hiểu yêu cầu", "done")
        yield from _stream_assess_doc(clean_q, doc_text, envelope, user, started,
                                     stream_fn=stream_fn)
        return

    from django.conf import settings
    # Mệnh lệnh ("soạn thư cho 3 người đầu") rẽ sang nhánh tool. Đi tiếp ②→⑤ là
    # sai từ gốc: ② sẽ tìm lại từ đầu và có thể ra một danh sách KHÁC với danh
    # sách người dùng đang trỏ tới.
    if query_plan is None:
        query_plan = plan_stage.plan(question, envelope=envelope,
                                     complete_fn=complete_fn)
    yield _step("Hiểu yêu cầu", "done")
    # Hỏi lại đứng TRƯỚC mọi nhánh khác: không nhánh nào trả lời đúng được một
    # câu mà chính ① còn không biết nó hỏi gì.
    if query_plan.wants_clarification:
        yield from _stream_clarify(question, query_plan, started)
        return
    if query_plan.wants_action and act_stage.available(user):
        yield {"type": "preamble",
               "text": f"Bạn yêu cầu: {query_plan.information_need or question}. "
                       "Mình thực hiện trên nhóm người đang nói tới. Đang làm…"}
        yield from _stream_action(question, query_plan, envelope, user, history, started)
        return
    # ① không biết gì về kho tri thức nội bộ (plan.py viết trước khi module đó
    # tồn tại) và bị buộc không bao giờ chọn "general" khi câu hỏi nhắc tới
    # "ứng viên"/"hồ sơ"/"kho" — nên một câu chính sách công ty ("quy định giới
    # thiệu ứng viên cho MSB") vẫn nhắc "ứng viên" và bị xếp "analyze", chạy
    # thẳng vào ②→⑤ tìm-người rồi báo "kho không có tài liệu quy định". Tài
    # liệu tri thức nội bộ luôn thắng nếu có — cùng nguyên tắc với
    # `chat.py::stream_chat` (nội bộ thắng web), chỉ khác chỗ áp dụng.
    internal_knowledge = None
    # Xem giải thích đầy đủ ở `answer()`: `query_plan.fallback` (① lỗi/timeout,
    # luôn rơi về shape="find_people") là một khe hở khác với "analyze" bị
    # nhầm — cả hai đều cần lưới đỡ này trước khi chạy thẳng pipeline tìm CV.
    if (query_plan.shape == "analyze" or query_plan.fallback) and query_plan.needs_people:
        from ai.conversation import knowledge_sources
        internal_knowledge = knowledge_sources(question, user)
        # Xem giải thích ở `answer()` — câu không nhắc CV/hồ sơ/kho mà vẫn ra
        # "analyze" là ① nhầm "MSB" (ngân hàng) với kho CV. Trừ khi lượt trước
        # vừa trả người (follow-up thật).
        if internal_knowledge or not (plan_stage.mentions_store(question)
                                       or plan_stage.has_recent_candidates(envelope)):
            from dataclasses import replace
            query_plan = replace(query_plan, shape="general")

    # Câu hỏi không về Kho con người → nhánh hội thoại (có tra web). Trước đây
    # nó vẫn chạy tiếp xuống ⑤ và nhận một câu trả lời sai giọng.
    if not query_plan.needs_people and not query_plan.wants_action:
        yield _step("Tra cứu & soạn câu trả lời")
        yield from _stream_chat(question, query_plan, envelope, user, started,
                                adapter, knowledge=internal_knowledge)
        return

    # "Đã nhận yêu cầu — đây là cách mình định làm." Ngay sau ①, trước ②③ (chỗ
    # tốn thời gian nhất) — để người dùng có một câu thực chất chứ không chỉ
    # nhìn chấm nháy suốt mấy chục giây.
    yield {"type": "preamble", "text": _preamble(query_plan, clean_q)}

    query_plan, chosen, near, stats, trace = yield from _pipeline(
        question, envelope=envelope, user=user, history=history,
        complete_fn=complete_fn, deadline=started + BUDGET_SECONDS,
        query_plan=query_plan)

    verified_rows = compose_stage.evidence_rows(chosen, stats)
    sources = compose_stage.build_sources(verified_rows)
    messages = compose_stage.build_messages(query_plan, chosen, near, stats, sources,
                                            history=history, user=user,
                                            memories=_memories(envelope),
                                            corpus_facts=_corpus_facts(query_plan, stats))
    yield _step("Viết câu trả lời")

    buffer, reasoning, provider, model = [], [], "", ""
    truncated = False
    compose_fallback = False
    fallback_reason = ""
    streamer = stream_fn or router_stream
    try:
        for chunk in streamer(messages, task=compose_stage.TASK,
                              temperature=0.35,
                              max_tokens=compose_stage.STREAM_MAX_TOKENS,
                              reasoning_effort="none"):
            kind = chunk.get("type")
            if kind == "answer":
                buffer.append(chunk.get("text") or "")
                yield chunk
            elif kind == "reasoning":
                # Vẫn GOM để lưu vào trace (soi lỗi), nhưng KHÔNG đẩy ra client:
                # người dùng nói chỉ cần thấy các bước, không cần đổ token suy
                # nghĩ ra màn hình.
                reasoning.append(chunk.get("text") or "")
            elif kind == "done":
                completion = chunk.get("completion")
                provider = getattr(completion, "provider", "") or ""
                model = getattr(completion, "model", "") or ""
                truncated = bool(getattr(completion, "truncated", False))
                if not buffer and completion is not None:
                    buffer.append(getattr(completion, "text", "") or "")
    except Exception as exc:                        # noqa: BLE001
        log.warning("answer.stream: ⑤ lỗi, không sinh câu trả lời CODE: %s", exc)
        truncated = True
        fallback_reason = "model_error"

    raw = "".join(buffer).strip()
    text, inline_reasoning = extract_thinking(raw)
    text = str(text or raw).strip()
    if not text:
        text = compose_stage.ai_unavailable_text(fallback_reason or "empty_response")
        compose_fallback = True
        fallback_reason = fallback_reason or "empty_response"
        yield {"type": "answer", "text": text}
    elif truncated:
        log.warning("answer.stream: ⑤ bị cắt vì hết token")
        text = compose_stage.ai_unavailable_text(fallback_reason or "truncated")
        trace["truncated_fallback"] = True
        compose_fallback = True
        fallback_reason = fallback_reason or "truncated"
        # `ok: False` — đây là bỏ cuộc, không phải bản đã sửa. Thiếu cờ này thì
        # giao diện hiện nhầm banner "đã tự sửa" lên trên câu xin lỗi (ảnh báo
        # lỗi 17/09: banner "đã sửa đúng" ngồi ngay trên câu "chưa thể trả lời").
        yield {"type": "revision", "text": text, "ok": False}

    # Vòng TỰ SỬA. ② đã có `widen()` khi truy hồi mỏng; ⑤ thì trước đây không có
    # gì bắt lỗi. Chỉ kiểm những thứ CODE tự khẳng định được bằng cách đối chiếu
    # với `chosen` — thứ tự, số lượng, có nguồn hay không.
    #
    # Tối đa HAI lượt sửa, không phải một: lượt đầu hay chỉ sửa đúng lỗi vừa nêu
    # mà lại lệch một lỗi khác (VD gộp trích dẫn làm lệch số lượng), và bây giờ
    # `_repair` đã cho model thấy bài cũ nên một lượt sửa thêm thường xử lý gọn.
    problems = verify_stage.check(query_plan, verified_rows, text, sources)
    attempts = 0
    while problems and attempts < MAX_REPAIR_ATTEMPTS:
        attempts += 1
        trace["verify"] = problems
        yield _step("Kiểm lại câu trả lời")
        revised = _repair(messages, problems, text, streamer)
        if not revised:
            break
        text = revised
        problems = verify_stage.check(query_plan, verified_rows, text, sources)

    trace["repair_attempts"] = attempts
    if attempts and not problems:
        trace["revised"] = True
        # Chữ cũ đã phát ra màn hình, không rút lại được — nên gửi bản đã sửa
        # dưới dạng sự kiện riêng để giao diện THAY THẾ, và người dùng thấy
        # rõ Radar đã tự sửa chứ không phải im lặng đổi bài.
        yield {"type": "revision", "text": text, "ok": True}
    elif problems:
        text = compose_stage.ai_unavailable_text("verification_failed")
        trace["verify_fallback"] = True
        compose_fallback = True
        fallback_reason = "verification_failed"
        # `ok: False` — bản sửa vẫn không qua kiểm chứng, đây là bỏ cuộc.
        yield {"type": "revision", "text": text, "ok": False}

    text, used = compose_stage.used_sources(text, sources)
    people = _answer_people(chosen, stats, sources, near=near)

    # Việc CÒN LẠI của cùng một câu hỏi. "Tìm ứng viên Java rồi soạn thư cho
    # người đầu" là một câu hai việc; dừng ở đây thì thư không bao giờ được soạn.
    for extra in _run_next_steps(query_plan, people, user, history, started):
        if extra.get("type") == "step_result":
            text = f"{text}\n\n{extra['text']}"
            yield {"type": "answer", "text": "\n\n" + extra["text"]}
        elif extra.get("type") == "tool_trace":
            # Không phát ra ngoài — đây là dấu vết để soi sau, không phải tiến độ.
            trace.setdefault("tools", []).extend(extra["tools"])
        else:
            yield extra

    trace["ms_total"] = int((time.monotonic() - started) * 1000)
    trace["compose"] = {"provider": provider, "model": model,
                        "sources": len(sources), "cited": len(used),
                        "fallback": compose_fallback,
                        "fallback_reason": fallback_reason}
    trace["citation_audit"] = verify_stage.citation_audit(verified_rows, text, sources)
    if query_plan.next_steps:
        trace["next_steps"] = query_plan.next_steps

    yield {"type": "done", "result": AnswerResult(
        text=text, sources=used, all_sources=sources,
        people=people,
        reasoning=("".join(reasoning) or inline_reasoning or "")[:6000],
        provider=provider, model=model, trace=trace)}
