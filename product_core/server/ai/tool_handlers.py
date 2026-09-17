# -*- coding: utf-8 -*-
"""Handler cho từng tool trong `ai/toolset.py` (Master Plan §23.1.3).

Mỗi handler: `(arguments: dict, *, user, surface, context: dict) -> dict`.
Chỉ đọc / chỉ đề xuất. Không tin `arguments` — validate ở đây. RBAC đã lọc một
lần ở `toolset.dispatch`, handler vẫn tự kiểm khi đụng dữ liệu người/hồ sơ.

`ToolError` → thông báo gọn cho model (model có thể sửa và thử lại); lỗi khác →
`toolset.dispatch` nuốt và trả "lỗi nội bộ".
"""
from accounts import roles


class ToolError(Exception):
    """Lỗi có thể trình bày cho model (sai tham số, không tìm thấy, …)."""


def _int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolError(f"'{name}' phải là số nguyên")


def _require(user, module):
    try:
        if not roles.can_access(user, module):
            raise ToolError("tài khoản không có quyền xem dữ liệu này")
    except ToolError:
        raise
    except Exception:                             # noqa: BLE001
        raise ToolError("không kiểm được quyền truy cập")


# --------------------------------------------------------------------------- #
# Tier 1
# --------------------------------------------------------------------------- #
def read_allowed_evidence(args, *, user, surface, context):
    _require(user, roles.MODULE_TALENT)
    from intel.models import ExtractedFact
    from people.models import Person

    pid = _int(args.get("person_id"), "person_id")
    person = Person.objects.filter(pk=pid, merged_into__isnull=True).first()
    if person is None:
        raise ToolError(f"không có Person #{pid} (hoặc đã hợp nhất)")

    fields = [str(f).strip() for f in (args.get("fields") or []) if str(f).strip()]
    qs = (ExtractedFact.objects
          .filter(person=person, is_current=True,
                  status=ExtractedFact.STATUS_ACCEPTED)
          .order_by("field", "-observed_at"))
    if fields:
        qs = qs.filter(field__in=fields[:12])

    rows = []
    for fact in qs[:40]:
        rows.append({
            "field": fact.field,
            "value": fact.canonical_label or fact.raw_value,
            "evidence": (fact.evidence or "")[:400],
            "source": fact.source_kind,
            "confidence": round(fact.confidence, 2),
        })
    return {
        "person_id": pid,
        "display_name": person.display_name or f"Person #{pid}",
        "facts": rows,
        "note": "" if rows else "Person này chưa có fact đã duyệt.",
    }


def remember_proposal(args, *, user, surface, context):
    from .memory_views import _quota
    from .models import LongTermMemory
    from .prompt_guard import scan as guard_scan

    value = str(args.get("value") or "").strip()
    if len(value) < 4:
        raise ToolError("'value' quá ngắn")
    if guard_scan(value):
        raise ToolError("nội dung ghi nhớ có dấu hiệu chèn chỉ dẫn — từ chối")
    scope = args.get("scope") or LongTermMemory.SCOPE_OPERATIONAL
    if scope not in (LongTermMemory.SCOPE_PROFILE, LongTermMemory.SCOPE_OPERATIONAL):
        raise ToolError("'scope' phải là 'profile' hoặc 'operational'")

    pending = LongTermMemory.objects.filter(
        user=user, scope=scope, status=LongTermMemory.STATUS_PENDING).count()
    if pending >= 10:
        raise ToolError("đang có quá nhiều đề xuất ghi nhớ chờ duyệt")

    row = LongTermMemory.objects.create(
        user=user, scope=scope, kind=LongTermMemory.KIND_FACT,
        status=LongTermMemory.STATUS_PENDING, value=value[:500],
        source="radar_ai", surface=surface)
    return {"status": "pending_review", "id": row.pk, "scope": scope,
            "note": "Đã đưa vào hàng chờ; người dùng cần duyệt trong Cài đặt "
                    f"(giới hạn {_quota(scope)} ghi nhớ đang dùng)."}


