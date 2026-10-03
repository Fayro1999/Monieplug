import hashlib
import hmac
import uuid
import requests

from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework import status

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import VendorQRCode, Scan2PayTransaction
from .serializers import (
    VendorQRCodeSerializer,
    Scan2PayTransactionSerializer,
    Scan2PayCheckoutSerializer,
    Scan2PayPaystackCheckoutSerializer
)


# ============================================================
# PAYSTACK
# ============================================================

PAYSTACK_BASE_URL = "https://api.paystack.co"


def paystack_headers():
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


# ============================================================
# PLATFORM CHARGE
# ============================================================

def calculate_platform_charge(amount):
    amount = Decimal(str(amount))

    if amount < Decimal("10000"):
        return Decimal("150")

    elif amount < Decimal("500000"):
        return Decimal("200")

    return Decimal("250")


# ============================================================
# AMOUNT VALIDATION
# ============================================================

def get_qr_amount(qr_code, amount_input):
    """
    Handles fixed-price and open-price QR codes.
    """

    try:

        # Fixed amount QR
        if qr_code.amount is not None:

            fixed_amount = Decimal(str(qr_code.amount))

            # If frontend supplied an amount for a fixed QR,
            # make sure it matches.
            if amount_input not in (None, ""):

                supplied_amount = Decimal(str(amount_input))

                if supplied_amount != fixed_amount:
                    return None, "Amount does not match the QR code."

            amount = fixed_amount

        # Open amount QR
        else:

            if amount_input in (None, ""):
                return None, "Amount is required."

            amount = Decimal(str(amount_input))

        if amount <= 0:
            return None, "Invalid amount."

        return amount, None

    except (InvalidOperation, TypeError, ValueError):

        return None, "Invalid amount format."


# ============================================================
# VENDOR PAYSTACK RECIPIENT
# ============================================================

def create_paystack_recipient(vendor):
    """
    Get or create the Paystack transfer recipient for a vendor.

    The vendor's existing WAAS/9PSB wallet account number
    is used as the recipient's NUBAN.
    """

    # Already created
    if vendor.paystack_recipient_code:

        return {
            "success": True,
            "recipient_code": vendor.paystack_recipient_code,
        }

    # Vendor must have a WAAS wallet account
    if not vendor.wallet_account_number:

        return {
            "success": False,
            "message": (
                "Vendor does not have a wallet account number."
            ),
        }

    # 9PSB bank code must be configured
    bank_code = getattr(
        settings,
        "PAYSTACK_9PSB_BANK_CODE",
        None,
    )

    if not bank_code:

        return {
            "success": False,
            "message": (
                "PAYSTACK_9PSB_BANK_CODE is not configured."
            ),
        }

    vendor_name = (
        f"{vendor.first_name} {vendor.last_name}"
    ).strip()

    if not vendor_name:
        vendor_name = vendor.email

    payload = {
        "type": "nuban",
        "name": vendor_name,
        "account_number": vendor.wallet_account_number,
        "bank_code": bank_code,
        "currency": "NGN",
    }

    try:

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transferrecipient",
            json=payload,
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": str(exc),
        }

    if not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Unable to create Paystack recipient.",
            ),
            "response": data,
        }

    recipient_code = (
        data.get("data", {})
        .get("recipient_code")
    )

    if not recipient_code:

        return {
            "success": False,
            "message": (
                "Paystack did not return a recipient code."
            ),
            "response": data,
        }

    vendor.paystack_recipient_code = recipient_code

    vendor.save(
        update_fields=["paystack_recipient_code"]
    )

    return {
        "success": True,
        "recipient_code": recipient_code,
    }


# ============================================================
# PAYSTACK VENDOR PAYOUT
# ============================================================

