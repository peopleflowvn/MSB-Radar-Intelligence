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
from django.db.models import Count, Q

from people.normalize import normalize_name
from people.models import Person

from .models import (BaseDossier, CandidateSetMember, CandidateSetRun,
                     ConstraintJudgementCache, SearchProjection)

PLAN_VERSION = 2
DOSSIER_VERSION = 1
SCHEMA_VERSION = 1
#: Ngân sách ký tự của một EvidenceView. Ước tính chi phí T3 phải dùng đúng
#: con số này, nếu không preflight báo rẻ hơn thực tế.
EVIDENCE_CHAR_BUDGET = 24000
#: Trần số member được vật chất hoá cho một snapshot. Không có trần thì một câu
#: chỉ có điều kiện semantic sẽ ghi cả kho vào `CandidateSetMember` mỗi lượt.
SNAPSHOT_MAX_MEMBERS = 50000
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


#: Hạt giống cho `SearchVocabulary`, dạng `kind → {canonical: (alias, …)}`.
#: Giữ trong code CHỈ để hệ thống mới dựng lên là chạy được và để test không cần
#: seed; nguồn sự thật khi bảng đã có dữ liệu là `SearchVocabulary`
#: (SEARCH-P1-02B). Thêm alias mới thì sửa bảng, không sửa file này.
SEED_VOCABULARY = {
    "location": {
        "ha noi": ("ha noi", "hanoi", "hn"),
        "ho chi minh": ("ho chi minh", "hochiminh", "hcm", "saigon", "sg",
                        "tp hcm", "sai gon"),
    },
    "title": {
        "data analyst": ("data analyst", "chuyen vien phan tich du lieu",
                         "phan tich du lieu"),
        "relationship manager": ("relationship manager", "quan he khach hang", "rm"),
        "accountant": ("accountant", "ke toan"),
    },
    "education": {"college": ("college", "cao dang")},
}
#: Giữ tên cũ cho code/test đang import.
GEO_ALIASES = {alias: canon for canon, aliases in SEED_VOCABULARY["location"].items()
               for alias in aliases}
TERM_ALIASES = {**SEED_VOCABULARY["title"], **SEED_VOCABULARY["education"]}
#: Field của constraint → `kind` trong từ điển.
VOCAB_KIND = {"title": "title", "skill": "skill", "skills": "skill",
              "company": "company", "education": "education",
              "location": "location", "industry": "product",
              "industries": "product", "application_position": "title"}
_VOCAB_CACHE = {"stamp": None, "data": {}, "version": 0}


def _vocab_stamp():
    """Dấu để biết từ điển đã đổi, không phải đọc lại cả bảng mỗi truy vấn."""
    try:
        from django.db.models import Max

        from .models import SearchVocabulary
        row = SearchVocabulary.objects.aggregate(
            m=Max("updated_at"), v=Max("version"), n=Count("pk"))
        return (row["m"].isoformat() if row["m"] else "", row["v"] or 0,
                row["n"] or 0)
    except Exception:                              # noqa: BLE001 - chưa migrate
        return None


def vocabulary(kind=None):
    """`{canonical: (alias, …)}` theo `kind`, lấy từ DB, fallback về hạt giống.

    Trả cả `version` để `explain` nói được truy vấn đã dùng từ điển bản nào — một
    kết quả khớp nhờ alias mà không giải thích được là một kết quả không kiểm được.
    """
    stamp = _vocab_stamp()
    if stamp is None:
        return ((SEED_VOCABULARY.get(kind, {}) if kind else SEED_VOCABULARY), 0)
    if stamp != _VOCAB_CACHE["stamp"]:
        from .models import SearchVocabulary
        data, version = {}, 0
        for row in SearchVocabulary.objects.filter(enabled=True).values(
                "kind", "canonical", "aliases", "version"):
            aliases = tuple(dict.fromkeys(
                [row["canonical"], *[canonical(x) for x in (row["aliases"] or [])]]))
            data.setdefault(row["kind"], {})[row["canonical"]] = aliases
            version = max(version, int(row["version"] or 0))
        _VOCAB_CACHE.update(stamp=stamp, data=data, version=version)
    data = _VOCAB_CACHE["data"]
    if not data:
        # Bảng trống (hệ thống mới) → hạt giống, và version 0 để thấy rõ là chưa
        # ai quản trị từ điển.
        return ((SEED_VOCABULARY.get(kind, {}) if kind else SEED_VOCABULARY), 0)
    return (data.get(kind, {}) if kind else data), _VOCAB_CACHE["version"]