def feedback(args, *, user, surface, context):
    from .models import AssistantFeedback, AssistantMessage, AssistantThread

    rating = args.get("rating")
    if rating not in (AssistantFeedback.RATING_UP, AssistantFeedback.RATING_DOWN):
        raise ToolError("'rating' phải là 'up' hoặc 'down'")
    thread = None
    tid = context.get("thread_id")
    if tid:
        thread = AssistantThread.objects.filter(
            user=user, thread_id=str(tid), surface=surface).first()
    message = None
    mid = context.get("message_id")
    if mid:
        message = AssistantMessage.objects.filter(pk=mid, thread__user=user).first()

    row = AssistantFeedback.objects.create(
        user=user, thread=thread, message=message, rating=rating,
        reason=str(args.get("reason") or "")[:500], surface=surface,
        question=str(context.get("question") or "")[:2000],
        answer=str(context.get("answer") or "")[:2000])
    return {"recorded": True, "id": row.pk, "rating": rating}


# --------------------------------------------------------------------------- #
# Tier 2 — kỹ năng ghép, toàn bộ chỉ đọc
# --------------------------------------------------------------------------- #
_COMPARE_DIMS = ("current_title", "current_company", "years_experience",
                 "location", "skills")


def compare_candidates(args, *, user, surface, context):
    _require(user, roles.MODULE_TALENT)
    from people.models import Person

    raw_ids = args.get("person_ids") or []
    ids = [_int(x, "person_ids[]") for x in raw_ids][:3]
    if len(ids) < 2:
        raise ToolError("cần ít nhất 2 person_id")
    dims = [d for d in (args.get("dimensions") or _COMPARE_DIMS)
            if d in _COMPARE_DIMS] or list(_COMPARE_DIMS)

    people = (Person.objects.filter(pk__in=ids, merged_into__isnull=True)
              .select_related("talent_profile"))
    found = {p.pk: p for p in people}
    missing = [i for i in ids if i not in found]
    if missing:
        raise ToolError(f"không có Person: {missing}")

    rows = []
    for pid in ids:
        p = found[pid]
        tp = getattr(p, "talent_profile", None)
        entry = {"person_id": pid, "display_name": p.display_name or f"Person #{pid}"}
        for d in dims:
            val = getattr(tp, d, None) if tp else None
            if d == "skills":
                val = list(val or [])
            entry[d] = val
        rows.append(entry)
    return {"dimensions": dims, "candidates": rows}


def canonical_lookup(args, *, user, surface, context):
    _require(user, roles.MODULE_TALENT)
    from intel.registry import resolve

    namespace = str(args.get("namespace") or "").strip()
    value = str(args.get("value") or "").strip()
    if not namespace or not value:
        raise ToolError("cần 'namespace' và 'value'")
    res = resolve(namespace, value, propose=False)
    return {
        "query": value, "namespace": namespace,
        "canonical_code": res.code, "canonical_label": res.label,
        "matched": bool(res.code),
        "normalized": res.normalized,
        "note": "" if res.code else "Chưa có mã canonical khớp — giá trị này sẽ "
                                    "vào hàng chờ alias nếu pipeline chạy.",
    }


def aggregate_corpus(args, *, user, surface, context):
    """Thống kê toàn kho có lọc — `talent.answer.corpus.breakdown`, tất định.

    Trả số đếm, không trả tên người: thống kê không phải đường vòng để liệt kê
    hồ sơ, nên không mở rộng bề mặt lộ dữ liệu cá nhân so với `overview()`.
    """
    _require(user, roles.MODULE_TALENT)
    from talent.answer import corpus

    filters = args.get("filters") or {}
    if not isinstance(filters, dict):
        raise ToolError("'filters' phải là object {tên trường: giá trị}")
    try:
        block = corpus.breakdown(str(args.get("field") or ""),
                                 filters={str(k): str(v) for k, v in filters.items()},
                                 limit=_int(args.get("limit") or corpus.TOP_N, "limit"))
    except ValueError as exc:
        raise ToolError(str(exc))
    block["note"] = ("Chỉ tính trên trường có cấu trúc; hồ sơ để trống trường lọc "
                     "không được tính vào nhóm. Nêu độ phủ khi trả lời.")
    return block