def paystack_vendor_payout(scan_transaction):
    """
    Transfer the vendor's share from Monieplug's Paystack
    balance to the vendor's WAAS/9PSB account.
    """

    vendor = scan_transaction.vendor

    # --------------------------------------------------------
    # Prevent duplicate payout
    # --------------------------------------------------------

    if scan_transaction.payout_status in (
        "PROCESSING",
        "SUCCESS",
    ):

        return {
            "success": True,
            "already_processing": True,
            "reference": scan_transaction.payout_reference,
        }

    # --------------------------------------------------------
    # Vendor amount
    # --------------------------------------------------------

    if scan_transaction.vendor_amount <= 0:

        return {
            "success": False,
            "message": "Invalid vendor settlement amount.",
        }

    # --------------------------------------------------------
    # Recipient
    # --------------------------------------------------------

    recipient_result = create_paystack_recipient(vendor)

    if not recipient_result["success"]:

        return {
            "success": False,
            "message": recipient_result["message"],
        }

    recipient_code = recipient_result["recipient_code"]

    # --------------------------------------------------------
    # Unique payout reference
    # --------------------------------------------------------

    payout_reference = (
        f"mp-payout-{scan_transaction.reference_id.hex}"
    )[:50]

    # --------------------------------------------------------
    # Paystack transfer
    # --------------------------------------------------------

    payload = {
        "source": "balance",

        "amount": int(
            scan_transaction.vendor_amount * 100
        ),

        "recipient": recipient_code,

        "reference": payout_reference,

        "reason": (
            f"Scan2Pay payout "
            f"{str(scan_transaction.reference_id)[:12]}"
        ),

        "currency": "NGN",
    }

    try:

        response = requests.post(
            f"{PAYSTACK_BASE_URL}/transfer",
            json=payload,
            headers=paystack_headers(),
            timeout=30,
        )

        data = response.json()

    except requests.RequestException as exc:

        return {
            "success": False,
            "message": str(exc),
        }

    if not data.get("status"):

        return {
            "success": False,
            "message": data.get(
                "message",
                "Vendor payout failed.",
            ),
            "response": data,
        }

    transfer_data = data.get("data", {})

    scan_transaction.payout_reference = (
        transfer_data.get(
            "reference",
            payout_reference,
        )
    )

    scan_transaction.payout_status = "PROCESSING"

    scan_transaction.save(
        update_fields=[
            "payout_reference",
            "payout_status",
            "updated_at",
        ]
    )

    return {
        "success": True,
        "reference": scan_transaction.payout_reference,
        "status": transfer_data.get("status"),
    }


# ============================================================
# VENDOR QR CREATION
# ============================================================

