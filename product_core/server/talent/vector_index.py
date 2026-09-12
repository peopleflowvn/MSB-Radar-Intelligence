# -*- coding: utf-8 -*-
"""Dense multilingual index for Radar Talent.

Embedding is deliberately an offline/background action. Search never sends a
whole warehouse to an LLM; it only queries vectors that were built from all
allowed Person fields and parsed CV chunks. If embeddings are not configured,
callers receive an empty dense branch and hybrid retrieval falls back safely.
"""
import hashlib
import json
import math
import re
import time
import unicodedata
import urllib.request

from django.conf import settings
from django.db import connection

from people.models import Person
from .models import CVChunk, PersonSearchDocument


def fold_text(text):
    """Bỏ dấu + hạ chữ thường. Là dạng được đánh chỉ mục full-text (`*_norm`).

    Dùng cấu hình `simple` của PostgreSQL trên text đã bỏ dấu để khớp không phụ
    thuộc dấu tiếng Việt mà không cần extension `unaccent` (không phải bản
    Postgres nào cũng có, và cài thêm cần quyền superuser).
    """
    value = unicodedata.normalize("NFD", str(text or "").casefold())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return value.replace("đ", "d")


def fts_tokens(text, *, limit=24):
    """Token an toàn để ghép thành tsquery (`a | b | c`). Chỉ chữ và số."""
    seen, out = set(), []
    for token in re.findall(r"[a-z0-9]+", fold_text(text)):
        if len(token) >= 2 and token not in seen:
            seen.add(token)
            out.append(token)
        if len(out) >= limit:
            break
    return out


def fts_filter(queryset, field, text, *, limit=24):
    """Lọc theo full-text OR trên PostgreSQL; trả None khi không dùng được.

    Trả `None` (chứ không phải queryset gốc) để caller biết phải lùi về nhánh
    khác — im lặng trả toàn bảng ở kho triệu bản ghi là một cách hỏng rất đắt.
    """
    if connection.vendor != "postgresql":
        return None
    tokens = fts_tokens(text, limit=limit)
    if not tokens:
        return None
    from django.contrib.postgres.search import SearchQuery, SearchVector
    query = SearchQuery(" | ".join(tokens), config="simple", search_type="raw")
    return (queryset
            .annotate(**{f"_sv_{field}": SearchVector(field, config="simple")})
            .filter(**{f"_sv_{field}": query}))

# Số chiều KHÔNG chốt cứng ở tầng model/migration (cột vector để biến chiều — xem
# `talent/models.py`). `DIMENSIONS` chỉ là chiều YÊU CẦU cho các API cần nêu rõ
# (Gemini `output_dimensionality`); đổi qua `TALENT_EMBEDDING_DIMENSIONS`. Vector
# trả về được chấp nhận nếu độ dài nằm trong [MIN, MAX] — không ép `== DIMENSIONS`
# để không loại nhầm model có chiều khác.
_DEFAULT_DIMENSIONS = 768
MIN_DIMENSIONS = 64
MAX_DIMENSIONS = 8192
CHUNK_CHARS = 1400
CHUNK_OVERLAP = 180
# Vector CẤP HỒ SƠ chỉ embed phần đầu content (trường có cấu trúc + đầu CV).
# Nhồi cả 20K ký tự vào bge-m3 trên CPU vừa chậm (5–15s/hồ sơ) vừa loãng tín
# hiệu; đoạn chi tiết đã có `CVChunk` lo. Full content vẫn dùng cho `content_norm`.
PROJECTION_EMBED_CHARS = 2200


def _dimensions():
    try:
        from .models import EmbeddingConfig
        cfg = EmbeddingConfig.objects.filter(pk=1).first()
        if cfg and cfg.dimensions:
            return int(cfg.dimensions)
    except Exception:                             # noqa: BLE001 - chưa migrate
        pass
    try:
        return int(getattr(settings, "TALENT_EMBEDDING_DIMENSIONS", _DEFAULT_DIMENSIONS))
    except (TypeError, ValueError):
        return _DEFAULT_DIMENSIONS


# Giữ tên cũ cho code đang import.
DIMENSIONS = _DEFAULT_DIMENSIONS


def _chunks(text):
    clean = " ".join(str(text or "").split())
    for start in range(0, len(clean), max(1, CHUNK_CHARS - CHUNK_OVERLAP)):
        chunk = clean[start:start + CHUNK_CHARS].strip()
        if chunk:
            yield chunk
        if start + CHUNK_CHARS >= len(clean):
            break