def match_candidate_job(args, *, user, surface, context):
    """Đối chiếu MỘT ứng viên với danh sách yêu cầu của một vị trí/JD.

    Dùng đúng luật khớp `must_have` trên trường có cấu trúc
    (`talent.answer.structured_match`) — không viết luật khớp thứ hai. Tất
    định: mỗi yêu cầu chỉ có ba khả năng ("satisfied"/"missing"/"unknown"),
    không có mức "gần đúng" mờ.
    """
    _require(user, roles.MODULE_TALENT)
    from people.models import Person
    from talent.answer import structured_match

    pid = _int(args.get("person_id"), "person_id")
    person = Person.objects.filter(pk=pid, merged_into__isnull=True).first()
    if person is None:
        raise ToolError(f"không có Person #{pid} (hoặc đã hợp nhất)")
    requirements = [str(r).strip() for r in (args.get("requirements") or []) if str(r).strip()]
    if not requirements:
        raise ToolError("cần ít nhất 1 'requirements'")
    rows = structured_match.match_requirements(pid, requirements)
    missing = [r["requirement"] for r in rows if r["status"] == "missing"]
    unknown = [r["requirement"] for r in rows if r["status"] == "unknown"]
    return {
        "person_id": pid, "display_name": person.display_name or f"Person #{pid}",
        "role_title": str(args.get("role_title") or "")[:200],
        "matches": rows,
        "satisfied_count": sum(1 for r in rows if r["status"] == "satisfied"),
        "total": len(rows),
        "missing": missing,
        "note": (f"{len(unknown)} yêu cầu KHÔNG quy về được trường có cấu trúc "
                 "(status='unknown') — nghĩa là chưa xác định được qua dữ liệu đã "
                 "bóc, KHÔNG PHẢI ứng viên không đáp ứng; đọc CV trực tiếp mới "
                 "biết chắc." if unknown else ""),
    }


def _activity_domains(user):
    """Nghiệp vụ mà tài khoản được đọc hoạt động — không rộng hơn Person 360.

    RM thuần chỉ thấy phần bán lẻ (đúng `talent.views._rm_only`). Recruiter
    không có module RB thì KHÔNG thấy hoạt động bán lẻ — chặt hơn màn hình một
    chút, có chủ đích: câu trả lời của agent dễ bị chép đi hơn một dòng timeline.
    """
    from talent.views import _rm_only

    domains = set()
    if roles.can_access(user, roles.MODULE_TALENT) and not _rm_only(user):
        domains.add("talent")
    if roles.can_access(user, roles.MODULE_RB):
        domains.add("rb")
    return domains


def _short_text(value, limit=200):
    from accounts import privacy
    return privacy.redact_contacts(" ".join(str(value or "").split()))[:limit]


