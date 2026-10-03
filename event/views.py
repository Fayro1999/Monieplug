import uuid
import requests
from decimal import Decimal
from rest_framework import status
from django.shortcuts import render
from django.contrib.auth.hashers import check_password
from rest_framework import generics, permissions
from rest_framework.exceptions import PermissionDenied
from .models import Event, Ticket,  TicketPurchase
from .serializers import EventSerializer, TicketSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .paygate import transfer_from_wallet
from django.core.mail import EmailMessage
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
import hmac, hashlib, json
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import PermissionDenied
from django.utils.dateparse import parse_datetime






import uuid

from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status

from drf_spectacular.utils import extend_schema

from .models import Ticket, TicketPurchase
from .serializers import GuestPaystackCheckoutSerializer

from .paystack import (
    create_paystack_guest_charge,
    calculate_platform_charge,
)



import hmac
import hashlib
import json

from decimal import Decimal

from django.conf import settings
from django.db import transaction

from django.http import HttpResponse

from django.views.decorators.csrf import csrf_exempt

from .models import TicketPurchase

from .paystack import (
    verify_paystack_signature,
)








class EventListCreateView(generics.ListCreateAPIView):
    """
    GET: List all events
    POST: Create new event with tickets (organizer only)
    """
    queryset = Event.objects.all().order_by('-created_at')
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    parser_classes = [MultiPartParser]  # keep for images

    def get_serializer_context(self):
        return {"request": self.request}


    



# 🔹 View, Update, Delete Event
class EventDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    get:
    Retrieve a single event.

    put/patch:
    Update an event (only organizer).

    delete:
    Delete an event (only organizer).

    Example GET Response:
    {
        "id": 1,
        "title": "Summer Festival",
        "description": "Biggest festival of the year",
        "tickets": [...]
    }
    """
    queryset = Event.objects.all()
    serializer_class = EventSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]




class TicketListCreateView(generics.ListCreateAPIView):
    """
    get:
    List tickets for a specific event.

    post:
    Create a ticket (only the event organizer can do this).
    """
    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        event_id = self.request.query_params.get('event')
        if event_id:
            return Ticket.objects.filter(event_id=event_id)
        return Ticket.objects.all()

    # <-- Add perform_create here
    def perform_create(self, serializer):
        event = serializer.validated_data['event']
        if event.organizer != self.request.user:
            raise PermissionDenied("You can only create tickets for your own events.")
        
        # Handle image if included in request.FILES
        ticket_image = self.request.FILES.get('ticket_image')
        serializer.save(ticket_image=ticket_image)


# Custom permission: Only event organizer can edit/delete ticket
class IsEventOrganizer(BasePermission):
    def has_object_permission(self, request, view, obj):
        # obj is a Ticket instance
        return obj.event.organizer == request.user



from django.shortcuts import get_object_or_404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.exceptions import PermissionDenied

from .models import Event, Ticket
from .serializers import TicketSerializer


class BulkTicketCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        event_id = request.data.get("event")
        tickets = request.data.get("tickets", [])

        # FIX 1: Safe event lookup
        event = get_object_or_404(Event, id=event_id)

        if event.organizer != request.user:
            raise PermissionDenied("Not allowed")

        created = []

        for t in tickets:
            created.append(
                Ticket.objects.create(
                    event=event,
                    name=t["name"],
                    price=t["price"],
                    # FIX 2: Image support added
                    ticket_image=t.get("ticket_image")
                )
            )

        return Response(
            TicketSerializer(created, many=True).data,
            status=201
        )



# 🔹 View, Update, Delete a Ticket
class TicketDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    get:
    Retrieve ticket details.

    put/patch:
    Update ticket (organizer only).

    delete:
    Delete ticket (organizer only).

    Example Response:
    {
        "id": 1,
        "name": "VIP",
        "price": "5000.00"
    }
    """

    queryset = Ticket.objects.all()
    serializer_class = TicketSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]



    
