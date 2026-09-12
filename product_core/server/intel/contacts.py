# -*- coding: utf-8 -*-
"""Tách liên hệ của ỨNG VIÊN khỏi liên hệ của NGƯỜI THAM CHIẾU trong CV.

Vì sao phải đọc lại text CV thay vì xử lý ô liên hệ Edge gửi lên: Edge nối mọi
email/SĐT bóc được từ CV vào một ô, làm mất sạch ngữ cảnh. Đo trên 283 hồ sơ
thật, giả thiết "giá trị đầu tiên là của ứng viên" chỉ đúng 50%; trong cùng một
ô còn lẫn email bị cắt cụt (`@gmail.co` cạnh `@gmail.com`) và biến thể lỗi OCR.

Text CV thì ngược lại — nó nói thẳng ra: "NGƯỜI THAM CHIẾU: Nguyễn Văn A —
Trưởng phòng — SeABank — 0912345678". Vị trí trong văn bản và tiêu đề mục chính
là sự thật gốc, nên bộ bóc phải làm việc trên đó.

Kỷ luật gọi AI ở đây giống `core/cv_parsing.py::can_ai_chuan_hoa`: chỉ gọi khi
CV thật sự có dấu hiệu mục tham chiếu. Phần lớn CV không có, và gọi cho mọi hồ
sơ là tốn tiền để nhận về danh sách rỗng.
"""
import hashlib
import json
import logging
import re

from ai.adapter import ModelError, ModelRequest, get_adapter
from ai.prompt_guard import GUARD_RULE, wrap_source
from django.utils import timezone
from people.models import ContactMention, Person, PersonLink
from people.normalize import normalize_email, normalize_phone
from people.resolution import contact_pool

log = logging.getLogger(__name__)

EXTRACTION_TASK = "cv_reference_extraction"
EXTRACTOR = "radar_contacts"
#: Liên hệ vớt từ ô gộp Edge gửi (cv_emails/cv_phones), CHƯA biết của ai.
EXTRACTOR_BLOB = "edge_blob"
#: Điểm tin cho liên hệ vớt từ ô gộp: đủ thấp để `promote_confident` (gate 0.80)
#: KHÔNG bao giờ tự thăng hạng — chúng luôn phải qua người xem.
BLOB_CONFIDENCE = 0.25
SCHEMA_VERSION = 1

#: Dấu hiệu CV có mục người tham chiếu. Rẻ, chạy trên mọi CV; chỉ khi khớp mới
#: gọi AI. Cố ý gồm cả tiếng Anh (CV ngành ngân hàng hay song ngữ).
_REFERENCE_MARKERS = (
    "người tham chiếu", "nguoi tham chieu", "tham chiếu", "tham chieu",
    "người giới thiệu", "nguoi gioi thieu", "người liên hệ", "nguoi lien he",
    "liên hệ khẩn cấp", "lien he khan cap", "người bảo lãnh",
    "reference", "references", "referee", "referred by",
    "emergency contact", "contact person",
)

_PROMPT = (
    "Bạn đọc CV để tách liên hệ của CHÍNH ứng viên khỏi liên hệ của người khác "
    "được nhắc tới trong CV (người tham chiếu, người giới thiệu, liên hệ khẩn "
    "cấp). CHỈ ghi lại thứ CV nêu rõ. TUYỆT ĐỐI không suy diễn, không bịa email "
    "hay số điện thoại không có trong văn bản. Mỗi người được nhắc tới phải kèm "
    "evidence là trích dẫn NGUYÊN VĂN từ CV (tối đa 200 ký tự).\n" + GUARD_RULE
)

_KIND_ALIASES = {
    "reference": ContactMention.KIND_REFERENCE,
    "referee": ContactMention.KIND_REFERENCE,
    "tham_chieu": ContactMention.KIND_REFERENCE,
    "referrer": ContactMention.KIND_REFERRER,
    "referred_by": ContactMention.KIND_REFERRER,
    "gioi_thieu": ContactMention.KIND_REFERRER,
    "emergency": ContactMention.KIND_EMERGENCY,
    "khan_cap": ContactMention.KIND_EMERGENCY,
    "self": ContactMention.KIND_SELF,
    "candidate": ContactMention.KIND_SELF,
}


def has_reference_markers(text):
    """CV này có đáng gọi AI không. Không khớp dấu hiệu nào thì bỏ qua."""
    folded = str(text or "").lower()
    return any(marker in folded for marker in _REFERENCE_MARKERS)


def _digits(value):
    return re.sub(r"\D", "", str(value or ""))