def person_activity(args, *, user, surface, context):
    """Trạng thái quan hệ + dòng thời gian gần đây của MỘT Person."""
    _require(user, roles.MODULE_TALENT)
    from people.models import Person

    pid = _int(args.get("person_id"), "person_id")
    limit = max(1, min(_int(args.get("limit") or 15, "limit"), 30))
    person = Person.objects.filter(pk=pid, merged_into__isnull=True).first()
    if person is None:
        raise ToolError(f"không có Person #{pid} (hoặc đã hợp nhất)")
    domains = _activity_domains(user)
    wanted = str(args.get("domain") or "").strip()
    if wanted:
        if wanted not in domains:
            raise ToolError("tài khoản không được xem hoạt động của nghiệp vụ này")
        domains = {wanted}

    relationships = [{
        "domain": r.domain, "state": r.state, "owner": r.owner,
        "interest_level": r.interest_level, "last_contact_at": r.last_contact_at,
        "next_action": _short_text(r.next_action), "next_action_at": r.next_action_at,
        "do_not_contact": r.do_not_contact, "reason": _short_text(r.reason),
    } for r in person.relationships.filter(domain__in=domains)]

    events = [{"kind": "interaction", "domain": row.domain, "action": row.action,
               "actor": row.actor_name, "at": row.occurred_at}
              for row in person.interactions.filter(domain__in=domains)
              .exclude(action="viewed").order_by("-occurred_at")[:limit]]
    events += [{"kind": "signal", "domain": row.domain, "action": row.signal_type,
                "source": row.source, "confidence": round(row.confidence, 2),
                "status": row.status, "at": row.observed_at}
               for row in person.signals.filter(domain__in=domains)
               .order_by("-observed_at")[:limit]]
    events.sort(key=lambda e: e["at"], reverse=True)
    for event in events:
        event["at"] = event["at"].isoformat() if event["at"] else None
    for rel in relationships:
        for key in ("last_contact_at", "next_action_at"):
            rel[key] = rel[key].isoformat() if rel[key] else None
    return {
        "person_id": pid,
        "display_name": person.display_name or f"Person #{pid}",
        "domains": sorted(domains),
        "relationships": relationships,
        "timeline": events[:limit],
        "note": ("Lượt 'đã xem' hồ sơ bị lược bỏ. do_not_contact=true nghĩa là KHÔNG "
                 "được đề xuất liên hệ người này."),
    }


def fact_provenance(args, *, user, surface, context):
    _require(user, roles.MODULE_TALENT)
    from intel.models import ExtractedFact
    from people.models import Person

    pid = _int(args.get("person_id"), "person_id")
    field = str(args.get("field") or "").strip()
    if not field:
        raise ToolError("cần 'field'")
    if not Person.objects.filter(pk=pid, merged_into__isnull=True).exists():
        raise ToolError(f"không có Person #{pid}")

    facts = (ExtractedFact.objects
             .filter(person_id=pid, field=field)
             .order_by("-is_current", "-observed_at")[:15])
    rows = [{
        "value": f.canonical_label or f.raw_value,
        "raw_value": f.raw_value,
        "source": f.source_kind,
        "evidence": (f.evidence or "")[:300],
        "confidence": round(f.confidence, 2),
        "status": f.status,
        "is_current": f.is_current,
        "observed_at": f.observed_at.isoformat() if f.observed_at else None,
    } for f in facts]
    return {"person_id": pid, "field": field, "history": rows,
            "note": "" if rows else f"Person #{pid} chưa có fact cho '{field}'."}