from decimal import Decimal
import uuid
import requests

from django.conf import settings
from django.core.mail import EmailMessage
from django.contrib.auth.hashers import check_password

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status

from drf_spectacular.utils import extend_schema
from django.core.files.storage import default_storage

from .models import Ticket, TicketPurchase


# =========================
# WAAS CONFIG
# =========================
WAAS_AUTH_URL = "http://102.216.128.75:9090/waas/api/v1/authenticate"
WAAS_DEBIT_URL = "http://102.216.128.75:9090/waas/api/v1/debit/transfer"
WAAS_CREDIT_URL = "http://102.216.128.75:9090/waas/api/v1/credit/transfer"


# =========================
# GET WAAS TOKEN
# =========================
def get_waas_token():
    payload = {
        "username": settings.WAAS_USERNAME,
        "password": settings.WAAS_PASSWORD,
        "clientId": settings.WAAS_CLIENT_ID,
        "clientSecret": settings.WAAS_CLIENT_SECRET,
    }

    try:
        r = requests.post(WAAS_AUTH_URL, json=payload, timeout=30)
        data = r.json()

        if data.get("accessToken"):
            return data["accessToken"]

        return None
    except Exception:
        return None


# =========================
# PLATFORM CHARGE
# =========================
def calculate_platform_charge(amount: Decimal) -> Decimal:
    if amount < 10000:
        return Decimal(150)
    elif amount < 500000:
        return Decimal(200)
    return Decimal(250)


# =========================
# WAAS TRANSFER
# =========================
def waas_transfer(token, account_no, amount, narration, is_credit=False):

    url = WAAS_CREDIT_URL if is_credit else WAAS_DEBIT_URL

    payload = {
        "accountNo": str(account_no),
        "totalAmount": str(round(Decimal(amount), 2)),
        "transactionId": uuid.uuid4().hex[:30],  # WAAS LIMIT FIXED
        "narration": narration[:100],
        "merchant": {
            "isFee": False
        }
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        return r.json()
    except Exception as e:
        return {"status": "FAILED", "message": str(e)}


# =========================
# CHECKOUT VIEW
# =========================
@extend_schema(exclude=True)
class EwalletCheckoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):

        data = request.data
        ticket_id = data.get("ticket_id")
        copies = int(data.get("copies", 1))
        full_name = data.get("full_name")
        email = data.get("email")
        transaction_pin = data.get("transaction_pin")

        user = request.user

        # -------------------------
        # PIN CHECK
        # -------------------------
        if not user.transaction_pin:
            return Response({"error": "Set transaction PIN first"}, status=403)

        if not check_password(transaction_pin, user.transaction_pin):
            return Response({"error": "Invalid transaction PIN"}, status=403)

        # -------------------------
        # TICKET
        # -------------------------
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({"error": "Invalid ticket"}, status=404)

        vendor = ticket.event.organizer

        if not vendor.wallet_account_number:
            return Response({"error": "Vendor wallet missing"}, status=400)

        if not user.wallet_account_number:
            return Response({"error": "User wallet missing"}, status=400)

        # -------------------------
        # CALCULATION
        # -------------------------
        total_amount = Decimal(ticket.price) * copies
        platform_charge = calculate_platform_charge(total_amount)
        vendor_amount = total_amount - platform_charge

        # -------------------------
        # WAAS TOKEN
        # -------------------------
        token = get_waas_token()
        if not token:
            return Response({"error": "WAAS auth failed"}, status=500)

        # -------------------------
        # DEBIT BUYER
        # -------------------------
        debit_resp = waas_transfer(
            token,
            user.wallet_account_number,
            total_amount,
            f"Ticket-{ticket.event.title}",
            is_credit=False
        )

        if debit_resp.get("status", "").upper() != "SUCCESS":
            return Response(
                {"error": "Debit failed", "details": debit_resp},
                status=400
            )

        # -------------------------
        # CREDIT VENDOR
        # -------------------------
        credit_resp = waas_transfer(
            token,
            vendor.wallet_account_number,
            vendor_amount,
            f"Payout-{ticket.event.title}",
            is_credit=True
        )

        if credit_resp.get("status", "").upper() != "SUCCESS":
            return Response(
                {"error": "Credit failed", "details": credit_resp},
                status=400
            )

        # -------------------------
        # SAVE PURCHASE
        # -------------------------
        purchase = TicketPurchase.objects.create(
            ticket=ticket,
            full_name=full_name,
            email=email,
            copies=copies,
            user=user,
            total_price=total_amount,
            platform_charge=platform_charge,
            organizer_amount=vendor_amount,
            debit_reference=...,
            credit_reference=...,
            payment_method="WAAS",
            status="SUCCESS",
            webhook_verified=True,
        )

        purchase.generate_qr_codes()

        # -------------------------
        # EMAIL RECEIPT
        # -------------------------
        msg = EmailMessage(
            subject=f"Ticket - {ticket.event.title}",
            body=f"""
Hello {full_name},

Payment Successful

Event: {ticket.event.title}
Copies: {copies}
Total: ₦{total_amount}
Platform Fee: ₦{platform_charge}
Vendor Gets: ₦{vendor_amount}

Ref: {purchase.reference_id}
""",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )

        msg.send(fail_silently=True)

        return Response({
            "message": "Payment successful",
            "reference": str(purchase.reference_id),
            "debit": debit_resp,
            "credit": credit_resp
        })
        