def _appears_in(value, cv_text, cv_digits):
    """Giá trị này có THẬT trong CV không — chốt chặn chống AI bịa.

    Với email so khớp chữ; với số điện thoại so trên chuỗi chỉ-chữ-số của cả CV,
    vì CV viết "0912 345 678" hay "(+84) 912.345.678" đều là cùng một số.
    """
    text = str(value or "").strip()
    if not text:
        return False
    if "@" in text:
        return text.lower() in cv_text.lower()
    digits = _digits(text)
    return len(digits) >= 8 and digits in cv_digits


def _fingerprint(subject_id, document_id, email, phone, full_name):
    raw = "|".join((str(subject_id), str(document_id or ""), email, phone,
                    str(full_name or "").strip().lower(), str(SCHEMA_VERSION)))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _parse_json(text):
    text = str(text or "").strip()
    if "```" in text:
        found = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
        if found:
            text = found.group(1)
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        return payload["result"]
    return payload if isinstance(payload, dict) else None


def extract_contacts(cv_text, candidate_hint="", adapter=None):
    """Gọi AI một lượt. Trả `(dict đã lọc, usage)`.

    Mọi email/SĐT không xuất hiện nguyên văn trong `cv_text` đều bị loại tại
    đây — model không được phép "nhớ hộ" một địa chỉ nào.
    """
    cv_text = str(cv_text or "")
    request = ModelRequest(
        messages=[
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": wrap_source(cv_text[:12000], "CV")},
            {"role": "user", "content":
                f"Ứng viên của CV này tên là: {candidate_hint or '(không rõ)'}.\n"
                'Trả JSON {"candidate": {"emails": [], "phones": []}, '
                '"references": [{"full_name": "", "title": "", "company": "", '
                '"email": "", "phone": "", "kind": "reference|referrer|emergency", '
                '"relationship": "", "evidence": "", "confidence": 0.0}]}. '
                "references rỗng nếu CV không nhắc tới ai khác."},
        ],
        # `reasoning_effort="none"` bắt buộc: thiếu nó, cùng hạ tầng này từng
        # mất 40s/lượt và hỏng JSON ~50% vì model tiêu hết ngân sách token để
        # "nghĩ" thay vì viết JSON (xem intel/extraction.py).
        task=EXTRACTION_TASK, temperature=0.0, max_tokens=2000,
        response_format={"type": "json_object"},
        extra={"reasoning_effort": "none"})
    try:
        response = (adapter or get_adapter()).complete(request)
    except ModelError as exc:
        log.warning("Bóc liên hệ lỗi: %s", exc)
        return {}, {}

    usage = {"model": response.model,
             "prompt_tokens": response.usage.prompt_tokens,
             "completion_tokens": response.usage.completion_tokens}
    data = _parse_json(response.text)
    if data is None:
        usage["parse_failed"] = True
        log.warning("Bóc liên hệ: %s trả %d token nhưng không đọc ra JSON. Đầu ra: %.120r",
                    response.model, response.usage.completion_tokens, response.text)
        return {}, usage

    cv_digits = _digits(cv_text)
    candidate = data.get("candidate") or {}
    cleaned = {
        "candidate": {
            "emails": [e for e in _as_list(candidate.get("emails"))
                       if _appears_in(e, cv_text, cv_digits)],
            "phones": [p for p in _as_list(candidate.get("phones"))
                       if _appears_in(p, cv_text, cv_digits)],
        },
        "references": [],
    }
    for item in data.get("references") or []:
        if not isinstance(item, dict):
            continue
        email = str(item.get("email") or "").strip()
        phone = str(item.get("phone") or "").strip()
        if email and not _appears_in(email, cv_text, cv_digits):
            email = ""
        if phone and not _appears_in(phone, cv_text, cv_digits):
            phone = ""
        # Một người được nhắc tới mà không có cách nào liên hệ thì chưa dùng
        # được cho cả tuyển dụng lẫn bán hàng — bỏ, đừng tạo bản ghi rỗng.
        if not email and not phone:
            continue
        cleaned["references"].append({
            "full_name": str(item.get("full_name") or "")[:200],
            "title": str(item.get("title") or "")[:200],
            "company": str(item.get("company") or "")[:200],
            "relationship": str(item.get("relationship") or "")[:200],
            "email_raw": email, "phone_raw": phone,
            "kind": _KIND_ALIASES.get(str(item.get("kind") or "").strip().lower(),
                                      ContactMention.KIND_REFERENCE),
            "evidence": str(item.get("evidence") or "")[:400],
            "confidence": _as_confidence(item.get("confidence")),
        })
    return cleaned, usage


