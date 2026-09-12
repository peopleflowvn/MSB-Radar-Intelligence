# -*- coding: utf-8 -*-
from django.urls import path

from . import answer_views, intelligence_views, views

urlpatterns = [
    # Đường trả lời DUY NHẤT cho câu hỏi về Kho con người (Answer Engine).
    # `ai-search/` cũ đã gỡ — xem docs/RADAR_ANSWER_ENGINE.md.
    path("ask/", answer_views.talent_ask, name="talent-ask"),
    # Lấy lại kết quả một lượt khi mobile rớt kết nối giữa chừng.
    path("ask/turn/<str:client_turn_id>/", answer_views.talent_ask_turn,
         name="talent-ask-turn"),
    path("intelligence/scope/", intelligence_views.intelligence_scope,
         name="intelligence-scope"),
    path("intelligence/scope/validate/", intelligence_views.validate_scope,
         name="intelligence-scope-validate"),
    path("intelligence/document-feed/", intelligence_views.document_feed,
         name="intelligence-document-feed"),
    path("intelligence/evidence/documents/<int:document_id>/",
         intelligence_views.evidence_document, name="intelligence-evidence-document"),
    path("search/", views.talent_search, name="talent-search"),
    path("recently-viewed/", views.recently_viewed, name="talent-recently-viewed"),
    path("relationship-followups/", views.relationship_followups,
         name="talent-relationship-followups"),
    path("search/export/", views.talent_search_export, name="talent-search-export"),
    path("facets/", views.talent_facets, name="talent-facets"),
    path("embedding-config/", views.embedding_config, name="talent-embedding-config"),
    path("people/<int:person_id>/", views.person_detail, name="talent-person"),
    path("people/<int:person_id>/ask/", views.person_ask, name="talent-person-ask"),
    path("people/<int:person_id>/profile/", views.talent_profile_update,
         name="talent-profile-update"),
    path("people/<int:person_id>/relationship/", views.talent_relationship,
         name="talent-relationship"),
    path("people/<int:person_id>/rederive/", views.talent_rederive,
         name="talent-rederive"),
    path("people/<int:person_id>/tags/", views.person_tags, name="talent-person-tags"),
    path("documents/<int:document_id>/download/", views.document_download,
         name="talent-document-download"),
    path("documents/<int:document_id>/preview/", views.document_preview,
         name="talent-document-preview"),
    path("documents/<int:document_id>/text/", views.document_text,
         name="talent-document-text"),
    path("tags/", views.tag_list, name="talent-tags"),
    path("pools/", views.pool_list, name="talent-pools"),
    path("pools/<int:pool_id>/", views.pool_detail, name="talent-pool"),
    path("pools/<int:pool_id>/members/", views.pool_members, name="talent-pool-members"),
]
