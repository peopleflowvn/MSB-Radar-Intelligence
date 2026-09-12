# -*- coding: utf-8 -*-
"""Pipeline Edge-first + AI-fill-gaps (Master Plan §7.1, §7.2, §21.4, §21.6).

Một lượt xử lý một Person:

1. Đọc SourceRecord (mới nhất trước) + hồ sơ hiện có + curated.
2. Ánh xạ field Edge → fact (`source_kind=edge`). KHÔNG gọi AI cho phần này.
3. Đọc `Document.best_text` — KHÔNG parsing lại.
4. Xác định field còn thiếu.
5. (tuỳ chọn) MỘT lượt gọi AI: chỉ gửi phần text cần + danh sách field thiếu.
6. Validate → chuẩn hoá → ghi fact (`source_kind=ai`/`cv_text`).
7. Auto-accept field an toàn/confidence cao/không curated; còn lại vào review.
8. Ghi coverage report (§21.6).

AI trong extraction: tool calling **tắt**, output theo JSON allowlist, source text
bọc như dữ liệu (§21.4).
"""
import json
import logging

from ai.adapter import ModelError, ModelRequest, get_adapter
from ai.prompt_guard import GUARD_RULE, wrap_source

from . import edge_mapper
from .facts import current_facts, record_fact
from .field_rules import KNOWN_FIELDS
from .models import ExtractedFact, ExtractionRun

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
EXTRACTION_TASK = "candidate_extraction"

# Field AI được phép điền từ text CV. Loại các trường chỉ Edge/nghiệp vụ mới có.
_AI_FILLABLE = {
    "city", "current_title", "current_company", "seniority", "years_experience",
    "education_level", "university", "major", "graduation_year", "gpa",
    "skills", "industries", "languages", "certifications", "experience_summary",
    "achievements",
}
_AI_ALLOWLIST = sorted(_AI_FILLABLE)

_PROMPT = (
    "Bạn trích thông tin từ CV. CHỈ điền field khi CV nêu rõ; không có thì bỏ qua, "
    "TUYỆT ĐỐI không suy diễn hay bịa. Mỗi field trả kèm evidence là trích dẫn "
    "nguyên văn (tối đa 200 ký tự) và confidence 0..1.\n" + GUARD_RULE
)


