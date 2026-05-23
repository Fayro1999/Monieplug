from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User

    list_display = (
        "email",
        "phone",
        "first_name",
        "last_name",
        "is_active",
        "is_staff",
        "is_superuser",
    )
    list_filter = ("is_active", "is_staff", "is_superuser")

    ordering = ("email",)
    search_fields = ("email", "phone", "first_name", "last_name")

    fieldsets = (
        (None, {"fields": ("email", "phone", "password")}),
        ("Personal Info", {"fields": ("first_name", "last_name")}),
        (
            "Wallet Information",
            {
                "fields": (
                    "wallet_id",
                    "wallet_account_number",
                    "wallet_name",
                    "wallet_bank_name",
                )
            },
        ),
        (
            "Security",
            {
                "fields": (
                    "transaction_pin",
                    "email_verification_code",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login",)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "phone",
                    "first_name",
                    "last_name",
                    "password1",
                    "password2",
                    "is_active",
                    "is_staff",
                ),
            },
        ),
    )

    filter_horizontal = ("groups", "user_permissions")

