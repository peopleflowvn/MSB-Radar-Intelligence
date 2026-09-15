# -*- coding: utf-8 -*-
from django.urls import path

from . import api_views

urlpatterns = [
    path("documents/", api_views.document_collection, name="knowledge-documents"),
    path("documents/upload/", api_views.document_upload, name="knowledge-documents-upload"),
    path("documents/<int:document_id>/", api_views.document_detail, name="knowledge-document-detail"),
]
