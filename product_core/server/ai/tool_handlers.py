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
    "draft_outreach": draft_outreach,
    "enrich_company_from_web": enrich_company_from_web,
}
