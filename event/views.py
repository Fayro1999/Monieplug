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



    
# views.py (single-file Paystack payment + payout) - corrected
from decimal import Decimal
import uuid
import requests
from django.conf import settings
from django.core.mail import EmailMessage
from django.contrib.auth.hashers import check_password
from rest_framework.views import APIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from drf_spectacular.utils import extend_schema
from django.core.files.storage import default_storage

from .models import Ticket, TicketPurchase
from authent.models import User

# Paystack endpoints / config
PAYSTACK_SECRET_KEY = settings.PAYSTACK_SECRET_KEY
PAYSTACK_BASE_URL = "https://api.paystack.co"
PAYSTACK_INITIALIZE_URL = f"{PAYSTACK_BASE_URL}/transaction/initialize"
PAYSTACK_VERIFY_URL = f"{PAYSTACK_BASE_URL}/transaction/verify/"
PAYSTACK_TRANSFER_RECIPIENT_URL = f"{PAYSTACK_BASE_URL}/transferrecipient"
PAYSTACK_TRANSFER_URL = f"{PAYSTACK_BASE_URL}/transfer"
PAYSTACK_TRANSFER_FETCH_URL = f"{PAYSTACK_BASE_URL}/transfer/"

# Platform charge function
def calculate_platform_charge(amount: Decimal) -> Decimal:
    if amount < 10000:
        return Decimal(150)
    elif amount < 500000:
        return Decimal(200)
    else:
        return Decimal(250)

# Helpers
def _paystack_headers():
    return {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }

def _create_paystack_transfer_recipient(name: str, account_number: str, bank_code: str, currency: str = "NGN"):
    payload = {
        "type": "nuban",
        "name": name[:100],
        "account_number": account_number,
        "bank_code": bank_code,
        "currency": currency,
    }
    resp = requests.post(PAYSTACK_TRANSFER_RECIPIENT_URL, json=payload, headers=_paystack_headers(), timeout=30)
    try:
        j = resp.json()
    except ValueError:
        return {"status": False, "message": "Invalid JSON response from Paystack", "raw": resp.text}

    if not j.get("status"):
        return {"status": False, "message": j.get("message"), "data": j}

    recipient_code = j["data"]["recipient_code"]
    return {"status": True, "recipient_code": recipient_code, "data": j["data"]}

def _initiate_paystack_transfer(amount_naira: Decimal, recipient_code: str, reason: str):
    amount_kobo = int(amount_naira * 100)
    payload = {
        "source": "balance",
        "amount": amount_kobo,
        "recipient": recipient_code,
        "reason": reason[:100],
        "metadata": {"client_reference": str(uuid.uuid4())},
    }
    resp = requests.post(PAYSTACK_TRANSFER_URL, json=payload, headers=_paystack_headers(), timeout=30)
    try:
        j = resp.json()
    except ValueError:
        return {"status": False, "message": "Invalid JSON response from Paystack", "raw": resp.text}

    if not j.get("status"):
        return {"status": False, "message": j.get("message"), "data": j}

    return {"status": True, "data": j["data"]}

def _fetch_paystack_transfer(transfer_id: str):
    resp = requests.get(PAYSTACK_TRANSFER_FETCH_URL + transfer_id, headers=_paystack_headers(), timeout=30)
    try:
        j = resp.json()
    except ValueError:
        return {"status": False, "message": "Invalid JSON response", "raw": resp.text}
    if not j.get("status"):
        return {"status": False, "message": j.get("message"), "data": j}
    return {"status": True, "data": j["data"]}


