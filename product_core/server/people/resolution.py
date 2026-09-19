# -*- coding: utf-8 -*-
"""Phân giải SourceRecord thành Person (Master Plan mục 12).

Đây là chỗ nguy hiểm nhất của hệ thống. Hai kiểu sai, hậu quả rất khác nhau:

    Gộp nhầm  hai người thành một Person. Hồ sơ trộn lẫn, CV của người này nằm
              dưới tên người kia. Gần như không gỡ lại được, và thường chỉ bị
              phát hiện khi recruiter gọi nhầm người.
    Tách nhầm một người thành hai Person. Phiền, làm mất bối cảnh lịch sử,
              nhưng gộp lại được bất cứ lúc nào.

Vì vậy mọi lựa chọn ở đây đều nghiêng về TÁCH: thà bỏ sót một phép khớp còn hơn
khớp nhầm. Khi hai định danh mạnh chỉ về hai Person khác nhau, hệ thống KHÔNG tự
gộp mà tạo IdentityConflict cho người xử lý.
"""
import json
import logging

from django.db import IntegrityError, transaction

from .models import (DocumentTextLink, Identity, IdentityConflict, ParsedTextVersion,
                     Person)
from .normalize import (choose_primary_email, choose_primary_phone, dedupe_emails,
                        normalize_email, normalize_name, normalize_phone,
                        normalize_provider_person_id, normalize_url_identity,
                        split_contacts, split_emails)

log = logging.getLogger(__name__)

# Kết quả phân giải
CREATED = "created"          # chưa từng thấy người này
MATCHED = "matched"          # khớp đúng một Person
CONFLICT = "conflict"        # nhiều Person — cần người xử lý
SKIPPED = "skipped"          # không có định danh mạnh nào để khớp


class Resolution:
    """Kết quả một lần phân giải."""

    def __init__(self, outcome, person=None, conflict=None, identities=None):
        self.outcome = outcome
        self.person = person
        self.conflict = conflict
        self.identities = identities or []

    def __repr__(self):
        return f"<Resolution {self.outcome} person={self.person.pk if self.person else None}>"


def _values(payload, key):
    """Đọc một ô liên hệ về danh sách chuỗi, chịu được cả 3 dạng Edge từng gửi.

    `email`/`phone` là chuỗi (có thể chứa nhiều giá trị nối bằng dấu phẩy — định
    dạng cũ), còn `cv_emails`/`cv_phones` của Edge mới là danh sách JSON và tới
    đây có thể là list thật hoặc chuỗi JSON tuỳ đường tuần tự hoá.
    """
    raw = payload.get(key)
    if isinstance(raw, (list, tuple)):
        return [str(item) for item in raw if str(item or "").strip()]
    text = str(raw or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, list):
            return [str(item) for item in parsed if str(item or "").strip()]
    return split_emails(text) if "email" in key else split_contacts(text)


def contact_pool(payload):
    """Mọi email/điện thoại đọc được từ payload, đã chuẩn hoá và khử trùng.

    `primary_*` là giá trị được chọn làm định danh mạnh; `extra_*` là phần còn
    lại — KHÔNG được tự gắn cho ứng viên, chúng đi qua đường có bằng chứng
    (`ContactMention`) để AI đọc lại text CV rồi mới phân xử của ai.
    """
    fullname = payload.get("fullname") or payload.get("full_name") or ""
    emails = dedupe_emails(_values(payload, "email") + _values(payload, "cv_emails"))
    phones = _values(payload, "phone") + _values(payload, "cv_phones")

    primary_email, email_guessed = choose_primary_email(emails, fullname)
    primary_phone, phone_guessed = choose_primary_phone(phones)

    normalized_emails = [value for value in (normalize_email(e) for e in emails) if value]
    normalized_phones, seen = [], set()
    for value in (normalize_phone(p) for p in phones):
        if value and value not in seen:
            seen.add(value)
            normalized_phones.append(value)

    return {
        "primary_email": primary_email,
        "primary_phone": primary_phone,
        "extra_emails": [e for e in normalized_emails if e != primary_email],
        "extra_phones": [p for p in normalized_phones if p != primary_phone],
        # CỐ Ý chỉ tính phần email. Người có hai số điện thoại là chuyện thường
        # và chọn số đầu gần như luôn đúng; bật cờ soát tay cho cả nhóm đó thì
        # 13% kho hàng vào hàng đợi review (đã đo: 36/283) và người dùng sẽ
        # ngừng đọc cờ này — mất luôn tác dụng cảnh báo cho ca thật sự nguy hiểm.
        # `email_guessed` chỉ bật khi có nhiều email mà KHÔNG cái nào khớp tên,
        # tức đúng lúc không biết địa chỉ đang gắn là của ai.
        "guessed": bool(email_guessed),
        "phone_guessed": bool(phone_guessed),
    }


