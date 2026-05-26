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
            total_price=total_amount,
            user=user,
        )

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
