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
import urllib.error
import urllib.request

from django.conf import settings
from django.db import connection

from people.models import Person
from .models import CVChunk, PersonSearchDocument

#: Ai được phép có mặt trong chỉ mục tìm kiếm Talent, và ai được phép quay ra
#: từ nó. `is_applicant` KHÔNG thừa bên cạnh `merged_into`: mọi đường tất định
#: của Answer Engine (`count`, `resolve`, `superlative`, `structured_match`,
#: `corpus`) đều đi qua `Person.applicants()`. Lệch phạm vi giữa chỉ mục và
#: những đường đó nghĩa là "có bao nhiêu người X" và "liệt kê người X" trả hai
#: con số khác nhau trên cùng một kho.
VISIBLE = {"person__is_applicant": True, "person__merged_into__isnull": True}


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


class VectorDimensionMismatch(RuntimeError):
    """Query and stored vectors cannot safely participate in the same ANN query."""


#: Chờ giữa hai lần gọi embedding khi bị 429. Đủ để vượt cửa sổ giới hạn tốc độ
#: của GreenNode mà không làm người dùng cảm thấy treo.
QUERY_EMBED_RETRY_DELAY = 1.2


class VectorBranchUnavailable(RuntimeError):
    """Nhánh vector không chạy được, và lý do phải nói ra bằng tên riêng.

    `str(exc)` là mã lý do (`vendor_unsupported`, `no_vectors_for_model`,
    `embedding_failed`) để trace và ablation không phải đoán từ một list rỗng.
    """


def _stored_dimension(model):
    """Observed dimension for the active model, without scanning the index."""
    for queryset in (PersonSearchDocument.objects, CVChunk.objects):
        value = (queryset.filter(embedding_model=model)
                 .exclude(embedding__isnull=True)
                 .values_list("embedding", flat=True).first())
        if value is not None:
            return len(value)
    return None


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


#: Lý do lần `embed()` gần nhất thất bại: "" (thành công), "rate_limited"
#: (HTTP 429) hoặc "error". `embed()` cố ý không ném lỗi (tìm kiếm không được vỡ
#: vì embedding), nên worker nền cần kênh này để phân biệt "provider đang giới
#: hạn tốc độ — chờ rồi thử lại ĐÚNG hàng này" với "hàng này hỏng — bỏ qua".
LAST_EMBED_ERROR = ""


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
            _set_embed_error("")
            return vector, model
    except urllib.error.HTTPError as exc:
        _set_embed_error("rate_limited" if exc.code == 429 else "error")
        return None, model
    except Exception:  # background rebuild records coverage; search must never break
        _set_embed_error("error")
        return None, model
    finally:
        from ai import telemetry
        entry["latency_ms"] = int((time.monotonic() - started) * 1000)
        entry["error"] = "" if entry["ok"] else "embedding_failed"
        telemetry.record(entry)
    return None, model


def _set_embed_error(kind):
    global LAST_EMBED_ERROR
    LAST_EMBED_ERROR = kind


def index_person(person_id, *, with_embeddings=True):
    """Dựng projection + chunk (+ embedding tuỳ chọn) cho MỘT người.

    Embedding tách khỏi projection có chủ đích: lúc nhận dữ liệu chỉ dựng text —
    rẻ, không gọi mạng, không làm ingest chậm hay hỏng vì provider lỗi. Vector do
    worker nền (`embed_talent_index`) bù sau theo `embedding_fingerprint`.
    """
    # `applicants()` chứ không chỉ `merged_into__isnull=True`: người có
    # `is_applicant=False` là người được NHẮC TỚI trong CV của người khác (sếp
    # cũ, người giới thiệu — xem `intel/contacts.py`), không phải hồ sơ ứng
    # tuyển. Chỗ đó đã ghi rõ ý định "để tìm kiếm ứng viên và thống kê corpus
    # không đếm họ", nhưng chỉ mình `Person.applicants()` thực thi được — chỉ
    # mục thì không, nên họ vẫn vào pool đọc sâu của Answer Engine và bị gọi là
    # "ứng viên". Không lập chỉ mục họ thì vừa đúng ngữ nghĩa vừa khỏi trả tiền
    # embedding cho hồ sơ không ai được phép tìm thấy.
    person = (Person.applicants().filter(pk=person_id)
              .select_related("talent_profile")
              .prefetch_related("documents", "source_records").first())
    if person is None:
        # Xoá cả chunk, không riêng projection: một người đang là ứng viên rồi
        # bị gộp / bị bỏ cờ ứng tuyển phải RỜI HẲN chỉ mục, nếu không nhánh
        # dense đoạn CV vẫn trả họ về mãi mãi.
        PersonSearchDocument.objects.filter(person_id=person_id).delete()
        CVChunk.objects.filter(person_id=person_id).delete()
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


