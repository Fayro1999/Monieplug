# authent/serializers.py
from rest_framework import serializers


class SignupSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    dob = serializers.DateField()
    gender = serializers.CharField()
    address1 = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    country = serializers.CharField()


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


class GetAccountBalanceSerializer(serializers.Serializer):
    account_number = serializers.CharField()
    customer_ref = serializers.CharField()
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    mobile_no = serializers.CharField(required=False)