def document_text(person):
    profile = getattr(person, "talent_profile", None)
    fields = [person.display_name, person.headline, person.location]
    if profile:
        fields += [profile.current_title, profile.current_company, profile.location,
                   profile.education, profile.summary, " ".join(profile.skills or []),
                   " ".join(profile.industries or [])]
    # Source payload holds Edge facts absent from CV (applied job/salary/date…).
    for record in person.source_records.all().iterator(chunk_size=100):
        fields.append(json.dumps(record.payload or {}, ensure_ascii=False, default=str))
    try:
        from intel.facts import current_facts
        fields.extend(f"{fact.field}: {fact.canonical_label or fact.raw_value}"
                      for fact in current_facts(person)[:120])
    except Exception:  # intel may not be migrated during bootstrap
        pass
    return "\n".join(str(value) for value in fields if value)[:120_000]


def _embedding_config():
    """Cấu hình embedding, theo thứ tự ưu tiên:

    0. `EmbeddingConfig` singleton (đổi từ `/settings` — bật/tắt, Gemini vs tự host).
    1. Endpoint TỰ HOST qua settings (`TALENT_EMBEDDING_BASE_URL` + `_MODEL`).
    2. Route `talent_embedding` trong DB (Gemini/OpenAI…).
    """
    try:
        from .models import EmbeddingConfig
        cfg = EmbeddingConfig.objects.filter(pk=1).first()
    except Exception:                             # noqa: BLE001 - chưa migrate
        cfg = None
    if cfg is not None:
        resolved = cfg.resolve()
        if resolved is not None:
            return resolved
        if cfg.mode == EmbeddingConfig.MODE_OFF:
            return None
        # cfg tồn tại nhưng chưa đủ thông tin cho mode đã chọn ⇒ thử env/route.

    from django.conf import settings
    base = str(getattr(settings, "TALENT_EMBEDDING_BASE_URL", "") or "").strip()
    model = str(getattr(settings, "TALENT_EMBEDDING_MODEL", "") or "").strip()
    if base and model:
        key = str(getattr(settings, "TALENT_EMBEDDING_API_KEY", "") or "local")
        return "local", base.rstrip("/"), key, model

    from ai.models import ProviderConfig, TaskModelRoute
    from ai.providers import PROVIDER_DEFAULTS
    route = TaskModelRoute.objects.filter(task="talent_embedding", enabled=True).first()
    if route is None:
        return None
    config = ProviderConfig.objects.filter(provider=route.provider, enabled=True).first()
    if config is None or not config.get_api_key() or not route.model:
        return None
    base_url = config.base_url or PROVIDER_DEFAULTS.get(config.provider, {}).get("base_url", "")
    if not base_url:
        return None
    return config.provider, base_url.rstrip("/"), config.get_api_key(), route.model


# Nhiều model embedding cần tiền tố bất đối xứng cho truy vấn vs đoạn văn.
_E5_PREFIX = {"RETRIEVAL_QUERY": "query: ", "RETRIEVAL_DOCUMENT": "passage: "}
_NOMIC_PREFIX = {"RETRIEVAL_QUERY": "search_query: ",
                 "RETRIEVAL_DOCUMENT": "search_document: "}


def _instruction_prefix(model, task_type):
    low = str(model).lower()
    if "nomic" in low:
        return _NOMIC_PREFIX.get(task_type, "search_document: ")
    if any(tag in low for tag in ("e5", "bge-m3", "gte-", "arctic-embed")):
        return _E5_PREFIX.get(task_type, "passage: ")
    return ""


