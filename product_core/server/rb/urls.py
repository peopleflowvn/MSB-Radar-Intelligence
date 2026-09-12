# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path("people/", views.customer_search, name="rb-customer-search"),
    path("recently-viewed/", views.recently_viewed, name="rb-recently-viewed"),
    path("relationship-followups/", views.relationship_followups,
         name="rb-relationship-followups"),
    path("tasks/", views.customer_tasks, name="rb-customer-tasks"),
    path("opportunities/", views.opportunity_list, name="rb-opportunities"),
    path("opportunities/bulk/", views.opportunities_bulk,
         name="rb-opportunities-bulk"),
    path("owners/", views.owner_list, name="rb-owners"),
    path("opportunities/export/", views.opportunity_export, name="rb-opportunities-export"),
    path("opportunities/<int:opportunity_id>/", views.opportunity_detail,
         name="rb-opportunity"),
    path("people/<int:person_id>/", views.profile_detail, name="rb-profile"),
    path("people/<int:person_id>/profile/", views.profile_update,
         name="rb-profile-update"),
    path("people/<int:person_id>/interests/", views.interest_list,
         name="rb-interests"),
    path("suggest/", views.suggest, name="rb-suggest"),
    path("agent/analyze/", views.agent_analyze, name="rb-agent-analyze"),
    path("metrics/", views.metrics, name="rb-metrics"),
    # Cơ hội hôm nay (Master Plan mục 13, 33)
    path("today/", views.todays_opportunities, name="rb-today"),
    path("suggestions/<int:suggestion_id>/action/", views.suggestion_action,
         name="rb-suggestion-action"),
    path("opportunities/<int:opportunity_id>/outcomes/", views.opportunity_outcomes,
         name="rb-opportunity-outcomes"),
    path("work-profile/", views.work_profile, name="rb-work-profile"),
    path("prospects/", views.prospect_search, name="rb-prospects"),
    path("opportunities/<int:opportunity_id>/draft/", views.outreach_draft,
         name="rb-outreach-draft"),
    path("opportunities/<int:opportunity_id>/sent/", views.outreach_sent,
         name="rb-outreach-sent"),
]
