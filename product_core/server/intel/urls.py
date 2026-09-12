# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path("people/<int:person_id>/facts/", views.person_facts, name="intel-person-facts"),
    path("people/<int:person_id>/runs/", views.person_runs, name="intel-person-runs"),
    path("review/", views.review_queue, name="intel-review"),
    path("review/<int:item_id>/", views.review_resolve, name="intel-review-resolve"),
    path("contacts/", views.contact_mention_queue, name="intel-contacts"),
    path("contacts/<int:mention_id>/", views.contact_mention_resolve,
         name="intel-contact-resolve"),
    path("aliases/", views.alias_queue, name="intel-aliases"),
    path("aliases/<int:alias_id>/", views.alias_resolve, name="intel-alias-resolve"),
    path("runs/", views.runs_dashboard, name="intel-runs"),
]
