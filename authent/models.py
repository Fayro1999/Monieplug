
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
import uuid


class UserManager(BaseUserManager):

    def create_user(self, email, phone, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")

        if not phone:
            raise ValueError("Phone is required")

        email = self.normalize_email(email)

        user = self.model(
            email=email,
            phone=phone,
            **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)

        return user

    def create_superuser(self, email, phone, password=None, **extra_fields):

        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)

        return self.create_user(
            email,
            phone,
            password,
            **extra_fields
        )


class User(AbstractBaseUser, PermissionsMixin):

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    # ===============================
    # PERSONAL INFORMATION
    # ===============================

    first_name = models.CharField(
        max_length=50
    )

    last_name = models.CharField(
        max_length=50
    )

    email = models.EmailField(
        unique=True
    )

    phone = models.CharField(
        max_length=20,
        unique=True
    )

    date_of_birth = models.DateField(
        blank=True,
        null=True
    )

    gender = models.PositiveSmallIntegerField(
        choices=[
            (0, "Male"),
            (1, "Female"),
        ],
        blank=True,
        null=True
    )

    address = models.CharField(
        max_length=200,
        blank=True,
        null=True
    )

    city = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    state = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    country = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    # ===============================
    # KYC / IDENTITY INFORMATION
    # ===============================

    bvn = models.CharField(
        max_length=11,
        blank=True,
        null=True
    )

    nin = models.CharField(
        max_length=11,
        blank=True,
        null=True
    )

    nin_user_id = models.CharField(
        max_length=11,
        blank=True,
        null=True
    )

    facial_image = models.TextField(
        blank=True,
        null=True
    )

    next_of_kin_name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    next_of_kin_phone = models.CharField(
        max_length=15,
        blank=True,
        null=True
    )

    # ===============================
    # ACCOUNT STATUS
    # ===============================

    is_active = models.BooleanField(
        default=False
    )

    is_staff = models.BooleanField(
        default=False
    )

    # ===============================
    # WAAS WALLET INFORMATION
    # ===============================

    wallet_id = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    wallet_account_number = models.CharField(
        max_length=20,
        blank=True,
        null=True
    )

    wallet_name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    wallet_bank_name = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default="WAAS"
    )

    # ===============================
    # SECURITY
    # ===============================

    transaction_pin = models.CharField(
        max_length=128,
        blank=True,
        null=True
    )

    # ===============================
    # EMAIL VERIFICATION
    # ===============================

    email_verification_code = models.CharField(
        max_length=6,
        blank=True,
        null=True
    )

    is_email_verified = models.BooleanField(
        default=False
    )

    # ===============================
    # KYC / IDENTITY STATUS
    # ===============================

    is_identity_verified = models.BooleanField(
        default=False
    )

    verification_status = models.CharField(
        max_length=20,
        choices=[
            ("Pending", "Pending"),
            ("Ongoing", "Ongoing"),
            ("Completed", "Completed"),
            ("Failed", "Failed"),
            ("Abandoned", "Abandoned"),
        ],
        default="Pending"
    )

    verification_mode = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    identity_transaction_ref = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    identity_verified_at = models.DateTimeField(
        blank=True,
        null=True
    )

    # ===============================
# REFERRAL
# ===============================

    referral_name = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    referral_phone = models.CharField(
        max_length=15,
        blank=True,
        null=True
    )

    paystack_recipient_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        unique=True
    )

    # ===============================
    # USER MANAGER
    # ===============================

    objects = UserManager()

    USERNAME_FIELD = "phone"

    REQUIRED_FIELDS = [
        "email",
        "first_name",
        "last_name"
    ]

    def __str__(self):
        return self.email