# --------------------------------------------------------------------------- #
# Tier 3 — sinh nội dung / tra ngoài. KHÔNG gửi / đăng gì.
# --------------------------------------------------------------------------- #
def draft_outreach(args, *, user, surface, context):
    _require(user, roles.MODULE_TALENT)
    from people.models import Person

    from .adapter import ModelRequest, get_adapter
    from .persona import stable_system

    pid = _int(args.get("person_id"), "person_id")
    person = Person.objects.filter(pk=pid, merged_into__isnull=True).first()
    if person is None:
        raise ToolError(f"không có Person #{pid}")
    ctx = str(args.get("context") or "").strip()
    if len(ctx) < 4:
        raise ToolError("'context' quá ngắn — cần lý do tiếp cận")
    channel = args.get("channel") or "email"
    if channel not in ("email", "linkedin", "call_note", "sms"):
        channel = "email"

    evidence = read_allowed_evidence({"person_id": pid}, user=user, surface=surface,
                                     context=context)
    facts_line = "; ".join(f"{f['field']}={f['value']}" for f in evidence["facts"][:8])
    name = evidence["display_name"]

    system = (stable_system(surface, user) + " "
              "Nhiệm vụ: viết BẢN NHÁP tin nhắn tiếp cận, lịch sự, ngắn (<=120 từ), "
              "tiếng Việt, KHÔNG bịa thông tin ngoài dữ kiện được cấp, KHÔNG hứa hẹn "
              "lương/chức danh cụ thể. Đây là bản nháp để người dùng tự chỉnh và gửi.")
    prompt = (f"Kênh: {channel}\nỨng viên: {name}\nDữ kiện: {facts_line or 'ít dữ kiện'}\n"
              f"Bối cảnh tiếp cận: {ctx}\n\nViết bản nháp.")
    try:
        resp = get_adapter().complete(ModelRequest(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            task="assistant_outreach", temperature=0.4, max_tokens=700,
            extra={"budget_seconds": 40, "reasoning_effort": "none"}))
    except Exception:                             # noqa: BLE001
        raise ToolError("không gọi được mô hình để soạn nháp")
    draft = str(getattr(resp, "text", "") or "").strip()
    if not draft:
        raise ToolError("mô hình không trả bản nháp")
    return {"person_id": pid, "channel": channel, "draft": draft[:1500],
            "sent": False,
            "disclaimer": "Bản nháp do Radar sinh — người dùng phải tự rà và gửi."}


#: Ba field `estimate_profile_gaps` biết suy — nhãn tiếng Việt để dựng prompt
#: và câu trả lời cho model tự luận ở tầng 2.
_ESTIMATE_FIELDS = {
    "years_experience": "số năm kinh nghiệm",
    "graduation_year": "năm tốt nghiệp",
    "birth_year": "năm sinh",
}
#: Field ExtractedFact loại khỏi ngữ cảnh cho model tự luận: chính field đang
#: đoán (nếu có mặt nghĩa là đã "known", không cần đoán), và field nhạy cảm/liên
#: hệ không liên quan gì tới tuổi tác hay kinh nghiệm — cho model thấy thêm chỉ
#: tăng rủi ro rò rỉ dữ liệu, không tăng chất lượng đoán.
_REASONING_CONTEXT_EXCLUDE = {"date_of_birth", "graduation_year", "years_experience",
                              "email", "phone", "current_address", "current_salary",
                              "expected_salary"}


def _reasoning_context_lines(person, tp):
    """Dữ kiện KHÔNG nhạy cảm, không phải chính field đang đoán — làm căn cứ
    cho model tự luận ở `_reason_missing_fields`."""
    from intel.facts import current_facts

    lines = []
    if tp is not None:
        for field, label in (("current_title", "chức danh"), ("current_company", "công ty"),
                             ("seniority", "cấp bậc"), ("education", "học vấn")):
            val = getattr(tp, field, "")
            if val:
                lines.append(f"{label}: {val}")
        if tp.skills:
            lines.append("kỹ năng: " + ", ".join(tp.skills[:15]))
        if tp.industries:
            lines.append("ngành từng làm: " + ", ".join(tp.industries[:8]))
    for fact in current_facts(person).exclude(field__in=_REASONING_CONTEXT_EXCLUDE)[:20]:
        val = (fact.canonical_label or fact.raw_value or "")[:200]
        if val:
            lines.append(f"{fact.field}: {val}")
    return lines[:25]


