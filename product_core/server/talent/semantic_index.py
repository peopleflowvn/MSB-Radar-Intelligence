# -*- coding: utf-8 -*-
"""Fallback semantic retrieval backed by the shared Canonical Registry.

The registry, not a hand-written list of occupations, supplies aliases for
location, job title, skill, industry, education, company, language and every
future namespace. Dense pgvector remains the primary semantic branch; this
module gives deterministic bilingual recall while embeddings are backfilled.
"""
import hashlib
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache

from people.models import Person

from .models import TalentSemanticIndex

DIMENSIONS = 512
MAX_SOURCE_CHARS = 120_000
MAX_TERMS = 4000

CONCEPTS = {
    "data": ("data", "du lieu", "dữ liệu", "analytics", "phan tich du lieu", "bi"),
    "sales": ("sales", "kinh doanh", "ban hang", "business development"),
    "people_management": ("people management", "quan ly doi nhom", "team management", "team lead"),
    "banking": ("banking", "bank", "ngan hang", "tai chinh ngan hang"),
    "software": ("software", "phan mem", "lap trinh", "developer", "engineer"),
    "accounting": ("accounting", "accountant", "ke toan", "kiem toan", "audit"),
    "human_resources": ("human resources", "hr", "nhan su", "talent acquisition", "recruitment"),
    "marketing": ("marketing", "tiep thi", "digital marketing", "growth"),
    "customer_service": ("customer service", "cham soc khach hang", "client service"),
    "risk": ("risk", "rui ro", "risk management", "quan tri rui ro"),
}


