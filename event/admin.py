from django.contrib import admin
from .models import Event, Ticket, TicketPurchase


class TicketInline(admin.TabularInline):
    model = Ticket
    extra = 0


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "date",
        "location",
        "organizer",
        "created_at",
    )
    list_filter = ("date", "created_at")
    search_fields = ("title", "location", "organizer__email")
    ordering = ("-created_at",)

    inlines = [TicketInline]


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ("name", "event", "price")
    list_filter = ("event",)
    search_fields = ("name", "event__title")


@admin.register(TicketPurchase)
class TicketPurchaseAdmin(admin.ModelAdmin):
    list_display = (
        "full_name",
        "email",
        "ticket",
        "copies",
        "total_price",
        "status",
        "debit_reference",
        "credit_reference",
        "created_at",
    )

    list_filter = ("status", "created_at")

    search_fields = (
        "full_name",
        "email",
        "reference_id",
        "debit_reference",
        "credit_reference",
    )

    readonly_fields = (
        "reference_id",
        "total_price",
        "qr_codes",
        "created_at",
    )

    fieldsets = (
        (
            "Buyer Info",
            {
                "fields": ("user", "full_name", "email"),
            },
        ),
        (
            "Ticket Info",
            {
                "fields": ("ticket", "copies", "total_price"),
            },
        ),
        (
            "WAAS Transaction Info",
            {
                "fields": ("status", "debit_reference", "credit_reference", "reference_id"),
            },
        ),
        (
            "QR Codes",
            {
                "fields": ("qr_codes",),
            },
        ),
        (
            "Meta",
            {
                "fields": ("created_at",),
            },
        ),
    )