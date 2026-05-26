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
            return Response({
                "message": "QR Code created",
             "qr_code_url": qr.qr_code_image.url,
             "qr_id": qr.id,
             "vendor_id": qr.vendor.id,
            "business_name": qr.business_name,
            "amount": qr.amount})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



from decimal import Decimal, InvalidOperation
import uuid
import requests

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import transaction

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import VendorQRCode, Scan2PayTransaction
from .serializers import Scan2PayCheckoutSerializer


# ================================
# PLATFORM CHARGE
# ================================
def calculate_platform_charge(amount):
    if amount < 10000:
        return Decimal("150")
    elif amount < 500000:
        return Decimal("200")
    return Decimal("250")


# ================================
# SCAN2PAY CHECKOUT
# ================================
class Scan2PayCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    # =================================
    # WAAS AUTH
    # =================================
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

    # =================================
    # WAAS CALL
    # =================================
    def waas_transfer(self, url, token, payload):
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            return {"status": "FAILED", "message": str(e)}

    # =================================
    # CHECKOUT
    # =================================
    @extend_schema(
        summary="Scan2Pay Checkout Payment",
        description="Customer pays via wallet_other_banks → platform settles vendor",
        request=Scan2PayCheckoutSerializer,
        responses={
            200: OpenApiResponse(description="Payment successful"),
            400: OpenApiResponse(description="Payment failed"),
            403: OpenApiResponse(description="Invalid PIN"),
            404: OpenApiResponse(description="QR not found"),
            500: OpenApiResponse(description="Server error"),
        },
    )
    def post(self, request, qr_id):

        user = request.user
        data = request.data

        amount_input = data.get("amount")
        transaction_pin = data.get("transaction_pin")

        # =================================
        # PIN VALIDATION
        # =================================
        if not user.transaction_pin:
            return Response({"error": "Transaction PIN not set"}, status=403)

        if not check_password(transaction_pin, user.transaction_pin):
            return Response({"error": "Invalid transaction PIN"}, status=403)

        # =================================
        # GET QR
        # =================================
        try:
            qr_code = VendorQRCode.objects.get(id=qr_id)
        except VendorQRCode.DoesNotExist:
            return Response({"error": "Invalid QR code"}, status=404)

        # =================================
        # AMOUNT HANDLING (HYBRID SAFE)
        # =================================
        try:
            if qr_code.amount:
                amount = Decimal(qr_code.amount)
            else:
                amount = Decimal(amount_input)

            if amount <= 0:
                return Response({"error": "Invalid amount"}, status=400)

        except (InvalidOperation, TypeError):
            return Response({"error": "Invalid amount format"}, status=400)

        # =================================
        # PLATFORM CHARGE
        # =================================
        platform_charge = calculate_platform_charge(amount)
        vendor_amount = amount - platform_charge

        if vendor_amount <= 0:
            return Response({"error": "Invalid settlement amount"}, status=400)

        # =================================
        # WAAS TOKEN
        # =================================
        token = self.get_waas_token()
        if not token:
            return Response({"error": "WAAS authentication failed"}, status=500)

        transaction_id = str(uuid.uuid4()).replace("-", "")[:25]
        narration = f"Scan2Pay-{qr_code.qr_label}"[:100]

        # =================================
        # STEP 1: COLLECTION (Customer → Platform)
        # wallet_other_banks
        # =================================
        collection_url = (
            "http://102.216.128.75:9090/"
            "waas/api/v1/wallet_other_banks"
        )

        collection_payload = {
    "transaction": {
        "reference": transaction_id
    },

    "order": {
        "amount": str(amount),
        "currency": "NGN",
        "description": f"Scan2Pay payment for {qr_code.qr_label}",
        "country": "NG"
    },

    # ✔ CUSTOMER = SENDER ONLY
    "customer": {
        "account": {
            "number": user.wallet_account_number,
            "bank": "120001",
            "senderaccountnumber": user.wallet_account_number,
            "name": f"{user.first_name} {user.last_name}",
            "sendername": f"{user.first_name} {user.last_name}"
        }
    },

    # ✔ MERCHANT / PLATFORM = RECEIVER
    "merchant": {
        "account": {
            "number": settings.PLATFORM_ACCOUNT_NUMBER,
            "bank": "120001",
            "merchantFeeAmount": str(platform_charge),
            
        },
        "isFee": True
    },

    "transactionType": "INTRA_BANK",
    "narration": narration
}
        collection_response = self.waas_transfer(
            collection_url,
            token,
            collection_payload
        )

        if collection_response.get("status", "").upper() != "SUCCESS":
            return Response(
                {
                    "error": "Payment collection failed",
                    "details": collection_response
                },
                status=400
            )

        # =================================
        # STEP 2: SETTLEMENT (Platform → Vendor)
        # =================================
        settlement_url = (
            "http://102.216.128.75:9090/"
            "waas/api/v1/credit/transfer"
        )

        settlement_payload = {
            "accountNo": qr_code.vendor.wallet_account_number,
            "totalAmount": str(vendor_amount),
            "transactionId": transaction_id + "V",
            "narration": f"Payout-{qr_code.qr_label}"[:100],
        }

        settlement_response = self.waas_transfer(
            settlement_url,
            token,
            settlement_payload
        )

        if settlement_response.get("status", "").upper() != "SUCCESS":
            return Response(
                {
                    "error": "Vendor settlement failed",
                    "details": settlement_response
                },
                status=400
            )

        # =================================
        # SAVE TRANSACTION
        # =================================
        with transaction.atomic():
            Scan2PayTransaction.objects.create(
                sender=user,
                vendor=qr_code.vendor,
                qr_code=qr_code,
                amount=amount,
                platform_charge=platform_charge,
                status="SUCCESS"
            )

        return Response({
            "message": "Payment successful",
            "reference_id": transaction_id,
            "amount": str(amount),
            "platform_charge": str(platform_charge),
            "vendor_received": str(vendor_amount)
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
