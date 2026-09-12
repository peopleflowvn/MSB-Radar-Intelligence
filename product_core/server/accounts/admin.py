# -*- coding: utf-8 -*-
from django.contrib import admin
from django.utils import timezone

from .models import (AccessLog, AuthenticationEvent, EmailLoginCode, EmailOtpSettings,
                     ExternalIdentity, ResendInboxEmail, ResendWebhookEvent, UserLoginPolicy)


@admin.register(AccessLog)
class AccessLogAdmin(admin.ModelAdmin):
    """Chỉ đọc. Nhật ký tuân thủ mà sửa được thì không còn là bằng chứng."""

    list_display = ("created_at", "user_name", "roles", "action", "module",
                    "person_name", "allowed", "cross_domain")
    list_filter = ("action", "module", "allowed", "cross_domain")
    search_fields = ("user_name", "person_name", "path", "ip")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AccessLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "realm", "username_snapshot", "linked_at",
                    "last_login_at", "revoked_at")
    list_filter = ("provider", "realm", "revoked_at")
    search_fields = ("user__username", "username_snapshot", "tenant_id", "object_id")
    readonly_fields = ("user", "provider", "realm", "tenant_id", "object_id",
                       "username_snapshot", "display_name_snapshot", "linked_at",
                       "last_login_at", "revoked_at", "revoked_by", "revoke_reason")
    actions = ("revoke_selected",)

    @admin.action(description="Thu hồi các liên kết Microsoft đã chọn")
    def revoke_selected(self, request, queryset):
        queryset.filter(revoked_at__isnull=True).update(
            revoked_at=timezone.now(), revoked_by=request.user,
            revoke_reason="Thu hồi thủ công từ Django Admin")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(UserLoginPolicy)
class UserLoginPolicyAdmin(admin.ModelAdmin):
    list_display = ("user", "login_type", "updated_at")
    list_filter = ("login_type",)
    search_fields = ("user__username", "user__email")


@admin.register(AuthenticationEvent)
class AuthenticationEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "realm", "result", "username_masked", "user", "actor", "ip")
    list_filter = ("provider", "realm", "result")
    search_fields = ("username_masked", "user__username", "correlation_id", "ip")
    readonly_fields = [f.name for f in AuthenticationEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmailOtpSettings)
class EmailOtpSettingsAdmin(admin.ModelAdmin):
    list_display = ("enabled", "from_email", "from_name", "updated_at", "updated_by")
    readonly_fields = ("resend_api_key_encrypted", "updated_at", "updated_by")

    def has_add_permission(self, request):
        return not EmailOtpSettings.objects.exists()


@admin.register(EmailLoginCode)
class EmailLoginCodeAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "realm", "sent_to", "expires_at", "attempts", "used_at")
    list_filter = ("realm", "used_at")
    search_fields = ("user__username", "sent_to")
    readonly_fields = [f.name for f in EmailLoginCode._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ResendWebhookEvent)
class ResendWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("received_at", "event_type", "email_id", "svix_id")
    list_filter = ("event_type",)
    search_fields = ("email_id", "svix_id")
    readonly_fields = [f.name for f in ResendWebhookEvent._meta.fields]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False


@admin.register(ResendInboxEmail)
class ResendInboxEmailAdmin(admin.ModelAdmin):
    list_display = ("received_at", "sender", "subject", "email_id")
    search_fields = ("sender", "subject", "email_id")
    readonly_fields = [f.name for f in ResendInboxEmail._meta.fields]

    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False
