# -*- coding: utf-8 -*-
from django.urls import path

from . import branding_assets, views

urlpatterns = [
    path("branding/upload-og-image/", branding_assets.upload_og_image,
         name="branding-upload-og-image"),
    path("login/", views.login_view, name="auth-login"),
    path("logout/", views.logout_view, name="auth-logout"),
    path("me/", views.me_view, name="auth-me"),
    path("assistant-preference/", views.assistant_preference,
         name="assistant-preference"),
    path("public-settings/", views.public_settings, name="public-settings"),
    path("login-options/", views.login_options, name="login-options"),
    path("login-discovery/", views.login_discovery, name="login-discovery"),
    path("local/reset-password/request/", views.local_password_reset_request, name="local-reset-request"),
    path("local/reset-password/confirm/", views.local_password_reset_confirm, name="local-reset-confirm"),
    path("email-otp/<str:realm>/request/", views.email_otp_request, name="email-otp-request"),
    path("email-otp/<str:realm>/verify/", views.email_otp_verify, name="email-otp-verify"),
    path("email-otp/settings/", views.email_otp_settings, name="email-otp-settings"),
    path("email-otp/test-send/", views.email_otp_test_send, name="email-otp-test-send"),
    path("resend/webhook/", views.resend_webhook, name="resend-webhook"),
    path("resend/inbox/", views.resend_inbox, name="resend-inbox"),
    path("resend/events/", views.resend_webhook_events, name="resend-events"),
    path("access-log/", views.access_log_list, name="access-log"),
    path("access-log/summary/", views.access_log_summary, name="access-log-summary"),
    path("role-modules/", views.role_module_matrix, name="role-module-matrix"),
    path("contact-unlock/quota/", views.contact_unlock_quota,
         name="contact-unlock-quota"),
    path("contact-unlock/<int:person_id>/", views.contact_unlock,
         name="contact-unlock"),
    path("users/", views.user_list, name="user-list"),
    path("users/bulk-template/", views.user_bulk_template, name="user-bulk-template"),
    path("users/bulk-create/", views.user_bulk_create, name="user-bulk-create"),
    path("users/<int:user_id>/", views.user_detail, name="user-detail"),
]