def _reason_missing_fields(person, tp, fields):
    """Tầng 2 — cho model TỰ LUẬN suy đoán field còn thiếu từ MỌI dữ kiện khác
    đã biết (chức danh, kỹ năng, học vấn...), khi công thức tất định ở
    `talent.estimate` không đủ mốc thời gian để tính.

    KHÁC HẲN công thức: ở đây model được PHÉP tự do suy luận thay vì bị giới
    hạn trong một phép tính cố định — đổi lại KHÔNG TẤT ĐỊNH, hai lượt hỏi có
    thể ra hai con số khác nhau. Thí điểm theo yêu cầu người dùng 2026-09-17,
    CHỈ áp dụng ở tool ước tính này — không áp cho `match_candidate_job`,
    `aggregate_corpus` và các tool tất định khác, vì chúng phải cho cùng một
    đáp án ở mọi màn hình dùng chung; phá bất biến đó thì hai màn hình có thể
    kết luận khác nhau cho cùng một ứng viên.

    Trả `{}` (không lỗi) khi thiếu dữ kiện để suy luận hoặc model không gọi
    được — đây là phần LÀM GIÀU, không phải phần cốt lõi của tool.
    """
    from .adapter import ModelRequest, get_adapter
    from .jsonx import extract_json

    context = _reasoning_context_lines(person, tp)
    if not context:
        return {}

    wanted = [f for f in fields if f in _ESTIMATE_FIELDS]
    if not wanted:
        return {}
    labels = "; ".join(f'"{f}" ({_ESTIMATE_FIELDS[f]})' for f in wanted)
    system = (
        "Bạn ƯỚC TÍNH field còn thiếu của một ứng viên từ dữ kiện CV đã có. "
        "KHÁC với trích xuất dữ liệu: ở đây bạn ĐƯỢC PHÉP tự do suy luận/phỏng "
        "đoán hợp lý (ví dụ chức danh 'Senior' thường ứng với nhiều năm kinh "
        "nghiệm hơn 'Fresher/Junior'; ngành và kỹ năng gợi ý ngành học). TUYỆT "
        "ĐỐI không bịa thêm dữ kiện ngoài danh sách được cấp — chỉ được suy "
        "luận TỪ chúng. Field nào không đủ căn cứ để đoán thì để null, đừng "
        "cố đoán bừa.\n"
        f"Trả về DUY NHẤT một JSON object, khoá là tên field trong [{labels}], "
        "mỗi giá trị là object {\"value\": số hoặc null, \"reasoning\": lý do "
        "ngắn 1-2 câu bằng tiếng Việt, \"confidence\": \"thấp\" hoặc \"trung bình\"}.")
    prompt = "Dữ kiện đã biết về ứng viên:\n" + "\n".join(f"- {line}" for line in context)
    try:
        resp = get_adapter().complete(ModelRequest(
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": prompt}],
            task="assistant_estimate_reasoning", temperature=0.2, max_tokens=500,
            response_format={"type": "json_object"},
            extra={"budget_seconds": 20, "reasoning_effort": "none"}))
    except Exception:                                  # noqa: BLE001
        return {}

    payload = extract_json(getattr(resp, "text", ""))
    if not isinstance(payload, dict):
        return {}

    out = {}
    for field in wanted:
        entry = payload.get(field)
        if not isinstance(entry, dict):
            continue
        value = entry.get("value")
        if value in (None, "", "null"):
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if field != "years_experience" or value == int(value):
            value = int(value)
        confidence = str(entry.get("confidence") or "thấp").strip().casefold()
        if confidence not in ("thấp", "trung bình"):
            confidence = "thấp"
        reasoning = str(entry.get("reasoning") or "").strip()[:300]
        out[field] = {
            "value": value, "method": "model_reasoning", "confidence": confidence,
            "basis": reasoning or "mô hình tự luận từ các dữ kiện CV khác",
        }
    return out


