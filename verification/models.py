from django.db import models
from django.conf import settings


class Verification(models.Model):

    STATUS_CHOICES = [
        ("Pending", "Pending"),
        ("Ongoing", "Ongoing"),
        ("Completed", "Completed"),
        ("Failed", "Failed"),
        ("Abandoned", "Abandoned"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="verifications",
    )

    reference_id = models.CharField(
        max_length=100,
        unique=True,
    )

    verification_type = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    verification_mode = models.CharField(
        max_length=50,
        blank=True,
        null=True,
    )

    verification_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="Pending",
    )

    verification_value = models.CharField(
        max_length=255,
        blank=True,
        null=True,
    )

    selfie_url = models.URLField(
        blank=True,
        null=True,
    )

    id_url = models.URLField(
        blank=True,
        null=True,
    )

    confidence_score = models.FloatField(
        blank=True,
        null=True,
    )

    raw_response = models.JSONField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    completed_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    def __str__(self):
        return f"{self.user.phone} - {self.reference_id}"