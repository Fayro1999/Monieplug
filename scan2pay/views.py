from decimal import Decimal
import uuid, requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.contrib.auth.hashers import check_password
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from .models import VendorQRCode, Scan2PayTransaction
from .serializers import VendorQRCodeSerializer, Scan2PayTransactionSerializer, Scan2PayCheckoutSerializer
from drf_spectacular.utils import extend_schema, OpenApiResponse

ROVA_API_BASE_URL = "https://baas.dev.getrova.co.uk"
PLATFORM_ACCOUNT_NUMBER = "4000005778"
PLATFORM_BANK_CODE = "000003"  # Fidelity Bank

def calculate_platform_charge(amount):
    if amount < 10000:
        return 150
    elif amount < 500000:
        return 200
    return 250

def rova_transfer(destination_account, destination_bank_code, amount, narration):
    url = f"{ROVA_API_BASE_URL}/transfer"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.ROVA_BAAS_TOKEN}",
    }
    payload = {
        "destinationAccount": destination_account,
        "destinationBankCode": destination_bank_code,
        "amount": f"{Decimal(amount):.2f}",
        "clientReference": str(uuid.uuid4()),
        "narration": narration[:20],
    }
    response = requests.post(url, json=payload, headers=headers, timeout=30)
    try:
        return response.json()
    except ValueError:
        return {"status": "ERROR", "message": response.text}

# Vendor creates QR Code
class VendorQRCodeCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data.copy()
        data["vendor"] = request.user.id
        serializer = VendorQRCodeSerializer(data=data, context={"request": request})
        if serializer.is_valid():
            qr = serializer.save()
            return Response({"message": "QR Code created", "qr_code_url": qr.qr_code_image.url})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

import uuid
import requests
from decimal import Decimal, InvalidOperation
from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core.mail import EmailMessage
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status


class Scan2PayCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    # 🔐 WAAS TOKEN
    def get_waas_token(self):
        url = "http://102.216.128.75:9090/waas/api/v1/authenticate"

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:
            resp = requests.post(url, json=payload, timeout=30)
            return resp.json().get("accessToken")
        except Exception:
            return None

    # 💳 WAAS TRANSFER CORE
    def waas_transfer(self, url, token, payload):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)
        return response.json()

    # =========================
    # ✅ SWAGGER GOES HERE
    # =========================
    @extend_schema(
        summary="Scan2Pay Checkout Payment",
        description="Debits customer wallet and credits vendor wallet via WAAS",
        request=Scan2PayCheckoutSerializer,
        responses={
            200: OpenApiResponse(description="Payment successful"),
            400: OpenApiResponse(description="Payment failed"),
            403: OpenApiResponse(description="Invalid PIN"),
            500: OpenApiResponse(description="Server error"),
        },
    )
    def post(self, request):

        data = request.data

        qr_id = data.get("qr_id")
        amount = data.get("amount")
        full_name = data.get("full_name")
        email = data.get("email")
        transaction_pin = data.get("transaction_pin")

        user = request.user

        if not user.transaction_pin:
            return Response({"error": "Transaction PIN not set"}, status=403)

        if not check_password(transaction_pin, user.transaction_pin):
            return Response({"error": "Invalid transaction PIN"}, status=403)

        try:
            qr_code = VendorQRCode.objects.get(id=qr_id)
        except VendorQRCode.DoesNotExist:
            return Response({"error": "Invalid QR code"}, status=404)

        try:
            amount = Decimal(qr_code.amount if qr_code.amount else amount)
        except (InvalidOperation, TypeError):
            return Response({"error": "Invalid amount"}, status=400)

        if amount <= 0:
            return Response({"error": "Amount must be greater than 0"}, status=400)

        platform_charge = calculate_platform_charge(amount)
        vendor_amount = amount - platform_charge

        token = self.get_waas_token()
        if not token:
            return Response({"error": "WAAS authentication failed"}, status=500)

        transaction_id = str(uuid.uuid4()).replace("-", "")[:25]

        narration = f"Scan2Pay-{qr_code.qr_label}"[:100]

        merchant = {
            "merchantFeeAccount": PLATFORM_ACCOUNT_NUMBER,
            "merchantFeeAmount": "0",
            "isFee": False
        }

        try:
            with transaction.atomic():

                debit_payload = {
                    "accountNo": user.wallet_account_number,
                    "totalAmount": str(amount),
                    "transactionId": transaction_id,
                    "narration": narration,
                    "merchant": merchant
                }

                debit_url = "http://102.216.128.75:9090/waas/api/v1/debit/transfer"
                debit_response = self.waas_transfer(debit_url, token, debit_payload)

                if debit_response.get("status", "").upper() != "SUCCESS":
                    return Response({"error": "Wallet debit failed", "details": debit_response}, status=400)

                credit_payload = {
                    "accountNo": qr_code.vendor.wallet_account_number,
                    "totalAmount": str(vendor_amount),
                    "transactionId": transaction_id + "V",
                    "narration": f"Payout-{qr_code.qr_label}"[:100],
                    "merchant": merchant
                }

                credit_url = "http://102.216.128.75:9090/waas/api/v1/credit/transfer"
                credit_response = self.waas_transfer(credit_url, token, credit_payload)

                if credit_response.get("status", "").upper() != "SUCCESS":
                    return Response({"error": "Vendor credit failed", "details": credit_response}, status=400)

                Scan2PayTransaction.objects.create(
                    sender=user,
                    vendor=qr_code.vendor,
                    qr_code=qr_code,
                    amount=amount,
                    platform_charge=platform_charge,
                    status="SUCCESS",
                    reference_id=transaction_id
                )

        except Exception as e:
            return Response({"error": "Transaction failed", "message": str(e)}, status=500)

        return Response({
            "message": "Payment successful",
            "reference_id": transaction_id
        }, status=200)
        
# Unregistered user
class Scan2PayUnregisteredView(APIView):
    def post(self, request):
        data = request.data
        qr_id = data.get("qr_id")
        try:
            qr_code = VendorQRCode.objects.get(id=qr_id)
        except VendorQRCode.DoesNotExist:
            return Response({"error": "Invalid QR code"}, status=404)

        return Response({
            "message": "Please make a bank transfer to complete payment. For faster transactions, sign up with us!",
            "vendor": qr_code.vendor.email,
            "dynamic_account_number": PLATFORM_ACCOUNT_NUMBER,
            "bank_code": PLATFORM_BANK_CODE,
            "amount": qr_code.amount or "Open amount",
        })
