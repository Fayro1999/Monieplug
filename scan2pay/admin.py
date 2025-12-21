from django.contrib import admin
from .models import VendorQRCode, Scan2PayTransaction


@admin.register(VendorQRCode)
class VendorQRCodeAdmin(admin.ModelAdmin):
    list_display = (
        "business_name",
        "vendor",
        "qr_label",
        "amount",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = (
        "business_name",
        "vendor__email",
        "qr_label",
    )
    readonly_fields = ("qr_code_image", "created_at")

    fieldsets = (
        (
            "Vendor Info",
            {
                "fields": (
                    "vendor",
                    "business_name",
                    "business_address",
                )
            },
        ),
        (
            "Payment Setup",
            {
                "fields": (
                    "amount",
                    "payment_variation",
                    "qr_label",
                )
            },
        ),
        (
            "QR Code",
            {
                "fields": ("qr_code_image",),
            },
        ),
        (
            "Meta",
            {
                "fields": ("created_at",),
            },
        ),
    )


@admin.register(Scan2PayTransaction)
class Scan2PayTransactionAdmin(admin.ModelAdmin):
    list_display = (
        "reference_id",
        "vendor",
        "sender",
        "amount",
        "platform_charge",
        "status",
        "created_at",
    )
    list_filter = ("status", "created_at")
    search_fields = (
        "reference_id",
        "vendor__email",
        "sender__email",
    )
    readonly_fields = ("reference_id", "created_at")

    fieldsets = (
        (
            "Transaction Parties",
            {
                "fields": (
                    "vendor",
                    "sender",
                    "qr_code",
                )
            },
        ),
        (
            "Transaction Details",
            {
                "fields": (
                    "amount",
                    "platform_charge",
                    "status",
                )
            },
        ),
        (
            "Reference",
            {
                "fields": ("reference_id",),
            },
        ),
        (
            "Meta",
            {
                "fields": ("created_at",),
            },
        ),
    )