def missing_projection_ids(limit=500):
    """Ứng viên hợp lệ nhưng CHƯA có `PersonSearchDocument` — bất kể vào hệ
    thống bằng đường nào (nhập tay, nhập hàng loạt tắt `TALENT_INDEX_ON_SAVE`,
    kích hoạt lại sau khi gộp/bỏ cờ ứng tuyển, hay một đường ghi tương lai chưa
    lường trước). Lưới an toàn cuối: không dựa vào việc biết TRƯỚC mọi nơi có
    thể ghi `Person`/`Document`, chỉ so trực tiếp với tập phải có mặt trong
    chỉ mục — đúng `Person.applicants()` mà mọi đường tất định khác đã dùng.
    """
    return list(Person.applicants().filter(search_document__isnull=True)
                .order_by("pk").values_list("pk", flat=True)[:limit])


def current_model():
    """Tên model embedding ĐANG cấu hình (không gọi mạng)."""
    config = _embedding_config()
    return config[3] if config else ""


def has_vectors_for(model):
    """Chỉ mục có vector nào của `model` chưa — hỏi trước khi trả tiền embedding."""
    if not model:
        return False
    return (PersonSearchDocument.objects.filter(embedding_model=model)
            .exclude(embedding__isnull=True).exists()
            or CVChunk.objects.filter(embedding_model=model)
            .exclude(embedding__isnull=True).exists())


