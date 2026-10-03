from rest_framework import serializers

from .models import VendorQRCode, Scan2PayTransaction


class VendorQRCodeSerializer(serializers.ModelSerializer):

    class Meta:
        model = VendorQRCode
        fields = "__all__"
        read_only_fields = [
            "qr_code_image",
            "vendor",
            "created_at",
        ]

    def create(self, validated_data):
        request = self.context.get("request")

        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError(
                "User authentication required to create QR code."
            )

        qr_code = VendorQRCode.objects.create(
            vendor=request.user,
            **validated_data
        )

        return qr_code


class Scan2PayTransactionSerializer(serializers.ModelSerializer):

    class Meta:
        model = Scan2PayTransaction

        fields = "__all__"

        read_only_fields = [
            "reference_id",
            "status",
            "payout_status",
            "created_at",
            "updated_at",
            "vendor",
            "sender",
            "platform_charge",
            "vendor_amount",
            "payment_method",
            "paystack_account_number",
            "paystack_account_name",
            "paystack_bank_name",
            "paystack_account_expires_at",
            "paystack_reference",
            "payout_reference",
        ]


class Scan2PayCheckoutSerializer(serializers.Serializer):

    qr_id = serializers.UUIDField()

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        help_text=(
            "Payment amount. Required only when the QR code does not "
            "have a fixed amount."
        ),
    )

    customer_name = serializers.CharField(
        max_length=255,
        help_text=(
            "Customer's full name. For registered customers, "
            "the frontend should prefill this from the customer's profile."
        ),
        
    )

    customer_email = serializers.EmailField(
    help_text=(
            "Customer's email address. For registered customers, "
            "the frontend should prefill this from the customer's profile."
        ),
    )

    payment_method = serializers.ChoiceField(
        choices=[
            ("WALLET", "Wallet Balance"),
            ("PAYSTACK", "Paystack"),
        ]
    )

    transaction_pin = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True
    )

    def validate(self, attrs):

        payment_method = attrs.get("payment_method")

        if payment_method == "WALLET":
            transaction_pin = attrs.get("transaction_pin")

            if not transaction_pin:
                raise serializers.ValidationError({
                    "transaction_pin": (
                        "Transaction PIN is required for wallet payments."
                    )
                })

        return attrs


class Scan2PayPaystackCheckoutSerializer(serializers.Serializer):

    qr_id = serializers.UUIDField()

    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        help_text=(
            "Payment amount. Required only when the QR code "
            "does not have a fixed amount."
        ),
    )

    customer_name = serializers.CharField(
        max_length=255,
        help_text=(
            "Customer's full name. For registered customers, "
            "the frontend should prefill this from the customer's profile. "
            "For guest customers, this must be entered manually."
        ),
    )

    customer_email = serializers.EmailField(
        help_text=(
            "Customer's email address. For registered customers, "
            "the frontend should prefill this from the customer's profile. "
            "For guest customers, this must be entered manually."
        ),
    )