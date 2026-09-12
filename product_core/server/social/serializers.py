# -*- coding: utf-8 -*-
from rest_framework import serializers

from .models import Community, SocialAccount, SocialAction, SocialPost


class SocialAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialAccount
        fields = ["id", "provider", "label", "handle", "purpose", "is_active",
                  "last_seen_at", "note", "created_at"]


class CommunitySerializer(serializers.ModelSerializer):
    post_count = serializers.SerializerMethodField()

    class Meta:
        model = Community
        fields = ["id", "provider", "external_id", "name", "url", "topic",
                  "member_count", "is_active", "last_scanned_at", "post_count"]

    def get_post_count(self, community):
        return community.posts.count()


class SocialPostSerializer(serializers.ModelSerializer):
    community_name = serializers.CharField(source="community.name", read_only=True)
    person_name = serializers.CharField(source="person.display_name", read_only=True)
    top_domain = serializers.CharField(read_only=True)
    # Câu chốt của Social Radar: "từng ứng tuyển 9 tháng trước". Tính ở đây thay
    # vì lưu vào CSDL — nó phụ thuộc ngày hôm nay, lưu lại là để nó cũ dần đi.
    history_note = serializers.SerializerMethodField()

    class Meta:
        model = SocialPost
        fields = ["id", "provider", "external_id", "community", "community_name",
                  "author_name", "author_handle", "author_url", "content", "url",
                  "posted_at", "intent", "intent_reason", "intent_fallback",
                  "contacts", "person", "person_name", "history_note",
                  "top_domain", "status", "created_at"]

    def get_history_note(self, post):
        from .pipeline import history_note
        return history_note(post.person)


class SocialActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialAction
        fields = ["id", "post", "community", "hiring_need", "kind", "content",
                  "status", "created_by_name", "posted_at", "outcome", "created_at"]
