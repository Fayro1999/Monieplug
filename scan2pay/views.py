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
from .serializers import VendorQRCodeSerializer, Scan2PayTransactionSerializer

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

# Registered user checkout
class Scan2PayCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(exclude=True)
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

        if qr_code.amount:
            amount = Decimal(qr_code.amount)
        else:
            amount = Decimal(amount)

        platform_charge = calculate_platform_charge(amount)
        vendor_amount = amount - platform_charge

        narration = f"Scan2Pay-{qr_code.qr_label}"[:20]
        buyer_transfer = rova_transfer(
            destination_account=PLATFORM_ACCOUNT_NUMBER,
            destination_bank_code=PLATFORM_BANK_CODE,
            amount=amount,
            narration=narration,
        )
        if buyer_transfer.get("status") != "SUCCESS" or buyer_transfer["data"].get("status") != "SUCCESSFUL":
            return Response({"error": "Failed to debit user", "details": buyer_transfer}, status=400)

        vendor_transfer = rova_transfer(
            destination_account=qr_code.vendor.virtual_account_number,
            destination_bank_code="214001",
            amount=vendor_amount,
            narration=f"Payout-{qr_code.qr_label}"[:20],
        )
        if vendor_transfer.get("status") != "SUCCESS" or vendor_transfer["data"].get("status") != "SUCCESSFUL":
            return Response({"error": "Vendor payout failed", "details": vendor_transfer}, status=400)

        tx = Scan2PayTransaction.objects.create(
            sender=user,
            vendor=qr_code.vendor,
            qr_code=qr_code,
            amount=amount,
            platform_charge=platform_charge,
            status="SUCCESS"
        )

        email_subject = f"Your Payment Receipt - {qr_code.qr_label}"
        email_body = f"""
Hello {full_name},

✅ Payment Successful!

Business: {qr_code.business_name}
Amount Paid: ₦{amount}
Platform Charge: ₦{platform_charge}
Vendor Receives: ₦{vendor_amount}

Reference ID: {tx.reference_id}

Thank you for using Scan2Pay!
"""
        email_msg = EmailMessage(subject=email_subject, body=email_body, from_email=settings.DEFAULT_FROM_EMAIL, to=[email])
        email_msg.send(fail_silently=True)

        serializer = Scan2PayTransactionSerializer(tx)
        return Response({"message": "Payment completed successfully", "transaction": serializer.data})

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