def extract_identities(payload):
    """Rút các định danh mạnh từ payload của một bản ghi nguồn.

    Trả danh sách (kind, value_chuẩn_hoá, value_gốc). Giá trị không chuẩn hoá
    được sẽ bị bỏ — thà không có định danh còn hơn có một định danh sai.

    Ô `email`/`phone` có thể chứa NHIỀU giá trị (Edge gộp mọi liên hệ bóc được
    từ CV vào một ô). Ở đây chỉ lấy ĐÚNG MỘT giá trị mỗi loại làm định danh:
    gắn hết là cách chắc chắn nhất để gộp nhầm hai ứng viên chung một người tham
    chiếu thành một Person. Phần dư nằm ở `contact_pool()["extra_*"]`.
    """
    found = []
    pool = contact_pool(payload)

    if pool["primary_email"]:
        found.append((Identity.KIND_EMAIL, pool["primary_email"],
                      str(payload.get("email") or "")[:300]))

    if pool["primary_phone"]:
        found.append((Identity.KIND_PHONE, pool["primary_phone"],
                      str(payload.get("phone") or "")[:300]))

    for field, kind in (("linkedin", Identity.KIND_LINKEDIN),
                        ("facebook", Identity.KIND_FACEBOOK)):
        url = normalize_url_identity(payload.get(field))
        if url:
            found.append((kind, url, str(payload.get(field) or "")))

    # Mã ứng viên do nguồn cấp. Chỉ dùng candidate_id chứ không dùng cv_id:
    # cv_id là mã của một LƯỢT ỨNG TUYỂN, nên cùng một người nộp hai lần sẽ ra
    # hai cv_id — lấy nó làm định danh người là sai về mặt ngữ nghĩa.
    provider_id = normalize_provider_person_id(
        payload.get("source"), payload.get("candidate_id"))
    if provider_id:
        found.append((Identity.KIND_PROVIDER, provider_id, str(payload.get("candidate_id") or "")))

    return found


def find_people(identities):
    """Tìm các Person đang gắn với những định danh này.

    Trả dict {person_id: [định danh đã khớp]}. Nhiều hơn một khoá nghĩa là xung đột.
    """
    if not identities:
        return {}

    lookup = {}
    rows = Identity.objects.filter(
        kind__in=[k for k, _, _ in identities],
        value__in=[v for _, v, _ in identities],
    ).select_related("person")

    wanted = {(k, v) for k, v, _ in identities}
    for row in rows:
        if (row.kind, row.value) not in wanted:
            continue
        person = row.person.canonical()
        lookup.setdefault(person.pk, {"person": person, "identities": []})
        lookup[person.pk]["identities"].append(row)
    return lookup


@transaction.atomic
def resolve(payload, source_record_id=""):
    """Phân giải một payload thành Person. Không bao giờ tự gộp khi có xung đột."""
    identities = extract_identities(payload)
    if not identities:
        # Không có định danh mạnh nào. Cố ý KHÔNG tạo Person: một bản ghi chỉ có
        # mỗi cái tên sẽ sinh ra vô số Person rác trùng tên, không ai dùng được.
        return Resolution(SKIPPED)

    matches = find_people(identities)

    if len(matches) > 1:
        conflict = _record_conflict(matches, identities, source_record_id)
        return Resolution(CONFLICT, conflict=conflict, identities=identities)

    if len(matches) == 1:
        person = next(iter(matches.values()))["person"]
        _attach_identities(person, identities)
        _mark_applicant(person)
        _refresh_snapshot(person, payload)
        return Resolution(MATCHED, person=person, identities=identities)

    person = Person.objects.create(
        display_name=str(payload.get("fullname") or "").strip()[:200],
        normalized_name=normalize_name(payload.get("fullname"))[:200],
        origin=Person.ORIGIN_APPLICATION,
        is_applicant=True,
    )
    _attach_identities(person, identities)
    _refresh_snapshot(person, payload)
    return Resolution(CREATED, person=person, identities=identities)