def run_for_person(person, *, dry_run=False, use_ai=True, adapter=None, job=None):
    run = ExtractionRun.objects.create(
        person=person, dry_run=dry_run, schema_version=SCHEMA_VERSION)
    coverage = {"edge": 0, "profile": 0, "cv_text": 0, "ai": 0,
                "missing": 0, "conflict": 0, "ai_calls": 0,
                "prompt_tokens": 0, "completion_tokens": 0, "reused_no_ai": True}
    try:
        records = _ordered_records(person)

        # --- bước 2: Edge mapping ---
        edge_fields = set()
        for record in records:
            for row in edge_mapper.map_record(record):
                field = row["field"]
                if field not in KNOWN_FIELDS:
                    continue
                edge_fields.add(field)
                if dry_run:
                    continue
                _, created = record_fact(
                    person, field, row["raw_value"],
                    source_kind=ExtractedFact.SOURCE_EDGE, run=run,
                    confidence=0.95, source_record=record,
                    extractor="edge_mapping", schema_version=SCHEMA_VERSION,
                    observed_at=row["observed_at"])
                if created:
                    coverage["edge"] += 1

        # --- bước 3–4: text CV + field còn thiếu ---
        cv_text, document = _best_cv_text(person)
        have = set(edge_fields) | {f.field for f in current_facts(person)}
        missing = sorted((KNOWN_FIELDS & _AI_FILLABLE) - have)
        coverage["missing"] = len(missing)

        # --- bước 5–7: AI fill gaps ---
        if use_ai and cv_text and missing and not dry_run:
            coverage["reused_no_ai"] = False
            missing_set = set(missing)
            got, usage = _ai_extract(cv_text, missing, adapter or get_adapter())
            coverage["ai_calls"] = 1
            coverage["prompt_tokens"] = usage.get("prompt_tokens", 0)
            coverage["completion_tokens"] = usage.get("completion_tokens", 0)
            coverage["ai_model"] = usage.get("model", "")
            # Gọi AI, tốn token, mà không ra field nào — phải nhìn thấy được ở
            # `coverage`, đừng để lượt chạy đóng lại im lìm ở trạng thái `done`.
            if usage.get("parse_failed"):
                coverage["ai_parse_failed"] = True
            elif not got:
                coverage["ai_empty"] = True
            for field, item in got.items():
                # Chỉ nhận field ĐÚNG là field còn thiếu đã hỏi — không để AI đè
                # lên trường Edge đã có (§7.2).
                if field not in _AI_FILLABLE or field not in missing_set:
                    continue
                # Model có thể trả {value,evidence,confidence} hoặc trả thẳng giá trị.
                if isinstance(item, dict):
                    value, evidence, conf = (item.get("value"), item.get("evidence"),
                                             item.get("confidence"))
                else:
                    # Model trả giá trị thẳng, không có evidence/confidence: đủ để
                    # qua gate thường (0.70–0.75) nhưng không qua gate cao (0.80+).
                    value, evidence, conf = item, "", 0.75
                if value in (None, "", [], {}):
                    continue
                values = value if isinstance(value, list) else [value]
                for one in values:
                    if not str(one).strip():
                        continue
                    _, created = record_fact(
                        person, field, str(one),
                        source_kind=ExtractedFact.SOURCE_AI, run=run,
                        confidence=_as_confidence(conf),
                        evidence=str(evidence or "")[:400],
                        document=document, extractor="radar_ai",
                        model=usage.get("model", ""), schema_version=SCHEMA_VERSION,
                        observed_at=_doc_observed(document))
                    if created:
                        coverage["ai"] += 1

        # --- bước 8: tách liên hệ ứng viên khỏi liên hệ người tham chiếu ---
        # Chạy ở đây vì text CV đã đọc sẵn. Có cổng `has_reference_markers` nên
        # phần lớn CV không tốn lượt gọi nào.
        if use_ai and cv_text and not dry_run:
            coverage["contacts"] = _extract_contacts(
                person, document, cv_text, adapter=adapter)
        # Phần dư trong ô liên hệ gộp Edge gửi (cv_emails/cv_phones) mà đường AI
        # text không chạm tới — ghi lại điểm tin thấp cho người xem, đừng để mất.
        if not dry_run:
            try:
                from . import contacts
                mentions = contacts.record_blob_contacts(person, records)
                coverage["blob_contacts"] = len(mentions)
            except Exception:                       # noqa: BLE001
                log.exception("Không ghi được liên hệ vớt cho Person %s", person.pk)

        coverage["conflict"] = person.facts.filter(
            run=run, status=ExtractedFact.STATUS_CONFLICT).count() if not dry_run else 0

        # --- bước 9: fact → bề mặt tìm kiếm ---
        # Không có bước này thì fact vừa bóc chỉ nằm trong bảng ExtractedFact và
        # chỉ giúp đúng một nhánh hẹp (lọc theo mã canonical). `apply_extracted_facts`
        # đổ chúng vào TalentProfile (nguồn của tìm kiếm cấu trúc + chỉ mục ngữ
        # nghĩa), `build_for_person` dựng MaterializedProfile cho lọc nhanh.
        if not dry_run:
            _project_to_search(person)

        run.coverage = coverage
        run.finish(ExtractionRun.STATUS_DONE)
    except Exception as exc:                    # noqa: BLE001
        log.exception("Extraction lỗi cho Person %s", person.pk)
        run.coverage = coverage
        run.finish(ExtractionRun.STATUS_FAILED, error=str(exc))
    return run


