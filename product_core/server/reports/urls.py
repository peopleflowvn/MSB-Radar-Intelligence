# -*- coding: utf-8 -*-
from django.urls import path

from . import views

urlpatterns = [
    path("overview/", views.overview, name="reports-overview"),
    path("saved-views/", views.saved_view_list, name="reports-saved-views"),
    path("saved-views/<int:view_id>/", views.saved_view_detail,
         name="reports-saved-view"),
    path("filter-history/", views.filter_history, name="reports-filter-history"),
]
