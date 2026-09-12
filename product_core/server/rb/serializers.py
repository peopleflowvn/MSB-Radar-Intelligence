# -*- coding: utf-8 -*-
from rest_framework import serializers
from core.workflows import stage_metadata

from accounts import privacy
from accounts.models import UserWorkProfile

from .models import (PRODUCT_CHOICES, OpportunityOutcome, OpportunitySuggestion,
                     ProductInterest, RBOpportunity, RBProfile)


class RBCustomerSerializer(serializers.Serializer):
    """Thẻ săn khách từ Person; hồ sơ RB chưa tồn tại vẫn phải được tìm thấy."""
    def to_representation(self, person):
        profile = getattr(person, "rb_profile", None)
        opportunities = [row for row in person.rb_opportunities.all()
                         if row.status in RBOpportunity.OPEN_STATUSES]
        interests = profile.interests.all() if profile else []
        relationship = next((row for row in person.relationships.all()
                             if row.domain == "rb"), None)
        return {
            "id": profile.id if profile else None, "person": person.id,
            "display_name": person.display_name,
            # Che vo dieu kien — xem accounts/privacy.py.
            "primary_email": privacy.mask_email(person.primary_email),
            "primary_phone": privacy.mask_phone(person.primary_phone),
            "contact_masked": bool(person.primary_email or person.primary_phone),
            "sales_owner_name": (relationship.owner if relationship
                                  else profile.sales_owner_name if profile else ""),
            "lead_status": (relationship.state if relationship
                            else profile.lead_status if profile else RBProfile.LEAD_COLD),
            "lead_status_label": (dict(RBProfile.LEAD_CHOICES).get(relationship.state,
                                  relationship.state) if relationship
                                  else profile.get_lead_status_display() if profile
                                  else "Chưa tiếp cận"),
            "segment": profile.segment if profile else "",
            "occupation": profile.occupation if profile else "",
            "employer": profile.employer if profile else "",
            "interaction_summary": profile.interaction_summary if profile else "",
            "last_contact_at": (relationship.last_contact_at if relationship
                                else profile.last_contact_at if profile else None),
            "next_action": (relationship.next_action if relationship
                            else profile.next_action if profile else ""),
            "next_action_at": (relationship.next_action_at if relationship
                               else profile.next_action_at if profile else None),
            "interests": ProductInterestSerializer(interests, many=True).data,
            "open_opportunities": [{"id": row.id, "product": row.product,
                "product_label": row.get_product_display(), "status": row.status,
                "assigned_to_name": row.assigned_to_name,
                "next_action_at": row.next_action_at} for row in opportunities],
            "active_owners": sorted({row.assigned_to_name for row in opportunities
                                     if row.assigned_to_name}),
            "interest_level": relationship.interest_level if relationship else 0,
            "preferred_channel": relationship.preferred_channel if relationship else "",
            "do_not_contact": relationship.do_not_contact if relationship else False,
            "relationship_reason": relationship.reason if relationship else "",
            "relationship_notes": relationship.notes if relationship else "",
            "updated_at": profile.updated_at if profile else person.updated_at,
        }


class ProductInterestSerializer(serializers.ModelSerializer):
    product_label = serializers.CharField(source="get_product_display", read_only=True)

    class Meta:
        model = ProductInterest
        fields = ["id", "product", "product_label", "confidence", "evidence",
                  "source", "observed_at"]


class RBProfileSerializer(serializers.ModelSerializer):
    # Liên hệ đọc từ `Person`, KHÔNG lưu bản sao ở RBProfile — xem docstring của
    # `rb/models.py`.
    display_name = serializers.CharField(source="person.display_name", read_only=True)
    primary_email = serializers.SerializerMethodField()
    primary_phone = serializers.SerializerMethodField()
    contact_masked = serializers.SerializerMethodField()
    lead_status_label = serializers.CharField(source="get_lead_status_display",
                                              read_only=True)
    interests = ProductInterestSerializer(many=True, read_only=True)
    open_opportunities = serializers.SerializerMethodField()
    active_owners = serializers.SerializerMethodField()
    interest_level = serializers.SerializerMethodField()
    preferred_channel = serializers.SerializerMethodField()
    do_not_contact = serializers.SerializerMethodField()
    relationship_reason = serializers.SerializerMethodField()
    relationship_notes = serializers.SerializerMethodField()

    def get_primary_email(self, profile):
        return privacy.mask_email(profile.person.primary_email)

    def get_primary_phone(self, profile):
        return privacy.mask_phone(profile.person.primary_phone)

    def get_contact_masked(self, profile):
        return bool(profile.person.primary_email or profile.person.primary_phone)

    class Meta:
        model = RBProfile
        fields = ["id", "person", "display_name", "primary_email", "primary_phone",
                  "contact_masked",
                  "sales_owner_name", "lead_status", "lead_status_label", "segment",
                  "occupation", "employer", "interaction_summary", "last_contact_at",
                  "next_action", "next_action_at", "interests", "open_opportunities",
                  "active_owners", "interest_level", "preferred_channel",
                  "do_not_contact", "relationship_reason", "relationship_notes",
                  "updated_at"]

    def _relationship(self, profile):
        return next((row for row in profile.person.relationships.all()
                     if row.domain == "rb"), None)

    def get_interest_level(self, profile):
        row = self._relationship(profile)
        return row.interest_level if row else 0

    def get_preferred_channel(self, profile):
        row = self._relationship(profile)
        return row.preferred_channel if row else ""

    def get_do_not_contact(self, profile):
        row = self._relationship(profile)
        return row.do_not_contact if row else False

    def get_relationship_reason(self, profile):
        row = self._relationship(profile)
        return row.reason if row else ""

    def get_relationship_notes(self, profile):
        row = self._relationship(profile)
        return row.notes if row else ""

    def get_open_opportunities(self, profile):
        return [{"id": row.id, "product": row.product,
                 "product_label": row.get_product_display(), "status": row.status,
                 "assigned_to_name": row.assigned_to_name,
                 "next_action_at": row.next_action_at}
                for row in profile.person.rb_opportunities.all()
                if row.status in RBOpportunity.OPEN_STATUSES]

    def get_active_owners(self, profile):
        return sorted({row.assigned_to_name for row in profile.person.rb_opportunities.all()
                       if row.status in RBOpportunity.OPEN_STATUSES and row.assigned_to_name})