# --------------------------------------------------------------------------- #
def _project_to_search(person):
    """Đưa fact vừa bóc lên bề mặt tìm kiếm. Lỗi bị nuốt: fact đã ghi xong.

    `apply_extracted_facts` lấp cột `TalentProfile` còn trống — đó là nguồn của
    tìm kiếm cấu trúc, chỉ mục ngữ nghĩa và Person 360, nên lưu profile kéo theo
    `post_save` dựng lại chỉ mục.

    CỐ Ý KHÔNG gọi `intel.projection.build_for_person` ở đây. `MaterializedProfile`
    là tối ưu hoá cho kịch bản triệu hồ sơ (Master Plan §21.7) — search đọc một
    ảnh phẳng thay vì join hàng nghìn fact. Ở quy mô hiện tại, bộ lọc mã canonical
    trong `talent/search.py` truy `ExtractedFact` qua index `(person, field,
    is_current)` là đủ nhanh, và `MaterializedProfile` hiện KHÔNG có nơi nào đọc.
    Auto-ghi một bảng không ai đọc chỉ là nợ. Khi quy mô đòi hỏi, dựng đường đọc
    bằng bảng nối chuẩn hoá `PersonCode(person, bucket, code)` (lọc có index, chạy
    được trên cả SQLite lẫn Postgres) — KHÔNG dùng JSON-containment. Lệnh
    `rebuild_search_projection` vẫn còn để dựng lại thủ công khi cần đối chiếu.
    """
    try:
        from talent.derive import apply_extracted_facts
        apply_extracted_facts(person)
    except Exception:                            # noqa: BLE001
        log.exception("Không đổ fact vào TalentProfile cho Person %s", person.pk)


def _extract_contacts(person, document, cv_text, adapter=None):
    """Ghi các liên hệ người tham chiếu tìm thấy trong CV. Trả số bản ghi mới.

    Lỗi bị nuốt có chủ đích: đây là bước phụ, không được phép làm hỏng cả lượt
    extraction đã ghi xong fact ở các bước trên.
    """
    from . import contacts
    if not contacts.has_reference_markers(cv_text):
        return 0
    try:
        found, usage = contacts.extract_contacts(
            cv_text, person.display_name, adapter=adapter)
        saved = contacts.record_mentions(person, document, found,
                                         model=usage.get("model", ""))
        contacts.promote_confident(saved)
        return len(saved)
    except Exception:                            # noqa: BLE001 — xem docstring
        log.exception("Không bóc được liên hệ tham chiếu cho Person %s", person.pk)
        return 0


def _ordered_records(person):
    records = list(person.source_records.all())
    return sorted(records,
                  key=lambda r: str((r.payload or {}).get("applied_ts") or ""),
                  reverse=True)


def _best_cv_text(person):
    doc = (person.documents
           .filter(document_type="cv", parse_status="done")
           .order_by("-observed_at", "-created_at").first())
    if doc and doc.best_text:
        return doc.best_text, doc
    return "", None


def _doc_observed(document):
    if document and document.observed_at:
        return document.observed_at
    return None


def _as_confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number > 1:
        number /= 100
    return max(0.0, min(1.0, number))


