# -*- coding: utf-8 -*-
"""Scale-safe Talent search contracts used behind SEARCH_* feature flags.

This module deliberately separates deterministic store filtering from semantic
judgement.  It never loads the whole population into Python and never treats an
LLM top-k as the population boundary.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

from django.db import transaction
from django.db.models import Q

from people.normalize import normalize_name
from people.models import Person

from .models import (BaseDossier, CandidateSetMember, CandidateSetRun,
                     ConstraintJudgementCache, SearchProjection)

PLAN_VERSION = 2
DOSSIER_VERSION = 1
SCHEMA_VERSION = 1
ALLOWED_DOMAINS = {"TALENT", "CUSTOMER", "BOTH", "GENERAL", "CLARIFY"}
ALLOWED_KINDS = {"term", "range", "temporal", "geo"}
ALLOWED_OPS = {"eq", "contains", "gte", "lte", "between", "before", "after"}
BOOLEAN_OPS = {"and", "or", "not"}
CONSTRAINT_CLASSES = {"HARD_DETERMINISTIC", "HARD_SEMANTIC", "PREFERENCE"}
MAX_BOOLEAN_DEPTH = 8
MAX_BOOLEAN_LEAVES = 50


def _hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def canonical(value) -> str:
    return normalize_name(str(value or "")).strip()


GEO_ALIASES = {"hanoi": "ha noi", "hn": "ha noi", "hochiminh": "ho chi minh",
               "hcm": "ho chi minh", "saigon": "ho chi minh", "sg": "ho chi minh"}
TERM_ALIASES = {
    "data analyst": ("data analyst", "chuyen vien phan tich du lieu", "phan tich du lieu"),
    "relationship manager": ("relationship manager", "quan he khach hang", "rm"),
    "accountant": ("accountant", "ke toan"),
    "college": ("college", "cao dang"),
}


@dataclass(frozen=True)
class Constraint:
    field: str
    value: object
    kind: str = "term"
    op: str = "contains"
    provenance: str = "user"
    classification: str = "HARD_DETERMINISTIC"
    constraint_id: str = ""

    def __post_init__(self):
        if self.kind not in ALLOWED_KINDS or self.op not in ALLOWED_OPS:
            raise ValueError(f"Unsupported constraint {self.kind}/{self.op}")
        classification = str(self.classification or "").upper()
        if classification not in CONSTRAINT_CLASSES:
            raise ValueError(f"Unsupported constraint class {self.classification}")
        object.__setattr__(self, "classification", classification)
        if not self.field or self.value in (None, "", []):
            raise ValueError("Constraint requires field and value")
        if not self.constraint_id:
            object.__setattr__(self, "constraint_id", _hash(
                [self.field, self.kind, self.op, self.value,
                 self.classification])[:16])

    def as_dict(self):
        return asdict(self)


@dataclass
class RadarTurnPlan:
    domain: str = "TALENT"
    query_type: str = "list"
    must: list[Constraint] = field(default_factory=list)
    prefer: list[Constraint] = field(default_factory=list)
    exclude: list[Constraint] = field(default_factory=list)
    where: dict | None = None
    semantic_concepts: list[str] = field(default_factory=list)
    exhaustive: bool = False
    version: int = PLAN_VERSION

    def __post_init__(self):
        self.domain = str(self.domain).upper()
        if self.domain not in ALLOWED_DOMAINS:
            raise ValueError(f"Unsupported domain {self.domain}")
        if self.query_type not in {"list", "count", "aggregate", "compare"}:
            raise ValueError(f"Unsupported query type {self.query_type}")
        if self.where is not None:
            self.where = normalize_boolean_ast(self.where)

    def as_dict(self):
        result = asdict(self)
        result["must"] = [row.as_dict() for row in self.must]
        result["prefer"] = [row.as_dict() for row in self.prefer]
        result["exclude"] = [row.as_dict() for row in self.exclude]
        result["where"] = self.where
        return result

    @classmethod
    def from_dict(cls, raw):
        raw = dict(raw or {})
        for key in ("must", "prefer", "exclude"):
            raw[key] = [row if isinstance(row, Constraint) else Constraint(**row)
                        for row in raw.get(key, [])]
        return cls(**raw)


def normalize_boolean_ast(raw, *, _depth=0, _counter=None):
    """Validate/canonicalize nested AND/OR/NOT without evaluating user code."""
    if _counter is None:
        _counter = [0]
    if _depth > MAX_BOOLEAN_DEPTH:
        raise ValueError(f"Boolean AST exceeds depth {MAX_BOOLEAN_DEPTH}")
    if not isinstance(raw, dict):
        raise ValueError("Boolean AST node must be an object")
    if set(raw) == {"constraint"}:
        return normalize_boolean_ast(raw["constraint"], _depth=_depth,
                                     _counter=_counter)
    if "field" in raw:
        allowed = {"field", "value", "kind", "op", "provenance",
                   "classification", "constraint_id"}
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unsupported constraint fields: {sorted(unknown)}")
        _counter[0] += 1
        if _counter[0] > MAX_BOOLEAN_LEAVES:
            raise ValueError(f"Boolean AST exceeds {MAX_BOOLEAN_LEAVES} leaves")
        constraint = Constraint(**raw)
        if constraint.classification != "HARD_DETERMINISTIC":
            raise ValueError("Boolean where only accepts HARD_DETERMINISTIC constraints")
        return {"constraint": constraint.as_dict()}
    if set(raw) != {"op", "children"}:
        raise ValueError("Boolean node requires exactly op and children")
    op = str(raw.get("op") or "").lower()
    children = raw.get("children")
    if op not in BOOLEAN_OPS or not isinstance(children, list) or not children:
        raise ValueError("Boolean op must be and/or/not with non-empty children")
    if op == "not" and len(children) != 1:
        raise ValueError("Boolean NOT requires exactly one child")
    return {"op": op, "children": [normalize_boolean_ast(
        child, _depth=_depth + 1, _counter=_counter) for child in children]}


def from_legacy_plan(plan):
    """Lossless-enough bridge for shadowing the current Talent planner."""
    shape = getattr(plan, "shape", "find_people")
    query_type = {"count": "count", "compare": "compare",
                  "analyze": "aggregate"}.get(shape, "list")
    must = [Constraint("search_text", value, provenance="legacy.must_have",
                       classification="HARD_SEMANTIC")
            for value in (getattr(plan, "must_have", None) or [])]
    prefer = [Constraint("search_text", value, provenance="legacy.should_have",
                         classification="PREFERENCE")
              for value in (getattr(plan, "should_have", None) or [])]
    return RadarTurnPlan(domain="TALENT", query_type=query_type, must=must,
                         prefer=prefer,
                         semantic_concepts=list(getattr(plan, "search_queries", None) or []),
                         exhaustive=False)


FIELD_MAP = {
    "title": "title_norm", "company": "company_norm", "location": "location_norm",
    "education": "education_norm", "skill": "skills_norm", "skills": "skills_norm",
    "industry": "industries_norm", "industries": "industries_norm",
    "years_experience": "years_experience", "application_date": "last_application_at",
    "application_position": "application_positions", "source": "source_channels",
    "search_text": "searchable_text",
}


def _condition(constraint: Constraint):
    field_name = FIELD_MAP.get(constraint.field)
    if not field_name:
        raise ValueError(f"Field is not deterministically searchable: {constraint.field}")
    value = constraint.value
    if constraint.kind in {"term", "geo"}:
        value = canonical(value)
        if constraint.kind == "geo":
            value = GEO_ALIASES.get(value.replace(" ", ""), GEO_ALIASES.get(value, value))
        aliases = TERM_ALIASES.get(value, (value,))
        result = Q()
        array_fields = {"skills_norm", "industries_norm", "source_channels",
                        "application_positions"}
        for alias in aliases:
            result |= (Q(**{f"{field_name}__contains": [alias]})
                       if field_name in array_fields
                       else Q(**{f"{field_name}__contains": alias}))
        return result
    if constraint.op == "between":
        low, high = value
        return Q(**{f"{field_name}__gte": low, f"{field_name}__lte": high})
    lookup = {"gte": "gte", "lte": "lte", "before": "lt", "after": "gt",
              "eq": "exact"}.get(constraint.op)
    if not lookup:
        raise ValueError(f"Unsupported deterministic operator: {constraint.op}")
    return Q(**{f"{field_name}__{lookup}": value})


def _boolean_condition(node, applied, unresolved):
    if "constraint" in node:
        constraint = Constraint(**node["constraint"])
        try:
            result = _condition(constraint)
            applied.append(constraint.constraint_id)
            return result
        except ValueError:
            unresolved.append(constraint.constraint_id)
            # An unresolved hard condition must never widen the result set.
            return Q(pk__in=[])
    children = [_boolean_condition(child, applied, unresolved)
                for child in node["children"]]
    op = node["op"]
    if op == "not":
        return ~children[0]
    result = children[0]
    for child in children[1:]:
        result = result & child if op == "and" else result | child
    return result


def compile_projection_query(plan: RadarTurnPlan):
    """Compile hard AST to a lazy indexed QuerySet plus machine-readable explain."""
    query = SearchProjection.objects.filter(version=SCHEMA_VERSION)
    applied, unresolved, semantic, preferences = [], [], [], []
    for item in plan.must:
        if item.classification == "HARD_SEMANTIC":
            semantic.append(item.constraint_id)
            continue
        if item.classification == "PREFERENCE":
            preferences.append(item.constraint_id)
            continue
        try:
            query = query.filter(_condition(item))
            applied.append(item.constraint_id)
        except ValueError:
            unresolved.append(item.constraint_id)
    for item in plan.exclude:
        if item.classification == "HARD_SEMANTIC":
            semantic.append(item.constraint_id)
            continue
        if item.classification == "PREFERENCE":
            preferences.append(item.constraint_id)
            continue
        try:
            query = query.exclude(_condition(item))
            applied.append(item.constraint_id)
        except ValueError:
            unresolved.append(item.constraint_id)
    if plan.where:
        query = query.filter(_boolean_condition(plan.where, applied, unresolved))
    preferences.extend(item.constraint_id for item in plan.prefer)
    if unresolved:
        query = query.none()
    return query.order_by("person_id"), {
        "plan_version": plan.version, "projection_version": SCHEMA_VERSION,
        "applied": applied, "unresolved": unresolved,
        "semantic_requirements": list(dict.fromkeys(semantic)),
        "preference_signals": list(dict.fromkeys(preferences)),
        "retrieval_branches_required": bool(semantic or preferences
                                             or plan.semantic_concepts),
        "deterministic_complete": not unresolved,
    }


def _source_values(person):
    channels, positions, dates, edge = set(), set(), [], []
    for row in person.source_records.all():
        payload = row.payload or {}
        channel = payload.get("channel") or payload.get("source") or row.source
        position = (payload.get("position") or payload.get("job_title")
                    or payload.get("applied_position"))
        if channel:
            channels.add(canonical(channel))
        if position:
            positions.add(canonical(position))
        when = payload.get("applied_at") or payload.get("application_date")
        if when:
            dates.append(str(when))
        edge.append({"source_record_id": row.pk, "source": row.source,
                     "payload": payload})
    return sorted(channels), sorted(positions), max(dates, default=None), edge


def build_projection(person_id: int):
    person = (Person.applicants().filter(pk=person_id).select_related("talent_profile")
              .prefetch_related("source_records", "documents").first())
    if person is None:
        SearchProjection.objects.filter(person_id=person_id).delete()
        BaseDossier.objects.filter(person_id=person_id).delete()
        return None
    profile = getattr(person, "talent_profile", None)
    channels, positions, _last_date, _edge = _source_values(person)
    values = {
        "title_norm": canonical(getattr(profile, "current_title", "")),
        "company_norm": canonical(getattr(profile, "current_company", "")),
        "location_norm": canonical(getattr(profile, "location", "") or person.location),
        "education_norm": canonical(getattr(profile, "education", "")),
        "skills_norm": sorted({canonical(x) for x in (getattr(profile, "skills", []) or []) if x}),
        "industries_norm": sorted({canonical(x) for x in (getattr(profile, "industries", []) or []) if x}),
        "source_channels": channels, "application_positions": positions,
        "years_experience": getattr(profile, "years_experience", None),
        "scope": {"is_applicant": True}, "version": SCHEMA_VERSION,
    }
    values["searchable_text"] = "\n".join(str(x) for x in [
        person.display_name, values["title_norm"], values["company_norm"],
        values["location_norm"], values["education_norm"], *values["skills_norm"],
        *values["industries_norm"], *channels, *positions] if x)
    values["fingerprint"] = _hash(values)
    row, _ = SearchProjection.objects.update_or_create(person=person, defaults=values)
    return row


_HEADINGS = {
    "experience": ("kinh nghiem", "work experience", "employment", "qua trinh cong tac"),
    "skills": ("ky nang", "skills", "technical skills"),
    "education": ("hoc van", "education", "academic"),
    "project": ("du an", "projects"), "certificate": ("chung chi", "certificates"),
    "language": ("ngoai ngu", "languages"), "summary": ("tom tat", "summary", "objective"),
}


def split_sections(text):
    """Deterministic section splitter preserving complete source text and offsets."""
    text = str(text or "")
    lines = text.splitlines(keepends=True)
    result, current, start, body, offset = [], "other", 0, [], 0
    for line in lines:
        folded = canonical(line).strip(" :-")
        section = next((name for name, aliases in _HEADINGS.items()
                        if folded in aliases or any(folded.startswith(a + " ") for a in aliases)), None)
        if section and body:
            result.append({"section": current, "start": start, "end": offset,
                           "text": "".join(body)})
            current, start, body = section, offset, []
        elif section:
            current, start = section, offset
        body.append(line)
        offset += len(line)
    if body or not result:
        result.append({"section": current, "start": start, "end": offset,
                       "text": "".join(body)})
    return result


def build_dossier(person_id: int):
    projection = build_projection(person_id)
    if projection is None:
        return None
    person = (Person.objects.filter(pk=person_id).select_related("talent_profile")
              .prefetch_related("documents", "source_records").get())
    profile = getattr(person, "talent_profile", None)
    channels, positions, dates, edge = _source_values(person)
    sections, lineage = [], []
    for document in person.documents.all():
        for section in split_sections(document.best_text):
            evidence_id = f"document:{document.pk}:{section['start']}:{section['end']}"
            sections.append({**section, "evidence_id": evidence_id,
                             "document_id": document.pk})
            lineage.append({"evidence_id": evidence_id, "source": "document",
                            "source_id": document.pk})
    profile_data = {name: getattr(profile, name, None) for name in (
        "current_title", "current_company", "years_experience", "seniority",
        "education", "location", "desired_location", "desired_position", "skills",
        "industries") if profile is not None}
    payload = {"profile": profile_data, "applications": [
        {"positions": positions, "channels": channels, "dates": dates}],
        "edge": edge, "facts": [], "sections": sections, "lineage": lineage,
        "status": {"missing_cv": not bool(sections), "conflicts": []}}
    fingerprint = _hash(payload)
    row, _ = BaseDossier.objects.update_or_create(
        person=person, defaults={"version": DOSSIER_VERSION, "fingerprint": fingerprint,
                                 **payload})
    return row


def evidence_view(dossier: BaseDossier, constraints, *, max_chars=24000):
    """Select diverse evidence per constraint; never blind-prefix truncate a CV."""
    sections, selected, used = list(dossier.sections or []), [], set()
    for constraint in constraints:
        terms = set(canonical(constraint.value).split())
        ranked = sorted(sections, key=lambda row: (
            -sum(term in canonical(row.get("text")) for term in terms),
            row.get("section") == "other", row.get("start", 0)))
        for row in ranked:
            key = row.get("evidence_id")
            if key in used:
                continue
            selected.append({**row, "constraint_id": constraint.constraint_id})
            used.add(key)
            break
    # Second pass supplies section diversity until the explicit budget is used.
    for row in sections:
        if row.get("evidence_id") not in used:
            selected.append({**row, "constraint_id": ""})
            used.add(row.get("evidence_id"))
    out, chars = [], 0
    for row in selected:
        size = len(row.get("text") or "")
        if out and chars + size > max_chars:
            break
        out.append(row)
        chars += size
    return {"dossier_fingerprint": dossier.fingerprint, "evidence": out,
            "available_sections": len(sections), "selected_sections": len(out),
            "available_chars": sum(len(x.get("text") or "") for x in sections),
            "selected_chars": chars, "complete": len(out) == len(sections)}


@transaction.atomic
def create_candidate_set(plan: RadarTurnPlan, *, user=None, scope_token=""):
    queryset, explain = compile_projection_query(plan)
    population = Person.applicants().count()
    total = queryset.count()
    from talent import vector_index
    model = vector_index.current_model()
    configured = vector_index._dimensions()
    stored = vector_index._stored_dimension(model) if model else None
    semantic_available = bool(model and stored is not None and stored == configured)
    explain["semantic"] = {"model": model, "configured_dimension": configured,
                           "stored_dimension": stored,
                           "available": semantic_available}
    branch_required = bool(explain.get("retrieval_branches_required"))
    explain["branches"] = {
        "structured": {"ran": True, "degraded": False},
        "field_fts": {"ran": False, "degraded": branch_required,
                      "reason": "not_implemented" if branch_required else "not_required"},
        "vector": {"ran": False, "degraded": branch_required,
                   "reason": "not_implemented" if branch_required else "not_required"},
    }
    run = CandidateSetRun.objects.create(
        user=user, mode=(CandidateSetRun.MODE_EXHAUSTIVE if plan.exhaustive
                         else CandidateSetRun.MODE_INTERACTIVE),
        plan=plan.as_dict(), scope_token=scope_token, population=population,
        candidate_total=total, not_read=total, pending=total, explain=explain,
        semantic_available=semantic_available,
        retrieval_degraded=bool((model and not semantic_available) or branch_required),
        complete=(total == 0 and not explain["unresolved"]))
    batch = []
    for ordinal, person_id in enumerate(
            queryset.values_list("person_id", flat=True).iterator(chunk_size=2000), 1):
        batch.append(CandidateSetMember(run=run, person_id=person_id, ordinal=ordinal,
                                        provenance={"structured": True}))
        if len(batch) == 2000:
            CandidateSetMember.objects.bulk_create(batch, batch_size=2000)
            batch = []
    if batch:
        CandidateSetMember.objects.bulk_create(batch, batch_size=2000)
    return run


def judgement_cache_key(dossier, constraint, *, scope_token, model="", prompt_version=""):
    return _hash([dossier.fingerprint, constraint.as_dict(), SCHEMA_VERSION,
                  model, prompt_version, scope_token])


def cache_judgement(dossier, constraint, judgement, *, scope_token, model="",
                    prompt_version="", token_usage=0):
    complete = bool(judgement.get("status") in {"supported", "contradicted"}
                    and judgement.get("evidence_ids"))
    if not complete:
        return None
    key = judgement_cache_key(dossier, constraint, scope_token=scope_token,
                              model=model, prompt_version=prompt_version)
    row, _ = ConstraintJudgementCache.objects.update_or_create(
        key=key, defaults={"person": dossier.person,
                           "dossier_fingerprint": dossier.fingerprint,
                           "constraint_canonical": canonical(constraint.value),
                           "scope_token": scope_token, "schema_version": SCHEMA_VERSION,
                           "model": model, "prompt_version": prompt_version,
                           "judgement": judgement, "complete": True,
                           "token_usage": max(0, int(token_usage or 0))})
    return row


GROUP_ORDER = {"HIGH": 0, "MEDIUM": 1, "NEAR": 2, "UNKNOWN": 3,
               "NOT_READ": 4, "NOT_MATCHED": 5}


def deterministic_group(judgements, *, read=True):
    if not read:
        return "NOT_READ"
    statuses = [row.get("status", "unknown") for row in judgements]
    if any(status == "contradicted" for status in statuses):
        return "NOT_MATCHED"
    if any(status == "unknown" for status in statuses) or not statuses:
        return "UNKNOWN"
    confidence = min(float(row.get("confidence", 0)) for row in judgements)
    return "HIGH" if confidence >= .8 else "MEDIUM" if confidence >= .55 else "NEAR"


def rank_rows(rows):
    """Stable deterministic order; demographics are intentionally not score inputs."""
    return sorted(rows, key=lambda row: (
        GROUP_ORDER.get(row.get("group", "UNKNOWN"), 99),
        -float(row.get("confidence", 0)), int(row.get("person_id", 0))))


def estimate_judgement_cost(*, candidates, chars_per_candidate=12000,
                            output_tokens_per_candidate=350):
    """Conservative preflight estimate; never starts exhaustive work blindly."""
    candidates = max(0, int(candidates or 0))
    prompt_tokens = candidates * max(0, int(chars_per_candidate or 0)) // 4
    completion_tokens = candidates * max(0, int(output_tokens_per_candidate or 0))
    return {"candidates": candidates, "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens}


def enforce_cost_guard(estimate, *, token_limit, confirmed=False):
    total = int((estimate or {}).get("total_tokens") or 0)
    limit = max(0, int(token_limit or 0))
    if limit and total > limit and not confirmed:
        raise PermissionError(
            f"estimated_tokens={total} exceeds token_limit={limit}; confirmation required")
    return {**estimate, "token_limit": limit, "confirmed": bool(confirmed),
            "allowed": True}


def process_candidate_set(run_id, *, batch_size=500, max_batches=None):
    """Resumable T2 processor; ``max_batches`` bounds online/API work."""
    from django.utils import timezone

    batches = 0
    while True:
        run = CandidateSetRun.objects.get(pk=run_id)
        if run.cancel_requested:
            run.state = "cancelled"
            run.heartbeat_at = timezone.now()
            run.save(update_fields=["state", "heartbeat_at", "updated_at"])
            return run
        members = list(run.members.filter(ordinal__gt=run.cursor)
                       .order_by("ordinal")[:max(1, batch_size)])
        if not members:
            unknown = run.members.filter(deterministic_status="unknown").count()
            run.state, run.unknown, run.not_read = "done", unknown, unknown
            run.judged = run.candidate_total - unknown
            run.pending = 0
            run.complete = unknown == 0 and not bool(run.explain.get("unresolved"))
            run.heartbeat_at = timezone.now()
            run.save(update_fields=["state", "unknown", "not_read", "judged",
                                    "pending", "complete", "heartbeat_at", "updated_at"])
            return run
        deterministic = not bool(run.explain.get("unresolved"))
        for member in members:
            member.deterministic_status = "supported" if deterministic else "unknown"
        CandidateSetMember.objects.bulk_update(members, ["deterministic_status"],
                                               batch_size=batch_size)
        run.cursor = members[-1].ordinal
        run.state = "running"
        run.pending = max(0, run.candidate_total - run.cursor)
        run.heartbeat_at = timezone.now()
        run.save(update_fields=["cursor", "state", "pending", "heartbeat_at", "updated_at"])
        batches += 1
        if max_batches is not None and batches >= max(1, int(max_batches)):
            return run
