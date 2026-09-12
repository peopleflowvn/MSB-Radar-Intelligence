# -*- coding: utf-8 -*-
from rest_framework import serializers
from accounts import privacy
from core.workflows import stage_metadata

from .models import Candidacy, HiringNeed, HuntCandidate, HuntRequest


class HiringNeedSerializer(serializers.ModelSerializer):
    counts = serializers.SerializerMethodField()
    is_calibrated = serializers.BooleanField(read_only=True)

    class Meta:
        model = HiringNeed
        fields = ["id", "title", "department", "jd_text", "criteria",
                  "criteria_fallback", "status", "owner_name", "is_calibrated",
                  "calibrated_at", "learned_weights", "counts",
                  "created_at", "updated_at"]

    def get_counts(self, need):
        """Đếm theo trạng thái — HM cần biết đã đánh giá được bao nhiêu."""
        rows = need.candidacies.values_list("state", flat=True)
        counts = {state: 0 for state, _ in Candidacy.STATE_CHOICES}
        for state in rows:
            counts[state] = counts.get(state, 0) + 1
        counts["total"] = len(rows)
        counts["open_hunts"] = need.hunt_requests.filter(
            status__in=HuntRequest.OPEN_STATUSES).count()
        return counts


class CandidacySerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidacy
        fields = ["id", "state", "score_snapshot", "note", "marked_by_name",
                  "marked_at", "created_at"]


class HuntCandidateSerializer(serializers.ModelSerializer):
    """Một người trong yêu cầu săn, kèm đủ thông tin để recruiter bấm gọi luôn.

    Số điện thoại và email nằm ngay đây chứ không bắt mở Person 360: recruiter
    làm việc theo danh sách, mỗi lần nhảy sang màn hình khác rồi quay lại là một
    lần mất chỗ đang làm.
    """

    person_id = serializers.IntegerField(source="person.id", read_only=True)
    display_name = serializers.CharField(source="person.display_name", read_only=True)
    headline = serializers.CharField(source="person.headline", read_only=True)
    # Che vo dieu kien — xem accounts/privacy.py.
    primary_email = serializers.SerializerMethodField()
    primary_phone = serializers.SerializerMethodField()
    contact_masked = serializers.SerializerMethodField()
    state_label = serializers.SerializerMethodField()
    stage_color = serializers.SerializerMethodField()
    sla_due_at = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    status_events = serializers.SerializerMethodField()

    def get_primary_email(self, row):
        return privacy.mask_email(row.person.primary_email)

    def get_primary_phone(self, row):
        return privacy.mask_phone(row.person.primary_phone)

    def get_contact_masked(self, row):
        return bool(row.person.primary_email or row.person.primary_phone)

    class Meta:
        model = HuntCandidate
        fields = ["person_id", "display_name", "headline", "primary_email",
                  "primary_phone", "contact_masked", "state", "state_label", "stage_color", "sla_due_at",
                  "is_overdue", "note", "return_reason",
                  "priority", "next_action_at", "assigned_to", "assigned_to_name",
                  "status_events", "outreach_draft", "outreach_sent_at",
                  "stage_entered_at", "updated_at"]

    def _stage(self, candidate):
        if not hasattr(candidate, "_workflow_meta"):
            candidate._workflow_meta = stage_metadata(
                "talent", candidate.state, candidate.get_state_display(),
                candidate.stage_entered_at)
        return candidate._workflow_meta

    def get_state_label(self, candidate):
        return self._stage(candidate)["label"]

    def get_stage_color(self, candidate):
        return self._stage(candidate)["color"]

    def get_sla_due_at(self, candidate):
        return self._stage(candidate)["sla_due_at"]

    def get_is_overdue(self, candidate):
        return self._stage(candidate)["is_overdue"]

    def get_status_events(self, candidate):
        return [{"from_state": row.from_state, "to_state": row.to_state,
                 "actor_name": row.actor_name, "note": row.note,
                 "created_at": row.created_at}
                for row in candidate.status_events.all()[:20]]


class HuntRequestSerializer(serializers.ModelSerializer):
    hiring_need_title = serializers.SerializerMethodField()
    people = serializers.SerializerMethodField()
    progress = serializers.SerializerMethodField()
    visible_count = serializers.SerializerMethodField()

    class Meta:
        model = HuntRequest
        fields = ["id", "title", "hiring_need", "hiring_need_title", "people", "progress",
                  "visible_count",
                  "message", "status", "requested_by_name", "assigned_to_name",
                  "priority", "decline_reason", "created_at", "updated_at"]

    def get_hiring_need_title(self, hunt):
        return hunt.title or (hunt.hiring_need.title if hunt.hiring_need else "Shortlist")

    def get_people(self, hunt):
        rows = getattr(hunt, "_visible_candidates", None)
        if rows is None:
            rows = hunt.candidates.all()
        return HuntCandidateSerializer(rows, many=True).data

    def get_progress(self, hunt):
        """Đã xử lý bao nhiêu / tổng bao nhiêu — thứ recruiter nhìn đầu tiên."""
        rows = getattr(hunt, "_all_candidates", None)
        if rows is None:
            rows = list(hunt.candidates.all())
        return {
            "total": len(rows),
            "closed": sum(1 for row in rows if row.is_closed),
            "submitted": sum(1 for row in rows
                             if row.state == HuntCandidate.STATE_SUBMITTED),
        }

    def get_visible_count(self, hunt):
        rows = getattr(hunt, "_visible_candidates", None)
        return len(rows) if rows is not None else self.get_progress(hunt)["total"]