def canonical_for(kind, value):
    """Dạng chuẩn của một giá trị theo từ điển ("hanoi" và "hn" → "ha noi")."""
    table, _version = vocabulary(kind)
    for candidate in (value, value.replace(" ", "")):
        if candidate in table:
            return candidate
        for canon, aliases in table.items():
            if candidate == canon or candidate in aliases:
                return canon
    return value


def expand_term(field, value):
    """Các dạng cần tìm cho một giá trị: chính nó cộng alias trong từ điển."""
    kind = VOCAB_KIND.get(field)
    table, version = vocabulary(kind) if kind else ({}, 0)
    aliases = table.get(value)
    if aliases:
        return tuple(dict.fromkeys([value, *aliases])), version
    return (value,), version


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


def fts_available():
    from django.db import connection

    return connection.vendor == "postgresql"


def tsquery(value, *, mode="and"):
    """Chuỗi tsquery an toàn từ văn bản người dùng.

    Chỉ giữ chữ và số, nên không có cách nào chèn toán tử tsquery qua dữ liệu.
    `mode="and"` giữ phép giao cho điều kiện bắt buộc; `mode="or"` dùng cho nhánh
    recall, nơi mục tiêu là không bỏ sót chứ không phải kết luận.
    """
    from talent import vector_index

    tokens = vector_index.fts_tokens(value, limit=24)
    if not tokens:
        return ""
    return (" & " if mode == "and" else " | ").join(tokens)


def _fts_annotation(ctx, value, *, mode="and"):
    """Điều kiện `search_tsv @@ to_tsquery(...)` dạng annotation để ghép được
    với AND/OR/NOT của Boolean AST."""
    from django.db.models import BooleanField
    from django.db.models.expressions import RawSQL

    query = tsquery(value, mode=mode)
    if not query:
        return None
    alias = f"fts_{len(ctx['annotations'])}"
    ctx["annotations"][alias] = RawSQL(
        "search_tsv @@ to_tsquery('simple', %s)", (query,), output_field=BooleanField())
    ctx["tsqueries"].append(query)
    return Q(**{alias: True})


def _condition(constraint: Constraint, ctx=None):
    field_name = FIELD_MAP.get(constraint.field)
    if not field_name:
        raise ValueError(f"Field is not deterministically searchable: {constraint.field}")
    value = constraint.value
    if constraint.kind in {"term", "geo"}:
        value = canonical(value)
        if constraint.kind == "geo":
            # Địa danh: quy về dạng chuẩn TRƯỚC khi mở rộng ("hanoi" → "ha noi"),
            # nếu không thì "hanoi" và "Hà Nội" là hai truy vấn khác nhau.
            value = canonical_for("location", value)
        field_kind = "location" if constraint.kind == "geo" else constraint.field
        aliases, vocab_version = expand_term(field_kind, value)
        if ctx is not None:
            ctx["vocabulary_version"] = max(ctx.get("vocabulary_version", 0),
                                            vocab_version)
        # Văn bản gộp dùng chỉ mục GIN trên `search_tsv`; `LIKE '%…%'` trên cột
        # này là quét toàn bảng.
        if field_name == "searchable_text" and ctx is not None and fts_available():
            result = Q()
            matched = False
            for alias in aliases:
                condition = _fts_annotation(ctx, alias, mode="and")
                if condition is not None:
                    result |= condition
                    matched = True
            if matched:
                return result
        result = Q()
        array_fields = {"skills_norm", "industries_norm", "source_channels",
                        "application_positions"}
        if field_name in array_fields and not fts_available():
            # JSONB containment chỉ có trên PostgreSQL. Trên vendor khác điều
            # kiện này fail closed (unresolved) thay vì nổ hoặc âm thầm bỏ qua.
            raise ValueError(f"Array containment requires PostgreSQL: {constraint.field}")
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


