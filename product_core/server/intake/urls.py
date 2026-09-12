# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path("template.xlsx", views.download_template, name="intake-template"),
    path("export.csv", views.export_candidates, name="intake-export"),
    path("batches/", views.batch_collection, name="intake-batches"),
    path("batches/<int:batch_id>/", views.batch_detail, name="intake-batch"),
    path("batches/<int:batch_id>/rows/<int:row_id>/", views.row_detail,
         name="intake-row"),
    path("batches/<int:batch_id>/cvs/", views.batch_cvs, name="intake-batch-cvs"),
    path("batches/<int:batch_id>/commit/", views.batch_commit,
         name="intake-batch-commit"),
]
