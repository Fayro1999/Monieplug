# authent/serializers.py
from rest_framework import serializers
from .models import User


class SignupSerializer(serializers.Serializer):
    first_name = serializers.CharField(max_length=50)
    last_name = serializers.CharField(max_length=50)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    date_of_birth = serializers.DateField(format="%d/%m/%Y", input_formats=["%d/%m/%Y", "%Y-%m-%d"])
    gender = serializers.ChoiceField(choices=[("0", "Male"), ("1", "Female")])
    address = serializers.CharField(max_length=200)
    city = serializers.CharField(max_length=100)
    state = serializers.CharField(max_length=100)
    country = serializers.CharField(max_length=100)

    # Optional fields for WAAS wallet
    nin_user_id = serializers.CharField(max_length=11, required=False, allow_blank=True)
    bvn = serializers.CharField(max_length=11, required=False, allow_blank=True)
    next_of_kin_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    next_of_kin_phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    referral_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    referral_phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    email_verification_code = serializers.CharField(max_length=6, read_only=True)

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