# === Initialize checkout (frontend will redirect to Paystack) ===
@extend_schema(exclude=True)
class EwalletCheckoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        ticket_id = data.get("ticket_id")
        copies = int(data.get("copies", 1))
        payment_method = data.get("payment_method")  # "card" or "bank_transfer"
        transaction_pin = data.get("transaction_pin")

        # user may be None for guests
        user = request.user if request.user.is_authenticated else None

        # full_name/email: prefer provided values, else user values (if authenticated)
        full_name = data.get("full_name") or (user.get_full_name() if user else None)
        email = data.get("email") or (user.email if user else None)

        if not full_name:
            return Response({"error": "full_name is required for guest checkout"}, status=status.HTTP_400_BAD_REQUEST)
        if not email:
            return Response({"error": "email is required for guest checkout"}, status=status.HTTP_400_BAD_REQUEST)

        # If user is authenticated, require and validate transaction PIN
        if user:
            if not transaction_pin:
                return Response({"error": "Transaction PIN required for authenticated users"}, status=status.HTTP_403_FORBIDDEN)
            if not getattr(user, "transaction_pin", None) or not check_password(transaction_pin, user.transaction_pin):
                return Response({"error": "Invalid transaction PIN"}, status=status.HTTP_403_FORBIDDEN)

        # Validate ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({"error": "Invalid ticket"}, status=status.HTTP_404_NOT_FOUND)

        if payment_method not in ["card", "bank_transfer"]:
            return Response({"error": "Invalid payment method"}, status=status.HTTP_400_BAD_REQUEST)

        total_amount = (Decimal(ticket.price) * Decimal(copies)).quantize(Decimal("0.01"))
        paystack_amount = int(total_amount * 100)  # kobo

        # initialize Paystack transaction
        init_payload = {
            "email": email,
            "amount": paystack_amount,
            "channels": [payment_method],
            "metadata": {
                "ticket_id": str(ticket.id),
                "copies": copies,
                "full_name": full_name,
                "email": email,
                # store user id only when available - helps verify flow to link to user
                "user_id": str(user.id) if user else None,
                "payment_method": payment_method,
            },
        }
        headers = _paystack_headers()
        try:
            resp = requests.post(PAYSTACK_INITIALIZE_URL, json=init_payload, headers=headers, timeout=30)
            resp_json = resp.json()
        except Exception as e:
            return Response({"error": "Failed to contact Paystack", "details": str(e)}, status=500)

        if not resp_json.get("status"):
            return Response({"error": "Paystack init failed", "details": resp_json}, status=400)

        return Response({
            "authorization_url": resp_json["data"]["authorization_url"],
            "reference": resp_json["data"]["reference"],
            "amount": float(total_amount),
            "payment_method": payment_method,
        }, status=200)