def _ai_extract(cv_text, missing, adapter):
    fields_line = ", ".join(missing)
    request = ModelRequest(
        messages=[
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": wrap_source(cv_text[:12000], "CV")},
            {"role": "user", "content":
                f"Trích các field còn thiếu: {fields_line}. "
                'Trả JSON {"<field>": {"value": ..., "evidence": "...", "confidence": 0.0}}. '
                "value của skills/industries/languages/certifications/achievements "
                "là mảng chuỗi."},
        ],
        # `reasoning_effort="none"` là chỗ hay quên nhất trong cả hệ — THIẾU nó
        # từng làm việc này 40s/lượt và JSON hỏng ~50% (model "nghĩ" hết ngân
        # sách token thay vì viết JSON: đo được 5000-6000 token sinh ra cho một
        # yêu cầu max_tokens=1200). Có nó: 6,1s TB, JSON hợp lệ 4/4 trên CV thật
        # (đo trên production 05/09). max_tokens nâng 1200→2000: 14 trường kèm
        # evidence/confidence dễ vượt 1200 với CV nhiều bằng cấp/chứng chỉ.
        task=EXTRACTION_TASK, temperature=0.0, max_tokens=2000,
        response_format={"type": "json_object"},
        extra={"reasoning_effort": "none"})
    try:
        response = adapter.complete(request)
    except ModelError as exc:
        log.warning("AI extraction lỗi: %s", exc)
        return {}, {}
    data = _parse_json(response.text)
    usage = {"prompt_tokens": response.usage.prompt_tokens,
             "completion_tokens": response.usage.completion_tokens,
             "model": response.model}
    # Model TRẢ LỜI mà không đọc ra được field nào là hỏng, không phải "CV này
    # không có gì". Trước đây `_parse_json` nuốt lỗi rồi trả `{}`, `run_for_person`
    # ghi `ai=0` và đóng lượt chạy ở trạng thái `done` — nên không ai thấy gì sai.
    #
    # Đo trên production 04/09/2026, ba CV thật: cả ba đều `done`, 0/14 field,
    # tốn ~1.500 token mỗi lượt. Chuỗi thật là: GreenNode timeout (prompt 12K ký
    # tự) → router rơi sang gemini → gemini trả 30–129 token, JSON cụt giữa khoá
    # → parse hỏng → rỗng. Ba tầng đều "hoạt động bình thường" theo cách nhìn
    # của riêng nó, và hợp lại thành một tính năng chạy tốn tiền mà không ra gì.
    #
    # `usage["parse_failed"]` để `coverage` mang được dấu hiệu ấy lên trên.
    if data is None:
        usage["parse_failed"] = True
        log.warning(
            "AI extraction: %s trả %d token nhưng không đọc ra JSON "
            "(hỏng hoặc cụt giữa chừng). Đầu ra: %.120r",
            response.model, response.usage.completion_tokens, response.text)
    return (data if isinstance(data, dict) else {}), usage


def _parse_json(text):
    """Trả dict đã đọc được, hoặc **None** khi không đọc nổi.

    Trước đây trả `{}` cho cả hai trường hợp, nên chỗ gọi không phân biệt được
    *"CV này không có field nào"* với *"model trả ra rác"*. Gộp hai thứ ấy làm
    một là mất đúng thông tin cần để sửa: một bên phải đi chỉnh hạ tầng (timeout,
    hạn mức token, nhà cung cấp), một bên thì không cần làm gì cả.
    """
    text = str(text or "").strip()
    if "```" in text:
        import re
        m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
        if m:
            text = m.group(1)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(payload, dict) and "result" in payload and isinstance(payload["result"], dict):
        return payload["result"]
    return payload


def coverage_summary(runs):
    """Tổng hợp coverage của nhiều run — cho dashboard/gate (§21.6)."""
    agg = {"runs": 0, "edge": 0, "profile": 0, "cv_text": 0, "ai": 0, "missing": 0,
           "ai_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
           "runs_without_ai": 0}
    for run in runs:
        cov = run.coverage or {}
        agg["runs"] += 1
        for key in ("edge", "profile", "cv_text", "ai", "missing", "ai_calls",
                    "prompt_tokens", "completion_tokens"):
            agg[key] += int(cov.get(key) or 0)
        if cov.get("reused_no_ai"):
            agg["runs_without_ai"] += 1
    total_fields = agg["edge"] + agg["profile"] + agg["cv_text"] + agg["ai"]
    agg["edge_reuse_ratio"] = round(
        (agg["edge"] + agg["profile"]) / total_fields, 3) if total_fields else None
    return agg