def estimate_profile_gaps(args, *, user, surface, context):
    """Ước tính field còn thiếu của MỘT Person — hai tầng, cả hai đều KHÔNG
    phải fact có bằng chứng:

    1. **Công thức** (`talent.estimate`) — tất định, chỉ chạy được khi có ĐÚNG
       một mốc thời gian khác (năm sinh hoặc năm tốt nghiệp) đã biết.
    2. **Model tự luận** (`_reason_missing_fields`) — chỉ chạy cho field tầng 1
       BỎ TRỐNG, cho model tự do suy đoán từ mọi dữ kiện khác (chức danh, kỹ
       năng, học vấn...). Không tất định — gắn nhãn "model_reasoning" và độ
       tin để câu trả lời phân biệt rõ với tầng 1.

    Field nào CV đã ghi trực tiếp thì để nguyên trong "known", KHÔNG bao giờ bị
    ghi đè bằng giá trị đoán ở bất kỳ tầng nào.
    """
    _require(user, roles.MODULE_TALENT)
    from intel.facts import current_facts
    from people.models import Person
    from talent import estimate

    pid = _int(args.get("person_id"), "person_id")
    person = Person.objects.filter(pk=pid, merged_into__isnull=True).first()
    if person is None:
        raise ToolError(f"không có Person #{pid} (hoặc đã hợp nhất)")

    def _known_year(field):
        fact = current_facts(person, field).first()
        if fact is None:
            return None
        return estimate.extract_year(fact.canonical_label or fact.raw_value)

    tp = getattr(person, "talent_profile", None)
    known = {
        "years_experience": getattr(tp, "years_experience", None),
        "graduation_year": _known_year("graduation_year"),
        "birth_year": _known_year("date_of_birth"),
    }

    estimated = {}
    if known["years_experience"] is None and known["graduation_year"] is not None:
        value = estimate.estimate_years_experience(known["graduation_year"])
        if value is not None:
            estimated["years_experience"] = {
                "value": value, "method": "formula", "confidence": "trung bình",
                "basis": f"năm hiện tại - năm tốt nghiệp ({known['graduation_year']})"}
    if known["graduation_year"] is None and known["birth_year"] is not None:
        value = estimate.estimate_graduation_year(known["birth_year"])
        if value is not None:
            estimated["graduation_year"] = {
                "value": value, "method": "formula", "confidence": "trung bình",
                "basis": f"năm sinh ({known['birth_year']}) + tuổi tốt nghiệp trung bình "
                         f"({estimate.TYPICAL_GRADUATION_AGE})"}
    if known["birth_year"] is None and known["graduation_year"] is not None:
        value = estimate.estimate_birth_year(known["graduation_year"])
        if value is not None:
            estimated["birth_year"] = {
                "value": value, "method": "formula", "confidence": "trung bình",
                "basis": f"năm tốt nghiệp ({known['graduation_year']}) - tuổi tốt nghiệp "
                         f"trung bình ({estimate.TYPICAL_GRADUATION_AGE})"}

    still_missing = [f for f in _ESTIMATE_FIELDS
                     if known[f] is None and f not in estimated]
    if still_missing:
        estimated.update(_reason_missing_fields(person, tp, still_missing))

    return {
        "person_id": pid, "display_name": person.display_name or f"Person #{pid}",
        "known": known,
        "estimated": estimated,
        "note": ("Không đủ dữ kiện (mốc thời gian khác, chức danh, kỹ năng...) để "
                 "ước tính thêm field nào." if not estimated else ""),
        "disclaimer": ("Giá trị trong 'estimated' KHÔNG PHẢI dữ liệu có bằng chứng "
                       "trích dẫn từ CV. method='formula' là suy luận toán học từ một "
                       "mốc thời gian khác đã biết (đáng tin hơn); method='model_reasoning' "
                       "là model TỰ DO phỏng đoán từ dữ kiện gián tiếp (chức danh, kỹ "
                       "năng...) — kém chắc chắn hơn, có thể ra kết quả khác ở lượt hỏi "
                       "khác. Khi trả lời, LUÔN nói rõ đây là ước tính và mức độ tin cậy "
                       "tương ứng (ví dụ 'ước tính khoảng X năm kinh nghiệm, suy từ năm "
                       "tốt nghiệp' cho formula, hoặc 'phỏng đoán chưa chắc chắn, dựa "
                       "trên chức danh hiện tại' cho model_reasoning) — không trình bày "
                       "như một dữ kiện đã xác nhận."),
    }