def _mark_applicant(person):
    """Người này đã thật sự ứng tuyển — kể cả khi ta gặp họ lần đầu qua CV người khác.

    `origin` giữ nguyên (biết đến qua đâu là chuyện của quá khứ, không đổi);
    chỉ `is_applicant` bật lên, vì đó là thứ tìm kiếm và thống kê tuyển dụng lọc.
    """
    if not person.is_applicant:
        # `.save()`, không `.update()`: phải qua post_save để
        # `person_intelligence_visibility_changed` (talent/signals.py) tái lập
        # chỉ mục pgvector cho người vừa CHUYỂN thành ứng viên lần đầu — một
        # queryset `.update()` ghi thẳng SQL, bỏ qua signal, và người này sẽ
        # thiếu chỉ mục tìm kiếm cho tới khi có một sự kiện không liên quan nào
        # khác tình cờ trigger lại.
        person.is_applicant = True
        person.save(update_fields=["is_applicant", "updated_at"])


def _flag_guessed_contact(person, payload):
    """Bật cờ soát tay khi phải ĐOÁN đâu là liên hệ của chính ứng viên.

    Ô liên hệ có nhiều giá trị mà không giá trị nào khớp tên thì lựa chọn của
    `choose_primary_*` chỉ là phỏng đoán. Người xem cần thấy điều đó trên hồ sơ,
    vì chọn sai nghĩa là Person này đang mang định danh của người khác.
    """
    if person.needs_review or not contact_pool(payload)["guessed"]:
        return
    Person.objects.filter(pk=person.pk).update(needs_review=True)
    person.needs_review = True


def _attach_identities(person, identities):
    """Gắn định danh vào Person, bỏ qua cái đã thuộc về người khác.

    Chạy đua giữa hai tiến trình có thể khiến cùng một định danh được tạo hai
    lần; ràng buộc UNIQUE ở CSDL chặn lại và ta xử lý IntegrityError tại đây
    thay vì để cả lô đồng bộ đổ.
    """
    for kind, value, raw in identities:
        try:
            with transaction.atomic():
                identity, created = Identity.objects.get_or_create(
                    kind=kind, value=value,
                    defaults={"person": person, "raw_value": raw[:300]})
        except IntegrityError:
            continue
        if not created and identity.person_id != person.pk:
            # Định danh đã thuộc về Person khác. Đến được đây nghĩa là dữ liệu
            # thay đổi giữa lúc tra cứu và lúc ghi; để nguyên, không cướp.
            log.warning("Định danh %s:%s đã thuộc Person %s, không gắn sang %s",
                        kind, value, identity.person_id, person.pk)
            continue
        if not created:
            identity.save(update_fields=["last_seen_at"])


def _refresh_snapshot(person, payload):
    """Cập nhật các trường ảnh chụp nhanh của Person.

    Chỉ điền vào chỗ đang trống, KHÔNG ghi đè giá trị đã có. Bản ghi mới không
    nhất thiết là bản ghi đúng hơn: một CV cũ tải về sau vẫn là CV cũ.
    """
    fields = []

    name = str(payload.get("fullname") or "").strip()
    if name and not person.display_name:
        person.display_name = name[:200]
        person.normalized_name = normalize_name(name)[:200]
        fields += ["display_name", "normalized_name"]

    pool = contact_pool(payload)

    if pool["primary_email"] and not person.primary_email:
        person.primary_email = pool["primary_email"][:200]
        fields.append("primary_email")

    if pool["primary_phone"] and not person.primary_phone:
        person.primary_phone = pool["primary_phone"][:20]
        fields.append("primary_phone")

    position = str(payload.get("position") or "").strip()
    if position and not person.headline:
        person.headline = position[:200]
        fields.append("headline")

    location = str(payload.get("city") or payload.get("address") or "").strip()
    if location and not person.location:
        person.location = location[:200]
        fields.append("location")

    if fields:
        person.save(update_fields=fields + ["updated_at"])

    _flag_guessed_contact(person, payload)


def _record_conflict(matches, identities, source_record_id):
    """Ghi nhận xung đột để người xử lý, không tự quyết.

    Nếu đúng tổ hợp Person này đã có xung đột đang mở thì dùng lại, tránh việc
    mỗi lần đồng bộ lại đẻ thêm một phiếu giống hệt.
    """
    people = [entry["person"] for entry in matches.values()]
    person_ids = sorted(p.pk for p in people)

    existing = (IdentityConflict.objects
                .filter(status=IdentityConflict.STATUS_OPEN)
                .filter(people__pk__in=person_ids)
                .distinct())
    for candidate in existing:
        if sorted(candidate.people.values_list("pk", flat=True)) == person_ids:
            return candidate

    evidence = {
        "identities": [{"kind": k, "value": v} for k, v, _ in identities],
        "people": [
            {
                "id": entry["person"].pk,
                "display_name": entry["person"].display_name,
                "matched_by": [{"kind": i.kind, "value": i.value}
                               for i in entry["identities"]],
            }
            for entry in matches.values()
        ],
    }

    conflict = IdentityConflict.objects.create(
        evidence=evidence, source_record_id=str(source_record_id or ""))
    conflict.people.set(people)

    # Đánh dấu để giao diện hiển thị cảnh báo ngay trên hồ sơ, chứ không chỉ
    # nằm trong một hàng đợi mà không ai mở.
    Person.objects.filter(pk__in=person_ids).update(needs_review=True)

    log.info("Xung đột định danh giữa Person %s", person_ids)
    return conflict


