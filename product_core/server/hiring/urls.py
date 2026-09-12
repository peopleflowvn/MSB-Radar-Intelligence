# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path("needs/", views.hiring_need_list, name="hiring-needs"),
    path("needs/<int:need_id>/", views.hiring_need_detail, name="hiring-need"),
    path("needs/<int:need_id>/parse-jd/", views.parse_jd, name="hiring-parse-jd"),
    path("needs/<int:need_id>/suggestions/", views.suggestions,
         name="hiring-suggestions"),
    path("needs/<int:need_id>/mark/", views.mark_candidacy, name="hiring-mark"),
    path("needs/<int:need_id>/calibrate/", views.calibrate, name="hiring-calibrate"),
    path("needs/<int:need_id>/calibrate/reset/", views.reset_calibration,
         name="hiring-calibrate-reset"),
    path("needs/<int:need_id>/hunt/", views.request_hunt, name="hiring-request-hunt"),
    path("metrics/", views.metrics, name="hiring-metrics"),
    path("hunts/", views.hunt_list, name="hiring-hunts"),
    path("hunts/tasks/", views.hunt_tasks, name="hiring-hunt-tasks"),
    path("hunts/candidates/bulk/", views.hunt_candidates_bulk,
         name="hiring-hunt-candidates-bulk"),
    path("hunts/<int:hunt_id>/", views.hunt_detail, name="hiring-hunt"),
    path("hunts/<int:hunt_id>/people/<int:person_id>/",
         views.hunt_candidate_detail, name="hiring-hunt-candidate"),
    path("hunts/<int:hunt_id>/people/<int:person_id>/draft/",
         views.outreach_draft, name="hiring-outreach-draft"),
    path("hunts/<int:hunt_id>/people/<int:person_id>/sent/",
         views.outreach_sent, name="hiring-outreach-sent"),
]
