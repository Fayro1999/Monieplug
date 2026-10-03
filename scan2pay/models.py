from django.db import models
from django.contrib.auth import get_user_model
import uuid
import io
import qrcode

from django.core.files.base import ContentFile


User = get_user_model()


class VendorQRCode(models.Model):
    vendor = models.ForeignKey(
        User,
        on_delete=models.CASCADE
    )

    business_name = models.CharField(
        max_length=255
    )

    business_address = models.CharField(
        max_length=255
    )

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True
    )

    description = models.TextField(
        blank=True,
        null=True
    )

    qr_label = models.CharField(
        max_length=50
    )

    payment_variation = models.JSONField(
        blank=True,
        null=True
    )

    qr_code_image = models.ImageField(
        upload_to="scan2pay/qrcodes/",
        blank=True,
        null=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def save(self, *args, **kwargs):
        creating = self.pk is None

        super().save(*args, **kwargs)

        # Generate QR only on creation
        if creating or not self.qr_code_image:

            qr_data = (
                f"https://monieplug-new.vercel.app/"
                f"scantopay/qr?qr_id={self.id}"
            )

            qr = qrcode.make(qr_data)

            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")

            filename = f"{uuid.uuid4()}.png"

            self.qr_code_image.save(
                filename,
                ContentFile(buffer.getvalue()),
                save=False
            )

            super().save(
                update_fields=["qr_code_image"]
            )


class Scan2PayTransaction(models.Model):

    # ==========================================
    # CUSTOMER / SENDER
    # ==========================================

    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scan2pay_sent"
    )

    # Common customer details.
    #
    # Registered user:
    #     Automatically populated from User.
    #
    # Guest:
    #     Supplied during Paystack checkout.
    customer_name = models.CharField(
        max_length=255,
        null=True,
    blank=True
    )

    customer_email = models.EmailField(null=True,
    blank=True)

    # ==========================================
    # VENDOR
    # ==========================================

    vendor = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="scan2pay_received"
    )

    qr_code = models.ForeignKey(
        VendorQRCode,
        on_delete=models.SET_NULL,
        null=True
    )

    # ==========================================
    # AMOUNTS
    # ==========================================

    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    platform_charge = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    vendor_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0
    )

    # ==========================================
    # PAYMENT METHOD
    # ==========================================

    payment_method = models.CharField(
        max_length=20,
        choices=[
            ("WALLET", "Wallet Balance"),
            ("PAYSTACK", "Paystack"),
        ]
    )

    # ==========================================
    # PAYSTACK TEMPORARY TRANSFER ACCOUNT
    # ==========================================

    paystack_account_number = models.CharField(
        max_length=30,
        null=True,
        blank=True
    )

    paystack_account_name = models.CharField(
        max_length=255,
        null=True,
        blank=True
    )

    paystack_bank_name = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    paystack_account_expires_at = models.DateTimeField(
        null=True,
        blank=True
    )

    # ==========================================
    # REFERENCES
    # ==========================================

    reference_id = models.UUIDField(
        default=uuid.uuid4,
        editable=False,
        unique=True
    )

    paystack_reference = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True
    )

    payout_reference = models.CharField(
        max_length=100,
        null=True,
        blank=True
    )

    # ==========================================
    # PAYMENT STATUS
    # ==========================================

    status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
        ],
        default="PENDING"
    )

    # ==========================================
    # VENDOR PAYOUT STATUS
    # ==========================================

    payout_status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("PROCESSING", "Processing"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
        ],
        default="PENDING"
    )

    # ==========================================
    # TIMESTAMPS
    # ==========================================

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.reference_id} - {self.status}"