class RBOpportunitySerializer(serializers.ModelSerializer):
    display_name = serializers.CharField(source="person.display_name", read_only=True)
    primary_phone = serializers.SerializerMethodField()
    primary_email = serializers.SerializerMethodField()
    contact_masked = serializers.SerializerMethodField()
    product_label = serializers.CharField(source="get_product_display", read_only=True)
    status_label = serializers.SerializerMethodField()
    stage_color = serializers.SerializerMethodField()
    sla_due_at = serializers.SerializerMethodField()
    is_overdue = serializers.SerializerMethodField()
    assigned_to = serializers.IntegerField(source="assigned_to_id", read_only=True)
    status_events = serializers.SerializerMethodField()
    other_active_owners = serializers.SerializerMethodField()

    def get_primary_email(self, opportunity):
        return privacy.mask_email(opportunity.person.primary_email)

    def get_primary_phone(self, opportunity):
        return privacy.mask_phone(opportunity.person.primary_phone)

    def get_contact_masked(self, opportunity):
        return bool(opportunity.person.primary_email
                    or opportunity.person.primary_phone)

    class Meta:
        model = RBOpportunity
        fields = ["id", "person", "display_name", "primary_phone", "primary_email",
                  "contact_masked",
                  "product", "product_label", "need", "confidence", "evidence",
                  "suggested_action", "status", "status_label", "stage_color",
                  "sla_due_at", "is_overdue", "assigned_to",
                  "assigned_to_name", "priority", "next_action_at", "note",
                  "status_events", "close_reason", "outreach_draft", "outreach_sent_at",
                  "other_active_owners", "stage_entered_at", "created_at", "updated_at"]

    def _stage(self, opportunity):
        if not hasattr(opportunity, "_workflow_meta"):
            opportunity._workflow_meta = stage_metadata(
                "rb", opportunity.status, opportunity.get_status_display(),
                opportunity.stage_entered_at)
        return opportunity._workflow_meta

    def get_status_label(self, opportunity):
        return self._stage(opportunity)["label"]

    def get_stage_color(self, opportunity):
        return self._stage(opportunity)["color"]

    def get_sla_due_at(self, opportunity):
        return self._stage(opportunity)["sla_due_at"]

    def get_is_overdue(self, opportunity):
        return self._stage(opportunity)["is_overdue"]

    def get_status_events(self, opportunity):
        return [{"from_status": row.from_status, "to_status": row.to_status,
                 "actor_name": row.actor_name, "note": row.note,
                 "created_at": row.created_at}
                for row in opportunity.status_events.all()[:20]]

    def get_other_active_owners(self, opportunity):
        return sorted(set(RBOpportunity.objects.filter(
            person=opportunity.person, status__in=RBOpportunity.OPEN_STATUSES)
            .exclude(pk=opportunity.pk).exclude(assigned_to__isnull=True)
            .values_list("assigned_to_name", flat=True)))