def embed(text, *, task_type="RETRIEVAL_DOCUMENT"):
    """Gọi endpoint embedding (OpenAI-compatible hoặc Gemini). Trả (vector, model)
    hoặc (None, model) khi không dùng được — search KHÔNG bao giờ được vỡ vì việc này."""
    config = _embedding_config()
    if not config or not text:
        return None, ""
    provider, base_url, key, model = config
    if provider == "gemini":
        request = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + model.removeprefix("models/") + ":embedContent",
            data=json.dumps({
                "content": {"parts": [{"text": str(text)[:30_000]}]},
                "output_dimensionality": _dimensions(),
                "embed_content_config": {"task_type": task_type},
            }, ensure_ascii=False).encode("utf-8"),
            headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST")
    else:
        payload_text = _instruction_prefix(model, task_type) + str(text)[:20_000]
        request = urllib.request.Request(
            base_url + "/embeddings",
            data=json.dumps({"model": model, "input": payload_text},
                            ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, method="POST")
    started = time.monotonic()
    entry = {"task": "talent_embedding", "provider": provider, "model": model,
             "capability": "EMBEDDING", "route_reason": "embedding_config",
             "prompt_tokens": None, "completion_tokens": 0, "ok": False, "error": ""}
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
        usage = payload.get("usage") or payload.get("usageMetadata") or {}
        tokens = usage.get("prompt_tokens", usage.get("total_tokens", usage.get("promptTokenCount")))
        if type(tokens) is int and tokens >= 0:
            entry["prompt_tokens"] = tokens
        vector = ((payload.get("embedding") or {}).get("values")
                  or ((payload.get("data") or [{}])[0].get("embedding")))
        if (isinstance(vector, list)
                and MIN_DIMENSIONS <= len(vector) <= MAX_DIMENSIONS
                and all(type(value) in (int, float) and math.isfinite(value)
                        for value in vector)):
            entry["ok"] = True
            return vector, model
    except Exception:  # background rebuild records coverage; search must never break
        return None, model
    finally:
        from ai import telemetry
        entry["latency_ms"] = int((time.monotonic() - started) * 1000)
        entry["error"] = "" if entry["ok"] else "embedding_failed"
        telemetry.record(entry)
    return None, model


def index_person(person_id, *, with_embeddings=True):
    """Dựng projection + chunk (+ embedding tuỳ chọn) cho MỘT người.

    Embedding tách khỏi projection có chủ đích: lúc nhận dữ liệu chỉ dựng text —
    rẻ, không gọi mạng, không làm ingest chậm hay hỏng vì provider lỗi. Vector do
    worker nền (`embed_talent_index`) bù sau theo `embedding_fingerprint`.
    """
    person = (Person.objects.filter(pk=person_id, merged_into__isnull=True)
              .select_related("talent_profile")
              .prefetch_related("documents", "source_records").first())
    if person is None:
        PersonSearchDocument.objects.filter(person_id=person_id).delete()
        return None
    content = document_text(person)
    fingerprint = hashlib.sha256(content.encode("utf-8")).hexdigest()
    defaults = {"fingerprint": fingerprint, "content": content,
                "content_norm": fold_text(content)}
    if with_embeddings:
        vector, model = embed(content[:PROJECTION_EMBED_CHARS], task_type="RETRIEVAL_DOCUMENT")
        defaults.update(embedding=vector, embedding_model=model,
                        embedding_fingerprint=fingerprint if vector else "")
    row, _ = PersonSearchDocument.objects.update_or_create(person=person, defaults=defaults)

    seen_docs = []
    for document in person.documents.all():
        seen_docs.append(document.pk)
        existing = {chunk.ordinal: chunk for chunk in
                    CVChunk.objects.filter(document=document).only("ordinal", "fingerprint")}
        ordinal = -1
        for ordinal, text in enumerate(_chunks(document.best_text)):
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            current = existing.get(ordinal)
            # Nội dung đoạn không đổi ⇒ không ghi lại. Ở kho triệu CV, ghi đè mù
            # mỗi lần lưu hồ sơ là nhân bản write + huỷ sạch vector đã tính.
            if current is not None and current.fingerprint == digest and not with_embeddings:
                continue
            values = {"person": person, "fingerprint": digest, "text": text,
                      "text_norm": fold_text(text)}
            if with_embeddings:
                item_vector, item_model = embed(text, task_type="RETRIEVAL_DOCUMENT")
                values.update(embedding=item_vector, embedding_model=item_model,
                              embedding_fingerprint=digest if item_vector else "")
            CVChunk.objects.update_or_create(document=document, ordinal=ordinal,
                                             defaults=values)
        # Đoạn thừa của phiên bản text cũ (CV mới ngắn hơn) phải biến mất.
        CVChunk.objects.filter(document=document, ordinal__gt=ordinal).delete()
    CVChunk.objects.filter(person=person).exclude(document_id__in=seen_docs or [-1]).delete()
    return row


def stale_documents(limit=500):
    """PersonSearchDocument có vector cũ/chưa có — hàng đợi embedding cấp hồ sơ."""
    from django.db.models import F
    return (PersonSearchDocument.objects
            .exclude(embedding_fingerprint=F("fingerprint"))
            .order_by("pk")[:limit])


def stale_chunks(limit=500):
    """CVChunk có vector cũ/chưa có — hàng đợi embedding cấp đoạn CV."""
    from django.db.models import F
    return (CVChunk.objects
            .exclude(embedding_fingerprint=F("fingerprint"))
            .order_by("pk")[:limit])


def search(query, *, limit=250):
    """Return person ids from person + CV vectors, preserving best rank per person."""
    if connection.vendor != "postgresql":
        return []
    vector, model = embed(query, task_type="RETRIEVAL_QUERY")
    if not vector:
        return []
    from pgvector.django import CosineDistance
    rows = list(PersonSearchDocument.objects.exclude(embedding__isnull=True)
                .filter(embedding_model=model)
                .annotate(distance=CosineDistance("embedding", vector))
                .order_by("distance").values_list("person_id", flat=True)[:limit])
    chunks = list(CVChunk.objects.exclude(embedding__isnull=True)
                  .filter(embedding_model=model)
                  .annotate(distance=CosineDistance("embedding", vector))
                  .order_by("distance").values_list("person_id", flat=True)[:limit])
    out = []
    for person_id in rows + chunks:
        if person_id not in out:
            out.append(person_id)
    return out[:limit]
