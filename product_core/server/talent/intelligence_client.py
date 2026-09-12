"""Internal adapter from the existing Talent surface to Intelligence V2."""
import json
import urllib.error
import urllib.request

from django.conf import settings

from people.models import Person

from .answer.engine import AnswerResult
from .intelligence_views import issue_scope_token


class IntelligenceV2Error(RuntimeError):
    pass


def _post(payload, opener=urllib.request.urlopen):
    base = settings.INTELLIGENCE_BASE_URL.rstrip("/")
    token = settings.INTELLIGENCE_SERVICE_TOKEN
    if not base or not token:
        raise IntelligenceV2Error("Intelligence V2 is not configured")
    request = urllib.request.Request(
        base + "/v1/answer", data=json.dumps(payload, ensure_ascii=False).encode(),
        method="POST", headers={"Authorization": f"Bearer {token}",
                                "Content-Type": "application/json"})
    try:
        with opener(request, timeout=settings.INTELLIGENCE_REQUEST_TIMEOUT_SECONDS) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise IntelligenceV2Error(f"Intelligence V2 HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise IntelligenceV2Error("Intelligence V2 unavailable or malformed") from exc


def answer(user, question, *, conversation_id="", opener=urllib.request.urlopen):
    payload = _post({
        "question": question,
        "scope_token": issue_scope_token(user),
        "principal_id": str(user.pk),
        "thread_id": conversation_id or None,
    }, opener=opener)
    try:
        evidence = payload["evidence"]
        people_payload = payload["people"]
        trace_rows = payload.get("trace") or []
        person_ids = {int(row["person_id"]) for row in people_payload}
        names = dict(Person.objects.filter(pk__in=person_ids).values_list("pk", "display_name"))
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