def search_scored(query, *, limit=250, person_queryset=None, iterative=False):
    """`[(person_id, distance)]` gần nhất, có thể giới hạn phạm vi bằng SUBQUERY.

    `person_queryset` là một queryset có cột `person_id` (ví dụ `SearchProjection`
    đã lọc cứng). Nó được nhúng thành subquery SQL, **không** kéo danh sách ID về
    Python: ở kho 500k thì `IN (…)` với hàng chục nghìn phần tử vừa chậm vừa vỡ.

    Lọc TRƯỚC (pre-filter) chứ không phải ANN toàn kho rồi lọc sau: post-filter
    làm mất recall khi điều kiện cứng chỉ chọn vài trăm người — top-K của toàn
    kho có thể không chứa ai trong số đó.

    `iterative=True` bật `hnsw.iterative_scan` (pgvector ≥ 0.8) để ANN có filter
    không trả về ít hơn `limit` một cách âm thầm.
    """
    if connection.vendor != "postgresql":
        raise VectorBranchUnavailable("vendor_unsupported")
    if not has_vectors_for(current_model()):
        raise VectorBranchUnavailable("no_vectors_for_model")
    vector, model = embed(query, task_type="RETRIEVAL_QUERY")
    if not vector and LAST_EMBED_ERROR == "rate_limited":
        # Bị giới hạn tốc độ thì đợi một nhịp rồi thử LẠI MỘT LẦN: ablation trên
        # prod 20/09 mất cả nhánh vector của một lượt chỉ vì lời gọi thứ tư
        # trong vài giây bị 429. Một lần thử lại rẻ hơn hẳn việc mất nhánh; hai
        # lần thì bắt đầu ăn vào ngân sách thời gian của lượt hỏi.
        time.sleep(QUERY_EMBED_RETRY_DELAY)
        vector, model = embed(query, task_type="RETRIEVAL_QUERY")
    if not vector:
        # Gọi embedding hỏng (hết hạn mức, mạng, provider) KHÁC với "trong phạm
        # vi không ai có vector". Gộp hai thứ vào một `[]` làm báo cáo ablation
        # nói sai: production 20/09 ghi `no_vectors_in_scope` cho một lượt thực
        # ra là lỗi gọi embedding.
        raise VectorBranchUnavailable(
            "embedding_rate_limited" if LAST_EMBED_ERROR == "rate_limited"
            else "embedding_failed")
    configured = _dimensions()
    stored = _stored_dimension(model)
    observed = len(vector)
    if stored is None or observed != stored or observed != configured:
        raise VectorDimensionMismatch(
            "semantic_degraded: vector dimension mismatch "
            f"configured={configured} query={observed} stored={stored} model={model}")
    from pgvector.django import CosineDistance

    scope = None
    if person_queryset is not None:
        scope = person_queryset.values("person_id")
    if iterative:
        with connection.cursor() as cursor:
            try:
                cursor.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order'")
            except Exception:                      # noqa: BLE001 - pgvector cũ
                pass
    best = {}
    for model_class in (PersonSearchDocument, CVChunk):
        rows = (model_class.objects.exclude(embedding__isnull=True)
                .filter(embedding_model=model, **VISIBLE))
        if scope is not None:
            rows = rows.filter(person_id__in=scope)
        rows = (rows.annotate(distance=CosineDistance("embedding", vector))
                .order_by("distance").values_list("person_id", "distance")[:limit])
        for person_id, distance in rows:
            current = best.get(person_id)
            if current is None or distance < current:
                best[person_id] = distance
    return sorted(best.items(), key=lambda row: (row[1], row[0]))[:limit]


def search(query, *, limit=250):
    """Return person ids from person + CV vectors, preserving best rank per person."""
    if connection.vendor != "postgresql":
        return []
    # Không có vector nào của model đang dùng (vừa đổi model, chưa embed lại —
    # production 12/09→19/09: cấu hình bge-m3, kho toàn vector Gemini) thì KHÔNG
    # gọi embedding: kết quả chắc chắn rỗng mà mỗi lượt hỏi vẫn mất vài giây cho
    # sáu lời gọi mạng. `coverage()` nói rõ trạng thái này trong trace.
    if not has_vectors_for(current_model()):
        return []
    vector, model = embed(query, task_type="RETRIEVAL_QUERY")
    if not vector:
        return []
    configured = _dimensions()
    stored = _stored_dimension(model)
    observed = len(vector)
    if stored is None or observed != stored or observed != configured:
        raise VectorDimensionMismatch(
            "semantic_degraded: vector dimension mismatch "
            f"configured={configured} query={observed} stored={stored} model={model}")
    from pgvector.django import CosineDistance
    # `VISIBLE` là lưới an toàn ở tầng TRUY VẤN, song song với lưới ở tầng lập
    # chỉ mục (`index_person`). Chỉ mục có thể cũ — người vừa bị gộp hoặc vừa bị
    # bỏ cờ ứng tuyển sáng nay vẫn còn vector tới lúc worker chạy lại. Đây là
    # nhánh DUY NHẤT trước đây không lọc gì cả, kể cả `merged_into`.
    rows = list(PersonSearchDocument.objects.exclude(embedding__isnull=True)
                .filter(embedding_model=model, **VISIBLE)
                .annotate(distance=CosineDistance("embedding", vector))
                .order_by("distance").values_list("person_id", flat=True)[:limit])
    chunks = list(CVChunk.objects.exclude(embedding__isnull=True)
                  .filter(embedding_model=model, **VISIBLE)
                  .annotate(distance=CosineDistance("embedding", vector))
                  .order_by("distance").values_list("person_id", flat=True)[:limit])
    out = []
    for person_id in rows + chunks:
        if person_id not in out:
            out.append(person_id)
    return out[:limit]