def _boolean_condition(node, applied, unresolved, ctx=None):
    if "constraint" in node:
        constraint = Constraint(**node["constraint"])
        try:
            result = _condition(constraint, ctx)
            applied.append(constraint.constraint_id)
            return result
        except ValueError:
            unresolved.append(constraint.constraint_id)
            # An unresolved hard condition must never widen the result set.
            return Q(pk__in=[])
    children = [_boolean_condition(child, applied, unresolved, ctx)
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
    ctx = {"annotations": {}, "tsqueries": [], "vocabulary_version": 0}
    keeps, drops = [], []
    for item in plan.must:
        if item.classification == "HARD_SEMANTIC":
            semantic.append(item.constraint_id)
            continue
        if item.classification == "PREFERENCE":
            preferences.append(item.constraint_id)
            continue
        try:
            keeps.append(_condition(item, ctx))
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
            drops.append(_condition(item, ctx))
            applied.append(item.constraint_id)
        except ValueError:
            unresolved.append(item.constraint_id)
    if plan.where:
        keeps.append(_boolean_condition(plan.where, applied, unresolved, ctx))
    # Annotation phải có trước mọi filter tham chiếu tới nó, nên điều kiện được
    # gom lại rồi áp một lần. `exclude` vẫn là lời gọi riêng để giữ đúng ngữ
    # nghĩa NULL của Django, không đổi thành `filter(~Q)`.
    if ctx["annotations"]:
        query = query.annotate(**ctx["annotations"])
    for condition in keeps:
        query = query.filter(condition)
    for condition in drops:
        query = query.exclude(condition)
    preferences.extend(item.constraint_id for item in plan.prefer)
    if unresolved:
        query = query.none()
    semantic = list(dict.fromkeys(semantic))
    return query.order_by("person_id"), {
        "fts_index_used": bool(ctx["tsqueries"]),
        "vocabulary_version": ctx.get("vocabulary_version", 0),
        "plan_version": plan.version, "projection_version": SCHEMA_VERSION,
        "applied": applied, "unresolved": unresolved,
        "hard_filters_applied": len(applied),
        # Không có filter cứng nào nghĩa là T0 bằng đúng dân số trong scope: tập
        # này chưa phải CandidateSet, chỉ là chưa lọc gì.
        "population_scan": not applied and not unresolved,
        "semantic_requirements": semantic,
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


@dataclass(frozen=True)
class BranchHit:
    """Kết quả một nhánh recall (SEARCH-P1-03A). Mọi nhánh trả cùng hình dạng
    này để bật/tắt được độc lập và provenance không mất khi union."""

    branch: str
    person_id: int
    rank: int = 0
    raw_score: float = 0.0
    matched_constraints: tuple = ()


def recall_terms(plan: RadarTurnPlan):
    """Văn bản dùng cho nhánh recall: semantic requirement, concept và preference.

    Điều kiện `HARD_DETERMINISTIC` đã nằm trong predicate SQL nên không lặp lại;
    nhánh này tồn tại để không bỏ sót phần chỉ đọc mới kết luận được.
    """
    terms = []
    for item in [*plan.must, *plan.prefer]:
        if item.classification in {"HARD_SEMANTIC", "PREFERENCE"}:
            terms.append(str(item.value))
    terms.extend(str(x) for x in plan.semantic_concepts or [])
    return [term for term in dict.fromkeys(terms) if term.strip()]


def lexical_branch(base_queryset, plan: RadarTurnPlan, *, limit):
    """Nhánh field-aware FTS trên `search_tsv` (GIN), xếp theo `ts_rank_cd`.

    Chạy bên trong `base_queryset` — tức là đã chịu mọi filter cứng — nên nhánh
    này chỉ thêm recall, không bao giờ kéo vào người vi phạm điều kiện cứng.
    Trả `(None, state)` khi không dùng được để caller biết phải đánh degraded
    thay vì im lặng coi như đã tìm đủ.
    """
    from django.db.models import FloatField
    from django.db.models.expressions import RawSQL

    terms = recall_terms(plan)
    if not terms:
        return None, {"ran": False, "reason": "not_required"}
    if not fts_available():
        return None, {"ran": False, "reason": "vendor_unsupported"}
    parts = [f"({tsquery(term, mode='and')})" for term in terms
             if tsquery(term, mode="and")]
    if not parts:
        return None, {"ran": False, "reason": "no_indexable_token"}
    query = " | ".join(parts)
    rows = (base_queryset
            .extra(where=["search_tsv @@ to_tsquery('simple', %s)"], params=[query])
            .annotate(fts_rank=RawSQL("ts_rank_cd(search_tsv, to_tsquery('simple', %s))",
                                      (query,), output_field=FloatField()))
            .order_by("-fts_rank", "person_id")
            .values_list("person_id", "fts_rank")[:max(1, int(limit))])
    hits = [BranchHit("field_fts", person_id, rank=ordinal, raw_score=float(score or 0))
            for ordinal, (person_id, score) in enumerate(rows, 1)]
    capped = len(hits) >= max(1, int(limit))
    return hits, {"ran": True, "hits": len(hits), "top_n": int(limit),
                  "capped": capped, "tsquery": query,
                  "reason": "top_n_capped" if capped else ""}


#: Trên tập đã lọc cứng nhỏ hơn ngưỡng này, khoảng cách được tính chính xác
#: trong phạm vi đó. Lớn hơn thì bật `hnsw.iterative_scan` để ANN có filter không
#: âm thầm trả ít hơn `top_n`.
VECTOR_PREFILTER_MAX = 20000


def vector_branch(base_queryset, plan: RadarTurnPlan, *, limit, population=None):
    """Nhánh dense ANN trong phạm vi filter cứng (SEARCH-P1-03D).

    Nhánh này chỉ thêm recall cho phần diễn đạt tương đương; nó không bao giờ tự
    cho một Person pass điều kiện `must` — T2 vẫn xác minh lại toàn bộ.
    """
    terms = recall_terms(plan)
    if not terms:
        return None, {"ran": False, "reason": "not_required"}
    from talent import vector_index

    model = vector_index.current_model()
    if not model:
        return None, {"ran": False, "reason": "no_model"}
    total = population if population is not None else base_queryset.count()
    iterative = total > VECTOR_PREFILTER_MAX
    try:
        rows = vector_index.search_scored(" ".join(terms), limit=max(1, int(limit)),
                                          person_queryset=base_queryset,
                                          iterative=iterative)
    except vector_index.VectorDimensionMismatch as exc:
        return None, {"ran": False, "reason": "dimension_mismatch",
                      "error": str(exc)[:200]}
    except Exception as exc:                       # noqa: BLE001 - provider/mạng
        return None, {"ran": False, "reason": "error", "error": str(exc)[:200]}
    if not rows:
        # Không có vector cho model đang dùng, hoặc chưa ai trong phạm vi được
        # embed: nhánh coi như KHÔNG chạy, không phải "chạy và không thấy ai".
        return None, {"ran": False, "reason": "no_vectors_in_scope"}
    hits = [BranchHit("vector", person_id, rank=ordinal,
                      raw_score=round(1.0 - float(distance), 6))
            for ordinal, (person_id, distance) in enumerate(rows, 1)]
    capped = len(hits) >= max(1, int(limit))
    return hits, {"ran": True, "hits": len(hits), "top_n": int(limit),
                  "capped": capped, "model": model,
                  "mode": "ann_iterative" if iterative else "prefilter_exact",
                  "reason": "top_n_capped" if capped else ""}


def union_branches(*branch_hits):
    """Union theo Person, giữ rank/score/provenance từng nhánh.

    Thứ tự chỉ là thứ tự xử lý: người vào từ nhánh structured (đã thoả điều kiện
    cứng) đi trước, phần còn lại theo rank lexical. Không nhánh nào có quyền xoá
    hit của nhánh khác.
    """
    merged = {}
    for hits in branch_hits:
        for hit in hits or ():
            row = merged.setdefault(hit.person_id, {"person_id": hit.person_id,
                                                    "provenance": {}, "scores": {}})
            row["provenance"][hit.branch] = {
                "rank": hit.rank, "score": hit.raw_score,
                "matched_constraints": list(hit.matched_constraints)}
            row["scores"][hit.branch] = hit.raw_score
    ordered = sorted(merged.values(), key=lambda row: (
        0 if "structured" in row["provenance"] else 1,
        row["provenance"].get("field_fts", {}).get("rank", 0),
        row["provenance"].get("vector", {}).get("rank", 0),
        row["person_id"]))
    return ordered


def branch_state(explain, *, structured=None, fts=None, vector=None):
    """Trạng thái từng nhánh recall theo mục 3.7 backlog."""
    branch_required = bool(explain.get("retrieval_branches_required"))
    return {
        "structured": structured or {"ran": True, "required": True, "degraded": False},
        "field_fts": {"required": branch_required, "ran": False,
                      "reason": "not_implemented", **(fts or {})},
        "vector": {"required": branch_required, "ran": False,
                   "reason": "not_implemented", **(vector or {})},
    }


def branches_complete(explain):
    """`True` chỉ khi mọi nhánh bắt buộc đã chạy thật, đọc từ trạng thái đã ghi."""
    branches = (explain or {}).get("branches")
    if not branches:
        return not bool((explain or {}).get("retrieval_branches_required"))
    return all(bool(row.get("ran")) for row in branches.values()
               if row.get("required"))


def completeness_layers(explain, *, branches_ok, verification=False,
                        deep_read=False, evidence=False, grounded=False):
    """Bảy lớp completeness độc lập; không lớp nào được suy ra từ lớp khác."""
    return {
        "deterministic_complete": bool(explain.get("deterministic_complete")),
        "branches_complete": bool(branches_ok),
        # Chỉ gold set (P0-05) mới được đặt cờ này; chưa có gold thì luôn False.
        "semantic_recall_measured": False,
        "verification_complete": bool(verification),
        "deep_read_complete": bool(deep_read),
        "evidence_complete": bool(evidence),
        "answer_grounded": bool(grounded),
    }


def _snapshot_limit(max_members=None):
    from django.conf import settings

    if max_members is not None:
        return max(0, int(max_members))
    return max(0, int(getattr(settings, "SEARCH_V2_SNAPSHOT_MAX_MEMBERS",
                              SNAPSHOT_MAX_MEMBERS)))


def _enroll_union(run, rows):
    """Vật chất hoá membership đã union, giữ provenance và score từng nhánh."""
    batch = []
    for ordinal, row in enumerate(rows, 1):
        batch.append(CandidateSetMember(
            run=run, person_id=row["person_id"], ordinal=ordinal,
            provenance=row["provenance"],
            structured_score=row["scores"].get("structured"),
            lexical_score=row["scores"].get("field_fts"),
            semantic_score=row["scores"].get("vector")))
        if len(batch) == 2000:
            CandidateSetMember.objects.bulk_create(batch, batch_size=2000)
            batch = []
    if batch:
        CandidateSetMember.objects.bulk_create(batch, batch_size=2000)


def _enroll_members(run, queryset):
    """Vật chất hoá membership. PostgreSQL dùng một `INSERT ... SELECT` để không
    kéo ID về Python; các vendor khác dùng iterator + bulk_create."""
    from django.db import connection

    if connection.vendor == "postgresql":
        table = CandidateSetMember._meta.db_table
        inner, params = queryset.values_list("person_id", flat=True).query.sql_with_params()
        with connection.cursor() as cursor:
            cursor.execute(
                f'INSERT INTO "{table}" (run_id, person_id, ordinal, provenance, '
                f'deterministic_status, created_at) SELECT %s, src.person_id, '
                f'row_number() OVER (ORDER BY src.person_id), %s::jsonb, '
                f"'unknown', NOW() FROM ({inner}) AS src",
                [str(run.pk), json.dumps({"structured": True}), *params])
        return
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


@transaction.atomic
def create_candidate_set(plan: RadarTurnPlan, *, user=None, scope_token="",
                         max_members=None):
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
    hard_applied = bool(explain.get("hard_filters_applied"))
    limit = _snapshot_limit(max_members)
    explain["t0"] = {"population": population, "hard_filter_count": total,
                     "hard_filters_applied": explain.get("hard_filters_applied", 0)}

    # Nhánh lexical chạy trong phạm vi filter cứng: chỉ thêm recall cho phần
    # semantic, không bao giờ kéo vào người vi phạm điều kiện cứng.
    from django.conf import settings
    fts_top_n = int(getattr(settings, "SEARCH_V2_FTS_TOP_N", 2000))
    vector_top_n = int(getattr(settings, "SEARCH_V2_VECTOR_TOP_N", 500))
    lexical_hits, fts_state = lexical_branch(queryset, plan, limit=fts_top_n)
    vector_hits, vector_state = vector_branch(queryset, plan, limit=vector_top_n,
                                              population=total)
    recall_hits = [hits for hits in (lexical_hits, vector_hits) if hits]
    structured_state = {"ran": True, "required": True, "degraded": False,
                        "hits": total}
    union_rows = None
    if recall_hits and not hard_applied:
        # Không có filter cứng thì T0 bằng cả dân số; tập đó không phải
        # CandidateSet. Thành viên lấy từ các nhánh recall, và recall bị giới hạn
        # bởi `top_n` — điều này được ghi lại, không được phát biểu là "đã tìm
        # toàn bộ".
        structured_state = {"ran": False, "required": False, "degraded": False,
                            "reason": "no_hard_filter", "hits": 0}
        union_rows = union_branches(*recall_hits)
    elif recall_hits and total <= limit:
        structured_hits = [BranchHit("structured", person_id) for person_id in
                           queryset.values_list("person_id", flat=True)
                           .iterator(chunk_size=2000)]
        union_rows = union_branches(structured_hits, *recall_hits)
    explain["branches"] = branch_state(explain, structured=structured_state,
                                       fts=fts_state, vector=vector_state)
    complete_branches = branches_complete(explain)

    # Trần snapshot: thà từ chối vật chất hoá còn hơn ghi cả kho vào member table
    # rồi gọi đó là CandidateSet. Trần bị vượt là trạng thái `blocked`, không
    # phải cắt bớt im lặng.
    candidate_total = len(union_rows) if union_rows is not None else total
    enroll = not limit or candidate_total <= limit
    explain["snapshot"] = {
        "limit": limit, "enrolled": enroll,
        "source": "union" if union_rows is not None else "structured",
        "reason": "" if enroll else "snapshot_cap_exceeded"}
    explain["completeness"] = completeness_layers(
        explain, branches_ok=complete_branches)
    run = CandidateSetRun.objects.create(
        user=user, mode=(CandidateSetRun.MODE_EXHAUSTIVE if plan.exhaustive
                         else CandidateSetRun.MODE_INTERACTIVE),
        plan=plan.as_dict(), scope_token=scope_token, population=population,
        state=("pending" if enroll else "blocked"),
        candidate_total=candidate_total, not_read=candidate_total,
        pending=(candidate_total if enroll else 0),
        explain=explain, semantic_available=semantic_available,
        error=("" if enroll
               else f"snapshot_cap_exceeded: {candidate_total} > {limit}"),
        retrieval_degraded=bool((model and not semantic_available) or not enroll
                                or not complete_branches),
        complete=(candidate_total == 0 and complete_branches
                  and not explain["unresolved"]))
    if enroll and union_rows is not None:
        _enroll_union(run, union_rows)
    elif enroll:
        _enroll_members(run, queryset)
    return run


ABLATION_CONFIGS = ("structured", "field_fts", "vector",
                    "structured+field_fts", "full")


def ablation(plan: RadarTurnPlan, *, configs=ABLATION_CONFIGS, fts_top_n=2000,
             vector_top_n=500, cap=SNAPSHOT_MAX_MEMBERS):
    """Chạy từng cấu hình nhánh riêng để đo đóng góp thật (mục 3.7 backlog).

    Không có số này thì mọi việc tăng trọng số hay thêm nhánh chỉ là phỏng đoán:
    một nhánh có thể không thêm Person nào mà vẫn làm chậm và tốn tiền.
    """
    import time

    queryset, explain = compile_projection_query(plan)
    hard_applied = bool(explain.get("hard_filters_applied"))
    result = {"explain": explain, "configs": {}}
    for config in configs:
        started = time.perf_counter()
        ids, state = [], {}
        if config in {"structured", "structured+field_fts", "full"}:
            if hard_applied:
                ids = list(queryset.values_list("person_id", flat=True)
                           .iterator(chunk_size=2000))[:cap]
                state["structured"] = {"ran": True, "hits": len(ids)}
            else:
                state["structured"] = {"ran": False, "reason": "no_hard_filter"}
        if config in {"field_fts", "structured+field_fts", "full"}:
            hits, fts_state = lexical_branch(queryset, plan, limit=fts_top_n)
            state["field_fts"] = fts_state
            if hits:
                ids = list(dict.fromkeys([*ids, *(hit.person_id for hit in hits)]))[:cap]
        if config in {"vector", "full"}:
            hits, vector_state = vector_branch(queryset, plan, limit=vector_top_n)
            state["vector"] = vector_state
            if hits:
                ids = list(dict.fromkeys([*ids, *(hit.person_id for hit in hits)]))[:cap]
        result["configs"][config] = {
            "ids": ids, "count": len(ids), "branches": state,
            "ms": round((time.perf_counter() - started) * 1000, 1)}
    return result


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


def estimate_judgement_cost(*, candidates, chars_per_candidate=EVIDENCE_CHAR_BUDGET,
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


def verify_members(run, members):
    """T2: chạy lại hard-deterministic predicate trên đúng những member này.

    Trước đây mọi member được gán `supported` chỉ vì compiler không có
    `unresolved` — tức là báo "đã xác minh" mà không đối chiếu dữ liệu, và câu
    có điều kiện semantic cũng bị tính là đã kết luận. Ở đây verdict `supported`
    chỉ được cấp khi Person thực sự khớp predicate cứng VÀ không còn constraint
    semantic nào chờ T3.
    """
    plan = RadarTurnPlan.from_dict(run.plan or {})
    queryset, explain = compile_projection_query(plan)
    person_ids = [member.person_id for member in members]
    matched = set(queryset.filter(person_id__in=person_ids)
                  .values_list("person_id", flat=True))
    unresolved = bool(explain.get("unresolved"))
    # Trạng thái nhánh lấy từ run đã ghi, không suy lại từ compile mới: compile
    # mới không biết nhánh nào đã thật sự chạy lúc tạo snapshot.
    complete_branches = branches_complete(run.explain or {})
    semantic_pending = (bool(explain.get("semantic_requirements"))
                        or not complete_branches)
    for member in members:
        if unresolved:
            # Không biên dịch được điều kiện cứng thì không ai được coi là đã xác minh.
            member.deterministic_status = "unknown"
        elif member.person_id not in matched:
            member.deterministic_status = "contradicted"
        elif semantic_pending:
            member.deterministic_status = "unknown"
        else:
            member.deterministic_status = "supported"
    CandidateSetMember.objects.bulk_update(members, ["deterministic_status"],
                                           batch_size=max(1, len(members)))
    return {"matched": len(matched), "semantic_pending": semantic_pending,
            "unresolved": unresolved, "branches_complete": complete_branches}


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
        if run.state == "blocked":
            return run
        members = list(run.members.filter(ordinal__gt=run.cursor)
                       .order_by("ordinal")[:max(1, batch_size)])
        if not members:
            return _finish_candidate_set(run)
        verified = verify_members(run, members)
        run.cursor = members[-1].ordinal
        run.state = "running"
        run.pending = max(0, run.candidate_total - run.cursor)
        run.explain = {**(run.explain or {}), "verification": verified}
        run.heartbeat_at = timezone.now()
        run.save(update_fields=["cursor", "state", "pending", "explain",
                                "heartbeat_at", "updated_at"])
        batches += 1
        if max_batches is not None and batches >= max(1, int(max_batches)):
            return run


def _finish_candidate_set(run):
    """Đóng run bằng đúng số đếm trong DB, không suy ra từ `candidate_total`."""
    from django.utils import timezone

    statuses = {row["deterministic_status"]: row["n"] for row in run.members.values(
        "deterministic_status").annotate(n=Count("pk"))}
    enrolled = sum(statuses.values())
    unknown = statuses.get("unknown", 0) + statuses.get("", 0)
    complete_branches = branches_complete(run.explain or {})
    verification_complete = (enrolled == run.candidate_total and not unknown
                             and not bool((run.explain or {}).get("unresolved")))
    run.state = "done"
    run.unknown = unknown
    run.not_read = unknown
    run.judged = max(0, enrolled - unknown)
    run.pending = max(0, run.candidate_total - enrolled)
    run.complete = bool(verification_complete and complete_branches)
    run.explain = {**(run.explain or {}), "completeness": completeness_layers(
        run.explain or {}, branches_ok=complete_branches,
        verification=verification_complete)}
    run.heartbeat_at = timezone.now()
    run.save(update_fields=["state", "unknown", "not_read", "judged", "pending",
                            "complete", "explain", "heartbeat_at", "updated_at"])
    return run