class OpportunitySuggestionSerializer(serializers.ModelSerializer):
    """Thẻ "Cơ hội hôm nay" (Master Plan mục 13, 24).

    Thứ tự trường ở đây cố ý phản ánh thứ tự RM cần đọc: AI · NHU CẦU ·
    VÌ SAO BÂY GIỜ · GIÁ TRỊ · VIỆC NÊN LÀM. Chi tiết điểm số nằm dưới cùng —
    RM cần chúng khi phản bác, không phải khi lướt.
    """

    person_name = serializers.CharField(source="person.display_name", read_only=True)
    product_label = serializers.CharField(source="get_product_display", read_only=True)
    action_label = serializers.CharField(source="get_recommended_action_display",
                                         read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    why = serializers.SerializerMethodField()
    personalized_score = serializers.SerializerMethodField()
    personalized_why = serializers.SerializerMethodField()
    territory = serializers.SerializerMethodField()
    handoff_to = serializers.SerializerMethodField()
    is_discovery = serializers.SerializerMethodField()
    scores = serializers.SerializerMethodField()
    value_band = serializers.SerializerMethodField()
    occupation = serializers.SerializerMethodField()

    class Meta:
        model = OpportunitySuggestion
        fields = ["id", "person", "person_name", "occupation",
                  "product", "product_label", "need_summary",
                  "why", "priority_score", "personalized_score",
                  "personalized_why", "territory", "handoff_to",
                  "is_discovery", "confidence", "value_band",
                  "recommended_action", "action_label", "reasoning_summary",
                  "scores", "status", "status_label", "snoozed_until",
                  "created_at", "expires_at"]
        read_only_fields = fields

    def get_why(self, suggestion):
        return (suggestion.evidence or {}).get("why", [])

    def get_personalized_score(self, suggestion):
        """Diem sau khi tinh dia ban/trong tam cua nguoi dang xem.

        Bang `priority_score` khi nguoi dung chua khai bao ho so cong viec —
        he thong phai dung duoc ngay khi chua ai dien form nao.
        """
        return getattr(suggestion, "personalized_score", suggestion.priority_score)

    def get_personalized_why(self, suggestion):
        return getattr(suggestion, "personalized_why", [])

    def get_territory(self, suggestion):
        """in · out · unknown — xem `scoring.territory_of()`."""
        return getattr(suggestion, "territory", "unknown")

    def get_handoff_to(self, suggestion):
        """RM phu trach khu vuc cua khach nay, khi khach nam ngoai dia ban.

        La **goi y**, khong tu chuyen: chuyen viec cho nguoi khac la quyet dinh
        cua con nguoi, cung nguyen tac voi `accept()`.
        """
        return getattr(suggestion, "handoff_to", None)

    def get_is_discovery(self, suggestion):
        """The nay nam trong suat kham pha — ngoai khai bao cua RM."""
        return bool(getattr(suggestion, "is_discovery", False))

    def get_scores(self, suggestion):
        return {"fit": suggestion.fit_score, "need": suggestion.need_score,
                "timing": suggestion.timing_score,
                "reachability": suggestion.reachability_score,
                "value": suggestion.value_score}

    def get_value_band(self, suggestion):
        """Nhãn định tính, KHÔNG phải số tiền — xem `ProductValueConfig`."""
        score = suggestion.value_score
        if score >= 90:
            return "very_high"
        if score >= 70:
            return "high"
        if score >= 40:
            return "medium"
        return "low"

    def get_occupation(self, suggestion):
        profile = getattr(suggestion.person, "rb_profile", None)
        return getattr(profile, "occupation", "") or ""


class OpportunityOutcomeSerializer(serializers.ModelSerializer):
    outcome_label = serializers.CharField(source="get_outcome_display", read_only=True)
    channel_label = serializers.CharField(source="get_channel_display", read_only=True)

    class Meta:
        model = OpportunityOutcome
        fields = ["id", "opportunity", "person", "channel", "channel_label",
                  "action", "outcome", "outcome_label", "note", "response_at",
                  "created_by_name", "created_at"]
        read_only_fields = ["id", "created_by_name", "created_at", "person"]


class UserWorkProfileSerializer(serializers.ModelSerializer):
    """Nguoi dung tu khai dia ban va trong tam cong viec."""

    domain_label = serializers.CharField(source="get_domain_display", read_only=True)

    class Meta:
        model = UserWorkProfile
        fields = ["id", "domain", "domain_label", "regions", "focus_products",
                  "focus_job_families", "target_segments", "daily_capacity",
                  "preferred_channels", "notes", "active", "updated_at"]
        read_only_fields = ["id", "domain_label", "updated_at"]

    def validate_focus_products(self, value):
        return self._string_list(value, dict(PRODUCT_CHOICES),
                                 u"Nhóm sản phẩm không hợp lệ.")

    def validate_target_segments(self, value):
        return self._string_list(value, dict(RBProfile.SEGMENT_CHOICES),
                                 u"Phân khúc không hợp lệ.")

    def validate_regions(self, value):
        return self._string_list(value, None, "")

    def validate_focus_job_families(self, value):
        return self._string_list(value, None, "")

    def validate_preferred_channels(self, value):
        return self._string_list(value, None, "")

    @staticmethod
    def _string_list(value, allowed, message):
        if not isinstance(value, list):
            raise serializers.ValidationError(u"Phải là một danh sách.")
        cleaned = []
        for item in value:
            text = str(item or "").strip()[:100]
            if not text:
                continue
            if allowed is not None and text not in allowed:
                raise serializers.ValidationError(message)
            if text not in cleaned:
                cleaned.append(text)
        return cleaned
