"""Internal adapter from the existing Talent surface to Intelligence V2."""
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings

from accounts import roles
from knowledge.models import KnowledgeDocument
from people.models import Person

from .answer.engine import AnswerResult
from .intelligence_views import issue_scope_token


class IntelligenceV2Error(RuntimeError):
    pass


MAX_SEARCH_QUERIES = 4
RRF_K = 60


def _post(payload, opener=urllib.request.urlopen, *, path="/v1/answer", timeout=None):
    base = settings.INTELLIGENCE_BASE_URL.rstrip("/")
    token = settings.INTELLIGENCE_SERVICE_TOKEN
    if not base or not token:
        raise IntelligenceV2Error("Intelligence V2 is not configured")
    request = urllib.request.Request(
        base + path, data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST", headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"})
    try:
        with opener(request, timeout=timeout or settings.INTELLIGENCE_REQUEST_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise IntelligenceV2Error(f"Intelligence V2 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise IntelligenceV2Error("Intelligence V2 unavailable or malformed") from exc


def _knowledge_ids_for(user):
    """Negative radar_entity_ids this user's role may see (knowledge/models.py).

    Empty unless the user has MODULE_KNOWLEDGE — Intelligence's own
    SearchRequest/AnswerRequest.knowledge_ids defaults to "none", and
    evidence_document re-checks the same module at citation-resolution time,
    so passing an id here without the module grants nothing by itself; this
    just avoids asking for ids that would only be denied anyway.
    """
    if not roles.can_access(user, roles.MODULE_KNOWLEDGE):
        return []
    return [str(-pk) for pk in
            KnowledgeDocument.objects.filter(is_active=True).values_list("pk", flat=True)]


def _resolve_names(person_ids):
    """person_id > 0 -> people.Person.display_name; < 0 -> KnowledgeDocument.title.

    The two id spaces never overlap (Django pks are always positive), so a
    single dict merge is safe.
    """
    positive_ids = {pid for pid in person_ids if pid > 0}
    negative_ids = {pid for pid in person_ids if pid < 0}
    names = dict(Person.objects.filter(pk__in=positive_ids).values_list("pk", "display_name"))
    if negative_ids:
        names.update({
            -pk: title for pk, title in KnowledgeDocument.objects.filter(
                pk__in=[-pid for pid in negative_ids]).values_list("pk", "title")
        })
    return names


#: Ngữ cảnh tri thức nội bộ chèn vào một lượt hội thoại. Giữ nhỏ và có hạn giờ
#: riêng: đây nằm trên đường nóng của chat, không được phép kéo dài một lượt.
KNOWLEDGE_CONTEXT_LIMIT = 3
KNOWLEDGE_SNIPPET_CHARS = 1200
KNOWLEDGE_TIMEOUT_SECONDS = 3.0


def knowledge_search(user, question, *, limit=KNOWLEDGE_CONTEXT_LIMIT,
                     opener=urllib.request.urlopen):
    """[(nhãn, trích đoạn)] tài liệu nội bộ liên quan; [] nếu user không có quyền.

    `knowledge_only=True` nên KHÔNG có hồ sơ ứng viên nào lọt vào đây: một CV
    tình cờ nhắc "quy trình nghỉ phép" không được đọc ngược thành chính sách
    của công ty.

    RÀNG BUỘC ĐANG CÓ: `issue_scope_token` đi qua `validate_scope`, vốn đòi
    MODULE_TALENT + `can_read_cv`. Nên người CHỈ có MODULE_KNOWLEDGE sẽ bị từ
    chối và hàm này trả [] một cách im lặng. Mặc định không ai rơi vào ô đó
    (chỉ ADMIN có MODULE_KNOWLEDGE, và ADMIN có cả MODULE_TALENT); nhưng nếu
    Admin cấp `knowledge` cho một vai trò không có `talent`, phải mở rộng
    `validate_scope` bằng một tuyên bố scope RIÊNG — không nới lỏng tuyên bố
    "all_applicants" hiện tại, vì như thế là cấp luôn quyền đọc kho ứng viên.
    """
    knowledge_ids = _knowledge_ids_for(user)
    if not knowledge_ids:
        return []
    payload = _post({
        "query": question,
        "scope_token": issue_scope_token(user),
        "principal_id": str(user.pk),
        "filters": {},
        "limit": max(1, min(20, int(limit))),
        "knowledge_ids": knowledge_ids,
        "knowledge_only": True,
    }, opener=opener, path="/v1/search", timeout=KNOWLEDGE_TIMEOUT_SECONDS)

    hits = payload.get("hits") or []
    person_ids = {int(row["person"]["person_id"]) for row in hits
                  if (row.get("person") or {}).get("person_id")}
    names = _resolve_names(person_ids)
    sources = []
    for row in hits[:limit]:
        identity = int(row["person"]["person_id"])
        text = "\n".join(str(item.get("text") or "") for item in (row.get("evidence") or []))
        text = text.strip()[:KNOWLEDGE_SNIPPET_CHARS]
        if text:
            sources.append((names.get(identity) or f"Tài liệu nội bộ #{-identity}", text))
    return sources


def answer(user, question, *, conversation_id="", opener=urllib.request.urlopen):
    payload = _post({
        "question": question,
        "scope_token": issue_scope_token(user),
        "principal_id": str(user.pk),
        "thread_id": conversation_id or None,
        "knowledge_ids": _knowledge_ids_for(user),
    }, opener=opener)
    try:
        evidence = payload["evidence"]
        people_payload = payload["people"]
        trace_rows = payload.get("trace") or []
        person_ids = {int(row["person_id"]) for row in people_payload}
        names = _resolve_names(person_ids)
        citations = []
        for number, row in enumerate(evidence, 1):
            person_id = int(row["person_id"])
            location = str(row.get("location") or "")
            ordinal = int(location.split()[-1]) + 1 if location.startswith("chunk ") else 1
            citations.append({
                "n": number, "person_id": person_id,
                "name": names.get(person_id, ""),
                "document_id": int(row["document_id"]), "ordinal": ordinal,
                "snippet": str(row["text"]),
            })
        people = [{
            "person_id": person_id, "name": names.get(person_id, ""), "why": "",
            "attributes": {}, "citations": [row["n"] for row in citations
                                                if row["person_id"] == person_id],
        } for person_id in sorted(person_ids)]
        first_trace = trace_rows[0] if trace_rows else {}
        return AnswerResult(
            text=str(payload["answer"]), sources=citations, all_sources=citations,
            people=people, provider=str(first_trace.get("provider") or "intelligence-v2"),
            model=str(first_trace.get("model_alias") or ""),
            trace={"engine": "intelligence-v2", "model_trace": trace_rows,
                   "interpreted_query": payload.get("interpreted_query") or {}},
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise IntelligenceV2Error("Intelligence V2 response cannot be adapted") from exc


def _search_queries(query_plan):
    values = [str(getattr(query_plan, "information_need", "") or "").strip()]
    values.extend(str(value or "").strip()
                  for value in (getattr(query_plan, "search_queries", []) or []))
    return list(dict.fromkeys(value for value in values if value))[:MAX_SEARCH_QUERIES]


def _fuse_search_payloads(payloads, limit):
    """Fuse independently retrieved query variants by person using RRF."""
    grouped = {}
    for payload in payloads:
        for rank, hit in enumerate(payload.get("hits") or [], start=1):
            person = hit.get("person") or {}
            person_id = str(person.get("person_id") or "").strip()
            if not person_id:
                continue
            row = grouped.setdefault(person_id, {
                "person": person, "score": 0.0, "matched_filters": [],
                "evidence": [], "_evidence_ids": set(),
            })
            row["score"] += 1.0 / (RRF_K + rank)
            row["matched_filters"] = list(dict.fromkeys(
                row["matched_filters"] + list(hit.get("matched_filters") or [])))
            for evidence in hit.get("evidence") or []:
                evidence_id = str(evidence.get("evidence_id") or "") or json.dumps(
                    [evidence.get("document_id"), evidence.get("location"),
                     evidence.get("text")], ensure_ascii=False)
                if evidence_id not in row["_evidence_ids"]:
                    row["_evidence_ids"].add(evidence_id)
                    row["evidence"].append(evidence)
    ordered = sorted(grouped.values(), key=lambda row: (
        -row["score"], str(row["person"].get("person_id") or "")))[:limit]
    ceiling = len(payloads) / (RRF_K + 1) if payloads else 1.0
    for row in ordered:
        row["score"] = min(1.0, row["score"] / ceiling)
        row["evidence"] = row["evidence"][:4]
        row.pop("_evidence_ids", None)
    return {"hits": ordered}


def retrieve(user, query_plan, *, limit=60, conversation_id="",
             opener=urllib.request.urlopen):
    """Use Intelligence V2/Haystack for stage ② of the established pipeline.

    Intelligence owns retrieval; Product Core still owns intent planning,
    deterministic constraints, dossier judging, conversation and presentation.
    This boundary avoids turning greetings and actions into corpus questions.
    """
    from .answer.retrieve import Candidate, Passage, clean_passage

    queries = _search_queries(query_plan)
    if not queries:
        return []
    bounded_limit = max(1, min(100, int(limit)))
    scope_token = issue_scope_token(user)

    def search(query):
        return _post({
            "query": query, "scope_token": scope_token,
            "principal_id": str(user.pk), "filters": {},
            "limit": bounded_limit, "thread_id": conversation_id or None,
        }, opener=opener, path="/v1/search")

    if len(queries) == 1:
        payload = search(queries[0])
    else:
        with ThreadPoolExecutor(max_workers=len(queries)) as workers:
            futures = [workers.submit(search, query) for query in queries]
            payloads = []
            last_error = None
            for future in as_completed(futures):
                try:
                    payloads.append(future.result())
                except IntelligenceV2Error as exc:
                    last_error = exc
            if not payloads:
                raise last_error or IntelligenceV2Error("All query variants failed")
            payload = _fuse_search_payloads(payloads, bounded_limit)
    try:
        hits = payload["hits"]
        person_ids = {int(row["person"]["person_id"]) for row in hits}
        # retrieve() feeds the candidate dossier pipeline only; it deliberately
        # never sends knowledge_ids, so a negative id should not appear here.
        # _resolve_names stays defensive rather than assuming that holds.
        names = _resolve_names(person_ids)
        candidates = []
        for row in hits:
            person_id = int(row["person"]["person_id"])
            passages = []
            for evidence in row.get("evidence") or []:
                location = str(evidence.get("location") or "")
                ordinal = int(location.split()[-1]) if location.startswith("chunk ") else 0
                passages.append(Passage(
                    person_id=person_id,
                    document_id=int(evidence["document_id"]),
                    ordinal=ordinal,
                    text=clean_passage(evidence["text"]),
                    source=str(evidence.get("source") or "cv"),
                ))
            if passages:
                candidates.append(Candidate(
                    person_id=person_id,
                    name=names.get(person_id) or str(row["person"].get("display_name") or f"#{person_id}"),
                    score=float(row.get("score") or 0),
                    hits=max(1, len(row.get("matched_filters") or [])),
                    passages=passages,
                ))
        return candidates
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise IntelligenceV2Error("Intelligence V2 search response cannot be adapted") from exc
