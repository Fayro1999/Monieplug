# event/models.py

from django.db import models
from django.contrib.auth import get_user_model

import uuid
import io
import qrcode

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage


User = get_user_model()


class Event(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    date = models.DateTimeField()
    location = models.CharField(max_length=255)
    image = models.ImageField(
        upload_to="events/",
        blank=True,
        null=True
    )

    # Organizer = event owner/vendor
    organizer = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="events"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Ticket(models.Model):
    event = models.ForeignKey(
        Event,
        on_delete=models.CASCADE,
        related_name="tickets"
    )

    name = models.CharField(max_length=100)

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    ticket_image = models.ImageField(
        upload_to="tickets/",
        blank=True,
        null=True
    )

    def __str__(self):
        return f"{self.name} - {self.event.title}"


class TicketPurchase(models.Model):

    # ---------------------------------------------------------
    # CUSTOMER
    # ---------------------------------------------------------

    # Nullable because guest Paystack customers have no account.
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="event_purchases"
    )

    full_name = models.CharField(max_length=255)

    email = models.EmailField()

    # ---------------------------------------------------------
    # TICKET
    # ---------------------------------------------------------

    ticket = models.ForeignKey(
        Ticket,
        on_delete=models.CASCADE,
        related_name="purchases"
    )

    copies = models.PositiveIntegerField(default=1)

    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    # ---------------------------------------------------------
    # MONIEPLUG FINANCIAL BREAKDOWN
    # ---------------------------------------------------------

    # Amount kept by Monieplug.
    platform_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    # Amount payable to event organizer.
    organizer_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    # ---------------------------------------------------------
    # TICKET QR CODES
    # ---------------------------------------------------------

    # Stores generated QR filenames.
    qr_codes = models.JSONField(
        default=list,
        blank=True
    )

    # Public/internal purchase identifier.
    reference_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )

    # ---------------------------------------------------------
    # WAAS WALLET PAYMENT TRACKING
    # ---------------------------------------------------------

    debit_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    credit_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # PAYSTACK PAYMENT TRACKING
    # ---------------------------------------------------------

    paystack_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True
    )

    paystack_account_number = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    paystack_account_name = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    paystack_bank = models.CharField(
        max_length=255,
        blank=True,
        null=True
    )

    paystack_account_expires_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # PAYSTACK ORGANIZER PAYOUT
    # ---------------------------------------------------------

    # Paystack transfer reference used to pay organizer.
    paystack_transfer_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True
    )

    payout_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("PROCESSING", "Processing"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
            ("REVERSED", "Reversed"),
        ],
        default="PENDING"
    )

    payout_error = models.TextField(
        blank=True,
        null=True
    )

    # ---------------------------------------------------------
    # PAYMENT VERIFICATION
    # ---------------------------------------------------------

    webhook_verified = models.BooleanField(
        default=False
    )

    payment_method = models.CharField(
        max_length=30,
        choices=[
            ("WAAS", "WAAS Wallet"),
            ("PAYSTACK", "Paystack"),
        ],
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
            ("EXPIRED", "Expired"),
        ],
        default="PENDING"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    # ---------------------------------------------------------
    # METHODS
    # ---------------------------------------------------------

    def save(self, *args, **kwargs):
        """
        Save purchase without generating QR codes.

        QR codes should only be generated after confirmed payment.
        """
        if self.ticket_id and self.copies:
            self.total_price = self.ticket.price * self.copies

        super().save(*args, **kwargs)

    def generate_qr_codes(self):
        """
        Generate QR codes after successful payment.

        This method is intentionally separate from save()
        so unpaid purchases do not receive tickets.
        """

        if self.qr_codes:
            return self.qr_codes

        qr_list = []

        for i in range(self.copies):

            qr_data = (
                f"{self.email}|"
                f"{self.reference_id}|"
                f"copy-{i + 1}"
            )

            qr = qrcode.make(qr_data)

            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")

            filename = (
                f"{self.reference_id}_copy{i + 1}.png"
            )

            default_storage.save(
                f"qrcodes/{filename}",
                ContentFile(buffer.getvalue())
            )

            qr_list.append(filename)

        self.qr_codes = qr_list

        self.save(update_fields=["qr_codes"])

        return qr_list

    def __str__(self):
        return (
            f"{self.full_name} - "
            f"{self.ticket.event.title}"
        )