class VendorQRCodeCreateView(APIView):

    permission_classes = [IsAuthenticated]

    def post(self, request):

        data = request.data.copy()

        data["vendor"] = request.user.id

        serializer = VendorQRCodeSerializer(
            data=data,
            context={"request": request},
        )

        if serializer.is_valid():

            qr = serializer.save()

            return Response(
                {
                    "message": "QR Code created",
                    "qr_code_url": qr.qr_code_image.url,
                    "qr_id": qr.id,
                    "vendor_id": qr.vendor.id,
                    "business_name": qr.business_name,
                    "amount": (
                        str(qr.amount)
                        if qr.amount is not None
                        else None
                    ),
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            serializer.errors,
            status=status.HTTP_400_BAD_REQUEST,
        )


# ============================================================
# REGISTERED CUSTOMER - WALLET PAYMENT
# ============================================================



class Scan2PayCheckoutView(APIView):

    permission_classes = [IsAuthenticated]

    # --------------------------------------------------------
    # WAAS AUTHENTICATION
    # --------------------------------------------------------

    def get_waas_token(self):

        url = (
            "http://102.216.128.75:9090/"
            "waas/api/v1/authenticate"
        )

        payload = {
            "username": settings.WAAS_USERNAME,
            "password": settings.WAAS_PASSWORD,
            "clientId": settings.WAAS_CLIENT_ID,
            "clientSecret": settings.WAAS_CLIENT_SECRET,
        }

        try:

            response = requests.post(
                url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                timeout=30,
            )

            data = response.json()

            return data.get("accessToken")

        except (
            requests.RequestException,
            ValueError,
        ):

            return None

    # --------------------------------------------------------
    # WAAS REQUEST
    # --------------------------------------------------------

    def waas_transfer(
        self,
        url,
        token,
        payload,
    ):

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:

            response = requests.post(
                url,
                json=payload,
                headers=headers,
                timeout=30,
            )

            return response.json()

        except (
            requests.RequestException,
            ValueError,
        ) as exc:

            return {
                "status": "FAILED",
                "message": str(exc),
            }

    # --------------------------------------------------------
    # CHECKOUT
    # --------------------------------------------------------

    @extend_schema(
        summary="Scan2Pay Wallet Checkout",
        description=(
            "Registered customer pays using "
            "their Monieplug/WAAS wallet."
        ),
        request=Scan2PayCheckoutSerializer,
        responses={
            200: OpenApiResponse(
                description="Payment successful"
            ),
            400: OpenApiResponse(
                description="Payment failed"
            ),
            403: OpenApiResponse(
                description="Invalid PIN"
            ),
            404: OpenApiResponse(
                description="QR not found"
            ),
        },
    )
    def post(self, request, qr_id):

        user = request.user

        amount_input = request.data.get("amount")

        transaction_pin = request.data.get(
            "transaction_pin"
        )

        # ----------------------------------------------------
        # PIN
        # ----------------------------------------------------

        if not user.transaction_pin:

            return Response(
                {
                    "error": (
                        "Transaction PIN not set."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not transaction_pin:

            return Response(
                {
                    "error": (
                        "Transaction PIN is required."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not check_password(
            transaction_pin,
            user.transaction_pin,
        ):

            return Response(
                {
                    "error": "Invalid transaction PIN."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ----------------------------------------------------
        # QR
        # ----------------------------------------------------

        try:

            qr_code = VendorQRCode.objects.select_related(
                "vendor"
            ).get(id=qr_id)

        except VendorQRCode.DoesNotExist:

            return Response(
                {"error": "Invalid QR code."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ----------------------------------------------------
        # Prevent paying yourself
        # ----------------------------------------------------

        if user.id == qr_code.vendor_id:

            return Response(
                {
                    "error": (
                        "You cannot pay your own QR code."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # AMOUNT
        # ----------------------------------------------------

        amount, amount_error = get_qr_amount(
            qr_code,
            amount_input,
        )

        if amount_error:

            return Response(
                {"error": amount_error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # PLATFORM CHARGE
        # ----------------------------------------------------

        platform_charge = (
            calculate_platform_charge(amount)
        )

        vendor_amount = (
            amount - platform_charge
        )

        if vendor_amount <= 0:

            return Response(
                {
                    "error": (
                        "Invalid settlement amount."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # WAAS TOKEN
        # ----------------------------------------------------

        token = self.get_waas_token()

        if not token:

            return Response(
                {
                    "error": (
                        "WAAS authentication failed."
                    )
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ----------------------------------------------------
        # TRANSACTION REFERENCE
        # ----------------------------------------------------

        transaction_id = (
            str(uuid.uuid4())
            .replace("-", "")[:15]
        )

        narration = (
            f"Scan2Pay-{qr_code.qr_label}"
        )[:100]

        # ----------------------------------------------------
        # COLLECTION
        # CUSTOMER WALLET → PLATFORM
        # ----------------------------------------------------

        collection_url = (
            "http://102.216.128.75:9090/"
            "waas/api/v1/wallet_other_banks"
        )

        collection_payload = {

            "transaction": {
                "reference": transaction_id,
            },

            "order": {
                "amount": str(amount),
                "currency": "NGN",
                "description": (
                    f"Scan2Pay payment for "
                    f"{qr_code.qr_label}"
                ),
                "country": "NG",
            },

            "customer": {
                "account": {

                    "number": (
                        settings.PLATFORM_ACCOUNT_NUMBER
                    ),

                    "bank": "120001",

                    "senderaccountnumber": (
                        user.wallet_account_number
                    ),

                    "name": (
                        f"{user.first_name} "
                        f"{user.last_name}"
                    ),

                    "sendername": (
                        f"{user.first_name} "
                        f"{user.last_name}"
                    ),
                }
            },

            "merchant": {
                "isFee": True,
                "merchantFeeAccount": "1100015137",
                "merchantFeeAmount": "5.00",
            },

            "transactionType": "INTRA_BANK",

            "narration": narration,
        }

        collection_response = self.waas_transfer(
            collection_url,
            token,
            collection_payload,
        )

        if (
            collection_response
            .get("status", "")
            .upper()
            != "SUCCESS"
        ):

            return Response(
                {
                    "error": (
                        "Payment collection failed."
                    ),
                    "details": collection_response,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # SAVE SUCCESSFUL WALLET PAYMENT
        # ----------------------------------------------------

        with transaction.atomic():

            scan_transaction = (
                Scan2PayTransaction.objects.create(
                    sender=user,
                    vendor=qr_code.vendor,
                    qr_code=qr_code,

                    amount=amount,

                    platform_charge=platform_charge,

                    vendor_amount=vendor_amount,

                    payment_method="WALLET",

                    status="SUCCESS",

                    payout_status="PENDING",
                )
            )

        # ----------------------------------------------------
        # VENDOR SETTLEMENT
        # ----------------------------------------------------

        settlement_url = (
            "http://102.216.128.75:9090/"
            "waas/api/v1/credit/transfer"
        )

        settlement_payload = {

            "accountNo": (
                qr_code.vendor.wallet_account_number
            ),

            "totalAmount": str(vendor_amount),

            "transactionId": (
                transaction_id + "V"
            ),

            "narration": (
                f"Payout-{qr_code.qr_label}"
            )[:100],
        }

        settlement_response = self.waas_transfer(
            settlement_url,
            token,
            settlement_payload,
        )

        if (
            settlement_response
            .get("status", "")
            .upper()
            != "SUCCESS"
        ):

            scan_transaction.payout_status = "FAILED"

            scan_transaction.save(
                update_fields=[
                    "payout_status",
                    "updated_at",
                ]
            )

            return Response(
                {
                    "error": (
                        "Vendor settlement failed."
                    ),
                    "details": settlement_response,
                    "reference_id": str(
                        scan_transaction.reference_id
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # MARK PAYOUT SUCCESS
        # ----------------------------------------------------

        scan_transaction.payout_status = "SUCCESS"

        scan_transaction.save(
            update_fields=[
                "payout_status",
                "updated_at",
            ]
        )

        return Response(
            {
                "message": "Payment successful.",

                "payment_method": "WALLET",

                "reference_id": str(
                    scan_transaction.reference_id
                ),

                "amount": str(amount),

                "platform_charge": str(
                    platform_charge
                ),

                "vendor_received": str(
                    vendor_amount
                ),

                "status": "SUCCESS",

                "payout_status": "SUCCESS",
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# GUEST / REGISTERED CUSTOMER - PAYSTACK
# ============================================================

# ============================================================
# PAYSTACK PAYMENT
# ============================================================

@extend_schema(
    summary="Scan2Pay Paystack Checkout",
    description=(
        "Creates a Paystack Pay with Transfer payment for a Scan2Pay QR code.\n\n"

        "REGISTERED CUSTOMER:\n"
        "The frontend should automatically prefill customer_name and "
        "customer_email using the authenticated customer's profile.\n\n"

        "GUEST CUSTOMER:\n"
        "The frontend should display customer_name and customer_email "
        "as empty fields for the customer to complete.\n\n"

        "PAYMENT AMOUNT:\n"
        "If the QR code has a fixed amount, the backend uses that amount. "
        "If the QR code does not have a fixed amount, amount must be supplied.\n\n"

        "PAYMENT PROCESS:\n"
        "The endpoint creates a temporary Paystack bank account for this "
        "specific transaction. The customer must transfer the exact "
        "payment amount to the returned account before the expiry time.\n\n"

        "The Paystack webhook confirms the payment after the transfer "
        "is successfully received."
    ),
    request=Scan2PayPaystackCheckoutSerializer,
    responses={
        200: OpenApiResponse(
            description="Temporary Paystack payment account created."
        ),
        400: OpenApiResponse(
            description="Invalid request or payment details."
        ),
        404: OpenApiResponse(
            description="QR code not found."
        ),
        502: OpenApiResponse(
            description="Unable to communicate with Paystack."
        ),
    },
)
class Scan2PayPaystackView(APIView):

    permission_classes = [AllowAny]

    def post(self, request, qr_id):

        # ----------------------------------------------------
        # CUSTOMER DETAILS
        # ----------------------------------------------------

        customer_name = request.data.get(
            "customer_name"
        )

        customer_email = request.data.get(
            "customer_email"
        )

        amount_input = request.data.get(
            "amount"
        )

        # ----------------------------------------------------
        # CUSTOMER VALIDATION
        # ----------------------------------------------------

        if not customer_name:

            return Response(
                {
                    "error": (
                        "Customer name is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not customer_email:

            return Response(
                {
                    "error": (
                        "Customer email is required."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # QR
        # ----------------------------------------------------

        try:

            qr_code = VendorQRCode.objects.select_related(
                "vendor"
            ).get(id=qr_id)

        except VendorQRCode.DoesNotExist:

            return Response(
                {
                    "error": "Invalid QR code."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # ----------------------------------------------------
        # AMOUNT
        # ----------------------------------------------------

        amount, amount_error = get_qr_amount(
            qr_code,
            amount_input,
        )

        if amount_error:

            return Response(
                {"error": amount_error},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # PLATFORM CHARGE
        # ----------------------------------------------------

        platform_charge = (
            calculate_platform_charge(amount)
        )

        vendor_amount = (
            amount - platform_charge
        )

        if vendor_amount <= 0:

            return Response(
                {
                    "error": (
                        "Invalid settlement amount."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # CREATE INTERNAL TRANSACTION
        # ----------------------------------------------------

        scan_transaction = (
            Scan2PayTransaction.objects.create(

                # Guest has no Monieplug account
                sender=None,

                # Common customer fields
                customer_name=customer_name,
                customer_email=customer_email,

                vendor=qr_code.vendor,

                qr_code=qr_code,

                amount=amount,

                platform_charge=platform_charge,

                vendor_amount=vendor_amount,

                payment_method="PAYSTACK",

                status="PENDING",

                payout_status="PENDING",
            )
        )

        # ----------------------------------------------------
        # PAYSTACK REFERENCE
        # ----------------------------------------------------

        paystack_reference = (
            f"mp-scan-{scan_transaction.reference_id.hex}"
        )

        # ----------------------------------------------------
        # EXPIRY
        # ----------------------------------------------------

        expiry_minutes = int(
            getattr(
                settings,
                "PAYSTACK_PWT_EXPIRY_MINUTES",
                30,
            )
        )

        expires_at = (
            timezone.now()
            + timedelta(minutes=expiry_minutes)
        )

        expires_at_string = expires_at.strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        # ----------------------------------------------------
        # PAYSTACK CHARGE
        # ----------------------------------------------------

        payload = {

            "email": customer_email,

            "amount": int(
                amount * 100
            ),

            "currency": "NGN",

            "reference": paystack_reference,

            "bank_transfer": {
                "account_expires_at": (
                    expires_at_string
                )
            },

            "metadata": {

                "scan2pay_transaction_id": str(
                    scan_transaction.reference_id
                ),

                "qr_id": str(
                    qr_code.id
                ),

                "vendor_id": str(
                    qr_code.vendor.id
                ),
            },
        }

        try:

            response = requests.post(
                f"{PAYSTACK_BASE_URL}/charge",
                json=payload,
                headers=paystack_headers(),
                timeout=30,
            )

            paystack_response = response.json()

        except (
            requests.RequestException,
            ValueError,
        ) as exc:

            scan_transaction.status = "FAILED"

            scan_transaction.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            return Response(
                {
                    "error": (
                        "Paystack connection failed."
                    ),
                    "details": str(exc),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # ----------------------------------------------------
        # PAYSTACK FAILURE
        # ----------------------------------------------------

        if not paystack_response.get("status"):

            scan_transaction.status = "FAILED"

            scan_transaction.save(
                update_fields=[
                    "status",
                    "updated_at",
                ]
            )

            return Response(
                {
                    "error": (
                        "Unable to generate "
                        "payment account."
                    ),
                    "details": paystack_response,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ----------------------------------------------------
        # PAYSTACK DATA
        # ----------------------------------------------------

        paystack_data = (
            paystack_response.get(
                "data",
                {}
            )
        )

        account_number = (
            paystack_data.get(
                "account_number"
            )
        )

        account_name = (
            paystack_data.get(
                "account_name"
            )
        )

        bank = (
            paystack_data.get(
                "bank",
                {}
            )
        )

        bank_name = (
            bank.get("name")
            if isinstance(bank, dict)
            else None
        )

        account_expires_at = (
            paystack_data.get(
                "account_expires_at"
            )
        )

        # ----------------------------------------------------
        # SAVE PAYSTACK DATA
        # ----------------------------------------------------

        scan_transaction.paystack_reference = (
            paystack_data.get(
                "reference",
                paystack_reference,
            )
        )

        scan_transaction.paystack_account_number = (
            account_number
        )

        scan_transaction.paystack_account_name = (
            account_name
        )

        scan_transaction.paystack_bank_name = (
            bank_name
        )

        if account_expires_at:

            parsed_expiry = parse_datetime(
                account_expires_at
            )

            if parsed_expiry:

                if timezone.is_naive(
                    parsed_expiry
                ):

                    parsed_expiry = (
                        timezone.make_aware(
                            parsed_expiry
                        )
                    )

                scan_transaction.paystack_account_expires_at = (
                    parsed_expiry
                )

        scan_transaction.save()

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return Response(
            {
                "message": (
                    "Payment account generated. "
                    "Transfer the exact amount "
                    "before expiry."
                ),

                "payment_method": "PAYSTACK",

                "transaction_id": str(
                    scan_transaction.reference_id
                ),

                "paystack_reference": (
                    scan_transaction.paystack_reference
                ),

                "amount": str(amount),

                "platform_charge": str(
                    platform_charge
                ),

                "vendor_amount": str(
                    vendor_amount
                ),

                "bank": bank_name,

                "account_name": account_name,

                "account_number": account_number,

                "account_expires_at": (
                    account_expires_at
                ),

                "status": (
                    paystack_data.get(
                        "status"
                    )
                ),
            },
            status=status.HTTP_200_OK,
        )


# ============================================================
# PAYSTACK WEBHOOK
# ============================================================

class PaystackWebhookView(APIView):

    permission_classes = [AllowAny]

    authentication_classes = []

    def post(self, request):

        # ====================================================
        # VERIFY PAYSTACK SIGNATURE
        # ====================================================

        signature = request.headers.get(
            "x-paystack-signature"
        )

        if not signature:

            return Response(
                {"error": "Missing signature"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        expected_signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode(),
            request.body,
            hashlib.sha512,
        ).hexdigest()

        if not hmac.compare_digest(
            signature,
            expected_signature,
        ):

            return Response(
                {"error": "Invalid signature"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # ====================================================
        # EVENT
        # ====================================================

        event = request.data.get(
            "event"
        )

        data = request.data.get(
            "data",
            {}
        )

        # ====================================================
        # CUSTOMER PAYMENT SUCCESS
        # ====================================================

        if event == "charge.success":

            reference = data.get(
                "reference"
            )

            if not reference:

                return Response(
                    {"status": "ignored"},
                    status=status.HTTP_200_OK,
                )

            # ------------------------------------------------
            # Lock transaction
            # ------------------------------------------------

            try:

                with transaction.atomic():

                    scan_transaction = (
                        Scan2PayTransaction.objects
                        .select_for_update()
                    
                        .get(
                            paystack_reference=reference
                        )
                    )

                    # ----------------------------------------
                    # Already paid
                    # ----------------------------------------

                    if (
                        scan_transaction.status
                        == "SUCCESS"
                    ):

                        return Response(
                            {
                                "status": (
                                    "already_processed"
                                )
                            },
                            status=status.HTTP_200_OK,
                        )

                    # ----------------------------------------
                    # Must be Paystack transaction
                    # ----------------------------------------

                    if (
                        scan_transaction.payment_method
                        != "PAYSTACK"
                    ):

                        return Response(
                            {
                                "status": (
                                    "invalid_payment_method"
                                )
                            },
                            status=status.HTTP_200_OK,
                        )

                    # ----------------------------------------
                    # Amount verification
                    # ----------------------------------------

                    paid_amount = (
                        Decimal(
                            str(
                                data.get(
                                    "amount",
                                    0
                                )
                            )
                        )
                        / Decimal("100")
                    )

                    if (
                        paid_amount
                        != scan_transaction.amount
                    ):

                        scan_transaction.status = (
                            "FAILED"
                        )

                        scan_transaction.save(
                            update_fields=[
                                "status",
                                "updated_at",
                            ]
                        )

                        return Response(
                            {
                                "status": (
                                    "amount_mismatch"
                                )
                            },
                            status=status.HTTP_200_OK,
                        )

                    # ----------------------------------------
                    # Mark payment successful
                    # ----------------------------------------

                    scan_transaction.status = (
                        "SUCCESS"
                    )

                    scan_transaction.save(
                        update_fields=[
                            "status",
                            "updated_at",
                        ]
                    )

            except Scan2PayTransaction.DoesNotExist:

                return Response(
                    {"status": "ignored"},
                    status=status.HTTP_200_OK,
                )

            # ------------------------------------------------
            # PAY VENDOR
            # ------------------------------------------------

            payout_result = (
                paystack_vendor_payout(
                    scan_transaction
                )
            )

            if not payout_result["success"]:

                scan_transaction.payout_status = (
                    "FAILED"
                )

                scan_transaction.save(
                    update_fields=[
                        "payout_status",
                        "updated_at",
                    ]
                )

                # Payment succeeded even though
                # payout initiation failed.
                return Response(
                    {
                        "status": (
                            "payment_success_"
                            "payout_failed"
                        ),
                        "message": (
                            payout_result[
                                "message"
                            ]
                        ),
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "status": (
                        "payment_success_"
                        "payout_processing"
                    )
                },
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # VENDOR PAYOUT SUCCESS
        # ====================================================

        if event == "transfer.success":

            reference = data.get(
                "reference"
            )

            if reference:

                try:

                    scan_transaction = (
                        Scan2PayTransaction.objects.get(
                            payout_reference=reference
                        )
                    )

                    scan_transaction.payout_status = (
                        "SUCCESS"
                    )

                    scan_transaction.save(
                        update_fields=[
                            "payout_status",
                            "updated_at",
                        ]
                    )

                except Scan2PayTransaction.DoesNotExist:

                    pass

            return Response(
                {"status": "processed"},
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # VENDOR PAYOUT FAILED
        # ====================================================

        if event == "transfer.failed":

            reference = data.get(
                "reference"
            )

            if reference:

                try:

                    scan_transaction = (
                        Scan2PayTransaction.objects.get(
                            payout_reference=reference
                        )
                    )

                    scan_transaction.payout_status = (
                        "FAILED"
                    )

                    scan_transaction.save(
                        update_fields=[
                            "payout_status",
                            "updated_at",
                        ]
                    )

                except Scan2PayTransaction.DoesNotExist:

                    pass

            return Response(
                {"status": "processed"},
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # VENDOR PAYOUT REVERSED
        # ====================================================

        if event == "transfer.reversed":

            reference = data.get(
                "reference"
            )

            if reference:

                try:

                    scan_transaction = (
                        Scan2PayTransaction.objects.get(
                            payout_reference=reference
                        )
                    )

                    scan_transaction.payout_status = (
                        "FAILED"
                    )

                    scan_transaction.save(
                        update_fields=[
                            "payout_status",
                            "updated_at",
                        ]
                    )

                except Scan2PayTransaction.DoesNotExist:

                    pass

            return Response(
                {"status": "processed"},
                status=status.HTTP_200_OK,
            )

        # ====================================================
        # OTHER PAYSTACK EVENTS
        # ====================================================

        return Response(
            {"status": "ignored"},
            status=status.HTTP_200_OK,
        )