# === Verify payment and trigger payout ===
@extend_schema(exclude=True)
class PaystackVerifyAndPayoutView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        reference = request.data.get("reference")
        if not reference:
            return Response({"error": "Missing reference"}, status=status.HTTP_400_BAD_REQUEST)

        # 1) Verify transaction with Paystack
        try:
            resp = requests.get(f"{PAYSTACK_VERIFY_URL}{reference}", headers=_paystack_headers(), timeout=30)
            resp_json = resp.json()
        except Exception as e:
            return Response({"error": "Failed to contact Paystack for verification", "details": str(e)}, status=500)

        if not resp_json.get("status"):
            return Response({"error": "Paystack verification failed", "details": resp_json}, status=400)

        tx_data = resp_json["data"]
        if tx_data.get("status") != "success":
            return Response({"error": "Payment not successful", "details": tx_data}, status=400)

        # 2) Read metadata and compute amounts
        metadata = tx_data.get("metadata", {}) or {}
        ticket_id = metadata.get("ticket_id")
        copies = int(metadata.get("copies", 1))
        full_name = metadata.get("full_name") or request.data.get("full_name")
        email = metadata.get("email") or request.data.get("email")
        user_id = metadata.get("user_id")  # may be None for guest

        # Validate ticket
        try:
            ticket = Ticket.objects.get(id=ticket_id)
        except Ticket.DoesNotExist:
            return Response({"error": "Ticket referenced in metadata not found"}, status=404)

        # Determine buyer_user if user_id present
        buyer_user = None
        if user_id:
            try:
                buyer_user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                buyer_user = None

        paid_naira = (Decimal(tx_data.get("amount", 0)) / 100).quantize(Decimal("0.01"))
        total_amount = paid_naira
        platform_charge = calculate_platform_charge(total_amount)
        vendor_amount = (total_amount - platform_charge).quantize(Decimal("0.01"))

        # Prevent duplicate creation if the same reference was already processed
        existing = TicketPurchase.objects.filter(paystack_reference=reference).first()
        if existing:
            # Build QR URLs for response
            qr_urls = []
            for qr_file in getattr(existing, "qr_codes", []):
                qr_urls.append(request.build_absolute_uri(f"/media/qrcodes/{qr_file}"))
            return Response({
                "message": "Reference already processed",
                "purchase_id": str(existing.reference_id),
                "total_paid": float(existing.total_price),
                "platform_charge": float(calculate_platform_charge(existing.total_price)),
                "vendor_amount": float(existing.total_price - calculate_platform_charge(existing.total_price)),
                "qr_codes": qr_urls,
            }, status=200)

        # --- Create purchase record ---
        try:
            purchase = TicketPurchase.objects.create(
                ticket=ticket,
                full_name=full_name,
                email=email,
                copies=copies,
                total_price=total_amount,
                user=buyer_user,
                paystack_reference=reference,
            )
        except Exception as e:
            # unexpected create error
            return Response({"error": "Failed to create purchase record", "details": str(e)}, status=500)

        # --- Payout vendor via Paystack Transfers ---
        vendor = ticket.event.organizer
        event = ticket.event

        # Prefer event-level bank details (you collect while creating event)
        vendor_account = getattr(event, "account_number", None)
        vendor_bank_code = getattr(event, "bank_code", None)
        vendor_name = getattr(event, "account_name", None) or (f"{vendor.first_name} {vendor.last_name}" if hasattr(vendor, "first_name") else getattr(vendor, "username", "Vendor"))
        vendor_bank_name = getattr(event, "bank_name", None)

        if not vendor_account or not vendor_bank_code:
            # vendor details missing — purchase recorded, but no payout
            # Send admin email to notify
            EmailMessage(
                subject=f"Payment received but no vendor bank details - {ticket.event.title}",
                body=f"Payment for {ticket.event.title} was received ({total_amount}) but vendor has no account_number/bank_code.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.DEFAULT_FROM_EMAIL],
            ).send(fail_silently=True)
            # Build QR URLs
            qr_urls = []
            for qr_file in getattr(purchase, "qr_codes", []):
                qr_urls.append(request.build_absolute_uri(f"/media/qrcodes/{qr_file}"))
            return Response({
                "message": "Payment verified and purchase recorded, but vendor payout not initiated (vendor bank details missing).",
                "purchase_id": str(purchase.reference_id),
                "total_paid": float(total_amount),
                "platform_charge": float(platform_charge),
                "vendor_amount": float(vendor_amount),
                "qr_codes": qr_urls,
            }, status=200)

        # Reuse existing paystack recipient_code on the vendor (if your vendor model stores it)
        recipient_code = getattr(vendor, "paystack_recipient_code", None)

        if not recipient_code:
            create_rec = _create_paystack_transfer_recipient(
                name=str(vendor_name),
                account_number=str(vendor_account),
                bank_code=str(vendor_bank_code),
            )
            if not create_rec.get("status"):
                # Recipient creation failed — keep purchase, notify admin and return error details
                EmailMessage(
                    subject="Paystack recipient creation failed",
                    body=f"Failed to create recipient for vendor {vendor_name}. Details: {create_rec}",
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    to=[settings.DEFAULT_FROM_EMAIL],
                ).send(fail_silently=True)

                qr_urls = []
                for qr_file in getattr(purchase, "qr_codes", []):
                    qr_urls.append(request.build_absolute_uri(f"/media/qrcodes/{qr_file}"))

                return Response({
                    "message": "Payment verified and purchase recorded, but creating Paystack transfer recipient failed.",
                    "details": create_rec,
                    "purchase_id": str(purchase.reference_id),
                    "qr_codes": qr_urls,
                }, status=500)

            recipient_code = create_rec["recipient_code"]

            # Optionally save recipient_code to vendor model (if it has that field)
            try:
                if hasattr(vendor, "paystack_recipient_code"):
                    setattr(vendor, "paystack_recipient_code", recipient_code)
                    vendor.save(update_fields=["paystack_recipient_code"])
            except Exception:
                # ignore save errors
                pass

        # Initiate transfer (from Paystack balance)
        reason = f"Payout for {ticket.event.title} - {purchase.reference_id}"
        transfer_init = _initiate_paystack_transfer(amount_naira=vendor_amount, recipient_code=recipient_code, reason=reason)

        if not transfer_init.get("status"):
            # Transfer initiation failed - inform admin + return error (purchase already recorded)
            EmailMessage(
                subject="Paystack transfer initiation failed",
                body=f"Failed to initiate payout for purchase {purchase.reference_id}. Details: {transfer_init}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[settings.DEFAULT_FROM_EMAIL],
            ).send(fail_silently=True)

            qr_urls = []
            for qr_file in getattr(purchase, "qr_codes", []):
                qr_urls.append(request.build_absolute_uri(f"/media/qrcodes/{qr_file}"))

            return Response({
                "message": "Payment verified and purchase recorded, but vendor payout initiation failed.",
                "purchase_id": str(purchase.reference_id),
                "transfer_error": transfer_init,
                "qr_codes": qr_urls,
            }, status=500)

        transfer_data = transfer_init["data"]
        transfer_id = transfer_data.get("id")

        # Optionally fetch transfer status (immediate)
        transfer_fetch = _fetch_paystack_transfer(str(transfer_id))
        transfer_status = transfer_fetch.get("data", {}).get("status") if transfer_fetch.get("status") else transfer_data.get("status", "unknown")

        # --- Send receipt email to buyer ---
        email_subject = f"Your Ticket Receipt - {ticket.event.title}"
        email_body = f"""
Hello {full_name},

✅ Payment Successful!

Event: {ticket.event.title}
Tickets: {copies}
Total Paid: ₦{total_amount}
Platform Charge: ₦{platform_charge}
Vendor Receives: ₦{vendor_amount}

Reference ID: {purchase.reference_id}

Thank you for your purchase!
"""
        email_msg = EmailMessage(
            subject=email_subject,
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        for qr_file in getattr(purchase, "qr_codes", []):
            file_path = f"qrcodes/{qr_file}"
            if default_storage.exists(file_path):
                with default_storage.open(file_path, "rb") as f:
                    email_msg.attach(qr_file, f.read(), "image/png")
        email_msg.send(fail_silently=True)

        # Build QR code URLs for response
        qr_urls = []
        for qr_file in getattr(purchase, "qr_codes", []):
            qr_urls.append(request.build_absolute_uri(f"/media/qrcodes/{qr_file}"))

        return Response({
            "message": "Payment verified, purchase recorded, vendor payout initiated.",
            "purchase_id": str(purchase.reference_id),
            "total_paid": float(total_amount),
            "platform_charge": float(platform_charge),
            "vendor_amount": float(vendor_amount),
            "qr_codes": qr_urls,
            "transfer": {
                "id": transfer_id,
                "status": transfer_status,
                "details": transfer_data
            }
        }, status=200)


        

class PaystackBanksView(APIView):
    def get(self, request):
        url = "https://api.paystack.co/bank"
        headers = {
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"
        }

        r = requests.get(url, headers=headers)
        return Response(r.json(), status=r.status_code)





@csrf_exempt
def paystack_webhook(request):
    signature = request.headers.get("x-paystack-signature")

    computed = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        request.body,
        hashlib.sha512
    ).hexdigest()

    if signature != computed:
        return HttpResponse(status=400)

    payload = json.loads(request.body)

    event = payload.get("event")
    data = payload.get("data", {})

    if event == "charge.success":
        reference = data.get("reference")

        # VERY IMPORTANT: never trigger payout blindly
        # Only mark verified or enqueue processing
        TicketPurchase.objects.filter(
            paystack_reference=reference
        ).update(webhook_verified=True)

    return HttpResponse(status=200)