def normalize(text):
    value = unicodedata.normalize("NFD", str(text or "").casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    value = value.replace("đ", "d")
    return " ".join(re.findall(r"[a-z0-9+#.]+", value))


_PHRASE_TO_CONCEPT = {normalize(phrase): concept
                      for concept, phrases in CONCEPTS.items() for phrase in phrases}


@lru_cache(maxsize=1)
def _registry_aliases():
    """Accepted aliases from all active namespaces, without business hard-code.

    A failed/missing Intel migration must never break Talent search. Alias
    governance happens in `intel`: unknown values become proposed aliases and
    only approved values participate here after index rebuild.
    """
    try:
        from intel.models import CanonicalAlias
        rows = (CanonicalAlias.objects.filter(status=CanonicalAlias.STATUS_ACCEPTED,
                                               entry__active=True, namespace__active=True)
                .select_related("entry", "namespace")
                .values_list("alias_norm", "namespace__key", "entry__code"))
        return [(str(alias), f"registry:{namespace}:{code}")
                for alias, namespace, code in rows if alias and namespace and code]
    except Exception:  # noqa: BLE001 - bootstrap / no Intel table
        return []


def clear_registry_alias_cache():
    """Called by Canonical Registry mutations; no stale alias until restart."""
    _registry_aliases.cache_clear()


def concepts_and_terms(text):
    plain = normalize(text)
    tokens = plain.split()
    terms = list(tokens)
    for phrase, concept in _PHRASE_TO_CONCEPT.items():
        if phrase and re.search(r"(?:^| )" + re.escape(phrase) + r"(?: |$)", plain):
            terms.extend((f"concept:{concept}",) * 3)
    # This applies identically to every accepted namespace. A new alias added
    # by Admin starts improving query and CV recall after rebuild, with no code
    # change and no special-case dictionary.
    for phrase, concept in _registry_aliases():
        if phrase and re.search(r"(?:^| )" + re.escape(phrase) + r"(?: |$)", plain):
            terms.extend((f"concept:{concept}",) * 3)
    # Bigrams preserve phrases such as data engineer and quan ly.
    terms.extend(f"{tokens[i]}_{tokens[i + 1]}" for i in range(len(tokens) - 1))
    return plain, terms[:MAX_TERMS]


def _slot(term):
    return int.from_bytes(hashlib.blake2b(term.encode("utf-8"), digest_size=4).digest(), "big") % DIMENSIONS


def vectorize(terms):
    counts = Counter(_slot(term) for term in terms)
    norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
    return {str(key): round(value / norm, 6) for key, value in counts.items()}


def _source(person):
    profile = getattr(person, "talent_profile", None)
    parts = [person.display_name, person.location]
    if profile:
        parts.extend((profile.current_title, profile.current_company, profile.education,
                      profile.location, profile.summary, " ".join(profile.skills or []),
                      " ".join(profile.industries or [])))
    # Dữ liệu trang chi tiết và envelope thô của Edge có thể chưa có cột chuẩn,
    # nhưng vẫn phải tham gia recall. Chuẩn hóa sau không cần Edge gửi lại.
    for record in person.source_records.all().iterator(chunk_size=100):
        import json
        parts.append(json.dumps(record.payload or {}, ensure_ascii=False, default=str))
    for document in person.documents.select_related("primary_text_version").all():
        if document.best_text:
            parts.append(document.best_text)
    return "\n".join(str(part) for part in parts if part)[:MAX_SOURCE_CHARS]


def index_person(person_id):
    person = (Person.objects.filter(pk=person_id, merged_into__isnull=True)
              .select_related("talent_profile")
              .prefetch_related("documents__primary_text_version").first())
    if person is None:
        TalentSemanticIndex.objects.filter(person_id=person_id).delete()
        return None
    source = _source(person)
    fingerprint = hashlib.sha256(source.encode("utf-8")).hexdigest()
    current = TalentSemanticIndex.objects.filter(person_id=person_id).first()
    if current and current.fingerprint == fingerprint:
        return current
    plain, terms = concepts_and_terms(source)
    row, _ = TalentSemanticIndex.objects.update_or_create(
        person_id=person_id,
        defaults={"fingerprint": fingerprint, "normalized_text": plain,
                  "terms": sorted(set(terms))[:MAX_TERMS], "vector": vectorize(terms),
                  "source_characters": len(source)})
    return row


#: Trần số hồ sơ được chấm trong Python cho MỘT truy vấn. Không có trần này thì
#: ở kho triệu hồ sơ mỗi lượt tìm kiếm sẽ nạp toàn bộ bảng vào bộ nhớ.
MAX_SCAN = 20_000


def search(query, limit=500):
    plain, terms = concepts_and_terms(query)
    wanted = vectorize(terms)
    if not wanted:
        return []

    rows = TalentSemanticIndex.objects.all()
    # PostgreSQL: thu hẹp bằng full-text index trên `normalized_text` (GIN,
    # migration 0007) trước khi chấm — chỉ những hồ sơ có ít nhất một từ khoá.
    try:
        from .vector_index import fts_filter
        narrowed = fts_filter(rows, "normalized_text", plain)
        if narrowed is not None:
            rows = narrowed
    except Exception:                              # noqa: BLE001
        pass

    scored = []
    for person_id, vector in (rows.values_list("person_id", "vector")
                              .iterator(chunk_size=2000)):
        score = sum(float(vector.get(slot, 0.0)) * weight for slot, weight in wanted.items())
        if score > 0:
            scored.append((score, person_id))
        if len(scored) >= MAX_SCAN:
            break
    scored.sort(reverse=True)
    return [person_id for _score, person_id in scored[:limit]]


def similarity(left, right):
    """Cheap bilingual semantic similarity used by deterministic scoring."""
    _a, terms_a = concepts_and_terms(left)
    _b, terms_b = concepts_and_terms(right)
    a, b = set(terms_a), set(terms_b)
    if not a or not b:
        return 0.0
    concepts_a = {term for term in a if term.startswith("concept:")}
    concepts_b = {term for term in b if term.startswith("concept:")}
    if concepts_a & concepts_b:
        return 0.85
    return round(len(a & b) / max(1, len(a)), 3)
