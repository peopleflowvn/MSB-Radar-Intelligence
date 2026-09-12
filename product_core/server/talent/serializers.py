# -*- coding: utf-8 -*-
"""Serializer cho Talent Radar."""
from people.models import Person
from django.contrib.auth import get_user_model
from rest_framework import serializers
from accounts import privacy

from .models import Pool, Tag, TalentProfile


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ["id", "name", "slug", "color"]


class TalentCardSerializer(serializers.ModelSerializer):
    """Một dòng trong kết quả tìm kiếm.

    Cố ý gọn: danh sách 50 người mà kèm đủ mọi thứ thì vừa chậm vừa hiện dữ liệu cá
    nhân nhiều hơn mức cần để chọn xem ai. Chi tiết nằm ở Person 360.
    """

    talent = serializers.SerializerMethodField()
    source_count = serializers.SerializerMethodField()
    active_worklists = serializers.SerializerMethodField()
    # Che vo dieu kien — xem accounts/privacy.py. Danh sach KHONG BAO GIO tra
    # ve lien he day du; muon day du thi di qua endpoint mo khoa.
    primary_email = serializers.SerializerMethodField()
    primary_phone = serializers.SerializerMethodField()
    contact_masked = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ["id", "display_name", "primary_email", "primary_phone",
                  "contact_masked", "headline",
                  "location", "needs_review", "talent", "source_count",
                  "active_worklists", "updated_at"]

    def get_primary_email(self, person):
        return privacy.mask_email(person.primary_email)

    def get_primary_phone(self, person):
        return privacy.mask_phone(person.primary_phone)

    def get_contact_masked(self, person):
        return bool(person.primary_email or person.primary_phone)

    def get_talent(self, person):
        profile = getattr(person, "talent_profile", None)
        if profile is None:
            return None
        return {
            "current_title": profile.current_title,
            "current_company": profile.current_company,
            "years_experience": profile.years_experience,
            "seniority": profile.seniority,
            "location": profile.location,
            "skills": (profile.skills or [])[:12],
            "owner_name": profile.owner_name,
            "tags": [t.slug for t in profile.tags.all()],
            "last_source_at": profile.last_source_at,
        }

    def get_source_count(self, person):
        annotated = getattr(person, "source_count_value", None)
        return annotated if annotated is not None else person.source_records.count()

    def get_active_worklists(self, person):
        rows = []
        for candidate in person.hunt_candidates.all():
            hunt = candidate.hunt_request
            if not hunt.is_open or candidate.is_closed:
                continue
            rows.append({
                "hunt_id": hunt.id,
                "title": hunt.title or (hunt.hiring_need.title if hunt.hiring_need else "Danh sách xử lý"),
                "state": candidate.state,
                "state_label": candidate.get_state_display(),
                "priority": candidate.priority,
                "assigned_to_id": candidate.assigned_to_id,
                "assigned_to_name": candidate.assigned_to_name or hunt.assigned_to_name,
                "next_action_at": candidate.next_action_at,
                "note": candidate.note,
                "updated_at": candidate.updated_at,
            })
        return sorted(rows, key=lambda row: row["updated_at"], reverse=True)[:10]


class TalentProfileUpdateSerializer(serializers.ModelSerializer):
    owner_id = serializers.PrimaryKeyRelatedField(
        source="owner", queryset=get_user_model().objects.filter(is_active=True),
        allow_null=True, required=False)

    class Meta:
        model = TalentProfile
        fields = ["current_title", "current_company", "years_experience", "seniority",
                  "education", "expected_salary", "current_salary", "location",
                  "desired_location", "desired_level", "desired_position", "job_type",
                  "foreign_language", "marital_status", "summary", "skills",
                  "industries", "owner_id"]

    def validate_years_experience(self, value):
        if value is not None and not 0 <= value <= 80:
            raise serializers.ValidationError("Số năm kinh nghiệm phải từ 0 đến 80.")
        return value

    def validate_skills(self, value):
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise serializers.ValidationError("Kỹ năng phải là danh sách chuỗi.")
        return [x.strip() for x in value if x.strip()]

    def validate_industries(self, value):
        if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
            raise serializers.ValidationError("Ngành nghề phải là danh sách chuỗi.")
        return [x.strip() for x in value if x.strip()]


