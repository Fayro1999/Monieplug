from rest_framework import serializers
from .models import User
from decimal import Decimal


class SignupSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    date_of_birth = serializers.DateField(
        format="%d/%m/%Y",
        input_formats=["%d/%m/%Y", "%Y-%m-%d"]
    )

    gender = serializers.ChoiceField(
        choices=[
            ("0", "Male"),
            ("1", "Female"),
        ]
    )

    address = serializers.CharField(max_length=200)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    country = serializers.CharField(max_length=100)

    # Optional information required later for WAAS wallet opening
    nin_user_id = serializers.CharField(
        max_length=11,
        required=False,
        allow_blank=True
    )

    next_of_kin_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True
    )

    next_of_kin_phone = serializers.CharField(
        max_length=15,
        required=False,
        allow_blank=True
    )

    referral_name = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True
    )

    referral_phone = serializers.CharField(
        max_length=15,
        required=False,
        allow_blank=True
    )

    email_verification_code = serializers.CharField(
        max_length=6,
        read_only=True
    )


class InitiateIdentityVerificationSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()

    identity_type = serializers.ChoiceField(
        choices=[
            ("BVN", "BVN"),
            ("NIN", "NIN"),
        ]
    )

    bvn = serializers.CharField(
        min_length=11,
        max_length=11,
        required=False,
        allow_blank=True
    )

    nin = serializers.CharField(
        min_length=11,
        max_length=11,
        required=False,
        allow_blank=True
    )

    verification_type = serializers.ChoiceField(
        choices=[
            ("OTP", "OTP"),
            ("FACIAL", "FACIAL"),
        ]
    )

    image = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        write_only=True,
        help_text=(
            "Base64 facial image. Required only when "
            "verification_type is FACIAL."
        )
    )

    def validate(self, attrs):
        identity_type = attrs["identity_type"]
        bvn = attrs.get("bvn", "").strip()
        nin = attrs.get("nin", "").strip()
        verification_type = attrs["verification_type"]
        image = attrs.get("image")

        if identity_type == "BVN":
            if not bvn:
                raise serializers.ValidationError({
                    "bvn": "BVN is required."
                })

            if not bvn.isdigit():
                raise serializers.ValidationError({
                    "bvn": "BVN must contain digits only."
                })

        elif identity_type == "NIN":
            if not nin:
                raise serializers.ValidationError({
                    "nin": "NIN is required."
                })

            if not nin.isdigit():
                raise serializers.ValidationError({
                    "nin": "NIN must contain digits only."
                })

        if verification_type == "FACIAL" and not image:
            raise serializers.ValidationError({
                "image": (
                    "A Base64 facial image is required "
                    "for FACIAL verification."
                )
            })

        return attrs


class VerifyIdentitySerializer(serializers.Serializer):
    transaction_ref = serializers.CharField(
        max_length=100
    )

    otp = serializers.CharField(
        min_length=6,
        max_length=6
    )


class VerifyEmailSerializer(serializers.Serializer):
    code = serializers.CharField()



class LoginSerializer(serializers.Serializer):
    phone = serializers.CharField()
    password = serializers.CharField(write_only=True)


class SetTransactionPinSerializer(serializers.Serializer):
    pin = serializers.CharField(min_length=4, max_length=4)


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField()
    new_password = serializers.CharField(write_only=True)


class TransferFundsSerializer(serializers.Serializer):
    destinationAccount = serializers.CharField(max_length=10)
    destinationBankCode = serializers.CharField(max_length=6)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    narration = serializers.CharField(max_length=50, required=False)
    transaction_pin = serializers.CharField(write_only=True, required=True)


class VerifyAccountSerializer(serializers.Serializer):
    account_number = serializers.CharField()
    bank_code = serializers.CharField()


class WalletEnquiryResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    message = serializers.CharField()
    account = serializers.JSONField()

class GetBalanceSerializer(serializers.Serializer):
    accountNo = serializers.CharField()



class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "email",
            "phone",
            "wallet_id",
            "wallet_account_number",
            "wallet_name",
            "wallet_bank_name",
            "is_active",
            "is_staff",
        ]





class WalletTransactionHistorySerializer(serializers.Serializer):
    accountNumber = serializers.CharField()
    fromDate = serializers.CharField()
    toDate = serializers.CharField()
    numberOfItems = serializers.CharField()


class WalletTransactionHistoryResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    message = serializers.CharField()
    data = serializers.JSONField()


class OtherBankCustomerSerializer(serializers.Serializer):
    accountNumber = serializers.CharField()
    bankCode = serializers.CharField()


class OtherBankEnquirySerializer(serializers.Serializer):
    customer = OtherBankCustomerSerializer()


class OtherBankEnquiryResponseSerializer(serializers.Serializer):
    status = serializers.CharField()
    message = serializers.CharField()
    data = serializers.JSONField()


class WalletDebitCreditSerializer(serializers.Serializer):
    amount = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.01")
    )

    narration = serializers.CharField(
        max_length=100
    )

    transaction_id = serializers.CharField(
        max_length=25,
        required=True
    )


#class OnboardingStatusSerializer(serializers.Serializer):
    #status = serializers.CharField()
    #onboarding_step = serializers.CharField()
    #next_step = serializers.CharField(
        #allow_null=True,
        #required=False
    #)