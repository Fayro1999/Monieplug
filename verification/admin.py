from django.contrib import admin
from .models import Verification


@admin.register(Verification)
class VerificationAdmin(admin.ModelAdmin):

    list_display = (
        "user",
        "reference_id",
        "verification_status",
        "verification_mode",
        "created_at",
    )

    search_fields = (
        "reference_id",
        "user__phone",
        "user__email",
    )

    list_filter = (
        "verification_status",
        "verification_mode",
    )