def _chan_gui_nguoi_ra_ngoai(chuoi):
    """Luật TẤT ĐỊNH chặn dữ liệu người rời khỏi hệ thống qua đường tra web.

    `enrich_company_from_web` là đường ra ngoài DUY NHẤT mà agent tự bấm được:
    không cần ai click, nó gửi thẳng một chuỗi sang dịch vụ tìm kiếm bên thứ ba.
    Mọi tool khác chỉ đọc, hoặc ghi ở trạng thái chờ người duyệt.

    Trước đây chuỗi ấy không bị ràng buộc gì ngoài độ dài ≥ 2. Mô hình được đặt
    tên tham số là `company` nhưng không có gì bắt nó phải là tên công ty — một
    lượt bị dụ, hoặc chỉ là một lượt lẫn lộn, là tên ứng viên bay sang máy chủ
    tìm kiếm. Ở ngân hàng thì đó là sự cố dữ liệu cá nhân thật, và là loại không
    rút lại được: đã gửi đi rồi thì bên kia đã ghi log.

    `docs/AI_AGENT_ACCEPTANCE_CRITERIA.md` §1 cửa #2 đòi mỗi hành động có hậu
    quả phải qua **người bấm HOẶC luật tất định**. Không có người bấm ở đây, nên
    phải là luật — và luật thì nằm trong code, không nằm trong lời dặn prompt.
    """
    from accounts.privacy import _EMAIL_IN_TEXT, _PHONE_IN_TEXT

    if _EMAIL_IN_TEXT.search(chuoi) or _PHONE_IN_TEXT.search(chuoi):
        raise ToolError("không gửi email/số điện thoại ra dịch vụ ngoài")

    # Tên trùng người trong kho thì dừng. Công ty Việt Nam đôi khi mang tên
    # người sáng lập, nên đây có thể chặn nhầm — chấp nhận: chặn nhầm thì mô
    # hình hỏi lại bằng tên đầy đủ hơn, gửi nhầm thì không lấy lại được.
    from people.models import Person

    gon = " ".join(chuoi.split()).casefold()
    if Person.objects.filter(display_name__iexact=gon).exists():
        raise ToolError(
            f"“{chuoi}” trùng tên một người trong kho — không tra tên người "
            "trên dịch vụ ngoài. Nếu đây là tên công ty, hãy ghi đầy đủ hơn "
            "(kèm 'Công ty', 'JSC', 'Ltd'…).")


def enrich_company_from_web(args, *, user, surface, context):
    _require(user, roles.MODULE_TALENT)
    from . import websearch

    company = str(args.get("company") or "").strip()
    if len(company) < 2:
        raise ToolError("'company' quá ngắn")
    _chan_gui_nguoi_ra_ngoai(company)
    if not websearch.enabled():
        raise ToolError("web search chưa bật (ASSISTANT_WEB_SEARCH) hoặc thiếu backend")
    focus = str(args.get("focus") or "").strip()
    query = (f"Thông tin công khai về công ty {company}"
             + (f", tập trung: {focus}" if focus else "")
             + " (quy mô, ngành, tin gần đây)")
    try:
        res = websearch.web_answer(
            query, system="Tóm tắt ngắn gọn thông tin công khai về công ty, "
                          "nêu mốc thời gian, chỉ dựa trên nguồn tìm được.")
    except websearch.WebSearchUnavailable as exc:
        raise ToolError(f"tra web thất bại: {exc}")
    return {"company": company, "summary": res.text[:2000],
            "sources": res.citations[:6], "provider": res.provider}


HANDLERS = {
    "read_allowed_evidence": read_allowed_evidence,
    "remember_proposal": remember_proposal,
    "feedback": feedback,
    "compare_candidates": compare_candidates,
    "canonical_lookup": canonical_lookup,
    "fact_provenance": fact_provenance,
    "aggregate_corpus": aggregate_corpus,
    "match_candidate_job": match_candidate_job,
    "person_activity": person_activity,
    "estimate_profile_gaps": estimate_profile_gaps,
    "draft_outreach": draft_outreach,
    "enrich_company_from_web": enrich_company_from_web,
}