@transaction.atomic
def merge(primary, duplicate, note=""):
    """Gộp `duplicate` vào `primary`. **Chỉ được gọi bởi người dùng.**

    Master Plan mục 12: AI không quyết định việc gộp định danh. Hàm này là công
    cụ cho người xử lý sau khi họ đã xem bằng chứng.

    Không xoá `duplicate`: đặt merged_into để mọi liên kết cũ vẫn đi tới được
    Person đúng, và để việc gộp còn lần ra được về sau.
    """
    primary = primary.canonical()
    duplicate = duplicate.canonical()
    if primary.pk == duplicate.pk:
        return primary

    for identity in duplicate.identities.all():
        if Identity.objects.filter(kind=identity.kind, value=identity.value,
                                   person=primary).exists():
            identity.delete()
        else:
            identity.person = primary
            identity.save(update_fields=["person"])

    # Tài liệu có ràng buộc duy nhất theo (person, sha256) — cùng khuôn với
    # Identity và Relationship bên dưới, nên phải xử lý cùng cách.
    #
    # `duplicate.documents.update(person=primary)` sẽ ném IntegrityError ngay
    # khi hai Person cùng giữ một file CV — mà đó chính là tình huống hay gặp
    # nhất khi gộp: một người ứng tuyển hai nơi, nộp cùng một file, được khớp
    # bằng email ở nguồn này và bằng điện thoại ở nguồn kia. Nói cách khác, thao
    # tác gộp hỏng đúng lúc nó cần thiết nhất.
    for document in duplicate.documents.all():
        if primary.documents.filter(sha256=document.sha256).exists():
            # Cùng nội dung thì bản của primary đã đủ. Giữ liên kết lượt ứng
            # tuyển bằng cách chuyển `source_records` sang trước khi xoá, nếu
            # không thì mất dấu "file này dùng cho những lần ứng tuyển nào".
            keeper = primary.documents.get(sha256=document.sha256)
            keeper.source_records.add(*document.source_records.all())
            _move_document_texts(document, keeper, primary)
            if not keeper.storage_key and document.storage_key:
                # Bản của duplicate có file thật, bản của primary chỉ có
                # metadata. Giữ lại đường dẫn kho, nếu không file coi như mất.
                keeper.storage_key = document.storage_key
                keeper.save(update_fields=["storage_key", "updated_at"])
            document.delete()
        else:
            _move_document_texts(document, document, primary)
            document.person = primary
            document.save(update_fields=["person", "updated_at"])

    # Các link đã được trỏ sang ParsedTextVersion thuộc primary; xóa blob cũ để không
    # còn hai bản text giống nhau sau khi gộp định danh.
    duplicate.parsed_text_versions.all().delete()

    duplicate.signals.update(person=primary)
    duplicate.interactions.update(person=primary)
    duplicate.opportunities.update(person=primary)
    duplicate.contact_mentions.update(subject=primary)
    duplicate.mentioned_as.update(linked_person=primary)

    # Quan hệ NGƯỜI ↔ NGƯỜI: ràng buộc duy nhất theo (subject, related, kind) và
    # cấm tự trỏ. Chuyển đầu trỏ về primary, bỏ cái đã tồn tại hoặc hoá tự trỏ.
    for link in list(duplicate.links_out.all()):
        if (link.related_id == primary.pk
                or primary.links_out.filter(related_id=link.related_id,
                                            kind=link.kind).exists()):
            link.delete()
        else:
            link.subject = primary
            link.save(update_fields=["subject"])
    for link in list(duplicate.links_in.all()):
        if (link.subject_id == primary.pk
                or primary.links_in.filter(subject_id=link.subject_id,
                                           kind=link.kind).exists()):
            link.delete()
        else:
            link.related = primary
            link.save(update_fields=["related"])

    # Quan hệ có ràng buộc duy nhất theo (person, domain): chỉ chuyển sang khi
    # primary chưa có quan hệ ở nghiệp vụ đó.
    for relationship in duplicate.relationships.all():
        if primary.relationships.filter(domain=relationship.domain).exists():
            relationship.delete()
        else:
            relationship.person = primary
            relationship.save(update_fields=["person"])

    duplicate.merged_into = primary
    duplicate.needs_review = False
    duplicate.save(update_fields=["merged_into", "needs_review", "updated_at"])

    _fill_gaps(primary, duplicate)

    for conflict in IdentityConflict.objects.filter(
            status=IdentityConflict.STATUS_OPEN, people__pk=duplicate.pk):
        conflict.resolve(IdentityConflict.STATUS_MERGED, note)

    if not IdentityConflict.objects.filter(
            status=IdentityConflict.STATUS_OPEN, people__pk=primary.pk).exists():
        Person.objects.filter(pk=primary.pk).update(needs_review=False)

    return primary