class TalentProfileSerializer(serializers.ModelSerializer):
    tags = serializers.SerializerMethodField()
    owner_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = TalentProfile
        fields = ["current_title", "current_company", "years_experience", "seniority",
                  "education", "expected_salary", "current_salary", "location",
                  "desired_location", "desired_level", "desired_position", "job_type",
                  "foreign_language", "marital_status", "skills", "industries",
                  "summary", "owner_id", "owner_name", "tags", "curated_fields",
                  "last_source_at", "derived_at"]

    def get_tags(self, profile):
        return [tag.slug for tag in profile.tags.all()]


class PersonDetailSerializer(serializers.ModelSerializer):
    """Person 360 (Master Plan mục 24).

    Gom mọi thứ về một con người vào một phản hồi: danh tính, nguồn, tài liệu, dòng
    thời gian, tín hiệu, hồ sơ tuyển dụng. Một lời gọi thay vì bảy — màn hình này là
    nơi recruiter dừng lại lâu nhất, nên độ trễ ở đây cảm nhận rõ nhất.
    """

    talent = TalentProfileSerializer(source="talent_profile", read_only=True)
    identities = serializers.SerializerMethodField()
    sources = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()
    document_stats = serializers.SerializerMethodField()
    timeline = serializers.SerializerMethodField()
    signals = serializers.SerializerMethodField()
    relationships = serializers.SerializerMethodField()
    person_links = serializers.SerializerMethodField()
    pools = serializers.SerializerMethodField()
    active_worklists = serializers.SerializerMethodField()

    primary_email = serializers.SerializerMethodField()
    primary_phone = serializers.SerializerMethodField()
    contact_masked = serializers.SerializerMethodField()

    class Meta:
        model = Person
        fields = ["id", "display_name", "primary_email", "primary_phone",
                  "contact_masked", "headline",
                  "location", "needs_review", "created_at", "updated_at",
                  "talent", "identities", "sources", "documents", "document_stats", "timeline",
                  "signals", "relationships", "person_links", "pools", "active_worklists"]

    def get_primary_email(self, person):
        return privacy.mask_email(person.primary_email)

    def get_primary_phone(self, person):
        return privacy.mask_phone(person.primary_phone)

    def get_contact_masked(self, person):
        return bool(person.primary_email or person.primary_phone)

    def get_active_worklists(self, person):
        return TalentCardSerializer().get_active_worklists(person)

    def get_identities(self, person):
        return [{"kind": i.kind, "value": i.value, "first_seen_at": i.first_seen_at}
                for i in person.identities.all()]

    def get_sources(self, person):
        return [{
            "id": r.id, "source": r.source, "account": r.account,
            "entity_key": r.entity_key, "position": r.position,
            "applied_ts": (r.payload or {}).get("applied_ts", ""),
            "revision": r.revision,
            "first_seen_at": r.first_seen_at, "last_seen_at": r.last_seen_at,
        } for r in person.source_records.all()]

    def get_documents(self, person):
        """Các phiên bản CV, CŨ NHẤT TRƯỚC.

        Ngược thứ tự mặc định của model (mới nhất trước) một cách có chủ đích:
        đọc lịch sử một con người thì phải đi xuôi theo thời gian mới thấy được
        họ đã đi từ đâu tới đâu.

        Số thứ tự tính ngay tại đây thay vì gọi `version_number()` cho từng hàng
        — cách kia sinh một truy vấn đếm cho mỗi tài liệu.
        """
        rows, _stats, content_counts = self._document_metrics(person)
        return [{
            "id": d.id,
            "version": index,
            "filename": d.filename,
            "document_type": d.document_type,
            "source": d.source,
            "file_size": d.file_size,
            "mime_type": d.mime_type,
            "parse_status": d.parse_status,
            "observed_at": d.observed_at,
            "created_at": d.created_at,
            "has_file": bool(d.storage_key),
            "text_length": d.text_length,
            "text_variant_count": len(d.text_links.all()),
            "content_group": (d.primary_text_version.text_hash[:12]
                              if d.primary_text_version_id else ""),
            "same_content_occurrences": (content_counts.get(d.primary_text_version_id, 0)
                                         if d.primary_text_version_id else 0),
            "parse_provider": d.parse_provider,
            "parse_model": d.parse_model,
            "parse_error": d.parse_error,
            "parsed_at": d.parsed_at,
            "preview_status": d.preview_status,
            "preview_error": d.preview_error,
            "has_preview": bool(d.preview_key),
            # Cùng một file có thể được đính vào nhiều lượt ứng tuyển.
            "used_by": d.source_records.count(),
        } for index, d in enumerate(rows, start=1)]

    def get_document_stats(self, person):
        _rows, stats, _counts = self._document_metrics(person)
        return stats

    @staticmethod
    def _document_metrics(person):
        cached = getattr(person, "_document_metrics_cache", None)
        if cached is not None:
            return cached
        rows = sorted(person.documents.all(), key=lambda d: (d.observed_at or d.created_at))
        content_counts = {}
        submissions = 0
        for document in rows:
            occurrences = max(1, len(document.source_records.all()))
            submissions += occurrences
            if document.primary_text_version_id:
                content_counts[document.primary_text_version_id] = (
                    content_counts.get(document.primary_text_version_id, 0) + occurrences)
        distinct = len(content_counts)
        stats = {
            "submission_count": submissions,
            "file_version_count": len(rows),
            "distinct_text_count": distinct,
            "duplicate_text_count": sum(max(0, count - 1) for count in content_counts.values()),
            "unparsed_count": sum(1 for row in rows if not row.primary_text_version_id
                                  and not row.parsed_text),
            "ai_retry_count": sum(1 for row in rows if row.parse_error),
            "preview_pending_count": sum(1 for row in rows if row.preview_status != "done"),
            "text_variant_count": len({link.text_version_id for row in rows
                                       for link in row.text_links.all()}),
        }
        cached = (rows, stats, content_counts)
        person._document_metrics_cache = cached
        return cached

    def get_timeline(self, person):
        """Dòng thời gian gộp: tương tác + tín hiệu, mới nhất trước.

        Giới hạn 100 dòng: đây là màn hình để hiểu một con người, không phải để tra
        cứu toàn bộ lịch sử. Tra cứu đầy đủ là việc của nhật ký.
        """
        events = []
        for row in person.interactions.all()[:100]:
            events.append({"kind": "interaction", "at": row.occurred_at,
                           "action": row.action, "actor": row.actor_name,
                           "detail": row.detail})
        for row in person.signals.all()[:100]:
            events.append({"kind": "signal", "at": row.observed_at,
                           "action": row.signal_type, "actor": row.source,
                           "detail": {"confidence": row.confidence}})
        events.sort(key=lambda e: e["at"] or "", reverse=True)
        return events[:100]

    def get_signals(self, person):
        return [{"id": s.id, "signal_type": s.signal_type, "domain": s.domain,
                 "confidence": s.confidence, "status": s.status,
                 "observed_at": s.observed_at, "evidence": s.evidence}
                for s in person.signals.all()[:50]]

    def get_relationships(self, person):
        return [{"domain": r.domain, "state": r.state, "owner": r.owner,
                 "owner_id": r.owner_user_id, "interest_level": r.interest_level,
                 "last_contact_at": r.last_contact_at, "next_action": r.next_action,
                 "next_action_at": r.next_action_at,
                 "preferred_channel": r.preferred_channel,
                 "do_not_contact": r.do_not_contact, "reason": r.reason,
                 "notes": r.notes, "preferences": r.preferences,
                 "updated_at": r.updated_at}
                for r in person.relationships.all()]

    def get_person_links(self, person):
        """Quan hệ NGƯỜI ↔ NGƯỜI (khác `relationships` = người ↔ nghiệp vụ).

        `outgoing` = người mà hồ sơ này nhắc tới (người tham chiếu trong CV của
        họ). `incoming` = người đã nhắc tới hồ sơ này (họ là người tham chiếu
        trong CV người khác). Không có reader nào cho `PersonLink` trước đây —
        các link được tạo mà không hiện ở đâu.
        """
        def row(link, other):
            return {"kind": link.kind, "kind_display": link.get_kind_display(),
                    "person": {"id": other.pk, "display_name": other.display_name,
                               "origin": other.origin, "is_applicant": other.is_applicant},
                    "confidence": round(link.confidence, 2),
                    "evidence": link.evidence,
                    "source_document_id": link.source_document_id,
                    "created_at": link.created_at}
        return {
            "outgoing": [row(link, link.related) for link in person.links_out.all()],
            "incoming": [row(link, link.subject) for link in person.links_in.all()],
        }

    def get_pools(self, person):
        return [{"id": m.pool_id, "name": m.pool.name, "added_at": m.added_at,
                 "added_by": m.added_by_name}
                for m in person.pool_memberships.all()]


class PoolSerializer(serializers.ModelSerializer):
    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Pool
        fields = ["id", "name", "domain", "description", "owner_name", "member_count",
                  "is_archived", "created_at", "updated_at"]

    def get_member_count(self, pool):
        return pool.memberships.count()