def _as_list(value):
    if value in (None, "", [], {}):
        return []
    return [str(v).strip() for v in (value if isinstance(value, list) else [value])
            if str(v).strip()]


def _as_confidence(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    if number > 1:
        number /= 100
    return max(0.0, min(1.0, number))


def record_mentions(person, document, extracted, model=""):
    """Ghi các liên hệ đã bóc vào `ContactMention`. Trả list bản ghi.

    CHƯA tạo Person ở bước này: bóc xong chưa chắc đúng, và tạo người thật từ
    một lượt gọi AI chưa ai xem là cách nhanh nhất để làm bẩn kho dữ liệu.
    """
    saved = []
    for item in (extracted or {}).get("references") or []:
        email = normalize_email(item.get("email_raw"))
        phone = normalize_phone(item.get("phone_raw"))
        if not email and not phone:
            continue
        fingerprint = _fingerprint(person.pk, document.pk if document else "",
                                   email, phone, item.get("full_name"))
        mention, _ = ContactMention.objects.update_or_create(
            fingerprint=fingerprint,
            defaults={
                "subject": person, "document": document,
                "full_name": item.get("full_name", ""),
                "title": item.get("title", ""),
                "company": item.get("company", ""),
                "relationship_note": item.get("relationship", ""),
                "email_raw": item.get("email_raw", "")[:300],
                "phone_raw": item.get("phone_raw", "")[:100],
                "email": email, "phone": phone,
                "kind": item.get("kind", ContactMention.KIND_REFERENCE),
                "confidence": item.get("confidence", 0.5),
                "evidence": item.get("evidence", ""),
                "extractor": EXTRACTOR, "model": model,
            })
        saved.append(mention)
    return saved


def record_blob_contacts(person, records):
    """Ghi các email/SĐT DƯ trong ô liên hệ gộp Edge gửi (`cv_emails`/`cv_phones`).

    `intel/extraction._extract_contacts` chỉ bắt được người tham chiếu khi text CV
    có tiêu đề rõ ("NGƯỜI THAM CHIẾU: ..."). CV liệt kê người giới thiệu chen ngang
    một dòng thì lọt. Nhưng Edge vẫn vớt được email/SĐT của họ vào `cv_emails`/
    `cv_phones` — chỉ là không biết của ai.

    Ở đây ghi phần dư đó thành `ContactMention` điểm tin THẤP, không tên, không
    bằng chứng, `status=proposed` — để nằm trong hàng đợi cho người xem chứ không
    mất hẳn. `promote_confident` sẽ không đụng vì dưới ngưỡng.

    Bỏ qua email/SĐT đã có `ContactMention` (đường AI text ưu tiên hơn vì có ngữ
    cảnh) và liên hệ của chính ứng viên.
    """
    payload = {}
    for record in records:                       # gộp các key liên hệ, mới nhất trước
        for key in ("cv_emails", "cv_phones", "email", "phone", "fullname"):
            payload.setdefault(key, (record.payload or {}).get(key))
    pool = contact_pool(payload)
    others = [("email", value) for value in pool["extra_emails"]] + \
             [("phone", value) for value in pool["extra_phones"]]
    if not others:
        return []

    seen = set()
    for email, phone in ContactMention.objects.filter(
            subject=person).values_list("email", "phone"):
        seen.add(("email", email))
        seen.add(("phone", phone))

    saved = []
    for kind, value in others:
        if (kind, value) in seen:
            continue
        email = value if kind == "email" else ""
        phone = value if kind == "phone" else ""
        fingerprint = _fingerprint(person.pk, "", email, phone, EXTRACTOR_BLOB)
        mention, _ = ContactMention.objects.update_or_create(
            fingerprint=fingerprint,
            defaults={
                "subject": person, "document": None,
                "email": email, "phone": phone,
                "email_raw": email, "phone_raw": phone,
                "kind": ContactMention.KIND_REFERENCE,
                "confidence": BLOB_CONFIDENCE,
                "evidence": "Vớt từ ô liên hệ gộp Edge gửi; chưa xác định của ai.",
                "extractor": EXTRACTOR_BLOB, "model": "",
            })
        saved.append(mention)
    return saved


#: `ContactMention.kind` → `PersonLink.kind`. `self` không có mặt: đó là liên hệ
#: của chính ứng viên, không sinh ra quan hệ với ai.
_LINK_KIND = {
    ContactMention.KIND_REFERENCE: PersonLink.KIND_REFERENCE,
    ContactMention.KIND_REFERRER: PersonLink.KIND_REFERRED_BY,
    ContactMention.KIND_EMERGENCY: PersonLink.KIND_REFERENCE,
}


def promote(mention, created_by=""):
    """Biến một `ContactMention` đã duyệt thành Person thật + quan hệ.

    Dùng lại `people.resolution.resolve()` thay vì tự tạo Person: nhờ vậy được
    luôn khử trùng theo `Identity` và cơ chế xử lý xung đột. Hệ quả đẹp — nếu
    người tham chiếu này về sau TỰ ỨNG TUYỂN, trùng email sẽ khớp vào đúng
    Person đang có và toàn bộ lịch sử quan hệ còn nguyên.
    """
    from people import resolution

    if mention.kind == ContactMention.KIND_SELF:
        return None
    result = resolution.resolve({
        "fullname": mention.full_name,
        "email": mention.email,
        "phone": mention.phone,
        "position": mention.title,
    })
    if result.person is None:
        # SKIPPED (không có định danh) hoặc CONFLICT (cần người xử lý).
        return None

    person = result.person
    if result.outcome == resolution.CREATED:
        # Người này chưa từng ứng tuyển: đánh dấu để tìm kiếm ứng viên và thống
        # kê corpus không đếm họ như một hồ sơ ứng tuyển.
        Person.objects.filter(pk=person.pk).update(
            origin=Person.ORIGIN_CV_REFERENCE, is_applicant=False,
            updated_at=timezone.now())
        person.origin = Person.ORIGIN_CV_REFERENCE
        person.is_applicant = False

    if person.pk != mention.subject_id:
        PersonLink.objects.update_or_create(
            subject=mention.subject, related=person,
            kind=_LINK_KIND.get(mention.kind, PersonLink.KIND_REFERENCE),
            defaults={"confidence": mention.confidence,
                      "source_document": mention.document,
                      "created_by": created_by,
                      "evidence": {"quote": mention.evidence,
                                   "title": mention.title,
                                   "company": mention.company,
                                   "relationship": mention.relationship_note}})

    mention.linked_person = person
    mention.status = ContactMention.STATUS_ACCEPTED
    mention.save(update_fields=["linked_person", "status", "updated_at"])
    _raise_sales_signal(person, mention)
    return person


def _raise_sales_signal(person, mention):
    """Đưa người tham chiếu vào pool bán hàng qua đúng cửa đã có.

    `people.Signal(domain="rb")` là đầu vào chuẩn của `rb.routing.route_signal`,
    và nó chạy tiếp cả chuỗi ProductInterest → OpportunitySuggestion. Đi đường
    này thay vì tự tạo RBProfile nghĩa là được luôn phần chấm điểm, phân RM phụ
    trách và — quan trọng nhất — provenance: nhìn `Signal.evidence` là biết cơ
    hội này đến từ CV của ai.

    Lỗi bị nuốt: Person và quan hệ đã ghi xong; hỏng ở nhánh bán hàng không được
    kéo đổ cả bước thăng hạng.
    """
    from django.utils import timezone
    from people.models import Signal

    try:
        signal = Signal.objects.create(
            person=person, domain=Signal.DOMAIN_RB,
            signal_type="cv_reference", source="cv_reference",
            confidence=mention.confidence,
            observed_at=timezone.now(),
            evidence={"quote": mention.evidence,
                      "title": mention.title,
                      "company": mention.company,
                      "gioi_thieu_boi_person_id": mention.subject_id,
                      "document_id": mention.document_id})
        from rb.routing import route_signal
        route_signal(signal)
    except Exception:                            # noqa: BLE001 — xem docstring
        log.exception("Không đưa được người tham chiếu %s sang pool bán hàng", person.pk)


#: Ngưỡng tự thăng hạng. Cùng triết lý `auto_accept` của `intel/field_rules.py`:
#: giá trị đã qua chốt chặn "phải có nguyên văn trong CV" và model tự tin cao thì
#: nhận luôn; còn lại nằm ở `proposed` chờ người xem. Đặt cao vì thăng hạng nghĩa
#: là tạo một CON NGƯỜI mới trong kho — sai thì bẩn dữ liệu của cả hai nghiệp vụ.
AUTO_PROMOTE_GATE = 0.80


def promote_confident(mentions, created_by="auto"):
    """Thăng hạng các bản ghi đủ tin cậy. Trả số Person đã tạo/khớp."""
    promoted = 0
    for mention in mentions:
        if mention.status != ContactMention.STATUS_PROPOSED:
            continue
        if mention.confidence < AUTO_PROMOTE_GATE:
            continue
        try:
            if promote(mention, created_by=created_by) is not None:
                promoted += 1
        except Exception:                        # noqa: BLE001
            log.exception("Không thăng hạng được ContactMention %s", mention.pk)
    return promoted