#List of Commercial Banks
class WAASBanksView(APIView):
    """
    Fetch list of banks from WAAS API
    """

    def get(self, request):

        url = "http://102.216.128.75:9090/waas/api/v1/get_banks"

        try:
            response = requests.get(url, timeout=30)
            data = response.json()

            # WAAS response format
            return Response(
                {
                    "status": data.get("status"),
                    "message": data.get("message"),
                    "banks": data.get("data", [])
                },
                status=response.status_code
            )

        except requests.exceptions.RequestException as e:
            return Response(
                {
                    "status": "FAILED",
                    "message": f"Network error: {str(e)}",
                    "banks": []
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE
            )





@extend_schema(
    request=GuestPaystackCheckoutSerializer,
    responses={
        200: dict,
        400: dict,
        404: dict,
    },
)
class GuestPaystackCheckoutView(APIView):
    """
    Guest / unregistered customer checkout using Paystack
    Pay with Transfer.
    """

    permission_classes = [AllowAny]

    def post(self, request):

        serializer = GuestPaystackCheckoutSerializer(
            data=request.data
        )

        serializer.is_valid(raise_exception=True)

        ticket_id = serializer.validated_data["ticket_id"]
        copies = serializer.validated_data["copies"]
        full_name = serializer.validated_data["full_name"]
        email = serializer.validated_data["email"]

        # -----------------------------------
        # GET TICKET
        # -----------------------------------

        try:
            ticket = Ticket.objects.select_related(
                "event",
                "event__organizer",
            ).get(id=ticket_id)

        except Ticket.DoesNotExist:
            return Response(
                {
                    "error": "Invalid ticket."
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # -----------------------------------
        # ORGANIZER
        # -----------------------------------

        vendor = ticket.event.organizer

        if not vendor.wallet_account_number:
            return Response(
                {
                    "error": "Organizer wallet is not configured."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------
        # CALCULATE AMOUNT
        # -----------------------------------

        total_amount = (
            Decimal(ticket.price) * Decimal(copies)
        )

        platform_charge = calculate_platform_charge(
            total_amount
        )

        vendor_amount = (
            total_amount - platform_charge
        )

        if vendor_amount <= Decimal("0"):
            return Response(
                {
                    "error": "Invalid payment amount."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # -----------------------------------
        # CREATE LOCAL PURCHASE
        # -----------------------------------

        purchase = TicketPurchase.objects.create(
            ticket=ticket,
            full_name=full_name,
            email=email,
            copies=copies,
            total_price=total_amount,
            platform_charge=platform_charge,
            organizer_amount=vendor_amount,
            payment_method="PAYSTACK",
            status="PENDING",
            user=None,
        )
        # -----------------------------------
        # PAYSTACK REFERENCE
        # -----------------------------------

        paystack_reference = (
            f"mp-event-{purchase.reference_id.hex}"
        )

        # -----------------------------------
        # EXPIRY
        # -----------------------------------

        expiry_minutes = getattr(
            settings,
            "PAYSTACK_PWT_EXPIRY_MINUTES",
            30,
        )

        expires_at = (
            timezone.now()
            + timezone.timedelta(
                minutes=expiry_minutes
            )
        )

        expires_at_string = (
            expires_at
            .isoformat()
            .replace("+00:00", "Z")
        )

        # -----------------------------------
        # PAYSTACK CHARGE
        # -----------------------------------

        result = create_paystack_guest_charge(
            email=email,
            amount=total_amount,
            reference=paystack_reference,
            expires_at=expires_at_string,
            metadata={
                "purchase_id": str(
                    purchase.reference_id
                ),
                "ticket_id": str(ticket.id),
                "event_id": str(ticket.event.id),
                "organizer_amount": str(vendor_amount),
                "customer_type": "guest",
            },
        )

        if not result["success"]:

            purchase.delete()

            return Response(
                {
                    "error": result["message"],
                    "paystack_response": result.get(
                        "response"
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        paystack_data = result["data"]

        # -----------------------------------
        # SAVE PAYSTACK DETAILS
        # -----------------------------------

        purchase.paystack_reference = paystack_reference

        purchase.paystack_account_number = (
            paystack_data.get("account_number")
        )

        purchase.paystack_account_name = (
            paystack_data.get("account_name")
        )

        bank = paystack_data.get("bank", {})

        purchase.paystack_bank = (
            bank.get("name")
            if isinstance(bank, dict)
            else bank
        )

        account_expires_at = paystack_data.get(
            "account_expires_at"
        )

        if account_expires_at:
            account_expires_at = parse_datetime(
                account_expires_at
            )

        purchase.paystack_account_expires_at = (
            account_expires_at
        )

        purchase.save()
        # -----------------------------------
        # RESPONSE
        # -----------------------------------

        return Response(
            {
                "message": (
                    "Payment account generated. "
                    "Transfer the exact amount before expiry."
                ),
                "payment_method": "PAYSTACK",
                "customer_type": "GUEST",

                "purchase_reference": str(
                    purchase.reference_id
                ),

                "paystack_reference": (
                    paystack_reference
                ),

                "event": ticket.event.title,

                "ticket": ticket.name,

                "copies": copies,

                "amount": str(
                    total_amount
                ),

                "platform_charge": str(
                    platform_charge
                ),

                "vendor_amount": str(
                    vendor_amount
                ),

                "bank": (
                    paystack_data.get("bank", {})
                ),

                "account_name": (
                    paystack_data.get(
                        "account_name"
                    )
                ),

                "account_number": (
                    paystack_data.get(
                        "account_number"
                    )
                ),

                "account_expires_at": (
                    paystack_data.get(
                        "account_expires_at"
                    )
                ),

                "status": "pending_bank_transfer",
            },
            status=status.HTTP_200_OK,
        )


def send_ticket_email(purchase):
    """
    Send successful event ticket email with QR codes attached.
    """

    ticket = purchase.ticket
    event = ticket.event

    subject = f"Ticket - {event.title}"

    body = f"""
Hello {purchase.full_name},

Your payment was successful.

Event: {event.title}
Ticket: {ticket.name}
Copies: {purchase.copies}

Total Paid: ₦{purchase.total_price}
Platform Fee: ₦{purchase.platform_charge}
Organizer Amount: ₦{purchase.organizer_amount}

Purchase Reference:
{purchase.reference_id}

Thank you for using Monieplug.
"""

    email = EmailMessage(
        subject=subject,
        body=body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[purchase.email],
    )

    # ------------------------------------------------------------
    # Attach generated QR codes
    # ------------------------------------------------------------

    for qr_file in purchase.qr_codes:

        try:
            file_content = default_storage.open(
                qr_file,
                "rb",
            ).read()

            filename = os.path.basename(qr_file)

            email.attach(
                filename,
                file_content,
                "image/png",
            )

        except Exception:
            continue

    email.send(fail_silently=False)  



def initiate_organizer_payout(purchase):
    """
    Initiate Paystack payout to the event organizer.

    Customer payment:
        ₦5,000

    Example:
        Platform fee = ₦150
        Organizer = ₦4,850
    """

    organizer = purchase.ticket.event.organizer

    # --------------------------------------------------------
    # Already paid
    # --------------------------------------------------------

    if purchase.payout_status == "SUCCESS":
        return {
            "success": True,
            "message": "Organizer payout already completed.",
        }

    # --------------------------------------------------------
    # Already processing
    # --------------------------------------------------------

    if (
        purchase.payout_status == "PROCESSING"
        and purchase.paystack_transfer_reference
    ):
        return {
            "success": True,
            "message": "Organizer payout already processing.",
        }

    # --------------------------------------------------------
    # Organizer must have Paystack recipient
    # --------------------------------------------------------

    recipient_code = getattr(
        organizer,
        "paystack_recipient_code",
        None,
    )

    if not recipient_code:
        purchase.payout_status = "FAILED"
        purchase.payout_error = (
            "Organizer does not have a Paystack transfer recipient."
        )

        purchase.save(
            update_fields=[
                "payout_status",
                "payout_error",
            ]
        )

        return {
            "success": False,
            "message": "Organizer Paystack recipient is missing.",
        }

    # --------------------------------------------------------
    # Validate payout amount
    # --------------------------------------------------------

    organizer_amount = Decimal(
        str(purchase.organizer_amount)
    )

    if organizer_amount <= Decimal("0"):
        purchase.payout_status = "FAILED"
        purchase.payout_error = (
            "Organizer payout amount is invalid."
        )

        purchase.save(
            update_fields=[
                "payout_status",
                "payout_error",
            ]
        )

        return {
            "success": False,
            "message": "Invalid organizer payout amount.",
        }

    # --------------------------------------------------------
    # Generate UNIQUE Paystack transfer reference
    # --------------------------------------------------------

    transfer_reference = (
        f"mp_payout_{uuid.uuid4().hex}"
    )

    # 35-ish characters, comfortably inside
    # Paystack's 16-50 character requirement.
    # --------------------------------------------------------

    purchase.paystack_transfer_reference = (
        transfer_reference
    )

    purchase.payout_status = "PROCESSING"
    purchase.payout_error = ""

    purchase.save(
        update_fields=[
            "paystack_transfer_reference",
            "payout_status",
            "payout_error",
        ]
    )

    # --------------------------------------------------------
    # Initiate Paystack transfer
    # --------------------------------------------------------

    result = create_paystack_transfer(
        recipient_code=recipient_code,
        amount=organizer_amount,
        reference=transfer_reference,
        reason=(
            f"Monieplug payout - "
            f"{purchase.ticket.event.title}"
        ),
    )

    if not result["success"]:

        purchase.payout_status = "FAILED"
        purchase.payout_error = result.get(
            "message",
            "Paystack transfer failed.",
        )

        purchase.save(
            update_fields=[
                "payout_status",
                "payout_error",
            ]
        )

        return result

    return result



@csrf_exempt
def paystack_webhook(request):

    # ============================================================
    # ONLY POST
    # ============================================================

    if request.method != "POST":
        return HttpResponse(status=405)

    # ============================================================
    # VERIFY PAYSTACK SIGNATURE
    # ============================================================

    if not verify_paystack_signature(request):
        return HttpResponse(status=401)

    # ============================================================
    # PARSE JSON
    # ============================================================

    try:
        payload = json.loads(request.body)

    except (json.JSONDecodeError, TypeError):
        return HttpResponse(status=400)

    event = payload.get("event")
    data = payload.get("data") or {}

    # ============================================================
    # CUSTOMER PAYMENT SUCCESS
    # ============================================================

    if event == "charge.success":

        reference = data.get("reference")

        if not reference:
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # FIND PURCHASE
        # --------------------------------------------------------

        try:
            purchase = (
                TicketPurchase.objects
                .select_related(
                    "ticket",
                    "ticket__event",
                    "ticket__event__organizer",
                )
                .get(
                    paystack_reference=reference
                )
            )

        except TicketPurchase.DoesNotExist:
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # IDEMPOTENCY
        # --------------------------------------------------------

        if (
            purchase.webhook_verified
            and purchase.status == "SUCCESS"
        ):
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # VERIFY PAYSTACK STATUS
        # --------------------------------------------------------

        if data.get("status") != "success":
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # VERIFY CURRENCY
        # --------------------------------------------------------

        if data.get("currency") != "NGN":
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # VERIFY REFERENCE
        # --------------------------------------------------------

        if data.get("reference") != (
            purchase.paystack_reference
        ):
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # VERIFY AMOUNT FROM WEBHOOK
        # --------------------------------------------------------

        try:

            paid_amount = (
                Decimal(
                    str(
                        data.get(
                            "amount",
                            "0",
                        )
                    )
                )
                / Decimal("100")
            )

        except Exception:
            return HttpResponse(status=200)

        expected_amount = Decimal(
            str(purchase.total_price)
        )

        if paid_amount != expected_amount:
            return HttpResponse(status=200)

        # ========================================================
        # SECONDARY PAYSTACK VERIFICATION
        # ========================================================

        verification = verify_paystack_transaction(
            reference
        )

        if not verification.get("success"):
            # Returning 500 allows Paystack to retry.
            return HttpResponse(status=500)

        verified_data = (
            verification.get("data") or {}
        )

        if verified_data.get("status") != "success":
            return HttpResponse(status=200)

        if verified_data.get("currency") != "NGN":
            return HttpResponse(status=200)

        try:

            verified_amount = (
                Decimal(
                    str(
                        verified_data.get(
                            "amount",
                            "0",
                        )
                    )
                )
                / Decimal("100")
            )

        except Exception:
            return HttpResponse(status=200)

        if verified_amount != expected_amount:
            return HttpResponse(status=200)

        # ========================================================
        # MARK PURCHASE SUCCESSFUL
        # ========================================================

        try:

            with transaction.atomic():

                purchase = (
                    TicketPurchase.objects
                    .select_for_update()
                    .select_related(
                        "ticket",
                        "ticket__event",
                        "ticket__event__organizer",
                    )
                    .get(
                        pk=purchase.pk
                    )
                )

                # Another webhook may have completed it.
                if (
                    purchase.webhook_verified
                    and purchase.status == "SUCCESS"
                ):
                    return HttpResponse(
                        status=200
                    )

                purchase.webhook_verified = True
                purchase.status = "SUCCESS"

                purchase.save(
                    update_fields=[
                        "webhook_verified",
                        "status",
                    ]
                )

        except TicketPurchase.DoesNotExist:
            return HttpResponse(status=200)

        except Exception:
            return HttpResponse(status=500)

        # ========================================================
        # GENERATE QR CODES
        # ========================================================

        try:

            purchase.generate_qr_codes()

        except Exception:
            # Payment is successful but ticket generation
            # failed. Returning 500 allows webhook retry.
            return HttpResponse(status=500)

        # ========================================================
        # SEND TICKET EMAIL
        # ========================================================

        try:

            send_ticket_email(
                purchase
            )

        except Exception:
            # Email failure must NOT make a successful
            # payment look unsuccessful.
            pass

        # ========================================================
        # INITIATE ORGANIZER PAYOUT
        # ========================================================

        payout_result = initiate_organizer_payout(
            purchase
        )

        # --------------------------------------------------------
        # IMPORTANT:
        #
        # A failed payout does NOT mean the customer payment
        # failed.
        #
        # The purchase remains SUCCESS.
        #
        # payout_status tells us separately what happened.
        # --------------------------------------------------------

        return HttpResponse(status=200)

    # ============================================================
    # ORGANIZER PAYOUT SUCCESS
    # ============================================================

    if event == "transfer.success":

        transfer_reference = data.get(
            "reference"
        )

        if not transfer_reference:
            return HttpResponse(status=200)

        try:

            purchase = (
                TicketPurchase.objects
                .get(
                    paystack_transfer_reference=(
                        transfer_reference
                    )
                )
            )

        except TicketPurchase.DoesNotExist:
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # IDEMPOTENCY
        # --------------------------------------------------------

        if purchase.payout_status == "SUCCESS":
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # Verify currency
        # --------------------------------------------------------

        if data.get("currency") not in (
            None,
            "NGN",
        ):
            return HttpResponse(status=200)

        # --------------------------------------------------------
        # Verify amount if supplied
        # --------------------------------------------------------

        if data.get("amount") is not None:

            try:

                transferred_amount = (
                    Decimal(
                        str(
                            data.get(
                                "amount"
                            )
                        )
                    )
                    / Decimal("100")
                )

                expected_payout = Decimal(
                    str(
                        purchase.organizer_amount
                    )
                )

                if transferred_amount != expected_payout:
                    return HttpResponse(
                        status=200
                    )

            except Exception:
                return HttpResponse(status=200)

        # --------------------------------------------------------
        # SUCCESS
        # --------------------------------------------------------

        purchase.payout_status = "SUCCESS"
        purchase.payout_error = ""

        purchase.save(
            update_fields=[
                "payout_status",
                "payout_error",
            ]
        )

        return HttpResponse(status=200)

    # ============================================================
    # ORGANIZER PAYOUT FAILED
    # ============================================================

    if event == "transfer.failed":

        transfer_reference = data.get(
            "reference"
        )

        if not transfer_reference:
            return HttpResponse(status=200)

        try:

            purchase = (
                TicketPurchase.objects
                .get(
                    paystack_transfer_reference=(
                        transfer_reference
                    )
                )
            )

        except TicketPurchase.DoesNotExist:
            return HttpResponse(status=200)

        # Never downgrade an already-successful payout.
        if purchase.payout_status == "SUCCESS":
            return HttpResponse(status=200)

        failure_message = (
            data.get("reason")
            or data.get("message")
            or "Paystack transfer failed."
        )

        purchase.payout_status = "FAILED"
        purchase.payout_error = str(
            failure_message
        )

        purchase.save(
            update_fields=[
                "payout_status",
                "payout_error",
            ]
        )

        return HttpResponse(status=200)

    # ============================================================
    # ORGANIZER PAYOUT REVERSED
    # ============================================================

    if event == "transfer.reversed":

        transfer_reference = data.get(
            "reference"
        )

        if not transfer_reference:
            return HttpResponse(status=200)

        try:

            purchase = (
                TicketPurchase.objects
                .get(
                    paystack_transfer_reference=(
                        transfer_reference
                    )
                )
            )

        except TicketPurchase.DoesNotExist:
            return HttpResponse(status=200)

        purchase.payout_status = "REVERSED"
        purchase.payout_error = (
            "Paystack reversed the organizer payout."
        )

        purchase.save(
            update_fields=[
                "payout_status",
                "payout_error",
            ]
        )

        return HttpResponse(status=200)

    # ============================================================
    # UNKNOWN / UNUSED PAYSTACK EVENT
    # ============================================================

    return HttpResponse(status=200)