def resolve_identity_conflict(conflict, decision, note=""):
    """Người xử lý một `IdentityConflict`: gộp (CÙNG một người) hoặc bỏ qua
    (HAI người khác nhau). Logic dùng chung cho Django admin
    (`people/admin.py::IdentityConflictAdmin`) VÀ API (`intel/views.py`) — tách
    ra một chỗ vì đây là quyết định nguy hiểm nhất hệ thống (xem docstring
    module); để hai bản trôi khỏi nhau theo thời gian là đúng loại lỗi mà lưu ý
    đó cảnh báo.
    """
    if conflict.status != IdentityConflict.STATUS_OPEN:
        return conflict
    if decision == "merge":
        people = list(conflict.people.order_by("created_at"))
        if len(people) >= 2:
            primary = people[0]
            for duplicate in people[1:]:
                merge(primary, duplicate, note=note)
        else:
            conflict.resolve(IdentityConflict.STATUS_MERGED, note)
    elif decision == "dismiss":
        conflict.resolve(IdentityConflict.STATUS_DISMISSED, note)
        for person in conflict.people.all():
            if not IdentityConflict.objects.filter(
                    status=IdentityConflict.STATUS_OPEN, people__pk=person.pk).exists():
                Person.objects.filter(pk=person.pk).update(needs_review=False)
    else:
        raise ValueError("decision phải là 'merge' hoặc 'dismiss'.")
    conflict.refresh_from_db()
    return conflict


def _move_document_texts(source_document, target_document, primary_person):
    """Chuyển/dedupe các bản parsing khi hai Person được gộp."""
    primary_target_id = None
    for link in source_document.text_links.select_related("text_version").all():
        old_version = link.text_version
        version, _ = ParsedTextVersion.objects.get_or_create(
            person=primary_person, text_hash=old_version.text_hash,
            defaults={"text": old_version.text, "text_length": old_version.text_length})
        target_link, created = DocumentTextLink.objects.get_or_create(
            document=target_document, text_version=version,
            defaults={"origins": link.origins, "provider": link.provider,
                      "model": link.model, "quality_score": link.quality_score})
        if not created:
            origins = list(target_link.origins or [])
            for origin in link.origins or []:
                if origin not in origins:
                    origins.append(origin)
            target_link.origins = origins
            if link.quality_score > target_link.quality_score:
                target_link.quality_score = link.quality_score
                target_link.provider = link.provider
                target_link.model = link.model
            target_link.save(update_fields=["origins", "quality_score", "provider",
                                            "model", "updated_at"])
        if source_document.primary_text_version_id == old_version.pk:
            primary_target_id = version.pk
    if primary_target_id and (target_document.person_id != primary_person.pk or
                              not target_document.primary_text_version_id or
                              source_document.quality_score > target_document.quality_score):
        target_document.primary_text_version_id = primary_target_id
        target_document.text_length = source_document.text_length
        target_document.quality_score = source_document.quality_score
        target_document.parse_provider = source_document.parse_provider
        target_document.parse_model = source_document.parse_model
        target_document.parse_status = source_document.parse_status
        target_document.save(update_fields=["primary_text_version", "text_length",
                                            "quality_score", "parse_provider", "parse_model",
                                            "parse_status", "updated_at"])


def _fill_gaps(primary, duplicate):
    """Lấy những trường primary còn trống từ bản trùng, không ghi đè."""
    fields = []
    for name in ("display_name", "primary_email", "primary_phone", "headline", "location"):
        if not getattr(primary, name) and getattr(duplicate, name):
            setattr(primary, name, getattr(duplicate, name))
            fields.append(name)
    if "display_name" in fields:
        primary.normalized_name = duplicate.normalized_name
        fields.append("normalized_name")
    if fields:
        primary.save(update_fields=fields + ["updated_at"])
