# -*- coding: utf-8 -*-
"""Nhớ lại kết quả ②③④ cho câu hỏi đã gặp.

Đo trên kho thật: mỗi lượt hỏi tốn ~38.700 token nạp vào + 6 lượt gọi model, và
**③ chiếm 75%** trong đó. Hỏi lại đúng một câu là trả lại toàn bộ số đó.

Cắt ở ranh giới ②③④ chứ không phải cả lượt:

* ② tất định với cùng bộ truy vấn; ③ chạy ở `temperature=0.1` nên gần như tất
  định; ④ là CODE thuần.
* ⑤ thì **không** cache: nó phụ thuộc lịch sử hội thoại và những điều người dùng
  đã dặn, nên cùng một danh sách người vẫn phải viết lại cho đúng ngữ cảnh lượt
  này. Chỉ cache ⑤ mới là chỗ người dùng nhận ra câu trả lời "bị lặp".

Khoá gồm **vân tay kho**, nên thêm/sửa hồ sơ là mọi mục cũ tự hết hiệu lực —
không cần ai nhớ đi xoá cache sau khi nhập dữ liệu.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading

from django.core.cache import cache

from .judge import Judgement

log = logging.getLogger(__name__)

#: 6 giờ. Vân tay kho đã lo phần dữ liệu đổi; TTL chỉ để dọn rác và để một lần
#: ③ phán đoán lệch không đóng đinh vĩnh viễn.
TTL_SECONDS = 6 * 3600
PREFIX = "answer:pipeline:v2"
_execution_cache = {"marker": None, "value": ""}
_execution_lock = threading.Lock()


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, default=str,
        separators=(",", ":")).encode("utf-8")).hexdigest()[:24]


def execution_fingerprint():
    """Semantic inputs of cached retrieval/judgement, without credentials.

    Cache entries survive process restarts and deployments. The corpus alone is
    insufficient: changing the planner/judge prompt or effective task route can
    otherwise serve an answer produced under an older contract for six hours.
    """
    try:
        from ai.models import ProviderConfig
        from ai.router import get_router
        from talent.answer import judge, plan

        router = get_router()
        router.maybe_refresh()
        prompt_hashes = {
            "plan": hashlib.sha256(plan.SYSTEM.encode("utf-8")).hexdigest(),
            "judge": hashlib.sha256(judge.SYSTEM.encode("utf-8")).hexdigest(),
        }
        # Environment is process-static in deployment. Hash only routing fields;
        # never retain API keys, tokens, secrets or passwords in the marker.
        env_routes = {key: value for key, value in router.env.items()
                      if key.startswith("MSB_AI_")
                      and any(part in key for part in ("PROVIDER", "MODEL", "BASE_URL"))
                      and not any(secret in key for secret in ("KEY", "TOKEN", "SECRET", "PASSWORD"))}
        marker = (id(router), getattr(router, "_config_stamp", None),
                  _digest(prompt_hashes), _digest(env_routes))
        with _execution_lock:
            if _execution_cache["marker"] == marker:
                return _execution_cache["value"]
        tasks = (plan.TASK, judge.TASK, "talent_embedding")
        routes = []
        providers = set()
        for task in tasks:
            config = router.effective_config(task)
            order = router.provider_order(task)
            providers.update(order)
            routes.append({
                "task": task,
                "provider": config.get("provider", ""),
                "model": config.get("model", ""),
                "source": config.get("config_source", ""),
                "order": order,
            })
        # Models of fallback providers also affect a result when the first route
        # is unavailable. Never include encrypted keys or key hints.
        fallback_models = list(ProviderConfig.objects.filter(provider__in=providers)
                               .order_by("provider")
                               .values("provider", "enabled", "priority", "base_url", "model"))
        value = _digest({
            "prompts": prompt_hashes,
            "routes": routes,
            "fallback_models": fallback_models,
        })
        with _execution_lock:
            _execution_cache.update(marker=marker, value=value)
        return value
    except Exception:                              # noqa: BLE001 - migration/startup edge
        log.warning("answer.cache: không lấy được dấu thực thi, bỏ qua cache",
                    exc_info=True)
        return ""


def permission_fingerprint(user):
    """Current identity/role/module scope of this user, never profile or PII."""
    if user is None:
        return _digest({"user": None})
    try:
        from accounts import roles
        user_roles = roles.roles_of(user)
        overrides = roles.role_module_overrides()
        modules = set()
        for role in user_roles:
            modules |= roles.modules_for_role(role, overrides)
        return _digest({
            "authenticated": bool(getattr(user, "is_authenticated", False)),
            "active": bool(getattr(user, "is_active", False)),
            "superuser": bool(getattr(user, "is_superuser", False)),
            "roles": sorted(user_roles),
            "modules": sorted(modules),
        })
    except Exception:                              # noqa: BLE001
        log.warning("answer.cache: không lấy được dấu quyền, bỏ qua cache",
                    exc_info=True)
        return ""


def corpus_fingerprint():
    """Vân tay rẻ của kho — đổi khi có hồ sơ mới hoặc đoạn CV được lập lại chỉ mục.

    `PersonSearchDocument` mốc thời gian tên là `indexed_at`, `CVChunk` là
    `updated_at` — hai bảng đặt tên khác nhau, và gọi nhầm tên thì `aggregate`
    ném lỗi. Trước đây khối `except` nuốt lỗi đó và trả "", tức **âm thầm tắt
    cache** mà không ai biết: đúng kiểu hỏng khó phát hiện nhất, vì mọi thứ vẫn
    chạy, chỉ là đắt gấp đôi.
    """
    from django.db.models import Count, Max

    from people.models import Document, Person
    from talent.models import CVChunk, PersonSearchDocument
    try:
        people = Person.applicants()
        persons = people.aggregate(n=Count("id"), at=Max("updated_at"))
        raw_documents = Document.objects.filter(person__in=people).aggregate(
            n=Count("id"), at=Max("updated_at"))
        docs = PersonSearchDocument.objects.filter(person__in=people).aggregate(
            n=Count("id"), at=Max("indexed_at"))
        chunks = CVChunk.objects.filter(person__in=people).aggregate(
            n=Count("id"), at=Max("updated_at"))
    except Exception:                              # noqa: BLE001
        log.warning("answer.cache: không lấy được vân tay kho, bỏ qua cache",
                    exc_info=True)
        return ""
    return _digest({"people": persons, "documents": raw_documents,
                    "search_documents": docs, "chunks": chunks})


def _context_marker(envelope):
    """Dấu ngữ cảnh: danh sách người của lượt trước.

    Cùng một câu chữ ("so sánh hai người đầu") nghĩa khác nhau tuỳ danh sách
    đang nói tới, nên nó phải nằm trong khoá.
    """
    projection = getattr(envelope, "projection", None)
    last = dict(getattr(projection, "last_result", None) or {}) if projection else {}
    ids = [item.get("id") or item.get("person_id")
           for item in (last.get("items") or [])]
    # Order is part of identity: [A, B] and [B, A] resolve "second" differently.
    return {"people": [str(i) for i in ids if i],
            "criteria": getattr(projection, "active_criteria", {}) or {},
            "patches": getattr(projection, "constraint_patches", []) or [],
            "mentioned": getattr(projection, "mentioned_ids", []) or [],
            "memories": getattr(projection, "memories", []) or [],
            "summary": getattr(projection, "summary", "") or "",
            "recent": getattr(projection, "recent_turns", []) or []}


def _plan_marker(query_plan):
    """Normalized inputs that can change retrieval or judgement."""
    if query_plan is None:
        return {}

    def text(value):
        return " ".join(str(value or "").split()).casefold()

    def items(values):
        return sorted(set(filter(None, (text(v) for v in (values or [])))))

    sort_by = getattr(query_plan, "sort_by", None) or {}
    return {
        "shape": text(getattr(query_plan, "shape", "")),
        "need": text(getattr(query_plan, "information_need", "")),
        "must": items(getattr(query_plan, "must_have", [])),
        "should": items(getattr(query_plan, "should_have", [])),
        "extract": items(getattr(query_plan, "extract", [])),
        "queries": items(getattr(query_plan, "search_queries", [])),
        # limit changes retrieve.pool_for(), so it is not merely presentation.
        "limit": int(getattr(query_plan, "limit", 0) or 0),
        "sort": {"key": text(sort_by.get("key")), "dir": text(sort_by.get("dir"))}
                if sort_by else None,
    }


def key_for(question, *, envelope=None, user=None, query_plan=None):
    """Khoá cache, hoặc None nếu lượt này không nên cache.

    Câu người dùng ổn định là neo chính. Kế hoạch đã chuẩn hoá cũng nằm trong
    khoá vì ②③ thực thi chính các điều kiện/truy vấn đó. Danh sách được sắp và
    chuẩn hoá khoảng trắng/chữ hoa để khác biệt trình bày không phá cache; khác
    điều kiện hoặc hướng truy hồi thì bắt buộc đọc lại.

    `limit` nằm trong dấu vì nó đổi kích thước pool truy hồi; `extract`/`sort_by`
    đổi dữ kiện ③ phải bóc. Chỉ `next_steps` nằm ngoài vì hành động chạy sau cache.

    Khoá cũng gồm:

    * **người hỏi** — để hai tài khoản không bao giờ dùng chung một mục cache.

      Nói cho đúng: hôm nay ② KHÔNG lọc theo quyền, và đó là đúng thiết kế —
      phân quyền ở đây là cấp module (`roles.can_access`), tức "vào được phòng
      nào", không phải "thấy được dòng nào". Ai vào được Talent thì thấy cùng
      một kho. Chiều theo-người-dùng nằm ở chỗ khác: hạn mức mở khoá liên hệ
      (`accounts.privacy.unlock`).

      Nên khoá theo người hỏi ở đây là lưới đỡ phòng xa, không phải hệ quả của
      một bộ lọc đang có. Ghi rõ vì bản trước viết "② lọc theo quyền" — một câu
      khẳng định không có mã nào đỡ, và người đọc sau sẽ tin là đã có lọc rồi
      không đi kiểm. Nếu sau này thêm lọc cấp dòng thật, sửa lại đoạn này;

    * **vân tay kho** — thêm hồ sơ là mọi mục cũ tự hết hiệu lực;
    * **dấu ngữ cảnh** — câu hỏi tiếp phụ thuộc danh sách lượt trước.
    """
    fingerprint = corpus_fingerprint()
    execution = execution_fingerprint()
    permission = permission_fingerprint(user)
    if not fingerprint or not execution or not permission:
        return None
    normalized = " ".join(str(question or "").split()).lower()
    if not normalized:
        return None
    payload = {
        "q": normalized,
        "plan": _plan_marker(query_plan),
        "corpus": fingerprint,
        "execution": execution,
        "permission": permission,
        "user": getattr(user, "pk", None),
        "context": _context_marker(envelope),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:40]
    return f"{PREFIX}:{digest}"


def _as_judgement(row):
    return Judgement(
        person_id=row["person_id"], name=row.get("name", ""),
        relevant=row.get("relevant", False), confidence=row.get("confidence", 0.0),
        why=row.get("why", ""), evidence=row.get("evidence") or [],
        extracted=row.get("extracted") or {}, gap=row.get("gap", ""),
        attribute_status=row.get("attribute_status") or {}, criteria=row.get("criteria") or [])


def load(key):
    """Trả `(judgements, retrieved)` đã lưu, hoặc None.

    Lưu ở mức ③ (phán đoán từng người) chứ không phải sau ④. ④ là CODE thuần và
    chạy tức thì, nên chạy lại nó với `limit`/`sort_by` của LƯỢT NÀY vừa đúng
    hơn vừa cho tỉ lệ trúng cao hơn: cùng một câu hỏi mà lần này xin 5 người,
    lần trước xin 10, vẫn dùng chung được phần đắt tiền.
    """
    if not key:
        return None
    try:
        blob = cache.get(key)
    except Exception as exc:                       # noqa: BLE001
        log.warning("answer.cache: đọc hỏng: %s", exc)
        return None
    if not blob:
        return None
    try:
        return ([_as_judgement(r) for r in blob["judgements"]],
                int(blob.get("retrieved") or 0))
    except Exception:                              # noqa: BLE001
        log.warning("answer.cache: mục hỏng khuôn, bỏ qua")
        return None


def save(key, judgements, retrieved):
    if not key:
        return
    try:
        cache.set(key, {
            "judgements": [j.as_dict() for j in judgements],
            "retrieved": int(retrieved),
        }, TTL_SECONDS)
    except Exception as exc:                       # noqa: BLE001
        # Cache hỏng không được làm hỏng lượt trả lời.
        log.warning("answer.cache: ghi hỏng: %s", exc)
