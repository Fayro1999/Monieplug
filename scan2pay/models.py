from django.db import models
from django.contrib.auth import get_user_model
import uuid, io, qrcode
from django.core.files.base import ContentFile

User = get_user_model()

class VendorQRCode(models.Model):
    vendor = models.ForeignKey(User, on_delete=models.CASCADE)
    business_name = models.CharField(max_length=255)
    business_address = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    qr_label = models.CharField(max_length=50)
    payment_variation = models.JSONField(blank=True, null=True)  # ["Service", "Product"]
    qr_code_image = models.ImageField(upload_to="scan2pay/qrcodes/")
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.qr_code_image:
            qr_data = f"{self.vendor.id}|{self.amount}|{self.qr_label}"
            qr = qrcode.make(qr_data)
            buffer = io.BytesIO()
            qr.save(buffer, format="PNG")
            filename = f"{uuid.uuid4()}.png"
            self.qr_code_image.save(filename, ContentFile(buffer.getvalue()), save=False)
        super().save(*args, **kwargs)


class Scan2PayTransaction(models.Model):
    sender = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)
    vendor = models.ForeignKey(User, on_delete=models.CASCADE, related_name="scan2pay_received")
    qr_code = models.ForeignKey(VendorQRCode, on_delete=models.SET_NULL, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    platform_charge = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    reference_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    status = models.CharField(max_length=20, choices=[
        ("PENDING","Pending"),
        ("SUCCESS","Success"),
        ("FAILED","Failed")
    ], default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.reference_id} - {self.status}"
