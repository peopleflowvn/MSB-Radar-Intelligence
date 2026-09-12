# -*- coding: utf-8 -*-
from django.urls import path

from . import memory_views, stream_views, views

urlpatterns = [
    path("assistant/stream/", stream_views.assistant_stream, name="ai-assistant-stream"),
    path("memory/", memory_views.memory_list, name="ai-memory"),
    path("memory/<int:memory_id>/", memory_views.memory_detail, name="ai-memory-detail"),
    path("feedback/", memory_views.submit_feedback, name="ai-feedback"),
    path("search-history/", memory_views.search_history, name="ai-search-history"),
    path("conversations/", views.conversation_list, name="ai-conversations"),
    path("conversations/<str:thread_id>/", views.conversation_detail,
         name="ai-conversation-detail"),
    path("providers/", views.provider_list, name="ai-providers"),
    path("providers/routes/<str:task>/", views.task_route, name="ai-task-route"),
    path("providers/<str:provider>/", views.provider_update, name="ai-provider-update"),
    path("providers/<str:provider>/test/", views.provider_test, name="ai-provider-test"),
    path("providers/<str:provider>/models/", views.provider_models, name="ai-provider-models"),
    path("usage/", views.usage_summary, name="ai-usage"),
]
