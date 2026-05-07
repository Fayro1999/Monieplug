# models.py
from django.db import models
from django.contrib.auth import get_user_model
import uuid, io, qrcode
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

User = get_user_model()


class Event(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()
    date = models.DateTimeField()
    location = models.CharField(max_length=255)
    image = models.ImageField(upload_to="events/", blank=True, null=True)

    # Organizer = vendor (must have WAAS wallet)
    organizer = models.ForeignKey(User, on_delete=models.CASCADE)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Ticket(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='tickets')
    name = models.CharField(max_length=100)  # VIP, Regular
    price = models.DecimalField(max_digits=10, decimal_places=2)
    ticket_image = models.ImageField(upload_to="tickets/", blank=True, null=True)

    def __str__(self):
        return f"{self.name} - {self.event.title}"


class TicketPurchase(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    full_name = models.CharField(max_length=255)
    email = models.EmailField()

    ticket = models.ForeignKey('Ticket', on_delete=models.CASCADE)
    copies = models.PositiveIntegerField(default=1)

    total_price = models.DecimalField(max_digits=10, decimal_places=2)

    # store QR filenames
    qr_codes = models.JSONField(default=list, blank=True)

    reference_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    # 🔥 WAAS tracking (VERY IMPORTANT)
    debit_reference = models.CharField(max_length=100, blank=True, null=True)
    credit_reference = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(
        max_length=20,
        choices=[
            ("PENDING", "Pending"),
            ("SUCCESS", "Success"),
            ("FAILED", "Failed"),
        ],
        default="PENDING"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        # ✅ Always calculate total
        self.total_price = self.ticket.price * self.copies

        # ✅ Generate QR codes safely
        if not self.qr_codes:
            qr_list = []

            for i in range(self.copies):
                qr_data = f"{self.email}|{self.reference_id}|copy-{i+1}"

                qr = qrcode.make(qr_data)
                buffer = io.BytesIO()
                qr.save(buffer, format='PNG')

                filename = f"{self.reference_id}_copy{i+1}.png"
                qr_list.append(filename)

                default_storage.save(
                    f"qrcodes/{filename}",
                    ContentFile(buffer.getvalue())
                )

            self.qr_codes = qr_list

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.full_name} - {self.ticket.event.title}"