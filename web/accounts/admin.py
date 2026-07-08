from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from accounts.models import WebUser


@admin.register(WebUser)
class WebUserAdmin(BaseUserAdmin):
    list_display = ("email", "display_name", "is_max_linked", "bot_user_id", "date_joined", "is_staff")
    list_filter = ("is_staff", "is_max_linked")
    search_fields = ("email", "display_name")
    ordering = ("-date_joined",)
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Профиль", {"fields": ("display_name", "vk_id", "yandex_id")}),
        ("MAX", {"fields": ("bot_user_id", "is_max_linked", "max_link_code", "max_link_code_expires")}),
        ("Права", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Даты", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {"classes": ("wide",), "fields": ("email", "display_name", "password1", "password2")}),
    )
    filter_horizontal = ("groups", "user_permissions")
