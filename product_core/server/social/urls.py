# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path("analyze/", views.analyze, name="social-analyze"),
    path("ingest/", views.ingest, name="social-ingest"),
    path("posts/", views.post_list, name="social-posts"),
    path("posts/<int:post_id>/rescore/", views.rescore, name="social-rescore"),
    path("communities/", views.community_list, name="social-communities"),
    path("accounts/", views.account_list, name="social-accounts"),
    path("actions/", views.action_list, name="social-actions"),
]
